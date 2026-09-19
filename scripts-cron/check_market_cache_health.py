#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_market_cache_health.py — market_cache 健康检查 + 关键表新鲜度（合并版）
=====================================================================================
每天 17:50 执行。2026-09-19 合并：原 table-freshness-check.py（17:55）并入本脚本，
原 job 已 pause——一处检查、一条推送（Census 合并工单 #1，避免两查 80% 重叠）。

检查两组共 6 项：
  A. market_cache 刷新健康（原 3 项）
     1. K线数量       今日 klines > 5000
     2. 日志 stocks    market_cache_refresh.log 今日待更新 stocks 列表
     3. duration       executions.db 今日 refresh 耗时 > 100s
  B. 关键表新鲜度（原 table_freshness_check.py 的 4 项）
     4. klines lag     交易日应为当日；滞后 ≥1 天即警（exchange_holidays 排除节假日）
     5. lhb_data lag   T+1 发布，阈值 4 天
     6. holder_change  低频更新，阈值 10 天
     7. lockup_release 未来日期表：未来数据 0 行 = 周刷未跑

设计约束（承自两个原脚本）：
- 全部检查只读；无写库、无改配置
- 有任一 issue → 汇总一条飞书 + exit 1；全过 → stdout 留痕 + exit 0
- klines 同时受检查 1（数量）与 4（新鲜度）覆盖：前者管"刷了多少"，后者管"刷到哪天"，
  两者互补不重复——09-18 事故中数量 1925 但日期是当日的场景正是靠 4 补上日期口径
