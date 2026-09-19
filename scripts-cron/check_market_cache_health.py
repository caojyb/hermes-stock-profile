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


# ── A. market_cache 刷新健康（2026-09-19 语义修正：today → 最近一次刷新） ─────────
#
# 修正说明（用户 2026-09-19 指出，原实现是错的）：
#   原实现三项都按 date=today 查——周末/节假日必然查空，要么误报要么被迫加交易日守卫跳过。
#   但股票数据系统与是否交易日无关：非交易日的"最新数据"就是上一交易日收盘的实时数据，
#   检查应该对"系统最新状态是否健康"下结论，而不是对"今天有没有干活"下结论。
#   修正后三项全部改查"最近一次刷新"的客观状态，任何一天跑都能得出正确结论。

def check_klines_count() -> tuple[bool, str]:
    """检查最新一期 klines 的股票数是否 > 5000（不限定今天）"""
    try:
        conn = sqlite3.connect(MARKET_DB, timeout=60)
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM klines")
        latest = cur.fetchone()[0]
        if not latest:
            conn.close()
            return False, "🚨 klines 表为空"
        cur.execute("SELECT COUNT(DISTINCT code) FROM klines WHERE date = ?", (latest,))
        count = cur.fetchone()[0]
        conn.close()
        if count > 5000:
            return True, f"✅ 最新K线({latest})股票数: {count}"
        else:
            return False, f"⚠️ 最新K线({latest})股票数仅 {count}（预期 >5000）"
    except Exception as e:
        return False, f"❌ K线数量检查失败: {e}"


def _latest_stocks_count() -> tuple:
    """从最近一次 market_cache 刷新记录里取 stocks 列表长度。

    双源（按优先级）：
    1. cron/output/a6a60497fbb6/*.md 存档——wrapper 用 MARKET_CACHE_QUIET=1 后
       `待更新 stocks=` 行走 _qprint 被静默，只进 cron 投递存档，不落 ~/.hermes/logs
    2. ~/.hermes/logs/market_cache_refresh.log——非 quiet 路径的兜底
    返回 (stocks数 或 None, 来源文件路径 或 None)
    """
    import glob
    output_dir = BASE_DIR / 'cron' / 'output' / 'a6a60497fbb6'
    # 源1: 投递存档（排除 latest.md 累积文件，按时间戳文件名取最新）
    try:
        files = sorted(glob.glob(str(output_dir / '2026-*.md')), reverse=True)
        for f in files[:5]:
            content = Path(f).read_text(errors='replace')
            m = re.findall(r'待更新 stocks=(\d+)', content)
            if m:
                return int(m[-1]), f
    except Exception:
        pass
    # 源2: 日志文件
    try:
        if LOG_FILE.exists():
            content = LOG_FILE.read_text(errors='replace')
            m = re.findall(r'待更新 stocks=(\d+)', content)
            if m:
                return int(m[-1]), str(LOG_FILE)
    except Exception:
        pass
    return None, None


def check_market_cache_log() -> tuple[bool, str]:
    """检查最近一次刷新的 stocks 列表长度是否 > 5000（不限定今天）"""
    stocks, src = _latest_stocks_count()
    if stocks is None:
        return False, "⚠️ 未找到任何 stocks 列表记录（market_cache 可能从未成功刷新）"
    if stocks > 5000:
        return True, f"✅ 最近刷新 stocks 列表长度: {stocks}（{Path(src).name}）"
    elif stocks > 0:
        return False, f"⚠️ 最近刷新 stocks 列表长度仅 {stocks}（预期 >5000）"
    else:
        return False, f"🚨 最近刷新 stocks 列表为空（可能 DB_PATH 切换或数据异常，{src}）"


def check_duration() -> tuple[bool, str]:
    """检查最近一次 market_cache 刷新的 duration（不限定今天）"""
    try:
        executions_db = BASE_DIR / 'cron' / 'executions.db'
        if not executions_db.exists():
            return False, "⚠️ executions.db 不存在"

        conn = sqlite3.connect(executions_db, timeout=60)
        cur = conn.cursor()
        # 最近一次 market_cache 执行（含失败——失败的 duration 恰好是假成功信号）
        cur.execute("""
            SELECT status, strftime('%s', finished_at) - strftime('%s', started_at) as duration_sec,
                   DATE(claimed_at)
            FROM executions
            WHERE job_id = 'a6a60497fbb6'
              AND finished_at IS NOT NULL
            ORDER BY claimed_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        conn.close()

        if not row:
            return False, "⚠️ 无 market_cache 执行记录"

        status, duration_sec, run_date = row
        if duration_sec is None:
            return False, "⚠️ market_cache duration 为 NULL"

        if duration_sec > 100:
            return True, f"✅ 最近刷新({run_date}, {status}) duration: {duration_sec}s"
        else:
            return False, f"⚠️ 最近刷新({run_date}, {status}) duration 仅 {duration_sec}s（预期 >100s，可能假成功）"
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

    # 交易日判断: 决定 klines 的期望新鲜度
    # 语义（用户 2026-09-19 修正）: 检查"系统最新状态"而非"今天有没有干活"——
    #   交易日: klines 应为当日（滞后 ≥1 天即警，refresh 挂了的次日信号全吃旧数据）
    #   周末/节假日: 最新数据=上一交易日收盘，滞后 = 距上一交易日的天数，
    #              跨过一个完整周末滞后 2-3 天是正常态，阈值放宽到 3 天
    try:
        from exchange_holidays import is_trading_calendar_day
        trading_today = is_trading_calendar_day(today)
    except Exception:
        trading_today = today.weekday() < 5
    if trading_today:
        klines_max_lag = 0
    else:
        # 非交易日: 周一 lag=3(周五数据)、周日 lag=2、周六 lag=1 均正常 → 阈值 3
        klines_max_lag = 3

    alerts = []
    ok_lines = []
    checks = []
    for table, col, kind, max_lag, desc in FRESHNESS_CHECKS:
        if table == 'klines':
            checks.append((table, col, kind, klines_max_lag, desc))
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
