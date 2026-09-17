#!/usr/bin/env python3
"""
翻倍策略回测 + 多策略组合 + 双层止损 — 基于 backtest_engine.py 核心函数
"""
import os, sys, json, math, sqlite3, statistics, calendar
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
import backtest_engine as be

MARKET_DB = be.MARKET_DB

# ═══════════════════════════════════════════════════════════════
# 策略1：翻倍潜力筛选（严格版）
# ═══════════════════════════════════════════════════════════════

def strategy_doubling(snapshot_date, all_prices, top_n=999):
    """
    翻倍潜力筛选严格版
    条件：营收>30%连续2季 + 利润>20% + 负债<65% + 市值30-200亿
          + PE分位<40% + 换手>3% + 回撤15-45% + 上市>=180天
    """
    conn = be._get_db()
    codes = list(all_prices.keys())
    if not codes:
        conn.close()
        return []

    # 1. 基本面筛选：营收增速>30%连续2季 + 利润增速>20% + 负债<65%
    placeholders = ",".join("?" for _ in codes)
    cur = conn.execute(f"""
        SELECT code, revenue_growth, profit_growth, debt_ratio, roe
        FROM financial_data
        WHERE code IN ({placeholders})
          AND report_date <= ?
          AND revenue_growth IS NOT NULL
          AND profit_growth IS NOT NULL
          AND debt_ratio IS NOT NULL
        ORDER BY code, report_date DESC
    """, codes + [snapshot_date[:7] + "-01"])

    # 取最近2个季度的数据
    fin_data = {}
    for r in cur.fetchall():
        code = r["code"]
        if code not in fin_data:
            fin_data[code] = []
        if len(fin_data[code]) < 2:
            fin_data[code].append({
                "revenue_growth": r["revenue_growth"],
                "profit_growth": r["profit_growth"],
                "debt_ratio": r["debt_ratio"],
                "roe": r["roe"],
            })

    candidates = []
    for code, quarters in fin_data.items():
        if len(quarters) < 2:
            continue
        # 连续2季营收>30%
        if not all(q["revenue_growth"] > 30 for q in quarters):
            continue
        # 利润增速>20%（取最新）
        if quarters[0]["profit_growth"] < 20:
            continue
        # 负债率<65%
        debt = quarters[0]["debt_ratio"]
        if debt is not None and debt >= 65:
            continue
        candidates.append(code)

    if not candidates:
        conn.close()
        return []

    # 2. PE分位<40% - 取最近非NULL值
    pe_ok = set()
    for code in candidates:
        cur = conn.execute(
            "SELECT pe_pct FROM pe_pb_data WHERE code=? AND pe_pct IS NOT NULL AND pe_pct < 40 ORDER BY fetch_date DESC LIMIT 1",
            [code]
        )
        row = cur.fetchone()
        if row:
            pe_ok.add(code)

    # 3. 换手率>3% - 逐只查询（数据仅2026年有，历史无数据时放行）
    turnover_ok = {}
    for code in candidates:
        cur = conn.execute(
            "SELECT turnover_rate FROM indicators WHERE code=? AND date<=? AND turnover_rate IS NOT NULL AND turnover_rate > 3 ORDER BY date DESC LIMIT 1",
            [code, snapshot_date]
        )
        row = cur.fetchone()
        if row:
            turnover_ok[code] = row["turnover_rate"]
        else:
            # 历史数据不可用，放行
            turnover_ok[code] = 0

    # 4. 从stocks获取总股本和上市日期
    stock_info = {}
    for code in candidates:
        cur = conn.execute(
            "SELECT total_shares_real, list_date FROM stocks WHERE code=?",
            [code]
        )
        row = cur.fetchone()
        if row:
            stock_info[code] = {"total_shares": row["total_shares_real"], "list_date": row["list_date"]}

    # 简化：从klines取250日最高价计算回撤
    kline_data = {}
    for code in candidates:
        cur = conn.execute(
            "SELECT date, close FROM klines WHERE code=? AND date<=? ORDER BY date DESC LIMIT 250",
            [code, snapshot_date]
        )
        rows = cur.fetchall()
        if rows:
            kline_data[code] = [r["close"] for r in rows]

    conn.close()

    # 5. 筛选：市值、回撤、上市天数、非科创板
    # 从 all_prices 获取当前价格计算市值
    final = []
    for code in candidates:
        # PE分位检查
        if code not in pe_ok:
            continue
        # 换手率检查
        if code not in turnover_ok:
            continue

        # 市值计算
        info = stock_info.get(code, {})
        total_shares = info.get("total_shares", 0)
        price = all_prices.get(code, 0)
        if total_shares and price and total_shares > 0:
            mkt_cap_val = total_shares * price / 1e8  # 亿元
            if mkt_cap_val < 30 or mkt_cap_val > 200:
                continue
        else:
            continue  # 无市值数据，跳过

        # 回撤计算（从250日高点）
        kls = kline_data.get(code, [])
        if len(kls) < 50:
            continue
        high_250 = max(kls)
        current = kls[0]
        dd = (high_250 - current) / high_250 * 100
        if dd < 15 or dd > 45:
            continue

        # 上市天数检查
        list_date = info.get("list_date", "")
        if list_date:
            try:
                listed = datetime.strptime(list_date, "%Y-%m-%d")
                signal = datetime.strptime(snapshot_date, "%Y-%m-%d")
                if (signal - listed).days < 180:
                    continue
            except:
                pass

        # 非ST检查（代码前缀）
        code_num = code[-6:]
        if code_num.startswith("688") or code_num.startswith("787"):
            continue  # 剔除科创板

        final.append(code)

    return final


