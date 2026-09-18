#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verification_scorecard.py — 验证期记分牌（六轮提升点3: RETIREMENT_CRITERIA 判定自动化）
======================================================================================
每日收盘后算: Day X/20、trades Y/10、净超额（快照口径）、tripwire 状态。
到期自动引用 RETIREMENT_CRITERIA.md 出判定草案（人工签发）。
预承诺防自欺: 判定由数据产生，不由临场情绪产生。
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'stock-work'))

START_DATE = date(2026, 9, 18)   # 账本 021: 模拟仓重置基线日
TOTAL_DAYS = 20
MIN_TRADES = 10


def main():
    from core.compat_paths import SIMULATION_DB as SIM
    conn = sqlite3.connect(str(SIM), timeout=30)
    cur = conn.cursor()
    # 交易日计数（快照表里非周末日期）
    days = [r[0] for r in cur.execute(
        "SELECT DISTINCT date FROM portfolio_snapshots WHERE date >= ? ORDER BY date", (START_DATE.isoformat(),))]
    day_n = len(days)
    trades_n = cur.execute(
        "SELECT COUNT(*) FROM trades WHERE buy_date >= ?", (START_DATE.isoformat(),)).fetchone()[0]
    snaps = cur.execute(
        "SELECT total_value, max_drawdown_pct FROM portfolio_snapshots WHERE date >= ? ORDER BY date DESC LIMIT 1",
        (START_DATE.isoformat(),)).fetchone()
    cur_value, cur_dd = (snaps if snaps else (1_000_000, 0.0))
    # t20 扣成本净超额: strategy_performance 在 recommendation_outcomes.db（非 simulation）
    from core.compat_paths import RECOMMENDATION_OUTCOMES_DB as OUTCOMES
    sp = None
    try:
        conn_o = sqlite3.connect(str(OUTCOMES), timeout=30)
        sp = conn_o.execute("SELECT avg_excess_t20, win_rate_t20 FROM strategy_performance WHERE strategy='all'").fetchone()
        conn_o.close()
    except Exception as e:
        print(f"[EXC] 记分牌读归因表: {type(e).__name__}: {e}")
    conn.close()

    excess = sp[0] if sp else None
    lines = [f"📋 [信息] 验证期记分牌 | {date.today()} | Day {day_n}/{TOTAL_DAYS}", "=" * 46]
    lines.append(f"· 样本: {trades_n}/{MIN_TRADES} 笔" + ("（已达标）" if trades_n >= MIN_TRADES else "（不足则每20日顺延重判）"))
    lines.append(f"· 净值: {cur_value:,.0f}（基线 1,000,000）| 当前回撤: {cur_dd:.2f}%")
    if excess is not None:
        lines.append(f"· t20 扣成本前超额: {excess:+.2f}%（60.3bps 成本约 0.60%/回合，另计）")
    # tripwire 状态
    tw = []
    if cur_dd >= 15:
        tw.append("⚠️ 15% 熔断线命中")
    if excess is not None and excess <= 0:
        tw.append("⚠️ 超额转负（降级区间）")
    if excess is not None and excess <= -5:
        tw.append("🔴 退役线命中（≤-5%）")
    lines.append(f"· Tripwire: {'; '.join(tw) if tw else '全部安全'}")

    # 到期判定草案（预注册标准引用）
    if day_n >= TOTAL_DAYS and trades_n >= MIN_TRADES:
        lines.append("-" * 46)
        lines.append("📌 判定草案（引用 RETIREMENT_CRITERIA.md §1，需人工签发）:")
        ok = (excess is not None and excess > 0 and cur_dd < 15)
        lines.append(f"  → {'晋级：继续投入' if ok else '降级或退役：见 §1 三档标准逐条比对'}")
    lines.append("=" * 46)
    text = "\n".join(lines)
    print(text)
    try:
        sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')
        from feishu_sender import feishu_send_message
        feishu_send_message(text)
    except Exception as e:
        print(f"[EXC] 推送: {type(e).__name__}: {e}")
    try:
        from heartbeat import write
        write('verification-scorecard', {'ts': str(date.today()), 'day': day_n, 'trades': trades_n},
              expected_interval_seconds=86400)
    except Exception as e:
        print(f"[EXC] 心跳: {type(e).__name__}: {e}")


if __name__ == '__main__':
    main()
