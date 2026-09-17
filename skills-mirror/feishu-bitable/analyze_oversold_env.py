#!/usr/bin/env python3
"""分析超跌反弹策略在不同市场环境下的表现"""
from core.compat_paths import MARKET_DB as _DB_PATH
MARKET_DB = _DB_PATH

import os, sys, json, sqlite3, math, statistics, calendar
from datetime import datetime
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
import backtest_engine as be


def get_market_snapshot(conn, date_str):
    """获取某日市场状态"""
    cur = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN close < open THEN 1 ELSE 0 END) as down_count
        FROM klines WHERE date = ? AND close > 0 AND open > 0
    """, (date_str,))
    r = cur.fetchone()
    if r and r[0] > 100:
        return {"total": r[0], "down_pct": r[1] / r[0] * 100}
    return None

def run_analysis():
    conn = be._get_db()
    
    # 加载股票池和K线数据
    universe = be.load_stock_universe(conn, min_trade_days=200)
    print(f"股票池: {len(universe)} 只", file=sys.stderr)
    
    data = be.load_monthly_kline_data(conn, universe, "2023-07-01", "2026-07-31")
    snapshots = be.get_monthly_snapshots(data)
    print(f"月频调仓: {len(snapshots)} 个月", file=sys.stderr)
    
    # 获取策略
    strategy_fn = be._strategy_lowvol_highroe_oversold
    
    # 逐月分析
    monthly_records = []
    next_open_lookup = be.build_next_open_lookup(data)
    
    for i in range(1, len(snapshots)):
        prev_date, prev_prices = snapshots[i-1]
        curr_date, curr_prices = snapshots[i]
        
        selected = strategy_fn(prev_date, prev_prices, top_n=30)
        if not selected:
            continue
        
        # 获取该月市场状态
        mkt = get_market_snapshot(conn, prev_date)
        if not mkt:
            continue
        
        # 获取前一个月的市场状态（用于判断趋势）
        prev_mkt = get_market_snapshot(conn, snapshots[i-2][0]) if i >= 2 else None
        
        # 计算该月组合收益
        returns = []
        for code in selected:
            if code in prev_prices and code in curr_prices:
                signal_close = prev_prices[code]
                next_info = next_open_lookup.get(code, {}).get(prev_date, None)
                if next_info and next_info["open"] > 0:
                    buy_price = next_info["open"]
                    if signal_close > 0 and next_info["open"] > signal_close * 1.03:
                        continue
                else:
                    buy_price = signal_close
                raw_return = (curr_prices[code] - buy_price) / buy_price * 100
                pos = 1.0 / len(selected)
                cost = be.calc_trade_cost(pos, pos * (1 + raw_return/100))
                net_r = raw_return - cost / pos * 100
                returns.append(net_r)
        
        if returns:
            avg_ret = sum(returns) / len(returns)
            monthly_records.append({
                "month": prev_date[:7],
                "return": avg_ret,
                "is_win": avg_ret > 0,
                "market_down_pct": round(mkt["down_pct"], 1),
                "market_total": mkt["total"],
                "n_stocks": len(selected),
                "prev_market_down_pct": round(prev_mkt["down_pct"], 1) if prev_mkt else None,
            })
    
    conn.close()
    
    # 分析
    print(f"\n{'='*60}")
    print(f"超跌反弹策略 2023-07 ~ 2026-07 月频归因分析")
    print(f"{'='*60}")
    print(f"总月数: {len(monthly_records)}")
    print(f"盈利月: {sum(1 for r in monthly_records if r['is_win'])} ({sum(1 for r in monthly_records if r['is_win'])/len(monthly_records)*100:.1f}%)")
    print(f"亏损月: {sum(1 for r in monthly_records if not r['is_win'])}")
    
    # 按市场环境分组
    print(f"\n--- 按下跌占比分组 ---")
    for threshold in [30, 40, 50, 60, 70]:
        subset = [r for r in monthly_records if r['market_down_pct'] >= threshold]
        if subset:
            win = sum(1 for r in subset if r['is_win'])
            avg_ret = sum(r['return'] for r in subset) / len(subset)
            print(f"  下跌占比≥{threshold}%: {len(subset)}个月, 胜率{win/len(subset)*100:.1f}%, 均收益{avg_ret:+.2f}%")
    
    for threshold in [30, 40, 50, 60]:
        subset = [r for r in monthly_records if r['market_down_pct'] < threshold]
        if subset:
            win = sum(1 for r in subset if r['is_win'])
            avg_ret = sum(r['return'] for r in subset) / len(subset)
            print(f"  下跌占比<{threshold}%: {len(subset)}个月, 胜率{win/len(subset)*100:.1f}%, 均收益{avg_ret:+.2f}%")
    
    # 按市场极端恐慌分组（下跌占比>80%）
    panic = [r for r in monthly_records if r['market_down_pct'] > 80]
    if panic:
        win = sum(1 for r in panic if r['is_win'])
        avg_ret = sum(r['return'] for r in panic) / len(panic)
        print(f"\n--- 极端恐慌(下跌>80%) ---")
        print(f"  {len(panic)}个月, 胜率{win/len(panic)*100:.1f}%, 均收益{avg_ret:+.2f}%")
        for r in panic:
            print(f"    {r['month']}: 收益{r['return']:+.2f}%, 市场下跌{r['market_down_pct']}%")
    
    # 最佳/最差月份
    sorted_by_ret = sorted(monthly_records, key=lambda r: r['return'])
    print(f"\n--- 最差5个月 ---")
    for r in sorted_by_ret[:5]:
        print(f"  {r['month']}: {r['return']:+.2f}%, 市场下跌{r['market_down_pct']}%")
    print(f"\n--- 最佳5个月 ---")
    for r in sorted_by_ret[-5:]:
        print(f"  {r['month']}: {r['return']:+.2f}%, 市场下跌{r['market_down_pct']}%")
    
    # 连续恐慌测试
    print(f"\n--- 连续恐慌测试 ---")
    # 模拟：仅当连续3日下跌>80%时启用，否则空仓
    # 使用月频数据近似（实际需要日频）
    panic_months = sum(1 for r in monthly_records if r['market_down_pct'] > 70)
    print(f"  下跌>70%的月份: {panic_months}/{len(monthly_records)}")
    
    # 如果只在灾难月启用
    disaster = [r for r in monthly_records if r['market_down_pct'] > 80]
    if disaster:
        total_ret = sum(r['return'] for r in disaster)
        print(f"  只在恐慌月(>80%)启用: {len(disaster)}笔交易, 累计收益{total_ret:+.2f}%")
    
    # 如果只在相对恐慌月(>60%)启用
    semi_panic = [r for r in monthly_records if r['market_down_pct'] > 60]
    if semi_panic:
        total_ret = sum(r['return'] for r in semi_panic)
        wins = sum(1 for r in semi_panic if r['is_win'])
        print(f"  只在恐慌月(>60%)启用: {len(semi_panic)}笔交易, 胜率{wins/len(semi_panic)*100:.1f}%, 累计收益{total_ret:+.2f}%")

if __name__ == "__main__":
    run_analysis()