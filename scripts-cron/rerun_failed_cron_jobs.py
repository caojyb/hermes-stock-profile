#!/usr/bin/env python3
# @deprecated: 死代码，2026-09-13 确认无调用方
"""Rerun failed cron jobs from cron_run_results.json."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path('/home/caojy/.hermes/profiles/stock')
RESULTS_JSON = ROOT / 'scripts/cron/cron_run_results.json'
RERUN_JSON = ROOT / 'scripts/cron/cron_rerun_results.json'

CST = timezone(timedelta(hours=8))


def load_previous_results():
    with open(RESULTS_JSON) as f:
        return json.load(f)


def resolve_script_path(name):
    # Map job names to their script paths
    mapping = {
        'stock-market-cache-refresh': 'scripts/cron/market_cache_refresh.sh',
        'us-stock-weekly-update': 'scripts/cron/us_stock_weekly.sh',
        'stock-financial-weekly-refresh': 'scripts/cron/fetch_financial_refresh.sh',
        'stock-recommendation-pool-weekly': 'scripts/cron/weekly_pool_report.sh',
        'daily-sentiment-report': 'scripts/cron/sentiment_thermo.sh',
        'double-monitor-daily': 'scripts/cron/double_monitor.py',
        'double-pool-refresh': 'scripts/cron/double_refresh.py',
        'stock-intraday-minute': 'scripts/cron/intraday_cache.py',
        'stock-lhb-daily': 'scripts/cron/lhb_monitor.py',
        'stock-news-sentiment-pilot': 'scripts/cron/news_sentiment.py',
        'stock-opportunity-push': 'scripts/cron/stock_opportunity_scan.py',
        'daily-data-refresh': 'scripts/cron/daily_data_refresh.py',
    }
    rel = mapping.get(name)
    if not rel:
        return None
    p = ROOT / rel
    return p if p.exists() else None


def run_job(job):
    name = job['name']
    script_path = resolve_script_path(name)
    if not script_path:
        return {
            'job_id': job.get('job_id', 'NO_ID'),
            'name': name,
            'status': 'SCRIPT_NOT_FOUND',
            'exit_code': -1,
            'stdout': '',
            'stderr': f'Script not found for {name}',
            'duration_seconds': 0,
            'ran_at': datetime.now(CST).isoformat(),
        }

    start = datetime.now(CST)
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)] if script_path.suffix == '.py' else [str(script_path)],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=ROOT,
        )
        duration = (datetime.now(CST) - start).total_seconds()
        return {
            'job_id': job.get('job_id', 'NO_ID'),
            'name': name,
            'status': 'SUCCESS' if result.returncode == 0 else 'FAILED',
            'exit_code': result.returncode,
            'stdout': result.stdout[-2000:] if result.stdout else '',
            'stderr': result.stderr[-2000:] if result.stderr else '',
            'duration_seconds': round(duration, 2),
            'ran_at': start.isoformat(),
        }
    except subprocess.TimeoutExpired:
        duration = (datetime.now(CST) - start).total_seconds()
        return {
            'job_id': job.get('job_id', 'NO_ID'),
            'name': name,
            'status': 'TIMEOUT',
            'exit_code': -1,
            'stdout': '',
            'stderr': 'Timed out after 180s',
            'duration_seconds': round(duration, 2),
            'ran_at': start.isoformat(),
        }
    except Exception as e:
        duration = (datetime.now(CST) - start).total_seconds()
        return {
            'job_id': job.get('job_id', 'NO_ID'),
            'name': name,
            'status': 'ERROR',
            'exit_code': -1,
            'stdout': '',
            'stderr': str(e),
            'duration_seconds': round(duration, 2),
            'ran_at': start.isoformat(),
        }


def main():
    results = load_previous_results()
    failed = [r for r in results if r['status'] != 'SUCCESS']
    print(f'Rerunning {len(failed)} failed jobs...')
    rerun_results = []
    for job in failed:
        print(f'Rerunning {job["name"]}...', flush=True)
        res = run_job(job)
        rerun_results.append(res)
        print(f'  -> {res["status"]} (exit={res["exit_code"]}, {res["duration_seconds"]}s)')
        if res['stderr']:
            print(f'  stderr: {res["stderr"][:300]}')

    with open(RERUN_JSON, 'w') as f:
        json.dump(rerun_results, f, ensure_ascii=False, indent=2)

    success = sum(1 for r in rerun_results if r['status'] == 'SUCCESS')
    failed_now = [r for r in rerun_results if r['status'] != 'SUCCESS']
    print(f'\nRerun summary: {success}/{len(rerun_results)} succeeded, {len(failed_now)} failed')
    for r in failed_now:
        print(f'  FAIL: {r["name"]} ({r["job_id"]}) -> {r["status"]}: {r["stderr"][:150]}')


if __name__ == '__main__':
    main()