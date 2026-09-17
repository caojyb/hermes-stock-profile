#!/usr/bin/env python3
"""
回测中间过程验证 — 输出调仓日明细
"""
import sys, os
sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')

from backtest_engine import (
    _get_db, get_monthly_snapshots, load_monthly_kline_data,
    build_next_open_lookup, smart_money_filter, calc_metrics,
    calc_benchmark_metrics, calc_trade_cost, calc_market_down_pct,
    _strategy_lowvol_highroe_main_up as strategy_fn, load_stock_universe
)

# 参数
START = "2023-07"
END = "2026-07"
TOP_N = 30

print("=" * 80)
print("📊 主升浪策略回测 — 中间过程明细")
print("=" * 80)
print(f"  区间: {START} ~ {END}")
print(f"  选股: Top {TOP_N}")
print()

# 1. 加载数据
print("📡 加载数据...")
conn = _get_db()
universe = load_stock_universe(conn, min_trade_days=200)
print(f"  股票池: {len(universe)} 只")

start_full = "2023-07-01"
end_full = "2026-07-31"
data = load_monthly_kline_data(conn, universe, start_full, end_full)
conn.close()
print(f"  股票: {len(data)} 只")

# 2. 提取月频调仓快照
snapshots = get_monthly_snapshots(data)
print(f"  调仓月: {len(snapshots)} 个月")
print()

# 3. 构建次日开盘价查找表
next_open_lookup = build_next_open_lookup(data)

# 4. 获取数据库连接（用于聪明钱过滤器）
filter_conn = _get_db()

# 5. 逐月回测（带详细输出）
monthly_returns = []
equity = [1.0]
total_gapup_fails = 0
total_trades = 0
total_smart_filtered = 0
print_dates = 0  # 已打印的调仓日计数

print(f"{'='*80}")
print(f"📋 调仓日明细（前10个调仓日，每日前5只买入股票）")
print(f"{'='*80}")

for i in range(1, len(snapshots)):
    prev_date, prev_prices = snapshots[i - 1]
    curr_date, curr_prices = snapshots[i]

    # 策略选股
    selected = strategy_fn(prev_date, prev_prices, top_n=TOP_N)
    if not selected:
        continue

    # 打印前10个调仓日
    if print_dates < 10:
        print(f"\n  📅 调仓日 {print_dates+1}: {prev_date} → {curr_date}")
        print(f"    选股: {len(selected)} 只")

        # 前5只股票详情
        for j, code in enumerate(selected[:5]):
            # 获取股票名称
            c = filter_conn.cursor()
            c.execute("SELECT name FROM stocks WHERE code=?", [code])
            name_row = c.fetchone()
            name = name_row[0] if name_row else ""

            # 信号价格
            signal_close = prev_prices.get(code, 0)

            # 次日开盘价
            next_info = next_open_lookup.get(code, {}).get(prev_date, None)
            if next_info and next_info["open"] > 0:
                buy_price = next_info["open"]
                gapup = (buy_price / signal_close - 1) * 100 if signal_close > 0 else 0
                gapup_str = f"跳空{gapup:+.1f}%"
            else:
                buy_price = signal_close
                gapup_str = "无次日数据"

            # 聪明钱过滤器
            smart_pass = smart_money_filter(code, prev_date, data, filter_conn)

            print(f"    {j+1}. {code:<8s} {name:<12s} "
                  f"信号价{signal_close:>8.2f} 开盘价{buy_price:>8.2f} "
                  f"{gapup_str:<15s} {'✅' if smart_pass else '❌拦截'}")

        print_dates += 1

    # 执行回测（同上）
    returns = []
    for code in selected:
        total_trades += 1
        if code in prev_prices and code in curr_prices:
            signal_close = prev_prices[code]

            next_info = next_open_lookup.get(code, {}).get(prev_date, None)
            if next_info and next_info["open"] > 0:
                buy_price = next_info["open"]
                next_open = next_info["open"]

                if signal_close > 0 and next_open > signal_close * 1.03:
                    total_gapup_fails += 1
                    continue

                if not smart_money_filter(code, prev_date, data, filter_conn):
                    total_smart_filtered += 1
                    continue
            else:
                buy_price = signal_close

            sell_price = curr_prices[code]
            raw_return = (sell_price - buy_price) / buy_price * 100
            position_value = 1.0 / len(selected)
            buy_amount = position_value
            raw_ratio = max(-0.999, raw_return / 100)
            sell_amount = position_value * (1 + raw_ratio)
            cost = calc_trade_cost(buy_amount, sell_amount)
            cost_pct = cost / position_value * 100
            net_return = raw_return - cost_pct
            returns.append(net_return)

    if returns:
        avg_ret = sum(returns) / len(returns)
        monthly_returns.append(avg_ret)
        equity.append(equity[-1] * (1 + avg_ret / 100))

# 6. 最终统计
print(f"\n{'='*80}")
print(f"📊 最终统计")
print(f"{'='*80}")

metrics = calc_metrics(monthly_returns, equity)
print(f"  年化收益: {metrics['cagr_pct']:.2f}%")
print(f"  最大回撤: {metrics['max_drawdown_pct']:.2f}%")
print(f"  夏普比率: {metrics['sharpe_ratio']:.2f}")
print(f"  月胜率: {metrics['win_rate_pct']:.1f}%")
print(f"  盈亏比: {metrics['profit_loss_ratio']:.2f}")
print(f"  累计收益: {metrics['total_return_pct']:.2f}%")
print(f"  终值: {equity[-1]:.4f}")
print(f"  月数: {len(monthly_returns)}")
print(f"  跳空无法买入: {total_gapup_fails}/{total_trades} 次")
print(f"  聪明钱拦截: {total_smart_filtered} 次")

filter_conn.close()