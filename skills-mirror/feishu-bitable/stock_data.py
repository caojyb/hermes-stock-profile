"""
股票行情数据获取模块
支持A股、港股、美股实时行情及历史K线数据

数据源:
- 腾讯财经API (A股/港股/美股): https://qt.gtimg.cn/q=sz000981
- 腾讯日K: https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get

股票代码规则:
- A股: sh(沪市), sz(深市), bj(北交所) + 6位代码
- 港股: hk + 5位代码
- 美股: us + 代码 (如 usAAPL, usNDX, usSPY, usDIA)
"""

import requests
import json
import re
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Union, Any

# opentdx (TDX 资金流源): 可选依赖，未安装时 get_stock_money_flow 走 error 降级
try:
    from opentdx.client import macQuotationClient
    from opentdx.const import MARKET
    OPENTDX_AVAILABLE = True
except ImportError:
    OPENTDX_AVAILABLE = False

# ============ TDX 资金流基础设施 ============

_tdx_client = None
_tdx_lock = threading.Lock()


def _code_to_market(code: str):
    """6位A股代码 → TDX MARKET 枚举。未识别前缀 raise ValueError。
    映射是防呆关键: market 错误组合会静默返回其他标的的资金流(实测 000001+SH 返回上证指数)。"""
    code = code.strip()
    if code.startswith('6'):
        return MARKET.SH
    if code.startswith(('0', '3')):
        return MARKET.SZ
    if code.startswith(('4', '8', '920')):
        return MARKET.BJ
    raise ValueError(f"unknown market for code: {code}")


def _get_tdx_client():
    """模块级单例, 懒连接(构造无网络副作用, 已源码+运行时验证), 锁保护。
    auto_retry=True: 调用期断线库内自动重连(实测0.16s自愈)。
    connect 失败重试2次, 全败 raise 由调用方转 error dict。"""
    global _tdx_client
    if _tdx_client is not None:
        return _tdx_client
    with _tdx_lock:
        if _tdx_client is None:
            client = macQuotationClient(True, True, auto_retry=True, raise_exception=True)
            last_err = None
            for attempt in range(3):
                try:
                    client.connect().login()
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    import time as _time
                    if attempt < 2:
                        _time.sleep(0.5)
            if last_err is not None:
                raise last_err
            _tdx_client = client
    return _tdx_client