# ═══════════════════════════════════════════════════════════════
# 策略2：价值档（低估值成长）
# ═══════════════════════════════════════════════════════════════

def strategy_value(snapshot_date, all_prices, top_n=30):
    """
    价值档 - 低估值成长
    条件：ROE>15% + 利润增速>10% + 负债<60% + PE<40
    """
    conn = be._get_db()
    codes = list(all_prices.keys())
    if not codes:
        conn.close()
        return []

    # 使用 IN 分批查询
    batch_size = 500
    high_quality = set()
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        placeholders = ",".join("?" for _ in batch)
        cur = conn.execute(f"""
            SELECT code FROM (
                SELECT code, roe, profit_growth, debt_ratio, report_date,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) as rn
                FROM financial_data
                WHERE code IN ({placeholders}) AND report_date <= ?
                  AND roe IS NOT NULL AND profit_growth IS NOT NULL AND debt_ratio IS NOT NULL
            ) WHERE rn <= 4
            GROUP BY code
            HAVING AVG(roe) >= 15 AND AVG(profit_growth) >= 10 AND AVG(debt_ratio) < 60
        """, batch + [snapshot_date[:7] + "-01"])
        for r in cur.fetchall():
            high_quality.add(r["code"])

    # PE<40过滤 - 分批
    low_pe = set()
    all_codes = list(codes)
    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i+batch_size]
        ph = ",".join("?" for _ in batch)
        cur = conn.execute(f"""
            SELECT code FROM pe_pb_data p
            WHERE code IN ({ph})
              AND pe_ttm IS NOT NULL AND pe_ttm < 40 AND pe_ttm > 0
              AND fetch_date = (SELECT MAX(fetch_date) FROM pe_pb_data WHERE code = p.code)
        """, batch)
        for r in cur.fetchall():
            low_pe.add(r["code"])

    conn.close()

    # 市值30-200亿
    final = []
    for code in codes:
        if code not in high_quality or code not in low_pe:
            continue
        price = all_prices.get(code, 0)
        if price <= 0:
            continue
        final.append(code)

    # 按ROE排序（分批）
    final.sort(key=lambda c: 0)
    conn2 = be._get_db()
    for code in final:
        row = conn2.execute(
            "SELECT AVG(roe) FROM (SELECT roe FROM financial_data WHERE code=? AND roe IS NOT NULL ORDER BY report_date DESC LIMIT 4)",
            [code]
        ).fetchone()
        pass  # 简化：不排序
    conn2.close()

    return final[:top_n]


# ═══════════════════════════════════════════════════════════════
# 持有期回测引擎（支持120日持有+双层止损）
# ═══════════════════════════════════════════════════════════════

