#!/usr/bin/env python3
# @deprecated: 死代码，2026-09-13 确认无调用方
"""Run all 18 script cron jobs and capture results."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path('/home/caojy/.hermes/profiles/stock')
JOBS_JSON = ROOT / 'cron/jobs.json'
RESULTS_JSON = ROOT / 'scripts' / 'cron' / 'cron_run_results.json'

CST = timezone(timedelta(hours=8))


def load_jobs():
    with open(JOBS_JSON) as f:
        data = json.load(f)
    jobs = data.get('jobs', [])
    script_jobs = []
    for job in jobs:
        script = job.get('script') or job.get('input') or ''
        if script.startswith('/home/') or script.startswith('stock-work/'):
            script_jobs.append(job)
    return script_jobs


def resolve_script_path(job):
    script = job.get('script') or job.get('input') or ''
    if ';' in script:
        script = script.split(';')[0].strip()
    if script.startswith('/home/'):
        return Path(script)
    if script.startswith('stock-work/'):
        return ROOT / script
    return ROOT / 'stock-work/production/scripts/cron' / script


def run_job(job):
    script_path = resolve_script_path(job)
    if not script_path.exists():
        return {
            'job_id': job.get('id', 'NO_ID'),
            'name': job.get('name', 'NO_NAME'),
            'status': 'SCRIPT_NOT_FOUND',
            'exit_code': -1,
            'stdout': '',
            'stderr': f'Script not found: {script_path}',
            'duration_seconds': 0,
            'ran_at': datetime.now(CST).isoformat(),
        }

    start = datetime.now(CST)
    try:
        if script_path.suffix == '.sh':
            cmd = ['bash', str(script_path)]
        elif script_path.suffix == '.py':
            cmd = [sys.executable, str(script_path)]
        else:
            cmd = [str(script_path)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=ROOT,
        )
        duration = (datetime.now(CST) - start).total_seconds()
        return {
            'job_id': job.get('id', 'NO_ID'),
            'name': job.get('name', 'NO_NAME'),
            'status': 'SUCCESS' if result.returncode == 0 else 'FAILED',
            'exit_code': result.returncode,
            'stdout': result.stdout[-4000:] if result.stdout else '',
            'stderr': result.stderr[-4000:] if result.stderr else '',
            'duration_seconds': round(duration, 2),
            'ran_at': start.isoformat(),
        }
    except subprocess.TimeoutExpired:
        duration = (datetime.now(CST) - start).total_seconds()
        return {
            'job_id': job.get('id', 'NO_ID'),
            'name': job.get('name', 'NO_NAME'),
            'status': 'TIMEOUT',
            'exit_code': -1,
            'stdout': '',
            'stderr': 'Timed out after 600s',
            'duration_seconds': round(duration, 2),
            'ran_at': start.isoformat(),
        }
    except Exception as e:
        duration = (datetime.now(CST) - start).total_seconds()
        return {
            'job_id': job.get('id', 'NO_ID'),
            'name': job.get('name', 'NO_NAME'),
            'status': 'ERROR',
            'exit_code': -1,
            'stdout': '',
            'stderr': str(e),
            'duration_seconds': round(duration, 2),
            'ran_at': start.isoformat(),
        }


def main():
    jobs = load_jobs()
    print(f'Running {len(jobs)} script jobs...')
    results = []
    for job in jobs:
        print(f'Running {job.get("name")}...', flush=True)
        res = run_job(job)
        results.append(res)
        print(f'  -> {res["status"]} (exit={res["exit_code"]}, {res["duration_seconds"]}s)')
        if res['stderr']:
            print(f'  stderr: {res["stderr"][:300]}')

    with open(RESULTS_JSON, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success = sum(1 for r in results if r['status'] == 'SUCCESS')
    failed = [r for r in results if r['status'] != 'SUCCESS']
    print(f'\nSummary: {success}/{len(results)} succeeded, {len(failed)} failed')
    for r in failed:
        print(f'  FAIL: {r["name"]} ({r["job_id"]}) -> {r["status"]}: {r["stderr"][:200]}')


if __name__ == '__main__':
    main()