def _kline_amount_5d(klines: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    """最后5根日K的成交额合计(腾讯amount字段为万元→转元)。不足5根或字段缺失返回 None。"""
    if not klines or len(klines) < 5:
        return None
    total_wan = 0.0
    for k in klines[-5:]:
        amt = k.get("amount")
        if amt is None:
            return None
        total_wan += amt
    return total_wan * 1e4


class StockDataFetcher:
    """股票行情数据获取类"""

    # 腾讯财经实时行情API
    TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={symbols}"

    # 腾讯财经K线API (新)
    TENCENT_KLINE_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"

    # HTTP请求头
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://finance.qq.com",
        "Accept": "*/*"
    }

    # A股市场前缀映射
    A_SHARE_MARKET = {
        "sh": "上海主板",
        "sz": "深圳主板",
        "bj": "北京板"
    }

    # 美股指数中文名称映射
    US_INDEX_NAMES = {
        "NDX": "纳斯达克100",
        "SPY": "标普500",
        "DIA": "道琼斯",
        "GXY": "金龙中国"
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _normalize_a_share_code(self, code: str) -> str:
        """标准化A股代码，添加市场前缀"""
        code = code.strip().lower()

        # 6位数字自动判断市场
        if code.isdigit() and len(code) == 6:
            # 上海: 600xxx, 601xxx, 603xxx, 605xxx, 688xxx (科创板)
            # 深圳: 000xxx, 001xxx, 002xxx(创业板), 300xxx(创业板)
            if code.startswith(('6', '601', '603', '605', '688')):
                return f"sh{code}"
            else:
                return f"sz{code}"

        # 已有前缀
        if code.startswith(('sh', 'sz', 'bj')):
            return code

        return code

    def _normalize_hk_code(self, code: str) -> str:
        """标准化港股代码，添加hk前缀"""
        code = code.strip().lower()
        if code.isdigit():
            return f"hk{code}"
        if code.startswith('hk'):
            return code
        return f"hk{code}"

    def _normalize_us_code(self, code: str) -> str:
        """标准化美股代码，添加us前缀"""
        code = code.strip().upper()
        # 已经带了us前缀的直接返回
        if code.startswith('US'):
            return code
        return f"us{code}"

    def _parse_tencent_quote(self, text: str, market_type: str = "A") -> Dict[str, Any]:
        """解析腾讯财经实时行情数据"""
        try:
            # 数据格式: v_sz000981="sz000981,名称,现价,昨收,今开,成交量,外盘,内盘,...",...
            match = re.search(r'="([^"]+)"', text)
            if not match:
                return {}

            parts = match.group(1).split('~')
            if len(parts) < 10:
                return {}

            if market_type == "US":
                return self._parse_us_quote(parts)
            elif market_type == "HK":
                return self._parse_hk_quote(parts)
            else:
                return self._parse_a_share_quote(parts)
        except (IndexError, ValueError) as e:
            return {"error": str(e), "raw": text[:200]}

    def _parse_a_share_quote(self, parts: List[str]) -> Dict[str, Any]:
        """解析A股行情数据
        
        腾讯财经A股数据格式:
        parts[0]: 市场标识 (1=沪, 51=深等)
        parts[1]: 股票名称 (可能乱码)
        parts[2]: 股票代码 (6位数字)
        parts[3]: 现价
        parts[4]: 昨收
        parts[5]: 今开
        parts[6]: 成交量(手)
        parts[9]: 买一价
        parts[19]: 卖一价
        parts[31]: 涨跌额
        parts[32]: 涨跌幅
        parts[33]: 最高价
        parts[34]: 最低价
        parts[37]: 成交额(万元)
        parts[39]: 振幅
        """
        try:
            code = parts[2] if len(parts) > 2 else ""
            price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
            prev_close = float(parts[4]) if len(parts) > 4 and parts[4] else 0
            open_price = float(parts[5]) if len(parts) > 5 and parts[5] else 0
            change = float(parts[31]) if len(parts) > 31 and parts[31] else (price - prev_close)
            change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else ((price - prev_close) / prev_close * 100 if prev_close else 0)

            # 判断市场
            if code.startswith(('6', '601', '603', '605', '688')):
                market = "上海主板"
            elif code.startswith(('8', '4', '3')):  # 北交所
                market = "北京板"
            else:
                market = "深圳主板"

            return {
                "code": code,
                "name": parts[1] if len(parts) > 1 else code,  # 名称可能乱码
                "price": price,
                "prev_close": prev_close,
                "open": open_price,
                "volume": int(parts[6]) if len(parts) > 6 and parts[6] else 0,
                "bid_price": float(parts[9]) if len(parts) > 9 and parts[9] else 0,
                "ask_price": float(parts[19]) if len(parts) > 19 and parts[19] else 0,
                "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                "turnover": float(parts[37]) if len(parts) > 37 and parts[37] else 0,
                "amplitude": float(parts[39]) if len(parts) > 39 and parts[39] else 0,
                "change": change,
                "change_pct": change_pct,
                "market": market
            }
        except (IndexError, ValueError) as e:
            return {"error": f"A股解析失败: {str(e)}"}

    def _parse_hk_quote(self, parts: List[str]) -> Dict[str, Any]:
        """解析港股行情数据
        
        腾讯财经港股数据格式:
        parts[0]: 市场标识 (100)
        parts[1]: 股票名称 (可能乱码)
        parts[2]: 股票代码 (5位数字)
        parts[3]: 现价
        parts[4]: 昨收
        parts[5]: 今开
        parts[6]: 成交量
        parts[9]: 买一价
        parts[19]: 卖一价
        parts[31]: 涨跌额
        parts[32]: 涨跌幅
        parts[33]: 最高价
        parts[34]: 最低价
        """
        try:
            code = parts[2] if len(parts) > 2 else ""
            price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
            prev_close = float(parts[4]) if len(parts) > 4 and parts[4] else 0
            open_price = float(parts[5]) if len(parts) > 5 and parts[5] else 0
            change = float(parts[31]) if len(parts) > 31 and parts[31] else (price - prev_close)
            change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else ((price - prev_close) / prev_close * 100 if prev_close else 0)

            return {
                "code": code,
                "name": parts[1] if len(parts) > 1 else code,
                "price": price,
                "prev_close": prev_close,
                "open": open_price,
                "volume": int(float(parts[6])) if len(parts) > 6 and parts[6] else 0,
                "bid_price": float(parts[9]) if len(parts) > 9 and parts[9] else 0,
                "ask_price": float(parts[19]) if len(parts) > 19 and parts[19] else 0,
                "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                "change": change,
                "change_pct": change_pct,
                "market": "港股"
            }
        except (IndexError, ValueError) as e:
            return {"error": f"港股解析失败: {str(e)}"}

    def _parse_us_quote(self, parts: List[str]) -> Dict[str, Any]:
        """解析美股行情数据
        
        腾讯财经美股数据格式:
        parts[0]: 市场标识 (200)
        parts[1]: 股票名称 (可能乱码)
        parts[2]: 股票代码 (如 AAPL.OQ, .NDX)
        parts[3]: 现价
        parts[4]: 昨收
        parts[5]: 今开
        parts[6]: 成交量
        parts[9]: 买一价
        parts[19]: 卖一价
        parts[30]: 日期时间
        parts[31]: 涨跌额
        parts[32]: 涨跌幅
        parts[33]: 最高价
        parts[34]: 最低价
        parts[35]: 货币 (USD)
        """
        try:
            symbol_raw = parts[2] if len(parts) > 2 else ""
            # 提取纯代码符号，去掉 .OQ, .AM 等后缀
            symbol = symbol_raw.replace('.OQ', '').replace('.AM', '').replace('.', '')
            name = self.US_INDEX_NAMES.get(symbol, parts[1] if len(parts) > 1 else symbol)
            
            price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
            prev_close = float(parts[4]) if len(parts) > 4 and parts[4] else 0
            open_price = float(parts[5]) if len(parts) > 5 and parts[5] else 0
            change = float(parts[31]) if len(parts) > 31 and parts[31] else (price - prev_close)
            change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else ((price - prev_close) / prev_close * 100 if prev_close else 0)
            high = float(parts[33]) if len(parts) > 33 and parts[33] else 0
            low = float(parts[34]) if len(parts) > 34 and parts[34] else 0
            currency = parts[35] if len(parts) > 35 else "USD"

            return {
                "code": symbol,
                "name": name,
                "price": price,
                "prev_close": prev_close,
                "open": open_price,
                "volume": int(parts[6]) if len(parts) > 6 and parts[6] else 0,
                "bid_price": float(parts[9]) if len(parts) > 9 and parts[9] else 0,
                "ask_price": float(parts[19]) if len(parts) > 19 and parts[19] else 0,
                "high": high,
                "low": low,
                "change": change,
                "change_pct": change_pct,
                "market": "美股",
                "currency": currency
            }
        except (IndexError, ValueError) as e:
            return {"error": f"美股解析失败: {str(e)}"}

    def get_a_share_quote(self, code: str) -> Dict[str, Any]:
        """
        获取A股实时行情

        Args:
            code: 股票代码，支持6位代码或带市场前缀(sh/sz/bj)

        Returns:
            行情数据字典
        """
        code = self._normalize_a_share_code(code)
        url = self.TENCENT_QUOTE_URL.format(symbols=code)

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return self._parse_tencent_quote(response.text, "A")
        except requests.RequestException as e:
            return {"error": f"请求失败: {str(e)}"}

    def get_a_share_quotes(self, codes: List[str]) -> List[Dict[str, Any]]:
        """
        批量获取A股实时行情

        Args:
            codes: 股票代码列表

        Returns:
            行情数据列表
        """
        if not codes:
            return []

        normalized_codes = [self._normalize_a_share_code(c) for c in codes]
        symbols = ",".join(normalized_codes)
        url = self.TENCENT_QUOTE_URL.format(symbols=symbols)

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            results = []
            stock_data_list = re.findall(r'="([^"]+)"', response.text)
            for stock_data in stock_data_list:
                parts = stock_data.split('~')
                if len(parts) >= 35:
                    parsed = self._parse_a_share_quote(parts)
                    if parsed and "error" not in parsed:
                        results.append(parsed)
            return results
        except requests.RequestException as e:
            return [{"error": f"请求失败: {str(e)}"}]

    def get_hk_quote(self, code: Union[str, int]) -> Dict[str, Any]:
        """
        获取港股实时行情

        Args:
            code: 港股代码，支持数字或带hk前缀

        Returns:
            行情数据字典
        """
        code = self._normalize_hk_code(code)
        url = self.TENCENT_QUOTE_URL.format(symbols=code)

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return self._parse_tencent_quote(response.text, "HK")
        except requests.RequestException as e:
            return {"error": f"请求失败: {str(e)}"}

    def get_hk_quotes(self, codes: List[Union[str, int]]) -> List[Dict[str, Any]]:
        """
        批量获取港股实时行情

        Args:
            codes: 港股代码列表

        Returns:
            行情数据列表
        """
        if not codes:
            return []

        normalized_codes = [self._normalize_hk_code(c) for c in codes]
        symbols = ",".join(normalized_codes)
        url = self.TENCENT_QUOTE_URL.format(symbols=symbols)

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            results = []
            stock_data_list = re.findall(r'="([^"]+)"', response.text)
            for stock_data in stock_data_list:
                parts = stock_data.split('~')
                if len(parts) >= 35:
                    parsed = self._parse_hk_quote(parts)
                    if parsed and "error" not in parsed:
                        results.append(parsed)
            return results
        except requests.RequestException as e:
            return [{"error": f"请求失败: {str(e)}"}]

    def get_us_quote(self, symbol: str) -> Dict[str, Any]:
        """
        获取美股实时行情（使用腾讯API）

        Args:
            symbol: 美股代码，如AAPL, NDX, SPY, DIA, GXY

        Returns:
            行情数据字典
        """
        symbol = self._normalize_us_code(symbol)
        url = self.TENCENT_QUOTE_URL.format(symbols=symbol)

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return self._parse_tencent_quote(response.text, "US")
        except requests.RequestException as e:
            return {"error": f"请求失败: {str(e)}"}

    def get_us_quotes(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        批量获取美股实时行情

        Args:
            symbols: 美股代码列表

        Returns:
            行情数据列表
        """
        if not symbols:
            return []

        normalized_symbols = [self._normalize_us_code(s) for s in symbols]
        symbols_str = ",".join(normalized_symbols)
        url = self.TENCENT_QUOTE_URL.format(symbols=symbols_str)

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            results = []
            stock_data_list = re.findall(r'="([^"]+)"', response.text)
            for stock_data in stock_data_list:
                parts = stock_data.split('~')
                if len(parts) >= 35:
                    parsed = self._parse_us_quote(parts)
                    if parsed and "error" not in parsed:
                        results.append(parsed)
            return results
        except requests.RequestException as e:
            return [{"error": f"请求失败: {str(e)}"}]

    def get_a_share_kline(self, code: str, days: int = 65) -> Dict[str, Any]:
        """
        获取A股日K线数据（腾讯财经）

        Args:
            code: 股票代码
            days: 获取天数

        Returns:
            K线数据字典
        """
        code = self._normalize_a_share_code(code)
        params = {
            "apptype": "",
            "dir": 0,
            "enddate": "",
            "fqt": 1,  # 前复权
            "lmt": days,
            "market": 1,
            "osbr": 1,
            "p": 1,
            "param": f"{code},day,,,{days},qfq"
        }

        try:
            response = self.session.get(self.TENCENT_KLINE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            code_data = data.get("data", {}).get(code, {})

            if "qfqday" in code_data:
                klines = code_data["qfqday"]
            elif "day" in code_data:
                klines = code_data["day"]
            else:
                return {"error": "无K线数据", "code": code}

            parsed_klines = []
            for kline in klines:
                if len(kline) >= 6:
                    parsed_klines.append({
                        "date": kline[0],
                        "open": float(kline[1]),
                        "close": float(kline[2]),
                        "high": float(kline[3]),
                        "low": float(kline[4]),
                        "volume": float(kline[5]),  # 成交量可能是带单位的字符串
                        # 成交额(万元): 腾讯日K k[8], qfq/bfq 一致(实测250根0差异), 未被复权调整
                        "amount": float(kline[8]) if len(kline) > 8 and kline[8] else 0.0
                    })

            # 获取股票名称
            qt_data = code_data.get("qt", {}).get(code, [])
            name = qt_data[1] if len(qt_data) > 1 else code

            return {
                "code": code,
                "name": name,
                "klines": parsed_klines
            }
        except requests.RequestException as e:
            return {"error": f"请求失败: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "JSON解析失败"}
        except Exception as e:
            return {"error": str(e)}

    def get_us_kline(self, symbol: str, period: str = "1mo") -> Dict[str, Any]:
        """
        获取美股日K线数据（使用腾讯API）

        Args:
            symbol: 美股代码
            period: 数据周期 (5d, 10d, 20d, 30d, 60d, 90d, 180d, 1y, 2y)

        Returns:
            K线数据字典
        """
        symbol = self._normalize_us_code(symbol)
        # 转换周期参数
        period_map = {
            "5d": 5, "10d": 10, "20d": 20, "30d": 30,
            "60d": 60, "90d": 90, "180d": 180,
            "1y": 250, "2y": 500
        }
        days = period_map.get(period.lower(), 30)

        params = {
            "apptype": "",
            "dir": 0,
            "enddate": "",
            "fqt": 0,
            "lmt": days,
            "market": 2,  # 美股市场
            "osbr": 1,
            "p": 1,
            "param": f"{symbol},day,,,{days},"
        }

        try:
            response = self.session.get(self.TENCENT_KLINE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # 使用原始symbol获取数据，不要调用upper()
            code_data = data.get("data", {}).get(symbol, {})

            if "day" in code_data:
                klines = code_data["day"]
            else:
                return {"error": "无K线数据", "symbol": symbol}

            parsed_klines = []
            for kline in klines:
                if len(kline) >= 6:
                    parsed_klines.append({
                        "date": kline[0],
                        "open": float(kline[1]),
                        "close": float(kline[2]),
                        "high": float(kline[3]),
                        "low": float(kline[4]),
                        "volume": float(kline[5])
                    })

            return {
                "symbol": symbol.replace("us", "").upper(),  # 去掉us前缀并大写
                "klines": parsed_klines
            }
        except requests.RequestException as e:
            return {"error": f"请求失败: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "JSON解析失败"}
        except Exception as e:
            return {"error": str(e)}

    def get_hk_kline(self, code: str, days: int = 65) -> Dict[str, Any]:
        """
        获取港股日K线数据

        Args:
            code: 港股代码
            days: 获取天数

        Returns:
            K线数据字典
        """
        code = self._normalize_hk_code(code)
        params = {
            "apptype": "",
            "dir": 0,
            "enddate": "",
            "fqt": 0,
            "lmt": days,
            "market": 3,  # 港股市场
            "osbr": 1,
            "p": 1,
            "param": f"{code},day,,,{days},"
        }

        try:
            response = self.session.get(self.TENCENT_KLINE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            code_data = data.get("data", {}).get(code.lower(), {})

            if "day" in code_data:
                klines = code_data["day"]
            else:
                return {"error": "无K线数据", "code": code}

            parsed_klines = []
            for kline in klines:
                if len(kline) >= 6:
                    parsed_klines.append({
                        "date": kline[0],
                        "open": float(kline[1]),
                        "close": float(kline[2]),
                        "high": float(kline[3]),
                        "low": float(kline[4]),
                        "volume": float(kline[5])
                    })

            return {
                "code": code,
                "klines": parsed_klines
            }
        except requests.RequestException as e:
            return {"error": f"请求失败: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "JSON解析失败"}
        except Exception as e:
            return {"error": str(e)}

    def get_market_index(self) -> Dict[str, Any]:
        """
        获取主要市场指数行情

        Returns:
            主要指数行情字典
        """
        results = {}

        # A股和港股指数
        a_hk_symbols = ["sh000001", "sz399001", "sz399006", "hkHSI"]
        index_names = ["上证指数", "深证成指", "创业板指", "恒生指数"]

        try:
            url = self.TENCENT_QUOTE_URL.format(symbols=",".join(a_hk_symbols))
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            stock_data_list = re.findall(r'="([^"]+)"', response.text)

            for i, stock_data in enumerate(stock_data_list):
                parts = stock_data.split('~')
                if len(parts) >= 35 and i < len(index_names):
                    code = parts[2] if len(parts) > 2 else ""
                    price = float(parts[3]) if parts[3] else 0
                    prev_close = float(parts[4]) if parts[4] else 0
                    change = float(parts[31]) if len(parts) > 31 and parts[31] else (price - prev_close)
                    change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else ((price - prev_close) / prev_close * 100 if prev_close else 0)
                    results[index_names[i]] = {
                        "code": code,
                        "name": parts[1] if len(parts) > 1 else index_names[i],
                        "price": price,
                        "change": change,
                        "change_pct": change_pct,
                        "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                        "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0
                    }
        except requests.RequestException as e:
            results["error_ah"] = str(e)

        # 美股指数
        us_symbols = ["usNDX", "usSPY", "usDIA"]
        us_names = ["纳斯达克100", "标普500", "道琼斯"]

        try:
            url = self.TENCENT_QUOTE_URL.format(symbols=",".join(us_symbols))
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            stock_data_list = re.findall(r'="([^"]+)"', response.text)

            for i, stock_data in enumerate(stock_data_list):
                parts = stock_data.split('~')
                if len(parts) >= 36 and i < len(us_names):
                    symbol_raw = parts[2].replace('.OQ', '').replace('.AM', '').replace('.', '') if len(parts) > 2 else us_symbols[i]
                    results[us_names[i]] = {
                        "code": symbol_raw,
                        "name": us_names[i],
                        "price": float(parts[3]) if parts[3] else 0,
                        "change": float(parts[31]) if len(parts) > 31 and parts[31] else 0,
                        "change_pct": float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                        "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                        "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0
                    }
        except requests.RequestException as e:
            results["error_us"] = str(e)

        return results


def get_stock_quote(market: str, code: str) -> Dict[str, Any]:
    """
    便捷函数：获取单只股票行情

    Args:
        market: 市场类型 ("A", "HK", "US")
        code: 股票代码

    Returns:
        行情数据字典
    """
    fetcher = StockDataFetcher()

    if market.upper() == "A":
        return fetcher.get_a_share_quote(code)
    elif market.upper() == "HK":
        return fetcher.get_hk_quote(code)
    elif market.upper() == "US":
        return fetcher.get_us_quote(code)
    else:
        return {"error": f"不支持的市场类型: {market}"}


def get_stock_kline(market: str, code: str, **kwargs) -> Dict[str, Any]:
    """
    便捷函数：获取股票K线数据

    Args:
        market: 市场类型 ("A", "HK", "US")
        code: 股票代码
        **kwargs: 额外参数 (days for A-share/HK, period for US)

    Returns:
        K线数据字典
    """
    fetcher = StockDataFetcher()

    if market.upper() == "A":
        days = kwargs.get("days", 65)
        return fetcher.get_a_share_kline(code, days)
    elif market.upper() == "HK":
        days = kwargs.get("days", 65)
        return fetcher.get_hk_kline(code, days)
    elif market.upper() == "US":
        period = kwargs.get("period", "1mo")
        return fetcher.get_us_kline(code, period)
    else:
        return {"error": f"不支持的市场类型: {market}"}


# ============================================================
# 个股资金流 & 大盘RSI（供信号引擎调用）
# ============================================================

def get_stock_money_flow(code: str, days: int = 5,
                         turnover_yuan: Optional[float] = None,
                         turnover_5d_yuan: Optional[float] = None) -> Dict[str, Any]:
    """
    获取个股资金流向（TDX symbol_zjlx，主力/散户今日与5日）

    Args:
        code: 6位股票代码
        days: 保留参数，仅支持5（TDX 返回固定今日+5日窗口）
        turnover_yuan: 今日成交额（元），来自调用方已获取的行情（腾讯 parts[37] 万元×1e4）
        turnover_5d_yuan: 近5个交易日成交额合计（元），来自日K amount 求和

    Returns:
        {'main_pct': float, 'days_main_pct': float, 'code': str}
        main_pct = 今日主力净流入/今日成交额×100; days_main_pct = 5日主力净流入/5日成交额合计×100
        分母缺失时对应项为 None; 失败返回 {'error': ..., 'code': code}
    """
    code = code.strip()

    if not OPENTDX_AVAILABLE:
        return {"error": "opentdx_not_installed", "code": code}
    if days != 5:
        return {"error": f"unsupported_days: {days} (only 5)", "code": code}

    # 防呆: 前缀映射失败直接 error, 不允许错误 market 进查询(会静默拿错标的)
    try:
        market = _code_to_market(code)
    except ValueError as e:
        return {"error": f"unknown_market: {e}", "code": code}

    try:
        client = _get_tdx_client()
    except Exception as e:
        return {"error": f"tdx_connect_failed: {e}", "code": code}

    try:
        result = client.get_symbol_zjlx(code, market)
    except Exception as e:
        return {"error": f"tdx_query_failed: {e}", "code": code}

    data = result.get("data") if isinstance(result, dict) else None
    if not data or not isinstance(data, dict):
        return {"error": "tdx_empty_response", "code": code}

    main_net = data.get("今日主力净流入")
    main_net_5d = data.get("5日主力净流入")
    if main_net is None or main_net_5d is None:
        return {"error": "tdx_empty_response", "code": code}

    # 分母: 0/None 均不除(除零防护), 返回 None 由 signal_engine 的 .get(...,0) 容错
    # turnover_yuan=0.0 时除法不可做，归 None 是正确的降级行为（非笔误）
    main_pct = (main_net / turnover_yuan * 100) if turnover_yuan else None
    days_main_pct = (main_net_5d / turnover_5d_yuan * 100) if turnover_5d_yuan else None

    return {
        "main_pct": round(main_pct, 2) if main_pct is not None else None,
        "days_main_pct": round(days_main_pct, 2) if days_main_pct is not None else None,
        "code": code
    }


def get_market_rsi(index_code: str = "sh000300", days: int = 14) -> Optional[float]:
    """
    计算大盘指数RSI（基于腾讯财经K线）

    Args:
        index_code: 指数代码，默认沪深300(sh000300)
        days: RSI周期，默认14

    Returns:
        RSI值 (0-100)，失败返回None
    """
    fetcher = StockDataFetcher()
    kline = fetcher.get_a_share_kline(index_code, days=days + 5)

    if "error" in kline:
        return None

    klines = kline.get("klines", [])
    if len(klines) < days + 1:
        return None

    closes = [float(k["close"]) for k in klines[-(days + 1):]]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-days:]]
    losses = [-d if d < 0 else 0 for d in deltas[-days:]]

    avg_gain = sum(gains) / days
    avg_loss = sum(losses) / days

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


# 示例用法
if __name__ == "__main__":
    fetcher = StockDataFetcher()

    print("=" * 60)
    print("A股行情示例 (贵州茅台 600519)")
    print("=" * 60)
    quote = fetcher.get_a_share_quote("600519")
    print(f"代码: {quote.get('code')}, 名称: {quote.get('name')}")
    print(f"现价: {quote.get('price')}, 涨跌: {quote.get('change'):.2f} ({quote.get('change_pct'):.2f}%)")
    print(f"最高: {quote.get('high')}, 最低: {quote.get('low')}")
    print(f"成交量: {quote.get('volume')}, 市场: {quote.get('market')}")

    print("\n" + "=" * 60)
    print("港股行情示例 (腾讯00700)")
    print("=" * 60)
    quote = fetcher.get_hk_quote("00700")
    print(f"代码: {quote.get('code')}, 名称: {quote.get('name')}")
    print(f"现价: {quote.get('price')}, 涨跌: {quote.get('change'):.2f} ({quote.get('change_pct'):.2f}%)")
    print(f"最高: {quote.get('high')}, 最低: {quote.get('low')}")
    print(f"成交量: {quote.get('volume')}, 市场: {quote.get('market')}")

    print("\n" + "=" * 60)
    print("美股行情示例 (苹果 AAPL)")
    print("=" * 60)
    quote = fetcher.get_us_quote("AAPL")
    print(f"代码: {quote.get('code')}, 名称: {quote.get('name')}")
    print(f"现价: {quote.get('price')}, 涨跌: {quote.get('change'):.2f} ({quote.get('change_pct'):.2f}%)")
    print(f"最高: {quote.get('high')}, 最低: {quote.get('low')}")
    print(f"成交量: {quote.get('volume')}, 市场: {quote.get('market')}")

    print("\n" + "=" * 60)
    print("美股指数示例 (纳斯达克100 NDX)")
    print("=" * 60)
    quote = fetcher.get_us_quote("NDX")
    print(f"代码: {quote.get('code')}, 名称: {quote.get('name')}")
    print(f"现价: {quote.get('price')}, 涨跌: {quote.get('change'):.2f} ({quote.get('change_pct'):.2f}%)")
    print(f"最高: {quote.get('high')}, 最低: {quote.get('low')}")

    print("\n" + "=" * 60)
    print("主要市场指数")
    print("=" * 60)
    indices = fetcher.get_market_index()
    for name, data in indices.items():
        if "error" not in data:
            print(f"{name}: {data.get('price'):.2f}, {data.get('change'):.2f} ({data.get('change_pct'):.2f}%)")

    print("\n" + "=" * 60)
    print("A股K线示例 (平安银行 000001)")
    print("=" * 60)
    kline = fetcher.get_a_share_kline("000001", days=5)
    print(f"股票: {kline.get('name', '')}")
    print(f"K线数量: {len(kline.get('klines', []))}")
    if kline.get('klines'):
        print("最新5条:")
        for k in kline['klines'][-5:]:
            print(f"  {k['date']}: 开{k['open']:.2f} 收{k['close']:.2f} 高{k['high']:.2f} 低{k['low']:.2f}")

    print("\n" + "=" * 60)
    print("美股K线示例 (特斯拉 TSLA)")
    print("=" * 60)
    kline = fetcher.get_us_kline("TSLA", period="5d")
    print(f"股票: {kline.get('symbol', '')}")
    print(f"K线数量: {len(kline.get('klines', []))}")
    if kline.get('klines'):
        print("最新3条:")
        for k in kline['klines'][-3:]:
            print(f"  {k['date']}: 开{k['open']:.2f} 收{k['close']:.2f} 高{k['high']:.2f} 低{k['low']:.2f}")

    print("\n" + "=" * 60)
    print("港股K线示例 (腾讯 00700)")
    print("=" * 60)
    kline = fetcher.get_hk_kline("00700", days=5)
    print(f"股票: {kline.get('code', '')}")
    print(f"K线数量: {len(kline.get('klines', []))}")
    if kline.get('klines'):
        print("最新3条:")
        for k in kline['klines'][-3:]:
            print(f"  {k['date']}: 开{k['open']:.2f} 收{k['close']:.2f} 高{k['high']:.2f} 低{k['low']:.2f}")
