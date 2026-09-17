#!/usr/bin/env python3
"""
持仓诊断脚本
调度时间：每个交易日 09:15（开盘后）和 16:30（收盘后）
用法：python3 position_diagnosis.py [check|today]
  check: 运行诊断并发送报告
  today: 仅发送今日持仓摘要（轻量版）
"""
import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])

import signal
import akshare as ak
import pandas as pd
from datetime import date
from bitable_reader import read_positions


def is_trading_day():
    """检查今天是否为 A 股交易日，非交易日则直接退出"""
    try:
        df = ak.tool_trade_date_hist_sina()
        trading_dates = set(pd.to_datetime(df['trade_date']).dt.date)
        if date.today() not in trading_dates:
            print(f"今日 ({date.today()}) 非 A 股交易日，跳过执行")
            return False
    except Exception as e:
        print(f"交易日判断异常: {e}，继续执行")
    return True
from stock_data import get_stock_quote
from signal_engine import SignalEngine
from fundamental import FundamentalFetcher
from feishu_sender import send_position_digest, feishu_send_message


# 5分钟硬性超时保护
def timeout_handler(signum, frame):
    print("TIMEOUT: 脚本执行超过5分钟，强制终止")
    sys.exit(1)
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(300)


def get_market_summary():
    """获取大盘指数快照"""
    indices = {}
    index_map = {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
        "sh000300": "沪深300",
    }
    for code, name in index_map.items():
        try:
            # 去掉sh/sz前缀得到纯数字
            num = code[2:]
            market = "A"
            q = get_stock_quote(market, num)
            if "error" not in q:
                indices[code] = q
        except Exception:
            pass
    return indices


def main():
    if not is_trading_day():
        return
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"

    try:
        # 获取大盘情绪
        market_summary = {}
        try:
            fetcher = FundamentalFetcher()
            market_summary = get_market_summary()
        except Exception as e:
            print(f"获取大盘数据失败: {e}")

        # 持仓分析
        positions = []
        try:
            engine = SignalEngine()
            raw_positions = engine.analyze_all_positions()
            # 转换为字典（send_position_digest期望dict）
            positions = []
            for p in raw_positions:
                if hasattr(p, 'to_dict'):
                    d = p.to_dict()
                    # 把advice字段也展开
                    if p.advice:
                        d['signal_level'] = p.advice.signal_level
                        d['action'] = p.advice.action
                        d['stop_loss'] = p.advice.stop_loss
                        d['take_profit'] = p.advice.take_profit_1
                        d['reasons'] = p.advice.reasons
                    else:
                        d['signal_level'] = 0
                        d['action'] = '持有'
                        d['stop_loss'] = 0
                        d['take_profit'] = 0
                        d['reasons'] = []
                    positions.append(d)
                else:
                    positions.append(p)
        except Exception as e:
            print(f"持仓分析异常: {e}")
            feishu_send_message(f"⚠️ 持仓诊断异常: {str(e)}")
            return

        # 发送诊断摘要
        if positions:
            result = send_position_digest(positions, market_summary)
            if result.get("ok"):
                print(f"持仓诊断发送成功，共{len(positions)}只股票")
            else:
                print(f"发送失败: {result}")
        else:
            feishu_send_message("⚠️ 未能获取到持仓数据，请检查bitable连接")

    except Exception as e:
        error_msg = f"持仓诊断异常: {str(e)}"
        print(error_msg)
        feishu_send_message(f"⚠️ {error_msg}")


if __name__ == "__main__":
    main()
