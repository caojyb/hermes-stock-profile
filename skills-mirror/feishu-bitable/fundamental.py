"""
A股基本面数据 + 大盘情绪

数据来源:
- 新浪财经PE/PB: https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData
- 涨跌停家数: https://push2.eastmoney.com/api/qt/stock/clist/get
- 北向资金: https://push2.eastmoney.com/api/qt/kamtop/get
- 大盘指数: 腾讯财经 (上证sh000001, 深证sz399001, 沪深300sh000300, 创业板sz399006)
"""

import requests
import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple


class FundamentalFetcher:
    """A股基本面数据 + 大盘情绪"""

    # 东方财富PE/PB接口
    EASTMONEY_PE_PB_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

    # 涨跌停家数接口
    EASTMONEY_LIMIT_UP_URL = "https://push2.eastmoney.com/api/qt/stock/clist/get"

    # 北向资金接口
    EASTMONEY_NORTH_MONEY_URL = "https://push2.eastmoney.com/api/qt/kamtop/get"

    # 腾讯财经大盘指数
    TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={symbols}"

    # HTTP头
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://finance.eastmoney.com",
        "Accept": "*/*"
    }

    # 大盘指数映射
    INDEX_CODES = {
        "上证指数": "sh000001",
        "深证成指": "sz399001",
        "沪深300": "sh000300",
        "创业板": "sz399006"
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _parse_tencent_quote(self, text: str) -> Dict[str, Any]:
        """解析腾讯财经行情"""
        try:
            # 检查是否已经是提取后的数据（没有 =" 格式）
            if '=" ' not in text and '="1' not in text and '="5' not in text:
                # 已经是提取后的数据，直接分割
                parts = text.split('~')
            else:
                # 原始格式，需要先提取
                match = re.search(r'="([^"]+)"', text)
                if not match:
                    return {}
                parts = match.group(1).split('~')

            if len(parts) < 35:
                return {}

            code = parts[2] if len(parts) > 2 else ""
            price = float(parts[3]) if len(parts) > 3 and parts[3] else 0
            prev_close = float(parts[4]) if len(parts) > 4 and parts[4] else 0
            open_price = float(parts[5]) if len(parts) > 5 and parts[5] else 0
            change = float(parts[31]) if len(parts) > 31 and parts[31] else (price - prev_close)
            change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
            high = float(parts[33]) if len(parts) > 33 and parts[33] else 0
            low = float(parts[34]) if len(parts) > 34 and parts[34] else 0

            return {
                "code": code,
                "name": parts[1] if len(parts) > 1 else code,
                "price": price,
                "prev_close": prev_close,
                "open": open_price,
                "high": high,
                "low": low,
                "change": change,
                "change_pct": change_pct
            }
        except (IndexError, ValueError) as e:
            return {"error": str(e)}

    def get_index_quote(self, index_name: str) -> Dict[str, Any]:
        """
        获取大盘指数行情

        Args:
            index_name: 指数名称 (上证指数/深证成指/沪深300/创业板)

        Returns:
            指数行情数据
        """
        code = self.INDEX_CODES.get(index_name)
        if not code:
            return {"error": f"未知指数: {index_name}"}

        url = self.TENCENT_QUOTE_URL.format(symbols=code)
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            # 腾讯财经返回GBK编码
            text = response.content.decode('gbk', errors='replace')
            return self._parse_tencent_quote(text)
        except requests.RequestException as e:
            return {"error": f"网络错误: {str(e)}"}

    def get_all_indices(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有大盘指数行情

        Returns:
            所有指数行情数据
        """
        symbols = ",".join(self.INDEX_CODES.values())
        url = self.TENCENT_QUOTE_URL.format(symbols=symbols)

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            # 腾讯财经返回GBK编码
            text = response.content.decode('gbk', errors='replace')

            results = {}
            stock_data_list = re.findall(r'="([^"]+)"', text)
            for i, stock_data in enumerate(stock_data_list):
                parts = stock_data.split('~')
                if len(parts) >= 35:
                    index_name = list(self.INDEX_CODES.keys())[i]
                    parsed = self._parse_tencent_quote(stock_data)
                    if parsed and "error" not in parsed:
                        results[index_name] = parsed
            return results
        except requests.RequestException as e:
            return {"error": f"网络错误: {str(e)}"}

    def get_stock_pe_pb(self, code: str) -> Dict[str, Any]:
        """
        获取个股PE/PB等基本面数据 (使用新浪财经API)

        Args:
            code: 股票代码 (如 000001)

        Returns:
            基本面数据
        """
        # 根据代码判断市场
        if code.isdigit() and len(code) == 6:
            if code.startswith(('6', '601', '603', '605', '688')):
                nodes = ['sh_a']
            elif code.startswith(('0', '1', '2', '3')):
                nodes = ['sz_a']
            else:
                nodes = ['sh_a', 'sz_a', 'hs_a']
        else:
            nodes = ['sh_a', 'sz_a', 'hs_a']

        url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/'
        }

        try:
            # 搜索指定股票
            params = {
                'page': 1,
                'num': 100,
                'sort': 'symbol',
                'asc': 1,
                'node': 'hs_a',
                'symbol': '',
                '_s_r_a': 'page'
            }

            # 遍历所有可能的节点
            for node in nodes:
                params['node'] = node
                response = self.session.get(url, params=params, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()

                if data and isinstance(data, list):
                    for item in data:
                        if item.get('code') == code:
                            return {
                                "code": item.get("code", code),
                                "name": item.get("name", code),
                                "price": item.get("trade"),
                                "change": item.get("pricechange"),
                                "change_pct": item.get("changepercent"),
                                "pe": item.get("per"),
                                "pb": item.get("pb"),
                                "mktcap": item.get("mktcap"),
                                "nmc": item.get("nmc"),
                                "turnoverratio": item.get("turnoverratio")
                            }

            return {"error": "未找到数据", "code": code}
        except requests.RequestException as e:
            return {"error": f"网络错误: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "JSON解析错误"}
        except Exception as e:
            return {"error": str(e)}

    def get_stocks_pe_pb(self, codes: List[str]) -> List[Dict[str, Any]]:
        """
        批量获取个股PE/PB

        Args:
            codes: 股票代码列表

        Returns:
            基本面数据列表
        """
        results = []
        for code in codes:
            data = self.get_stock_pe_pb(code)
            if "error" not in data:
                results.append(data)
        return results

    def _get_stock_name(self, code: str) -> str:
        """通过腾讯接口获取股票名称"""
        try:
            # 6位代码判断市场
            if code.isdigit() and len(code) == 6:
                if code.startswith(('6', '601', '603', '605', '688')):
                    market = f"sh{code}"
                else:
                    market = f"sz{code}"
            else:
                market = code

            url = self.TENCENT_QUOTE_URL.format(symbols=market)
            response = self.session.get(url, timeout=5)
            # 腾讯财经返回GBK编码
            text = response.content.decode('gbk', errors='replace')
            match = re.search(r'="[^"]+~([^~]+)~', text)
            if match:
                return match.group(1)
        except:
            pass
        return code

    def get_limit_up_count(self) -> Dict[str, Any]:
        """
        获取涨跌停家数统计 (使用新浪财经API)

        Returns:
            涨跌停家数统计
        """
        # 使用新浪财经API - 通过涨跌幅排序获取涨停/跌停股票
        url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/'
        }

        try:
            # 获取涨幅榜 (涨停股票通常在涨幅榜前列)
            params_up = {
                'page': 1,
                'num': 100,
                'sort': 'changepercent',
                'asc': 0,  # 降序
                'node': 'hs_a',
                'symbol': '',
                '_s_r_a': 'page'
            }
            resp_up = self.session.get(url, params=params_up, headers=headers, timeout=10)
            resp_up.raise_for_status()
            data_up = resp_up.json()

            # 获取跌幅榜
            params_down = {
                'page': 1,
                'num': 100,
                'sort': 'changepercent',
                'asc': 1,  # 升序
                'node': 'hs_a',
                'symbol': '',
                '_s_r_a': 'page'
            }
            resp_down = self.session.get(url, params=params_down, headers=headers, timeout=10)
            resp_down.raise_for_status()
            data_down = resp_down.json()

            # 统计涨停家数 (涨幅>=9.9%)
            limit_up = sum(1 for s in data_up if isinstance(s, dict) and s.get('changepercent', 0) >= 9.9)
            # 统计跌停家数 (跌幅<=-9.9%)
            limit_down = sum(1 for s in data_down if isinstance(s, dict) and s.get('changepercent', 0) <= -9.9)

            return {
                "limit_up_count": limit_up,
                "limit_down_count": limit_down,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except requests.RequestException as e:
            return {"error": f"网络错误: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "JSON解析错误"}
        except Exception as e:
            return {"error": str(e)}

    def get_north_money_flow(self) -> Dict[str, Any]:
        """
        获取北向资金流向 (使用东方财富API)

        Returns:
            北向资金数据
        """
        params = {
            "fltt": 2,
            "invt": 2,
            "fields": "f12,f13,f14,f62"
        }

        try:
            response = self.session.get(self.EASTMONEY_NORTH_MONEY_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("data") and data["data"].get("diff"):
                diff = data["data"]["diff"]
                if diff:
                    item = diff[0]
                    return {
                        "name": item.get("f14", "北向资金"),
                        "north_money": item.get("f62", 0),  # 北向资金净流入 (单位：万元)
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
            return {"error": "未找到北向资金数据"}
        except requests.RequestException as e:
            return {"error": f"网络错误: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "JSON解析错误"}
        except Exception as e:
            return {"error": str(e)}

    def get_market_sentiment(self) -> Dict[str, Any]:
        """
        获取大盘情绪综合指标

        Returns:
            大盘情绪综合数据
        """
        sentiment = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "indices": {},
            "limit_up": None,
            "limit_down": None,
            "north_money": None
        }

        # 获取指数
        indices = self.get_all_indices()
        if "error" not in indices:
            sentiment["indices"] = indices

        # ?????
        limit_up_data = self.get_limit_up_count()
        if "error" not in limit_up_data:
            sentiment["limit_up"] = limit_up_data.get("limit_up_count", 0)
            sentiment["limit_down"] = limit_up_data.get("limit_down_count", 0)

        # 获取北向资金
        north = self.get_north_money_flow()
        if "error" not in north:
            sentiment["north_money"] = north

        # 计算情绪分数
        sentiment["sentiment_score"] = self._calculate_sentiment_score(sentiment)

        return sentiment

    def _calculate_sentiment_score(self, sentiment: Dict[str, Any]) -> Optional[float]:
        """
        计算市场情绪分数 (-100 ~ 100)

        依据:
        - 指数涨跌幅
        - 涨跌停家数比
        - 北向资金方向
        """
        score = 0.0
        count = 0

        # 指数权重
        if sentiment.get("indices"):
            index_scores = []
            for name, data in sentiment["indices"].items():
                if data.get("change_pct"):
                    # 涨跌幅转分数 (每1%算10分)
                    index_scores.append(data["change_pct"] * 10)
            if index_scores:
                score += sum(index_scores) / len(index_scores)
                count += 1

        # ???? (limit_up/limit_down ???????)
        if sentiment.get("limit_up") is not None:
            lu = sentiment.get("limit_up", 0)
            ld = sentiment.get("limit_down", 0)
            if lu + ld > 0:
                # ?????????????
                ratio = (lu - ld) / (lu + ld) * 50  # ??50
                score += ratio
                count += 1

        # ???? (north_money ???????)
        if sentiment.get("north_money") is not None:
            north = sentiment.get("north_money", 0)
            if north > 0:
                score += min(north / 10000, 30)  # ???30?
            else:
                score += max(north / 10000, -30)  # ???30?
            count += 1

        if count == 0:
            return None

        # 限制在-100~100
        return max(-100, min(100, round(score / count, 1)))

    def get_fundamental_summary(self, codes: List[str]) -> Dict[str, Any]:
        """
        获取股票基本面汇总

        Args:
            codes: 股票代码列表

        Returns:
            基本面汇总数据
        """
        fundamentals = []
        for code in codes:
            pe_pb = self.get_stock_pe_pb(code)
            if "error" not in pe_pb:
                fundamentals.append(pe_pb)

        if not fundamentals:
            return {"error": "未获取到任何基本面数据"}

        # 计算汇总统计
        valid_pe = [f["pe"] for f in fundamentals if f.get("pe") and f["pe"] > 0]
        valid_pb = [f["pb"] for f in fundamentals if f.get("pb") and f["pb"] > 0]

        return {
            "stocks": fundamentals,
            "summary": {
                "count": len(fundamentals),
                "avg_pe": round(sum(valid_pe) / len(valid_pe), 2) if valid_pe else None,
                "avg_pb": round(sum(valid_pb) / len(valid_pb), 2) if valid_pb else None,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }


# 便捷函数
_fetcher = None

def get_fetcher() -> FundamentalFetcher:
    """获取全局fetcher实例"""
    global _fetcher
    if _fetcher is None:
        _fetcher = FundamentalFetcher()
    return _fetcher

def get_stock_quote(index_name: str) -> Dict[str, Any]:
    """获取大盘指数行情"""
    return get_fetcher().get_index_quote(index_name)

def get_all_indices() -> Dict[str, Dict[str, Any]]:
    """获取所有大盘指数"""
    return get_fetcher().get_all_indices()

def get_stock_pe_pb(code: str) -> Dict[str, Any]:
    """获取个股PE/PB"""
    return get_fetcher().get_stock_pe_pb(code)

def get_limit_up_count() -> Dict[str, Any]:
    """获取涨跌停家数"""
    return get_fetcher().get_limit_up_count()

def get_north_money_flow() -> Dict[str, Any]:
    """获取北向资金"""
    return get_fetcher().get_north_money_flow()

def get_market_sentiment() -> Dict[str, Any]:
    """获取大盘情绪综合指标"""
    return get_fetcher().get_market_sentiment()

def get_fundamental_summary(codes: List[str]) -> Dict[str, Any]:
    """获取股票基本面汇总"""
    return get_fetcher().get_fundamental_summary(codes)


if __name__ == "__main__":
    # 测试
    fetcher = FundamentalFetcher()

    print("=" * 60)
    print("大盘指数")
    print("=" * 60)
    indices = fetcher.get_all_indices()
    for name, data in indices.items():
        print(f"{name}: {data.get('price', 0):.2f} ({data.get('change_pct', 0):+.2f}%)")

    print("\n" + "=" * 60)
    print("涨跌停家数")
    print("=" * 60)
    limit_up = fetcher.get_limit_up_count()
    print(f"涨停: {limit_up.get('limit_up_count', 'N/A')} | 跌停: {limit_up.get('limit_down_count', 'N/A')}")

    print("\n" + "=" * 60)
    print("北向资金")
    print("=" * 60)
    north = fetcher.get_north_money_flow()
    print(f"净流入: {north.get('north_money', 'N/A')} 万元")

    print("\n" + "=" * 60)
    print("大盘情绪综合")
    print("=" * 60)
    sentiment = fetcher.get_market_sentiment()
    print(f"情绪分数: {sentiment.get('sentiment_score', 'N/A')}")

    print("\n" + "=" * 60)
    print("个股基本面测试 (平安银行 000001)")
    print("=" * 60)
    fundamental = fetcher.get_stock_pe_pb("000001")
    print(fundamental)
