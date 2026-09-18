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
    # 去重: 自增 id 让 INSERT OR REPLACE 永远新增（六轮审计发现 19 行重复）
    cur.execute("DELETE FROM strategy_performance WHERE strategy='all' AND period='all'")
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

    # ── P2-④ 信号归因（第五轮审计 2026-09-18）──
    # 之前 strategy 全部硬编码 'all'，61.5% 是全场平均，无法问责到具体档位。
    # 现在 recommendation_outcomes.rec_id JOIN recommendation_pool.recommendations.id
    # 可以按 tier（价值/稳健/关注/激进）分档归因。每档一行，strategy=tier 名。
    try:
        # 注意: 不能先 sqlite3.connect(pool) 再 ATTACH 同一文件——会锁死 DETACH。
        # 直接 ATTACH 拿 tier 列表。
        cur.execute("ATTACH DATABASE ? AS pool", (str(RECOMMENDATION_DB),))
        tiers = [r[0] for r in cur.execute("SELECT DISTINCT tier FROM pool.recommendations").fetchall()]
        for tier in tiers:
            t = tier.replace("'", "''")
            cur.execute(f"DROP TABLE IF EXISTS temp.tier_outcome")
            cur.execute(f"""
                CREATE TEMP TABLE tier_outcome AS
                SELECT o.* FROM recommendation_outcomes o
                JOIN pool.recommendations r ON o.rec_id = r.id
                WHERE r.tier = '{t}'
            """)
            cur.execute("SELECT COUNT(*) FROM tier_outcome")
            t_total = cur.fetchone()[0]
            if t_total == 0:
                continue
            # 逐 horizon 统计（与上方 all 档相同口径）
            t_stats = {}
            # 六轮审计 P1: complete_recs 口径必须与 'all' 行一致（status='complete'），
            # 不能拿 total 冒充（虚高胜率）
            cur.execute("SELECT COUNT(*) FROM tier_outcome WHERE status='complete'")
            t_complete = cur.fetchone()[0]
            for horizon in ['t1', 't5', 't20']:
                filled_col = f"{horizon}_filled"
                return_col = f"{horizon}_return"
                bench_col = f"bench_{horizon}_return"
                excess_col = f"excess_{horizon}"
                skip_col = f"{horizon}_skip_reason"
                cur.execute(f"""
                    SELECT
                        COUNT(*),
                        SUM(CASE WHEN {filled_col} = 1 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN {filled_col} = 1 AND {return_col} > 0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN {filled_col} = 1 AND {bench_col} IS NOT NULL THEN 1 ELSE 0 END),
                        SUM(CASE WHEN {filled_col} = 1 AND {return_col} > {bench_col} THEN 1 ELSE 0 END),
                        AVG(CASE WHEN {filled_col} = 1 THEN {return_col} END),
                        AVG(CASE WHEN {filled_col} = 1 THEN {excess_col} END),
                        AVG(CASE WHEN {filled_col} = 1 AND {return_col} > 0 THEN {return_col} END),
                        AVG(CASE WHEN {filled_col} = 1 AND {return_col} < 0 THEN {return_col} END),
                        SUM(CASE WHEN {skip_col} = 'no_data' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN {skip_col} = 'future' THEN 1 ELSE 0 END)
                    FROM tier_outcome
                """)
                r = cur.fetchone()
                t_stats[horizon] = {
                    'total': r[0], 'filled': r[1], 'wins': r[2],
                    'bench_available': r[3], 'outperform': r[4],
                    'avg_return': r[5], 'avg_excess': r[6],
                    'avg_win': r[7], 'avg_loss': r[8],
                    'no_data_count': r[9], 'future_count': r[10],
                }

            def t_win_rate(h):
                return (t_stats[h]['wins'] / t_stats[h]['filled'] * 100) if t_stats[h]['filled'] else None

            def t_out_rate(h):
                return (t_stats[h]['outperform'] / t_stats[h]['bench_available'] * 100) if t_stats[h]['bench_available'] else None

            # INSERT OR REPLACE 对自增 id 无去重效果——先删同 strategy 旧行（保留单份快照）
            cur.execute("DELETE FROM strategy_performance WHERE strategy = ?", (tier,))
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
                tier, now,
                t_total, t_complete, 0,
                t_stats['t1']['filled'],
                0,  # fully_filled_recs 按 tier 暂不细分
                t_win_rate('t1'), t_win_rate('t5'), t_win_rate('t20'),
                t_stats['t1']['avg_return'], t_stats['t5']['avg_return'], t_stats['t20']['avg_return'],
                t_stats['t20']['avg_excess'], t_out_rate('t20'),
                t_stats['t20']['avg_win'], t_stats['t20']['avg_loss'],
                (abs(t_stats['t20']['avg_loss']) / t_stats['t20']['avg_win'] if t_stats['t20']['avg_win'] else None),
                None,
                now,
                (t_stats['t1']['no_data_count'] / t_total * 100 if t_total else 0),
                t_stats['t1']['future_count'], t_stats['t1']['no_data_count'],
            ))
            print(f"  tier[{tier}]: total={t_total} t1_win={t_win_rate('t1')} t20_avg={t_stats['t20']['avg_return']}")
        conn.commit()  # 释放写锁后再 DETACH
        cur.execute("DETACH DATABASE pool")
    except Exception as e:
        print(f"[EXC] aggregate_performance.py tier 归因: {type(e).__name__}: {e}")
    
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
