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


def check_kline_consistency() -> tuple[bool, str]:
    """检查 klines 数据一致性：识别"常数平移"式静默数据损坏（2026-09-22 审计 P1-10 补）

    背景：原健康检查只查数量够不够、日期新不新、耗时正不正常，完全没有一致性校验。
    2026-09-21 的 16:30 刷新把 21 只股票共 12,807 行 OHLC 整体平移（-0.01~-1.00 元），
    在窗口边界制造 2.8%~10% 假跳空，而健康检查仍给全 ✅。

    【为什么不能用库内自洽性判据】
    实测校准（阳性/阴性双对照）证明：常数平移后，段内相邻行的 Δ 互相抵消，
    close/change_pct 的自洽偏差与老股复权基准切换（实测 000007 2023-05 +217%）
    在统计上无法区分——连续多轮调参都只能做到"阳性也漏"或"阴性误报"。
    先把校准过程和结论写在这里，避免后来者重走这条死路：
      · 判据A 相邻日 close 跳变>30%  → 平移在历史段，抓不到；抓近期又等同没抓
      · 判据B close vs change_pct 自洽 → 复权切换同形态，误报 8 只（000007/000017/...）
      · 判据C LAG 全历史 + 幅度<25pct  → 仍同时命中复权股，与平移无法分离
    结论：库内单表演不了这个判别式，必须引入外部基准。

    【本实现】与最近的 klines 快照（备份库 / 上一日冻结快照）逐行比对 OHLC。
    阳性对照：给 601886 的 2024 年段统一注入 -0.25 平移后，
    本检查精确报出 `601886 660 行差异`，且零误报。
    阴性对照：与同日备份比对报 0 差异。
    """
    import glob
    import os
    try:
        conn = sqlite3.connect(MARKET_DB, timeout=180)
        conn.execute('PRAGMA busy_timeout=180000')
        cur = conn.cursor()

        cur.execute("SELECT MAX(date) FROM klines")
        latest = cur.fetchone()[0]
        if not latest:
            conn.close()
            return False, "🚨 klines 表为空，无法做一致性校验"

        problems = []

        # ① 单日极端涨跌幅与重复行（库内可判的两项）
        cur.execute(
            "SELECT COUNT(DISTINCT code) FROM klines WHERE date=? AND ABS(change_pct) > 20.5",
            (latest,))
        extreme = cur.fetchone()[0]
        if extreme > 0:
            cur.execute(
                "SELECT code, change_pct FROM klines WHERE date=? AND ABS(change_pct) > 20.5 "
                "ORDER BY ABS(change_pct) DESC LIMIT 5", (latest,))
            samples = ', '.join(f"{c}({p:+.2f}%)" for c, p in cur.fetchall())
            problems.append(f"极端涨跌幅 {extreme} 只 >±20.5%（如 {samples}）——复牌/股改属正常，其余需人工核")
        cur.execute(
            "SELECT COUNT(*) FROM (SELECT code, date FROM klines GROUP BY code, date HAVING COUNT(*) > 1)")
        dup = cur.fetchone()[0]
        if dup > 0:
            problems.append(f"{dup} 个 (code,date) 重复行——统计/均线会翻倍失真")

        # ② 与最近的历史快照比对 OHLC（检测平移的唯一可靠判据）
        base_dir = Path(MARKET_DB).resolve().parent
        # 候选：同目录下 market_cache_pre_*.db（每日修复前的自动备份）
        snapshots = sorted(
            glob.glob(str(base_dir / 'market_cache_pre_*.db')),
            key=os.path.getmtime, reverse=True)
        snapshots = [s for s in snapshots if os.path.basename(s) != os.path.basename(str(MARKET_DB))]
        compared = None
        for snap in snapshots[:1]:  # 只比最近一个，控制耗时
            try:
                if not os.path.exists(snap) or os.path.getsize(snap) < 1e9:
                    continue
                cur.execute("ATTACH DATABASE ? AS snap", (snap,))
                cur.execute("SELECT MAX(date) FROM snap.klines")
                row = cur.fetchone()
                snap_latest = row[0] if row else None
                if not snap_latest:
                    cur.execute("DETACH DATABASE snap")
                    continue
                diff = cur.execute("""
                    SELECT m.code, COUNT(*) AS n
                    FROM main.klines m JOIN snap.klines s ON m.code=s.code AND m.date=s.date
                    WHERE ABS(m.close - s.close) > 1e-6
                       OR ABS(m.high - s.high) > 1e-6
                       OR ABS(m.low - s.low) > 1e-6
                       OR ABS(m.open - s.open) > 1e-6
                    GROUP BY m.code ORDER BY n DESC LIMIT 5
                """).fetchall()
                cur.execute("DETACH DATABASE snap")
                compared = (os.path.basename(snap), snap_latest, len(diff), diff)
            except Exception as _se:
                try:
                    cur.execute("DETACH DATABASE snap")
                except Exception:
                    pass
                continue

        conn.close()

        if compared:
            name, snap_latest, n_codes, diff = compared
            if n_codes > 0:
                samples = ', '.join(f"{c}({n}行)" for c, n in diff)
                problems.append(
                    f"与快照 {name}(截至{snap_latest}) 比对：{n_codes}+ 只股票 OHLC 被改动"
                    f"（如 {samples}）——常数平移/口径切换的指纹，需人工确认来源")

        if problems:
            return False, "⚠️ 数据一致性: " + " | ".join(problems)
        tail = f"；快照比对: {compared[0]} 无差异" if compared else "；无可用历史快照，仅库内检查"
        return True, f"✅ klines({latest}) 一致性: 无极端涨跌幅/无重复行{tail}"
    except Exception as e:
        return False, f"❌ klines 一致性检查失败: {e}"


