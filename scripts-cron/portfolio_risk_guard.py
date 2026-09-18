#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组合级风控检查器（2026-09-18 二轮审计 30 天路线 ⑨）
==================================================
填补最大结构性缺口：组合级风控此前只有"单票止损 + 周度回撤检查"，
且周度检查在回撤 >= 15% 时**静默跳过**（最危险的时刻反而最安静）。

本模块提供三块能力（均可独立调用）：

1. portfolio_drawdown_circuit_breaker
   回撤熔断：>= 15% 触发 🚨 飞书硬告警（每次运行必推，不静默）；
   >= 20% 追加"暂停开仓"状态标记写入 simulation.db 的 risk_state 表。

2. sector_exposure_check
   行业暴露检查：单一行业（sector）持仓市值占比 > 40% 告警。

3. correlation_risk_check
   相关性风险：持仓中同行业 >= 4 只告警（个人组合简化版相关性暴露，
   用行业聚类近似，避免全量相关矩阵的计算与数据要求）。

入口: run_all() — 由 cron-health-sentinel 之后的一个每日 job 调用，
     或挂到 double_monitor 之后。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROFILE = Path('/home/caojy/.hermes/profiles/stock')
for p in (str(PROFILE / 'stock-work'),
          str(PROFILE / 'scripts/cron'),
          str(PROFILE / 'skills/stock/stock-expert/skills/feishu-bitable')):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.compat_paths import SIMULATION_DB  # noqa: E402

DRAWDOWN_ALERT = 15.0
DRAWDOWN_PAUSE = 20.0
SECTOR_PCT_LIMIT = 0.40
SECTOR_COUNT_LIMIT = 4


def _send_feishu(msg: str) -> bool:
    try:
        from feishu_sender import feishu_send_message
        return bool(feishu_send_message(msg))
    except Exception as e:
        print(f"[EXC] portfolio_risk_guard.send_feishu: {type(e).__name__}: {e}")
        return False


def portfolio_drawdown_circuit_breaker(sim_db: str = SIMULATION_DB) -> dict:
    """回撤熔断。>=15% 硬告警；>=20% 写暂停开仓标记。"""
    if not os.path.exists(sim_db):
        return {'status': 'NO_DB', 'drawdown': None}
    conn = sqlite3.connect(sim_db, timeout=30)
    try:
        row = conn.execute(
            "SELECT max_drawdown_pct FROM portfolio_snapshots ORDER BY date DESC LIMIT 1"
        ).fetchone()
        dd = float(row[0]) if row and row[0] is not None else None
        if dd is None:
            return {'status': 'NO_DATA', 'drawdown': None}

        result = {'status': 'OK', 'drawdown': dd}
        if dd >= DRAWDOWN_ALERT:
            level = '🚨🚨 严重' if dd >= DRAWDOWN_PAUSE else '🚨 警告'
            msg = (f"{level} 组合回撤熔断 | {date.today()}\n"
                   f"当前最大回撤: {dd:.2f}%（阈值 {DRAWDOWN_ALERT}%）\n"
                   f"{'⛔ 已写入暂停开仓标记（阈值 ' + str(DRAWDOWN_PAUSE) + '%）' if dd >= DRAWDOWN_PAUSE else '建议停止新建仓位，检查持仓结构'}")
            result['alert_sent'] = _send_feishu(msg)
            result['status'] = 'ALERT' if dd < DRAWDOWN_PAUSE else 'SEVERE'
        if dd >= DRAWDOWN_PAUSE:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_state (
                    key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
                )""")
            conn.execute(
                "INSERT OR REPLACE INTO risk_state (key, value, updated_at) VALUES ('trading_paused', '1', ?)",
                (date.today().isoformat(),))
            conn.commit()
            result['trading_paused'] = True
        else:
            # 回撤恢复时清除暂停标记
            try:
                conn.execute("DELETE FROM risk_state WHERE key='trading_paused'")
                conn.commit()
            except sqlite3.OperationalError:
                pass
        return result
    finally:
        conn.close()


def sector_exposure_check(sim_db: str = SIMULATION_DB) -> dict:
    """行业暴露：单一行业市值占比 > 40% 告警。"""
    if not os.path.exists(sim_db):
        return {'status': 'NO_DB'}
    conn = sqlite3.connect(sim_db, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT sector, SUM(COALESCE(sell_price, buy_price) * COALESCE(buy_shares, 0)) AS mv
            FROM trades WHERE status IN ('持有','部分止盈') GROUP BY sector
        """).fetchall()
        total = sum(r['mv'] or 0 for r in rows)
        if total <= 0:
            return {'status': 'NO_POSITIONS'}
        over = []
        for r in rows:
            pct = (r['mv'] or 0) / total
            if pct > SECTOR_PCT_LIMIT:
                over.append((r['sector'] or '未知', pct))
        result = {'status': 'OK' if not over else 'ALERT', 'over': over, 'total_mv': total}
        if over:
            detail = '\n'.join(f"  {s}: {p*100:.1f}%" for s, p in over[:5])
            _send_feishu(f"🟠 行业暴露告警 | {date.today()}\n以下行业占比超 {SECTOR_PCT_LIMIT*100:.0f}%:\n{detail}")
        return result
    finally:
        conn.close()


def correlation_risk_check(sim_db: str = SIMULATION_DB) -> dict:
    """相关性风险（行业聚类近似）：同行业 >= 4 只告警。"""
    if not os.path.exists(sim_db):
        return {'status': 'NO_DB'}
    conn = sqlite3.connect(sim_db, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT sector, COUNT(*) AS n FROM trades WHERE status IN ('持有','部分止盈') GROUP BY sector"
        ).fetchall()
        hot = [(r['sector'] or '未知', r['n']) for r in rows if r['n'] >= SECTOR_COUNT_LIMIT]
        result = {'status': 'OK' if not hot else 'ALERT', 'hot': hot}
        if hot:
            detail = '\n'.join(f"  {s}: {n} 只" for s, n in hot[:5])
            _send_feishu(f"🟠 相关性集中告警 | {date.today()}\n同行业持仓数超 {SECTOR_COUNT_LIMIT} 只:\n{detail}")
        return result
    finally:
        conn.close()


def run_all() -> dict:
    out = {
        'circuit_breaker': portfolio_drawdown_circuit_breaker(),
        'sector': sector_exposure_check(),
        'correlation': correlation_risk_check(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return out


import json  # noqa: E402  (run_all 使用)

if __name__ == '__main__':
    run_all()