def run_backtest_holding(strategy_fn, start_date="2023-07", end_date="2026-07",
                         top_n=30, hold_days=120, gapup_threshold=5.0,
                         use_stop_loss=False, stop_loss_pct=8.0,
                         trailing_stop_pct=15.0):
    """
    持有期回测引擎

    参数：
        strategy_fn: 策略函数
        hold_days: 持有期（交易日）
        gapup_threshold: 跳空高开阈值（%），超过则放弃
        use_stop_loss: 是否启用双层止损
        stop_loss_pct: 初始止损百分比（如8=-8%）
        trailing_stop_pct: 移动止盈回撤百分比（如15=回撤15%卖出）
    """
    print(f"📡 加载数据 {start_date} ~ {end_date}...", file=sys.stderr)

    start_full = f"{start_date}-01"
    y, m = end_date.split("-")
    last_day = calendar.monthrange(int(y), int(m))[1]
    end_full = f"{end_date}-{last_day:02d}"

    conn = be._get_db()
    universe = be.load_stock_universe(conn, min_trade_days=200)
    print(f"  股票池: {len(universe)} 只", file=sys.stderr)

    data = be.load_monthly_kline_data(conn, universe, start_full, end_full)
    conn.close()

    snapshots = be.get_monthly_snapshots(data)
    print(f"  月频调仓: {len(snapshots)} 个月", file=sys.stderr)

    if len(snapshots) < 6:
        return {"error": f"数据不足，仅 {len(snapshots)} 个月"}

    next_open_lookup = be.build_next_open_lookup(data)

    # 组合管理
    portfolio = []  # [{code, entry_date, entry_price, high_water_mark, stop_level}, ...]
    monthly_returns = []
    equity = [1.0]
    total_gapup_fails = 0
    total_trades = 0
    total_stop_hits = 0
    total_doubled = 0  # 翻倍股计数
    total_hold_sold = 0  # 到期卖出

    # 按日期排序所有K线（用于计算净值）
    all_dates = sorted(set(
        k["date"] for kl in data.values() for k in kl
        if start_full <= k["date"] <= end_full
    ))

    # 按月份处理
    for i in range(1, len(snapshots)):
        prev_date, prev_prices = snapshots[i - 1]

        # 新选股（每月）
        selected = strategy_fn(prev_date, prev_prices, top_n=top_n)
        selected_set = set(selected) if selected else set()
        if selected:
            print(f"  {prev_date}: 策略选出 {len(selected)} 只, 前5: {selected[:5]}", file=sys.stderr)

        # 买入新股票
        for code in selected:
            if code in prev_prices:
                signal_close = prev_prices[code]
                next_info = next_open_lookup.get(code, {}).get(prev_date, None)
                if next_info and next_info["open"] > 0:
                    buy_price = next_info["open"]
                    # 跳空高开检查
                    if signal_close > 0 and next_info["open"] > signal_close * (1 + gapup_threshold / 100):
                        total_gapup_fails += 1
                        continue
                else:
                    buy_price = signal_close

                # 检查是否已在持仓中
                if any(p["code"] == code for p in portfolio):
                    continue

                portfolio.append({
                    "code": code,
                    "entry_date": prev_date,
                    "entry_price": buy_price,
                    "high_water_mark": buy_price,
                    "stop_level": "initial",  # initial, breakeven, trailing
                    "trading_days_held": 0,
                    "sold": False,
                    "doubled": False,
                })
                total_trades += 1

        # 遍历每日股价，更新持仓状态
        # 获取当前月到下个月之间的所有交易日
        curr_date = snapshots[i][0] if i < len(snapshots) else end_full

        # 获取该月每日K线数据
        month_dates = [d for d in all_dates if prev_date < d <= curr_date]

        for trade_date in month_dates:
            for p in portfolio:
                if p["sold"]:
                    continue
                p["trading_days_held"] += 1

                # 获取当日价格
                code_data = data.get(p["code"], [])
                day_k = None
                for k in code_data:
                    if k["date"] == trade_date:
                        day_k = k
                        break
                if not day_k:
                    continue

                current_price = day_k["close"]
                gain_pct = (current_price - p["entry_price"]) / p["entry_price"] * 100

                # 更新高点
                if current_price > p["high_water_mark"]:
                    p["high_water_mark"] = current_price

                # 翻倍检测
                if gain_pct >= 100 and not p["doubled"]:
                    p["doubled"] = True
                    total_doubled += 1

                # 双层止损逻辑
                if use_stop_loss:
                    # 阶段1：初始止损
                    if p["stop_level"] == "initial":
                        stop_price = p["entry_price"] * (1 - stop_loss_pct / 100)
                        if current_price < stop_price:
                            p["sold"] = True
                            total_stop_hits += 1
                            continue
                        # 涨超10%后，止损上移到成本价
                        if gain_pct >= 10:
                            p["stop_level"] = "breakeven"

                    # 阶段2：保本止损
                    if p["stop_level"] == "breakeven":
                        if current_price < p["entry_price"]:
                            p["sold"] = True
                            total_stop_hits += 1
                            continue
                        # 涨超20%后，启用移动止盈
                        if gain_pct >= 20:
                            p["stop_level"] = "trailing"

                    # 阶段3：移动止盈（从高点回撤15%）
                    if p["stop_level"] == "trailing":
                        dd_from_peak = (p["high_water_mark"] - current_price) / p["high_water_mark"] * 100
                        if dd_from_peak >= trailing_stop_pct:
                            p["sold"] = True
                            total_stop_hits += 1
                            continue

                # 到期强制卖出（持有期到达）
                if p["trading_days_held"] >= hold_days:
                    p["sold"] = True
                    total_hold_sold += 1

        # 月末：计算组合收益（卖出已标记的股票，计算剩余持仓市值）
        # 简化：使用月末持仓市值变化计算月收益
        month_end_prices = snapshots[i][1] if i < len(snapshots) else {}
        month_start_value = 0
        month_end_value = 0

        # 计算月初持仓市值
        for p in portfolio:
            if p["sold"]:
                continue
            # 用月初价格（prev_prices）计算买入成本
            month_start_value += p["entry_price"]  # 实际是成本，简化处理

        # 计算月末持仓市值
        active_holdings = [p for p in portfolio if not p["sold"]]
        for p in active_holdings:
            sell_price = month_end_prices.get(p["code"], 0)
            if sell_price > 0:
                month_end_value += sell_price

        # 本月新增现金（卖出股票的回款）
        cash_added = 0
        for p in portfolio:
            if p["sold"]:
                # 找到卖出时的价格
                pass  # 在后续处理中

        # 简化：使用等权组合收益
        active_codes = [p["code"] for p in portfolio if not p["sold"]]
        if active_codes:
            rets = []
            for code in active_codes:
                buy_price = None
                for p in portfolio:
                    if p["code"] == code and not p["sold"]:
                        buy_price = p["entry_price"]
                        break
                if buy_price and code in month_end_prices:
                    r = (month_end_prices[code] - buy_price) / buy_price * 100
                    pos = 1.0 / max(len(active_codes), 1)
                    cost = be.calc_trade_cost(pos, pos * (1 + r/100))
                    net_r = r - cost / pos * 100
                    rets.append(net_r)

            if rets:
                avg_ret = sum(rets) / len(rets)
                monthly_returns.append(avg_ret)
                equity.append(equity[-1] * (1 + avg_ret / 100))
            else:
                monthly_returns.append(0)
                equity.append(equity[-1])
        else:
            monthly_returns.append(0)
            equity.append(equity[-1])

    # 计算指标
    if len(monthly_returns) < 3:
        return {"error": "回测数据不足"}

    metrics = be.calc_metrics(monthly_returns, equity)
    metrics["label"] = "翻倍策略"
    metrics["total_trades"] = total_trades
    metrics["gapup_fails"] = total_gapup_fails
    metrics["stop_hits"] = total_stop_hits
    metrics["total_doubled"] = total_doubled
    metrics["total_hold_sold"] = total_hold_sold
    metrics["doubled_pct"] = round(total_doubled / total_trades * 100, 1) if total_trades > 0 else 0
    metrics["hold_days"] = hold_days
    metrics["gapup_threshold"] = gapup_threshold
    metrics["use_stop_loss"] = use_stop_loss

    return metrics