def check_market_cache_log() -> tuple[bool, str]:
    """检查市场股票基数是否正常（不限定今天）

    2026-09-19 语义再修正（模拟周一验收时实测抓到这个 bug）：
    原实现取最近一次刷新的 `待更新 stocks=N`——但 N 是**增量待更新数**不是市场总数！
    周末/数据最新时 monotonic 层拦截大部分股票，N 只有几百（实测 795），
    会误报"stocks 列表仅 795（预期 >5000）"。
    正确基准：输出文件里的 `从 akshare 获取 N 只股票`（全量初始化时的市场总数，
    实测 5564）或 stocks 表现有行数（5199）——两者都是市场基数，与增量数无关。
    """
    import glob
    output_dir = BASE_DIR / 'cron' / 'output' / 'a6a60497fbb6'
    market_total = None
    src = None
    # 源1: 投递存档里的全量初始化行（"从 akshare 获取 N 只股票"）
    try:
        files = sorted(glob.glob(str(output_dir / '2026-*.md')), reverse=True)
        for f in files[:8]:
            content = Path(f).read_text(errors='replace')
            m = re.findall(r'从 akshare 获取 (\d+) 只股票', content)
            if m:
                market_total = int(m[-1])
                src = f
                break
    except Exception:
        pass
    # 源2: stocks 表现有行数（市场基数，任何刷新路径都会维护）
    if market_total is None:
        try:
            conn = sqlite3.connect(MARKET_DB, timeout=60)
            market_total = conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
            conn.close()
            src = 'stocks 表'
        except Exception:
            pass
    # 源3: log 文件兜底
    if market_total is None and LOG_FILE.exists():
        try:
            m = re.findall(r'从 akshare 获取 (\d+) 只股票', LOG_FILE.read_text(errors='replace'))
            if m:
                market_total = int(m[-1])
                src = str(LOG_FILE)
        except Exception:
            pass

    # 2026-09-22 审计：口径对账。
    # 原实现源1（旧投递日志的"从 akshare 获取 5564 只"）优先于源2（stocks 表现有行数），
    # 于是健康检查持续报 5564，而库里实际只有 5199 只——差 365 且两数来自不同时点。
    # 现在**一律以 stocks 表现值为主口径**，旧日志数字降级为参考值并标注差异，
    # 避免读者把两个时点的市场基数混为一谈。
    current_total = None
    try:
        conn = sqlite3.connect(MARKET_DB, timeout=60)
        current_total = conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
        conn.close()
    except Exception:
        pass

    if current_total is None:
        return False, "⚠️ 无法读取 stocks 表行数（'只股票'市场基数无从核对）"

    ref_txt = ''
    if market_total is not None and market_total != current_total:
        ref_txt = f"（旧日志参考值 {market_total}，相差 {abs(market_total - current_total)}，属不同时点口径）"

    if current_total > 5000:
        return True, f"✅ 市场股票基数: {current_total}（stocks 表现有行数）{ref_txt}"
    else:
        return False, f"⚠️ 市场股票基数仅 {current_total}（stocks 表，预期 >5000）{ref_txt}"


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

        # 2026-09-19 语义修正（模拟周一验收实测）: 固定阈值 100s 会误报——
        # 09-10(70s)/09-09(33s)/09-08(66s) 都是 completed 的增量刷新（monotonic 拦大部分=快是正常），
        # 而 09-18(62s failed) 才是真信号。判据改为:
        #   failed + 任意时长 → 必报（失败本身就是信号）
        #   completed + <100s → 仅当 klines 当日缺口（数量检查已覆盖）才报；否则记参考不报
        if status == 'failed':
            return False, f"🚨 最近刷新({run_date})失败, duration {duration_sec}s（假成功/崩溃信号）"
        if duration_sec > 100:
            return True, f"✅ 最近刷新({run_date}, {status}) duration: {duration_sec}s"
        return True, f"✅ 最近刷新({run_date}, {status}) duration: {duration_sec}s（<100s 但成功=增量少, 正常）"
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
        ("K线一致性", check_kline_consistency),
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