"""
import os
import sys
import json
import sqlite3
import re
from datetime import date, datetime
from pathlib import Path

# 路径设置
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / 'stock-work'))
from core.compat_paths import MARKET_DB
MARKET_DB = Path(MARKET_DB)
LOG_FILE = Path.home() / '.hermes/logs/market_cache_refresh.log'
HEARTBEAT_DIR = BASE_DIR / 'stock-work' / 'data' / 'state' / 'heartbeats'

sys.path.insert(0, str(BASE_DIR / 'skills' / 'stock' / 'stock-expert' / 'skills' / 'feishu-bitable'))


def send_feishu(msg: str):
    try:
        from feishu_sender import feishu_send_message
        feishu_send_message(msg)
    except Exception as e:
        print(f"[WARN] 飞书发送失败: {e}")


# ── A. market_cache 刷新健康（原 3 项，未改动） ──────────────────────────

def _is_trading_day() -> bool:
    """今天是否 A 股交易日（exchange_holidays 排除节假日）。

    A 组检查（数量/日志/duration）语义上是"今日盘后刷新是否正常"，
    周末/节假日天然无刷新——不判定会误报（周六实测 K 线 0 只/无日志/无执行记录三条假警）。
    """
    try:
        from exchange_holidays import is_trading_calendar_day
        return is_trading_calendar_day(date.today())
    except Exception:
        return date.today().weekday() < 5


def check_klines_count() -> tuple[bool, str]:
    """检查今天 klines 数量是否 > 5000"""
    if not _is_trading_day():
        return True, "⏸ 非交易日，跳过 K线数量检查"
    try:
        conn = sqlite3.connect(MARKET_DB, timeout=60)
        cur = conn.cursor()
        today = date.today().isoformat()
        cur.execute("SELECT COUNT(DISTINCT code) FROM klines WHERE date = ?", (today,))
        count = cur.fetchone()[0]
        conn.close()
        if count > 5000:
            return True, f"✅ 今日K线股票数: {count}"
        else:
            return False, f"⚠️ 今日K线股票数仅 {count}（预期 >5000）"
    except Exception as e:
        return False, f"❌ K线数量检查失败: {e}"


def check_market_cache_log() -> tuple[bool, str]:
    """检查日志中今天是否有 stocks 列表长度日志"""
    if not _is_trading_day():
        return True, "⏸ 非交易日，跳过 market_cache 日志检查"
    if not LOG_FILE.exists():
        return False, f"⚠️ 日志文件不存在: {LOG_FILE}"

    try:
        content = LOG_FILE.read_text()
        today = date.today().isoformat()
        # 查找今天的日志
        today_pattern = re.compile(rf'{today}.*?待更新 stocks=(\d+)', re.DOTALL)
        matches = today_pattern.findall(content)

        if not matches:
            return False, f"⚠️ 今日无 market_cache 日志（可能未执行）"

        # 取最后一次的 stocks 数
        last_stocks = int(matches[-1])
        if last_stocks > 5000:
            return True, f"✅ 今日 stocks 列表长度: {last_stocks}"
        elif last_stocks > 0:
            return False, f"⚠️ 今日 stocks 列表长度仅 {last_stocks}（预期 >5000）"
        else:
            return False, f"🚨 今日 stocks 列表为空（可能 DB_PATH 切换或数据异常）"
    except Exception as e:
        return False, f"❌ 日志检查失败: {e}"


def check_duration() -> tuple[bool, str]:
    """检查 executions.db 中今天 market_cache 的 duration"""
    if not _is_trading_day():
        return True, "⏸ 非交易日，跳过 duration 检查"
    try:
        executions_db = BASE_DIR / 'cron' / 'executions.db'
        if not executions_db.exists():
            return False, "⚠️ executions.db 不存在"

        conn = sqlite3.connect(executions_db, timeout=60)
        cur = conn.cursor()
        today = date.today().isoformat()
        # 查找今天的 market_cache 任务
        cur.execute("""
            SELECT job_id, strftime('%s', finished_at) - strftime('%s', started_at) as duration_sec
            FROM executions
            WHERE job_id = 'a6a60497fbb6'
              AND DATE(claimed_at) = ?
            ORDER BY claimed_at DESC LIMIT 1
        """, (today,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return False, "⚠️ 今日无 market_cache 执行记录"

        job_id, duration_sec = row
        if duration_sec is None:
            return False, "⚠️ market_cache duration 为 NULL"

        if duration_sec > 100:
            return True, f"✅ market_cache duration: {duration_sec}s"
        else:
            return False, f"⚠️ market_cache duration 仅 {duration_sec}s（预期 >100s，可能假成功）"
    except Exception as e:
        return False, f"❌ duration 检查失败: {e}"


# ── B. 关键表新鲜度（承自 table_freshness_check.py，2026-09-19 合并） ─────

# 表 → (日期列, 库, 允许滞后自然日, 说明)
FRESHNESS_CHECKS = [
    ('klines', 'date', 'MARKET', None, '全市场K线（交易日应为当日）'),
    ('lhb_data', 'trade_date', 'LHB', 4, '龙虎榜（T+1发布，阈值4天）'),
    ('holder_change', 'change_date', 'MARKET', 10, '股东变动（低频更新，阈值10天）'),
    ('lockup_release', 'release_date', 'MARKET', None, '限售解禁（未来日期表，检查方式不同）'),
]


def _freshness_db_path(kind):
    from core.compat_paths import MARKET_DB as M, get_db_path as g
    return str(M) if kind == 'MARKET' else str(g('lhb_cache'))


def check_table_freshness() -> tuple[bool, str]:
    """关键表新鲜度总检查（原 table_freshness_check.py main 逻辑，单条汇总返回）。

    阈值语义（承自原脚本六轮提升点6）：
    - klines: 交易日（is_trading_calendar_day 排除节假日）滞后 ≥1 天即警；
      周末/节假日 lag=None 跳过（周末不刷新是正常态）
    - lhb_data / holder_change: 滞后 > 阈值天报警
    - lockup_release: 未来数据 0 行 = 周刷未跑
    """
    today = date.today()
    try:
        conn_m = sqlite3.connect(_freshness_db_path('MARKET'), timeout=30)
        conn_l = sqlite3.connect(_freshness_db_path('LHB'), timeout=30)
    except Exception as e:
        return False, f"❌ 新鲜度检查失败: 无法连接数据库 {e}"

    # 交易日判断: 17:50 跑在交易日，此时 klines 应为当日
    try:
        from exchange_holidays import is_trading_calendar_day
        klines_expected_today = is_trading_calendar_day(today)
    except Exception:
        klines_expected_today = today.weekday() < 5

    alerts = []
    ok_lines = []
    checks = []
    for table, col, kind, max_lag, desc in FRESHNESS_CHECKS:
        if table == 'klines':
            checks.append((table, col, kind, 0 if klines_expected_today else None, desc))
        else:
            checks.append((table, col, kind, max_lag, desc))

    try:
        for table, col, kind, max_lag, desc in checks:
            try:
                conn = conn_m if kind == 'MARKET' else conn_l
                if table == 'lockup_release':
                    # 未来日期表: 检查是否有未来数据（0行=周刷未跑）
                    n = conn.execute(
                        "SELECT COUNT(*) FROM lockup_release WHERE release_date >= ?",
                        (today.isoformat(),)).fetchone()[0]
                    if n == 0:
                        alerts.append(f"{table}: 未来解禁数据 0 行（周刷未跑或数据源失败）")
                    else:
                        ok_lines.append(f"{table}: 未来数据 {n} 行")
                    continue
                mx = conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
                if not mx:
                    alerts.append(f"{table}: 表空")
                    continue
                lag = (today - date.fromisoformat(str(mx)[:10])).days
                if max_lag is not None and lag > max_lag:
                    alerts.append(f"{table}: 最新 {mx}，滞后 {lag} 天 > 阈值 {max_lag}（{desc}）")
                else:
                    ok_lines.append(f"{table}: 最新 {mx}（滞后 {lag} 天）")
            except Exception as e:
                alerts.append(f"{table}: 检查失败 {type(e).__name__}: {e}")
    finally:
        conn_m.close()
        conn_l.close()

    if alerts:
        return False, "表新鲜度异常: " + "; ".join(alerts)
    return True, "✅ 关键表新鲜（" + " | ".join(ok_lines) + "）"


def main():
    today = date.today().isoformat()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始 market_cache 健康检查（含关键表新鲜度）...")

    checks = [
        ("K线数量", check_klines_count),
        ("日志 stocks 列表", check_market_cache_log),
        ("执行 duration", check_duration),
        ("关键表新鲜度", check_table_freshness),
    ]

    issues = []
    report_lines = []

    for name, check_fn in checks:
        passed, msg = check_fn()
        report_lines.append(msg)
        if not passed:
            issues.append(f"❌ {name}: {msg}")

    # 输出报告
    print("\n" + "=" * 55)
    print("🏥 market_cache 健康检查 + 关键表新鲜度")
    print(f"   检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    for line in report_lines:
        print(line)

    if issues:
        print("\n" + "!" * 55)
        print(f"⚠️ 发现 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  {issue}")
        print("!" * 55)

        # 飞书告警（原 freshness 的"数据未到 ≠ 任务 ok"提示语一并并入）
        feishu_msg = f"🚨 market_cache 健康检查异常 [{today}]\n\n"
        feishu_msg += "\n".join(issues)
        feishu_msg += "\n\n数据未到 ≠ 任务 ok。请检查对应刷新链路。"
        send_feishu(feishu_msg)
        return 1
    else:
        print(f"\n✅ market_cache 运行正常，关键表全部新鲜")
        return 0


if __name__ == '__main__':
    sys.exit(main())
