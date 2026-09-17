#!/usr/bin/env python3
"""
盘前简报脚本
调度时间：每个交易日 08:30
"""
import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])

from feishu_sender import send_pre_market_brief, feishu_send_message
import json


def is_trading_day():
    """检查今天是否为 A 股交易日，非交易日则直接退出
    注意：akshare.tool_trade_date_hist_sina() 在部分环境会永久阻塞（py_mini_racer +
    requests 无超时机制），故通过日期判断 + curl 备用验证。
    """
    import subprocess, datetime

    today = datetime.date.today()
    # 简单判断：周六(5)、周日(6) 非交易日
    if today.weekday() >= 5:
        print(f"今日 ({today}) 是周末，跳过执行")
        return False

    # 用 curl 直接验证（可连通即认为接口正常）
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '6',
             'https://finance.sina.com.cn/realstock/company/klc_td_sh.txt'],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0 and len(result.stdout) > 100:
            # curl 返回加密的交易日历，只要能获取到数据即认为正常
            return True
    except Exception:
        pass

    # curl 也失败，但只要不是周末就继续（保守假设是交易日）
    print(f"交易日验证接口不可用，假设 ({today}) 为交易日继续执行")
    return True


def main():
    if not is_trading_day():
        return
    try:
        # 1. 获取美股夜盘数据（使用新浪批量接口，腾讯接口在部分环境不通）
        us_indices = {}
        us_symbols_map = {
            "纳斯达克100": "gb_ndx",
            "标普500": "gb_spy",
            "道琼斯": "gb_dia",
            "金龙中国": "gb_gxy",
        }
        try:
            import requests as _req
            _headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
            _url = "http://hq.sinajs.cn/list=" + ",".join(us_symbols_map.values())
            _r = _req.get(_url, headers=_headers, timeout=10)
            import re
            for name, sina_code in us_symbols_map.items():
                m = re.search(rf'hq_str_{sina_code}="([^"]+)"', _r.text)
                if m:
                    fields = m.group(1).split(",")
                    if len(fields) > 4:
                        price = float(fields[1])
                        change_pct = float(fields[2]) if fields[2] else 0.0
                        us_indices[name] = {
                            "code": name, "name": name,
                            "price": price, "change_pct": change_pct
                        }
        except Exception:
            pass

        # 2. 获取A50期货（盘中用，08:30时用隔夜美股代替）
        a50_pct = 0.0
        try:
            fetcher = FundamentalFetcher()
            idx = fetcher.get_index_quote()
            if idx:
                # 用上证指数代替A50
                sh = idx.get("sh000001", {})
                if sh:
                    a50_pct = sh.get("change_pct", 0)
        except Exception:
            pass

        # 3. 获取大盘情绪（使用新浪接口，腾讯接口在部分环境不通）
        sentiment = {}
        try:
            import requests as _req, re as _re
            _h = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
            _url = "http://hq.sinajs.cn/list=sh000001,sz399001,sh000300,sz399006"
            _r = _req.get(_url, headers=_h, timeout=10)
            _index_map = {"sh000001": "上证指数", "sz399001": "深证成指",
                          "sh000300": "沪深300", "sz399006": "创业板"}
            _indices = {}
            for _code, _name in _index_map.items():
                _m = _re.search(rf'hq_str_{_code}="([^"]+)"', _r.text)
                if _m:
                    _fields = _m.group(1).split(",")
                    if len(_fields) > 5:
                        _prev = float(_fields[2]); _cur = float(_fields[3])
                        _indices[_name] = {
                            "code": _code[2:], "name": _name,
                            "price": _cur, "prev_close": _prev,
                            "open": float(_fields[1]),
                            "high": float(_fields[4]),
                            "low": float(_fields[5]),
                            "change": round(_cur - _prev, 2),
                            "change_pct": round((_cur - _prev) / _prev * 100, 2) if _prev else 0
                        }
            sentiment = {"timestamp": "2026-05-05 08:00:00", "indices": _indices,
                         "limit_up": None, "limit_down": None, "north_money": None}
        except Exception:
            pass

        # 4. 发送盘前简报
        result = send_pre_market_brief(us_indices, a50_pct, sentiment)
        if result.get("ok"):
            print("盘前简报发送成功")
        else:
            print(f"发送失败: {result}")
            # 降级：尝试直接发文本
            lines = ["🌅 【盘前简报】", ""]
            for name, info in us_indices.items():
                pct = info.get("change_pct", 0)
                sign = "+" if pct >= 0 else ""
                lines.append(f"{name}: {info.get('price','N/A')}（{sign}{pct:.2f}%）")
            feishu_send_message("\n".join(lines))

    except Exception as e:
        error_msg = f"盘前简报异常: {str(e)}"
        print(error_msg)
        feishu_send_message(f"⚠️ {error_msg}")


if __name__ == "__main__":
    main()
