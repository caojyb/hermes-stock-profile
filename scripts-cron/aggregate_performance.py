#!/usr/bin/env python3
"""
Aggregate recommendation_outcomes into strategy_performance.

Run after track_outcomes.py backfill:
    python3 scripts/cron/track_outcomes.py --aggregate
"""

import sqlite3
import time
from datetime import datetime, date
import sys
from heartbeat import write
from pathlib import Path

from core.compat_paths import RECOMMENDATION_POOL_DB as _RECOMMENDATION_POOL_DB
from core.compat_paths import RECOMMENDATION_OUTCOMES_DB as _RECOMMENDATION_OUTCOMES_DB
OUTCOME_DB = Path(_RECOMMENDATION_OUTCOMES_DB)
RECOMMENDATION_DB = Path(_RECOMMENDATION_POOL_DB)


def _send_feishu(msg):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'stock' / 'stock-expert' / 'skills' / 'feishu-bitable'))
        from feishu_sender import feishu_send_message
        feishu_send_message(msg)
    except Exception as e:
        print(f"[WARN] 飞书发送失败: {e}")


def aggregate():
    _t0 = time.time()
    today = date.today().isoformat()
    conn = sqlite3.connect(OUTCOME_DB, timeout=30)
    cur = conn.cursor()

    # 基础统计
    cur.execute("""
        SELECT
            COUNT(*) AS total_recs,
            SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS complete_recs,
            SUM(CASE WHEN t1_skip_reason IS NOT NULL OR t5_skip_reason IS NOT NULL OR t20_skip_reason IS NOT NULL THEN 1 ELSE 0 END) AS skipped_recs,
            SUM(CASE WHEN t1_filled = 1 THEN 1 ELSE 0 END) AS filled_recs,
            SUM(CASE WHEN t1_filled = 1 AND t5_filled = 1 AND t20_filled = 1 THEN 1 ELSE 0 END) AS fully_filled_recs,
            SUM(CASE WHEN t1_skip_reason='no_data' OR t5_skip_reason='no_data' OR t20_skip_reason='no_data' THEN 1 ELSE 0 END) AS no_data_count,
            SUM(CASE WHEN t1_skip_reason='future' OR t5_skip_reason='future' OR t20_skip_reason='future' THEN 1 ELSE 0 END) AS future_count
        FROM recommendation_outcomes
    """)
    row = cur.fetchone()
    total_recs, complete_recs, skipped_recs, filled_recs, fully_filled_recs, no_data_count, future_count = row

    # 各 horizon 统计
    stats = {}
    for horizon in ['t1', 't5', 't20']:
        filled_col = f"{horizon}_filled"
        return_col = f"{horizon}_return"
        bench_col = f"bench_{horizon}_return"
        excess_col = f"excess_{horizon}"
        skip_col = f"{horizon}_skip_reason"

        cur.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {filled_col} = 1 THEN 1 ELSE 0 END) AS filled,
                SUM(CASE WHEN {filled_col} = 1 AND {return_col} > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN {filled_col} = 1 AND {bench_col} IS NOT NULL THEN 1 ELSE 0 END) AS bench_available,
                SUM(CASE WHEN {filled_col} = 1 AND {return_col} > {bench_col} THEN 1 ELSE 0 END) AS outperform,
                AVG(CASE WHEN {filled_col} = 1 THEN {return_col} END) AS avg_return,
                AVG(CASE WHEN {filled_col} = 1 THEN {excess_col} END) AS avg_excess,
                SUM(CASE WHEN {filled_col} = 1 AND {return_col} > 0 THEN 1 ELSE 0 END) AS win_count,
                SUM(CASE WHEN {filled_col} = 1 AND {return_col} < 0 THEN 1 ELSE 0 END) AS loss_count,
                AVG(CASE WHEN {filled_col} = 1 AND {return_col} > 0 THEN {return_col} END) AS avg_win,
                AVG(CASE WHEN {filled_col} = 1 AND {return_col} < 0 THEN {return_col} END) AS avg_loss,
                SUM(CASE WHEN {skip_col} = 'no_data' THEN 1 ELSE 0 END) AS no_data_count,
                SUM(CASE WHEN {skip_col} = 'future' THEN 1 ELSE 0 END) AS future_count
            FROM recommendation_outcomes
        """)
        r = cur.fetchone()
        stats[horizon] = {
            'total': r[0],
            'filled': r[1],
            'wins': r[2],
            'bench_available': r[3],
            'outperform': r[4],
            'avg_return': r[5],
            'avg_excess': r[6],
            'win_count': r[7],
            'loss_count': r[8],
            'avg_win': r[9],
            'avg_loss': r[10],
            'no_data_count': r[11],
            'future_count': r[12],
        }

    # 计算指标
    def win_rate(horizon):
        s = stats[horizon]
        if s['filled'] == 0:
            return None
        return s['wins'] / s['filled'] * 100

    def outperform_rate(horizon):
        s = stats[horizon]
        if s['bench_available'] == 0:
            return None
        return s['outperform'] / s['bench_available'] * 100

    # no_data_ratio：任一 horizon 有 no_data 即计入（严格口径）
    # no_data_count = SUM(t1/t5/t20_skip='no_data')
    no_data_ratio = (no_data_count / total_recs * 100) if total_recs > 0 else 0
    
    # 插入或更新 strategy_performance
    now = datetime.now().isoformat()
    cur.execute("""
        INSERT OR REPLACE INTO strategy_performance (
            strategy, period, calc_date,
            total_recs, complete_recs, skipped_recs, filled_recs, fully_filled_recs,
            win_rate_t1, win_rate_t5, win_rate_t20,
            avg_return_t1, avg_return_t5, avg_return_t20,
            avg_excess_t20, outperform_rate_t20,
            avg_win_t20, avg_loss_t20, pl_ratio_t20, median_return_t20,
            updated_at, no_data_ratio, future_count, no_data_count
        ) VALUES (?, 'all', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        'all', now,
        total_recs, complete_recs, skipped_recs, filled_recs, fully_filled_recs,
        win_rate('t1'), win_rate('t5'), win_rate('t20'),
        stats['t1']['avg_return'], stats['t5']['avg_return'], stats['t20']['avg_return'],
        stats['t20']['avg_excess'],
        outperform_rate('t20'),
        stats['t20']['avg_win'], stats['t20']['avg_loss'],
        (abs(stats['t20']['avg_loss']) / stats['t20']['avg_win'] if stats['t20']['avg_win'] else None),
        None,  # median_return_t20 暂不计算
        now, no_data_ratio, future_count, no_data_count
    ))

    cost_ms = int((time.time() - _t0) * 1000)
    write('strategy-performance-daily', 'ok', detail=f'total={total_recs}', cost_ms=cost_ms, expected_interval_seconds=86400)
    
    # 查上次 no_data_ratio（环比），排除今天
    cur.execute("""
        SELECT no_data_ratio FROM strategy_performance 
        WHERE strategy='all' AND period='all' AND calc_date < ?
        ORDER BY calc_date DESC LIMIT 1
    """, (today,))
    last_row = cur.fetchone()
    last_no_data_ratio = last_row[0] if last_row else None
    
    alerts = []
    if no_data_ratio > 50:
        alerts.append(f'P1: no_data 比例 {no_data_ratio:.1f}% > 50%')
    if last_no_data_ratio and no_data_ratio - last_no_data_ratio > 20:
        alerts.append(f'P1: no_data 环比上升 {no_data_ratio - last_no_data_ratio:.1f}% > 20%')
    
    if alerts:
        msg = '[Performance Alert]' + '\n' + '\n'.join(alerts)
        _send_feishu(msg)
        print('ALERTS:')
        for alert in alerts:
            print(f'  {alert}')
    else:
        print('No alerts.')
    
    conn.commit()
    conn.close()

    print(f"Aggregated strategy_performance:")
    print(f"  total_recs={total_recs}")
    print(f"  complete_recs={complete_recs}")
    print(f"  skipped_recs={skipped_recs}")
    print(f"  filled_recs={filled_recs}")
    print(f"  fully_filled_recs={fully_filled_recs}")
    print(f"  win_rate_t1={win_rate('t1'):.2f}%" if win_rate('t1') else "  win_rate_t1=N/A")
    print(f"  win_rate_t5={win_rate('t5'):.2f}%" if win_rate('t5') else "  win_rate_t5=N/A")
    print(f"  win_rate_t20={win_rate('t20'):.2f}%" if win_rate('t20') else "  win_rate_t20=N/A")
    print(f"  outperform_rate_t1={outperform_rate('t1'):.2f}%" if outperform_rate('t1') else "  outperform_rate_t1=N/A")
    print(f"  outperform_rate_t5={outperform_rate('t5'):.2f}%" if outperform_rate('t5') else "  outperform_rate_t5=N/A")
    print(f"  outperform_rate_t20={outperform_rate('t20'):.2f}%" if outperform_rate('t20') else "  outperform_rate_t20=N/A")


if __name__ == "__main__":
    aggregate()
