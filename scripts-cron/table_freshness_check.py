#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
table_freshness_check.py — 关键表新鲜度检查（六轮 P2: "任务 ok 但数据没到"的静默退化）
=====================================================================================
检查 klines/lhb_data/holder_change/lockup_release 的 MAX(日期) 滞后天数。
超阈值 → [关注] 推送；全部新鲜 → 静默（stdout 留痕）。
挂 17:55（数据刷新链尾端）。
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'stock-work'))

# 表 → (日期列, 库, 允许滞后自然日, 说明)
CHECKS = [
    ('klines', 'date', 'MARKET', 4, '全市场K线（周末/节假日滞后正常，阈值4天）'),
    ('lhb_data', 'trade_date', 'LHB', 4, '龙虎榜（T+1发布，阈值4天）'),
    ('holder_change', 'change_date', 'MARKET', 10, '股东变动（低频更新，阈值10天）'),
    ('lockup_release', 'release_date', 'MARKET', None, '限售解禁（未来日期表，检查方式不同）'),
]


def _db_path(kind):
    from core.compat_paths import MARKET_DB as M, get_db_path as g
    return str(M) if kind == 'MARKET' else str(g('lhb_cache'))


def main():
    today = date.today()
    alerts = []
    conn_m = sqlite3.connect(_db_path('MARKET'), timeout=30)
    conn_l = sqlite3.connect(_db_path('LHB'), timeout=30)
    # 六轮提升点6: klines 阈值 4天太松——刷新失败的次日滞后仅1天但所有信号吃旧数据。
    # 交易日判断: 17:55 跑在交易日，此时 klines 应为当日；滞后≥1 个自然日即报警（用 exchange_holidays 排除节假日）
    try:
        from exchange_holidays import is_trading_calendar_day
        klines_expected_today = is_trading_calendar_day(today)
    except Exception:
        klines_expected_today = today.weekday() < 5
    checks = []
    for table, col, kind, max_lag, desc in CHECKS:
        if table == 'klines':
            checks.append((table, col, kind, 0 if klines_expected_today else None, desc))
        else:
            checks.append((table, col, kind, max_lag, desc))
    for table, col, kind, max_lag, desc in checks:
        try:
            conn = conn_m if kind == 'MARKET' else conn_l
            if table == 'lockup_release':
                # 未来日期表: 检查是否有未来60天数据（0行=周刷未跑）
                n = conn.execute("SELECT COUNT(*) FROM lockup_release WHERE release_date >= ?",
                                 (today.isoformat(),)).fetchone()[0]
                if n == 0:
                    alerts.append(f"{table}: 未来解禁数据 0 行（周刷未跑或数据源失败）")
                continue
            mx = conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
            if not mx:
                alerts.append(f"{table}: 表空")
                continue
            lag = (today - date.fromisoformat(str(mx)[:10])).days
            if max_lag is not None and lag > max_lag:
                alerts.append(f"{table}: 最新 {mx}，滞后 {lag} 天 > 阈值 {max_lag}（{desc}）")
            else:
                print(f"  ✓ {table}: 最新 {mx}（滞后 {lag} 天）")
        except Exception as e:
            alerts.append(f"{table}: 检查失败 {type(e).__name__}: {e}")
    conn_m.close()
    conn_l.close()

    if alerts:
        lines = [f"⚠️ [关注] 关键表新鲜度告警 | {today}", "=" * 46]
        lines += [f"  - {a}" for a in alerts]
        lines.append("数据未到 ≠ 任务 ok。请检查对应刷新链路。")
        print("\n".join(lines))
        # 推送
        try:
            sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')
            from feishu_sender import feishu_send_message
            feishu_send_message("\n".join(lines))
        except Exception as e:
            print(f"[EXC] table_freshness_check.py 推送: {type(e).__name__}: {e}")
        sys.exit(1)
    print("✅ 全部关键表新鲜")
    try:
        from heartbeat import write
        write('table-freshness-check', {'ts': str(today)})
    except Exception as e:
        print(f"[EXC] 心跳: {type(e).__name__}: {e}")


if __name__ == '__main__':
    main()
