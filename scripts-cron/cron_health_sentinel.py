#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron 健康哨兵（2026-09-18 P1-2 修复）
====================================
每日扫描最近 24h 的 cron 运行记录，专抓三类静默失败：
  1. WARN_IN_OUTPUT: exit 0 但输出含 WARN/ERROR/Traceback（如 Bitable 读取失败被吞）
  2. MISSED_RUN:    jobs.json enabled 且 next_run 正常，但上次运行超过 3 个计划周期（停机缺口）
  3. FAILED:        executions.db 中 status=failed 的运行

输出摘要（有异常才输出，watchdog 模式）；--send 时推飞书。
"""
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROFILE = Path('/home/caojy/.hermes/profiles/stock')
EXECUTIONS_DB = PROFILE / 'cron/executions.db'
JOBS_JSON = PROFILE / 'cron/jobs.json'
OUTPUT_DIR = PROFILE / 'cron/output'

WARN_PATTERNS = re.compile(
    r'\[WARN\]|WARN]|ERROR]|Traceback|AttributeError|NameError|KeyError|'
    r'Exception|失败|🚨|DECISION_PERSISTENCE_FAILED|QUALITY_ERROR|QUANTITY_ZERO|'
    r'HOLDINGS_CONTEXT_MISMATCH', re.IGNORECASE)

# 这些 WARN 模式是已知可容忍的（白名单，避免噪音）
WARN_WHITELIST = re.compile(r'北向数据更新失败.*重试|akshare.*重试中', re.IGNORECASE)


def scan_warn_in_output(since: datetime) -> list:
    """扫描最近输出目录中的 WARN/ERROR（exit 0 静默失败）"""
    findings = []
    if not OUTPUT_DIR.exists():
        return findings
    for job_dir in OUTPUT_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        for f in job_dir.glob('*.md'):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < since:
                    continue
                text = f.read_text(errors='replace')
                hits = [ln.strip() for ln in text.splitlines() if WARN_PATTERNS.search(ln)]
                hits = [h for h in hits if not WARN_WHITELIST.search(h)]
                # P1-5 修复（2026-09-21）：跳过 prompt/技能提示词中的示例文本
                # 哨兵的输出文件可能是 agent 的 prompt 拼接，其中包含 markdown 示例
                # （如「**注意：** market_cache.py 的哨兵在脚本级别上下文...」），
                # 那不是真 WARN。判据：markdown 示例标记、代码块、或以说明性前缀开头。
                def _is_example(line: str) -> bool:
                    if line.startswith(('```', '    ', '\t', '#')):
                        return True
                    if line.startswith(('**注意', '**示例', '**说明', '例如', '示例', '注意：', '说明：')):
                        return True
                    if line.startswith('**') and line.rstrip().endswith('**'):
                        return True
                    if 'prompt' in line.lower() or 'skill' in line.lower():
                        return True
                    # 哨兵自身输出的节标题（扫描自己历史输出时会命中）
                    if line.startswith(('❌ 执行失败', '⚠️ exit 0 但输出含', '❌ 心跳读取失败',
                                        '❌ 心跳目录检查失败', '⚠️ 心跳过期')):
                        return True
                    return False
                hits = [h for h in hits if not _is_example(h)]
                if hits:
                    findings.append({
                        'job_id': job_dir.name,
                        'file': f.name,
                        'mtime': mtime.strftime('%m-%d %H:%M'),
                        'warnings': hits[:5],
                        'warn_count': len(hits),
                    })
            except (OSError, UnicodeDecodeError):
                continue
    return findings


def scan_failed_executions(since: datetime) -> list:
    findings = []
    if not EXECUTIONS_DB.exists():
        return findings
    # P1-5 修复（2026-09-21）：排除自身 job_id
    # 本脚本正在运行的那一行 status 就是 'running'，原逻辑会把自己算成执行失败，
    # 于是每次推送第一条都是「❌ 执行失败: f80b367d6b79 running」。
    SELF_JOB_IDS = {'f80b367d6b79', 'cron-health-sentinel', 'cron_health_sentinel'}
    conn = sqlite3.connect(EXECUTIONS_DB, timeout=30)
    rows = conn.execute(
        "SELECT job_id, status, claimed_at, substr(error,1,120) FROM executions "
        "WHERE claimed_at >= ? AND status != 'completed' ORDER BY claimed_at DESC LIMIT 50",
        (since.isoformat(),)).fetchall()
    conn.close()
    for job_id, status, claimed_at, error in rows:
        if job_id in SELF_JOB_IDS:
            continue
        findings.append({'job_id': job_id, 'status': status,
                         'at': claimed_at[:16] if claimed_at else '?', 'error': error or ''})
    return findings


def scan_missed_runs() -> list:
    """enabled job 上次运行距今超过 3 天 → 停机缺口嫌疑。
    2026-09-18: 排除法定节假日（如中秋 9-25 前后不误报）。"""
    findings = []
    if not JOBS_JSON.exists():
        return findings
    try:
        jobs = json.loads(JOBS_JSON.read_text())
    except json.JSONDecodeError:
        return findings
    now = datetime.now()
    # 只统计"日历交易日"（工作日且非节假日）的静默天数
    from exchange_holidays import is_trading_calendar_day
    job_list = jobs.get('jobs', jobs) if isinstance(jobs, dict) else jobs
    if isinstance(job_list, dict):
        job_list = list(job_list.values())
    for j in job_list:
        if not isinstance(j, dict) or not j.get('enabled', True):
            continue
        last = j.get('last_run_at')
        if not last:
            continue
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is not None:
                last_dt = last_dt.replace(tzinfo=None)
            # 数今天回溯到 last 之间有多少个交易日缺口
            gap_days = 0
            check = now.date()
            last_date = last_dt.date()
            while check > last_date and gap_days <= 5:
                if is_trading_calendar_day(check):
                    gap_days += 1
                check = check.fromordinal(check.toordinal() - 1)
            if gap_days >= 3:
                findings.append({'job_id': j.get('job_id', j.get('name', '?')),
                                 'name': j.get('name', ''), 'last_run': last[:10],
                                 'days_silent': gap_days})
        except ValueError:
            continue
    return findings


def scan_dispatch_lateness() -> list:
    """当日迟发/漏派检测（2026-09-22 审计整改 B5）。

    背景：09-22 15:07 有人主动重启 gateway + 16:23 改 jobs.json，两者交错使
    16:30/16:40/16:50 三个 slot 漏派，17:18:42 才由 catch-up 一次性补发成簇
    —— 三写者同时打 market_cache.db，唯一写 klines 的任务等锁 60s 仍失败，
    klines 只写出 1206/5005，下游 indicators/main_fund_flow 跟随崩塌（P0）。
    全程无任何告警；次日 08:05 的哨兵也看不到"当天"的迟发。

    判据：jobs.json 的 last_dispatch.lateness_seconds。
    阈值 300s：实测 25 个 job 准时状态的固有偏移是 4–58s（42s 是 60s tick 的
    固有落点），300s 远高于该基线，只抓真漏派。

    只报当日（is_trading_calendar_day 已在 scan_missed_runs 里用过）；
    非交易日直接跳过，避免周末用上周五的值误报。
    """
    findings = []
    if not JOBS_JSON.exists():
        return findings
    try:
        jobs = json.loads(JOBS_JSON.read_text())
    except json.JSONDecodeError:
        return findings
    from exchange_holidays import is_trading_calendar_day
    if not is_trading_calendar_day(datetime.now().date()):
        return findings
    job_list = jobs.get('jobs', jobs) if isinstance(jobs, dict) else jobs
    if isinstance(job_list, dict):
        job_list = list(job_list.values())
    today = datetime.now().date().isoformat()
    for j in job_list:
        if not isinstance(j, dict) or not j.get('enabled', True):
            continue
        disp = j.get('last_dispatch')
        if not isinstance(disp, dict):
            continue
        lateness = disp.get('lateness_seconds')
        at = disp.get('dispatched_at') or ''   # 字段名是 dispatched_at，不是 at
        # 只认当日 dispatch：迟发 slot 的 dispatched_at 是补发时刻（17:18），
        # 落在当天即可报；跨天历史迟发不重复刷。
        if not lateness or lateness <= 0 or not at:
            continue
        try:
            lateness_f = float(lateness)
        except (TypeError, ValueError):
            continue
        # 迟到跨越到次日的（如周五晚补发到周六）不报，避免周末噪音
        try:
            disp_date = datetime.fromisoformat(at).date()
        except ValueError:
            continue
        # 报"今天或昨天"：收盘后的哨兵（17:15）在当天跑；
        # 但 08:05 的每日哨兵复盘的是过去 24h，其中昨天的傍晚漏派必须仍能报出来，
        # 否则"15:07 重启导致 16:30 漏派"这类事故要等到次日 08:05 之后才消失、
        # 而傍晚发生时反而无声（这正是 09-22 的形态）。
        today = datetime.now().date()
        if disp_date not in (today, today.fromordinal(today.toordinal() - 1)):
            continue
        if lateness_f > 300:
            findings.append({
                'job_id': j.get('job_id', j.get('name', '?')),
                'name': j.get('name', ''),
                'lateness_seconds': round(lateness_f),
                'scheduled_at': (disp.get('scheduled_at') or '')[:19],
                'last_dispatch_at': at[:19],
                'today': today.isoformat(),
            })
    return findings


def main():
    send = '--send' in sys.argv
    # 顺带轮转 crash 日志（超过 5MB 滚动保留 3 片）
    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location(
            'rotate_crash_log', Path(__file__).parent / 'rotate_crash_log.py')
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mod.main()
    except Exception:
        pass
    since = datetime.now() - timedelta(hours=24)
    warn_hits = scan_warn_in_output(since)
    failed = scan_failed_executions(since)
    missed = scan_missed_runs()
    late = scan_dispatch_lateness()

    if not (warn_hits or failed or missed or late):
        print()  # watchdog: 全健康则静默
        return

    lines = [f"🩺 cron 健康哨兵 | {datetime.now():%m-%d %H:%M}", "=" * 46]
    if failed:
        lines.append(f"\n❌ 执行失败 ({len(failed)}):")
        for x in failed[:10]:
            lines.append(f"  {x['job_id']} {x['status']} @{x['at']} {x['error'][:60]}")
    if late:
        lines.append(f"\n⏰ 当日迟发/漏派 ({len(late)}) —— 阈值 300s:")
        for x in late[:10]:
            lines.append(f"  {x['name'] or x['job_id']} 迟发 {x['lateness_seconds']}s "
                         f"(应于 {x['scheduled_at'][11:19]}，实派 {x['last_dispatch_at'][11:19]})")
        lines.append("  注：迟发 slot 会被 catch-up 补发成簇，多写者同刻打同一库即 P0 撞锁形态")
    if warn_hits:
        lines.append(f"\n⚠️ exit 0 但输出含 WARN（静默失败） ({len(warn_hits)} 个输出文件):")
        for x in warn_hits[:10]:
            lines.append(f"  [{x['mtime']}] {x['job_id']}/{x['file']} ({x['warn_count']} 处)")
            for w in x['warnings'][:3]:
                lines.append(f"     {w[:90]}")
    if missed:
        lines.append(f"\n🕳️ 疑似停机缺口 ({len(missed)}):")
        for x in missed[:10]:
            lines.append(f"  {x['name'] or x['job_id']} 上次运行 {x['last_run']}（{x['days_silent']} 天前）")
    lines.append("=" * 46)
    report = '\n'.join(lines)
    print(report)
    if send:
        sys.path.insert(0, str(PROFILE / 'scripts/cron'))
        try:
            from decision._local_constants import FEISHU_CHAT_ID
            sys.path.insert(0, str(PROFILE / 'skills/stock/stock-expert/skills/feishu-bitable'))
            from feishu_sender import feishu_send_message
            feishu_send_message(FEISHU_CHAT_ID, report)
            print('✅ 已推送飞书')
        except Exception as e:
            print(f'❌ 飞书推送失败: {e}')


if __name__ == '__main__':
    main()