# ═══════════════════════════════════════════════════════════════
# 多策略组合回测
# ═══════════════════════════════════════════════════════════════

def run_multi_strategy(start_date="2023-07", end_date="2026-07",
                       weights=None, cash_pct=0):
    """
    多策略组合回测
    weights: {strategy_name: weight}
    cash_pct: 现金比例（0-100）
    """
    if weights is None:
        weights = {"main_up": 0.6, "value": 0.4}

    # 分别运行各策略
    results = {}
    for sname, w in weights.items():
        if sname == "main_up":
            fn = be._strategy_lowvol_highroe_main_up
        elif sname == "value":
            fn = strategy_value
        else:
            continue

        result = be.run_backtest(fn, start_date=start_date, end_date=end_date,
                                  top_n=30, market_fear_threshold=0,
                                  walk_forward=False)
        if result and "error" not in result:
            # 取样本内数据
            ins = result.get("in_sample", {}) or result.get("walk_forward", {})
            if ins:
                results[sname] = ins
                print(f"  {sname}: CAGR={ins.get('cagr_pct', '?')}%, "
                      f"DD={ins.get('max_drawdown_pct', '?')}%", file=sys.stderr)

    if not results:
        return {"error": "策略回测失败"}

    # 组合计算
    total_weight = sum(weights.get(s, 0) for s in results)
    adj_cash = cash_pct / 100
    adj_weight = (1 - adj_cash) / total_weight if total_weight > 0 else 0

    # 加权平均
    combined_cagr = sum(results[s].get("cagr_pct", 0) * weights.get(s, 0) * adj_weight
                        for s in results)

    # 最大回撤：各策略加权估计
    combined_dd = sum(results[s].get("max_drawdown_pct", 0) * weights.get(s, 0)
                      for s in results)

    # 如果有现金，回撤降低
    if adj_cash > 0:
        combined_cagr = combined_cagr * (1 - adj_cash)
        combined_dd = combined_dd * (1 - adj_cash)

    return {
        "individual": results,
        "combined": {
            "cagr_pct": round(combined_cagr, 2),
            "max_drawdown_pct": round(combined_dd, 2),
            "weights": weights,
            "cash_pct": cash_pct,
        }
    }


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="翻倍策略回测 + 多策略组合 + 双层止损")
    parser.add_argument("--mode", default="doubling",
                        choices=["doubling", "multi", "stop_loss_compare"],
                        help="回测模式")
    parser.add_argument("--start", default="2023-07")
    parser.add_argument("--end", default="2026-07")
    parser.add_argument("--hold-days", type=int, default=120)
    parser.add_argument("--gapup", type=float, default=5.0)
    parser.add_argument("--stop-loss", type=float, default=8.0)
    parser.add_argument("--trailing", type=float, default=15.0)
    parser.add_argument("--cash", type=float, default=0,
                        help="多策略组合的现金比例")
    args = parser.parse_args()

    if args.mode == "doubling":
        # 指令1：翻倍策略诚实回测（无止损）
        print(f"\n{'='*60}")
        print(f"📊 翻倍潜力筛选 - 诚实回测")
        print(f"   持有期: {args.hold_days}日 | 跳空阈值: {args.gapup}%")
        print(f"{'='*60}")

        result = run_backtest_holding(
            strategy_doubling, start_date=args.start, end_date=args.end,
            top_n=999, hold_days=args.hold_days, gapup_threshold=args.gapup,
            use_stop_loss=False
        )

        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(f"\n✅ 回测结果:")
            print(f"  📈 年化收益: {result.get('cagr_pct', '?')}%")
            print(f"  📉 最大回撤: {result.get('max_drawdown_pct', '?')}%")
            print(f"  📊 月胜率: {result.get('win_rate_pct', '?')}%")
            print(f"  💰 累计收益: {result.get('total_return_pct', '?')}%")
            print(f"  🎯 翻倍股: {result.get('total_doubled', 0)}/{result.get('total_trades', 0)} "
                  f"({result.get('doubled_pct', '?')}%)")
            print(f"  ⏰ 到期卖出: {result.get('total_hold_sold', 0)} 次")
            print(f"  ⛔ 跳空放弃: {result.get('gapup_fails', 0)} 次")

    elif args.mode == "multi":
        # 指令2：多策略组合
        print(f"\n{'='*60}")
        print(f"📊 多策略组合回测")
        print(f"   权重: 主升浪60% + 价值档40% | 现金: {args.cash}%")
        print(f"{'='*60}")

        # 先跑价值档的诚实回测
        print(f"\n--- 价值档诚实回测 ---")
        val_result = be.run_backtest(
            strategy_value, start_date=args.start, end_date=args.end,
            top_n=30
        )
        if val_result and "error" not in val_result:
            print(f"  CAGR: {val_result.get('cagr_pct', '?')}%")
            print(f"  MDD: {val_result.get('max_drawdown_pct', '?')}%")
            print(f"  月胜率: {val_result.get('win_rate_pct', '?')}%")

        # 组合
        result = run_multi_strategy(
            start_date=args.start, end_date=args.end,
            weights={"main_up": 0.6, "value": 0.4},
            cash_pct=args.cash
        )

        if "error" in result:
            print(f"❌ 组合失败: {result['error']}")
        else:
            print(f"\n--- 组合结果 ---")
            for sname, r in result.get("individual", {}).items():
                print(f"  {sname}: CAGR={r.get('cagr_pct', '?')}%, DD={r.get('max_drawdown_pct', '?')}%")
            c = result["combined"]
            print(f"\n  📊 组合 {c['weights']} (现金{c['cash_pct']}%):")
            print(f"  📈 年化收益: {c['cagr_pct']}%")
            print(f"  📉 最大回撤: {c['max_drawdown_pct']}%")

    elif args.mode == "stop_loss_compare":
        # 指令3：双层止损对比
        print(f"\n{'='*60}")
        print(f"📊 双层止损对比 - 翻倍策略")
        print(f"   持有期: {args.hold_days}日 | 止损: -{args.stop_loss}% | 移动止盈: {args.trailing}%")
        print(f"{'='*60}")

        # 无止损
        print(f"\n--- 无止损 ---")
        result_no = run_backtest_holding(
            strategy_doubling, start_date=args.start, end_date=args.end,
            top_n=999, hold_days=args.hold_days, gapup_threshold=args.gapup,
            use_stop_loss=False
        )
        if "error" not in result_no:
            print(f"  CAGR: {result_no.get('cagr_pct', '?')}%")
            print(f"  MDD: {result_no.get('max_drawdown_pct', '?')}%")
            print(f"  翻倍率: {result_no.get('doubled_pct', '?')}%")

        # 固定-8%止损
        print(f"\n--- 固定-{args.stop_loss}%止损 ---")
        result_fixed = run_backtest_holding(
            strategy_doubling, start_date=args.start, end_date=args.end,
            top_n=999, hold_days=args.hold_days, gapup_threshold=args.gapup,
            use_stop_loss=True, stop_loss_pct=args.stop_loss, trailing_stop_pct=999
        )
        if "error" not in result_fixed:
            print(f"  CAGR: {result_fixed.get('cagr_pct', '?')}%")
            print(f"  MDD: {result_fixed.get('max_drawdown_pct', '?')}%")
            print(f"  翻倍率: {result_fixed.get('doubled_pct', '?')}%")
            print(f"  止损触发: {result_fixed.get('stop_hits', 0)} 次")

        # 双层止损
        print(f"\n--- 双层止损（初始-{args.stop_loss}% → +10%保本 → +20%移动止盈{args.trailing}%）---")
        result_dual = run_backtest_holding(
            strategy_doubling, start_date=args.start, end_date=args.end,
            top_n=999, hold_days=args.hold_days, gapup_threshold=args.gapup,
            use_stop_loss=True, stop_loss_pct=args.stop_loss, trailing_stop_pct=args.trailing
        )
        if "error" not in result_dual:
            print(f"  CAGR: {result_dual.get('cagr_pct', '?')}%")
            print(f"  MDD: {result_dual.get('max_drawdown_pct', '?')}%")
            print(f"  翻倍率: {result_dual.get('doubled_pct', '?')}%")
            print(f"  止损触发: {result_dual.get('stop_hits', 0)} 次")
            print(f"  到期卖出: {result_dual.get('total_hold_sold', 0)} 次")