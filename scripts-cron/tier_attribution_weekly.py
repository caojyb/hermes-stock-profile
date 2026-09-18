#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tier_attribution_weekly.py — 周五归因周报（六轮 P2⑤）
======================================================
读 strategy_performance 分档行，推一条归因摘要进群:
让"激进档为何赚钱、稳健档为何亏钱"进入视野。每周五 17:20。
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'stock-work'))

DB = None


def main():
    from core.compat_paths import RECOMMENDATION_OUTCOMES_DB as DB_PATH
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    rows = conn.execute("""
        SELECT strategy, total_recs, complete_recs, win_rate_t1, win_rate_t20,
               avg_return_t20, avg_excess_t20, updated_at
        FROM strategy_performance ORDER BY avg_excess_t20 DESC
    """).fetchall()
    conn.close()
    if not rows:
        print("无归因数据，跳过")
        return

    lines = [f"📊 [信息] 分档归因周报 | {date.today()}", "=" * 48]
    for strat, total, complete, w1, w20, r20, e20, upd in rows:
        tag = 'all' if strat == 'all' else strat
        w1s = f"{w1:.1f}%" if w1 is not None else 'N/A'
        w20s = f"{w20:.1f}%" if w20 is not None else 'N/A'
        r20s = f"{r20:+.2f}%" if r20 is not None else 'N/A'
        e20s = f"{e20:+.2f}%" if e20 is not None else 'N/A'
        lines.append(f"· {tag}({total}条/完整{complete}): t1胜率{w1s} t20胜率{w20s} t20均收益{r20s} 超额{e20s}")
    lines.append("=" * 48)
    best = next((r for r in rows if r[0] != 'all' and r[6] is not None), None)
    worst = next((r for r in reversed(rows) if r[0] != 'all' and r[6] is not None), None)
    if best and worst and best[0] != worst[0]:
        lines.append(f"💡 最强: {best[0]} (超额{best[6]:+.2f}%) | 最弱: {worst[0]} (超额{worst[6]:+.2f}%)")
        lines.append("预注册规则: 稳健/价值档验证期持续为负 → 砍档（见 RETIREMENT_CRITERIA.md §3）")

    text = "\n".join(lines)
    print(text)
    try:
        sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')
        from feishu_sender import feishu_send_message
        feishu_send_message(text)
        print("✅ 已推送")
    except Exception as e:
        print(f"[EXC] 推送: {type(e).__name__}: {e}")
    try:
        from heartbeat import write
        write('tier-attribution-weekly', {'ts': str(date.today())}, expected_interval_seconds=7*86400)
    except Exception as e:
        print(f"[EXC] 心跳: {type(e).__name__}: {e}")


if __name__ == '__main__':
    main()
