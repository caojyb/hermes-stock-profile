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
    conn = sqlite3.connect(EXECUTIONS_DB, timeout=30)
    rows = conn.execute(
        "SELECT job_id, status, claimed_at, substr(error,1,120) FROM executions "
        "WHERE claimed_at >= ? AND status != 'completed' ORDER BY claimed_at DESC LIMIT 50",
        (since.isoformat(),)).fetchall()
    conn.close()
    for job_id, status, claimed_at, error in rows:
        findings.append({'job_id': job_id, 'status': status,
                         'at': claimed_at[:16] if claimed_at else '?', 'error': error or ''})
    return findings


def scan_missed_runs() -> list:
    """enabled job 上次运行距今超过 3 天 → 停机缺口嫌疑"""
    findings = []
    if not JOBS_JSON.exists():
        return findings
    try:
        jobs = json.loads(JOBS_JSON.read_text())
    except json.JSONDecodeError:
        return findings
    now = datetime.now()
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
            days = (now - last_dt).days
            if days >= 3:
                findings.append({'job_id': j.get('job_id', j.get('name', '?')),
                                 'name': j.get('name', ''), 'last_run': last[:10],
                                 'days_silent': days})
        except ValueError:
            continue
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

    if not (warn_hits or failed or missed):
        print()  # watchdog: 全健康则静默
        return

    lines = [f"🩺 cron 健康哨兵 | {datetime.now():%m-%d %H:%M}", "=" * 46]
    if failed:
        lines.append(f"\n❌ 执行失败 ({len(failed)}):")
        for x in failed[:10]:
            lines.append(f"  {x['job_id']} {x['status']} @{x['at']} {x['error'][:60]}")
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
