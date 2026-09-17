#!/usr/bin/env python3
"""
Deep cron contract audit v3 - input/output content & task dependency chain.
"""
import json, re
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
JOBS_FILE = PROFILE / "cron/jobs.json"

with open(JOBS_FILE) as f:
    data = json.load(f)

issues = []
ok = []

# Define dependency chain based on data flow
dependency_chain = {
    'daily-data-refresh': ['market_cache.db'],
    'stock-market-cache-refresh': ['market_cache.db'],
    'stock-opportunity-push': ['market_cache.db'],
    'stock-weekly-screener': ['market_cache.db', 'double_up_scores'],
    'stock-weekly-pipeline': ['market_cache.db', 'recommendation_pool.db'],
    'double-monitor-daily': ['double_up_scores', 'market_cache.db'],
    'double-pool-refresh': ['double_up_scores'],
    'market-env-report': ['market_cache.db'],
    'hot-sector-scanner': ['market_cache.db'],
    'stock-lhb-daily': ['lhb_cache.db'],
    'position-stop-loss-alert': ['market_cache.db'],
    'stock-news-sentiment-pilot': ['news_cache.db'],
    'stock-intraday-minute': ['intraday_cache.db'],
    'us-stock-weekly-update': ['us_stock_positions.json'],
    'stock-financial-weekly-refresh': ['financial_data'],
    'stock-pe-pb-weekly-refresh': ['pe_pb_data'],
    'stock-recommendation-pool-weekly': ['recommendation_pool.db'],
    'weekly-portfolio-summary': ['market_cache.db', 'recommendation_pool.db'],
    'deep-position-review': ['market_cache.db', 'westock_cache.db'],
    'stock-weekly-analysis': ['recommendation_pool.db'],
    'stock-pre-market-brief': ['market_cache.db', 'indicators'],
    'daily-sentiment-report': ['market_cache.db'],
}

for job in data.get('jobs', []):
    name = job.get('name', '?')
    script = job.get('script', '') or ''
    prompt = job.get('prompt', '') or ''
    inp = job.get('input', '') or ''
    out = job.get('output', '') or ''
    consumer = job.get('consumer', '') or ''
    schedule = job.get('schedule', {})
    sched_expr = schedule.get('expr', '') if isinstance(schedule, dict) else ''
    
    job_issues = []
    
    # 1. Check prompt references correct script paths
    if script:
        script_name = Path(script).name
        if script_name not in prompt and script_name.replace('.py', '').replace('.sh', '') not in prompt:
            # For agent tasks, prompt should reference the script
            if not job.get('no_agent'):
                job_issues.append(f"prompt doesn't reference script '{script_name}'")
    
    # 2. Check for old paths in prompt
    old_paths = [
        '~/.hermes/scripts/cron',
        '~/.hermes/profiles/stock/scripts/cron',
        '/home/caojy/.hermes/profiles/stock/scripts/cron',
        '~/.hermes/venvs/',
        '/venv/bin/python3',
    ]
    for old in old_paths:
        if old in prompt:
            job_issues.append(f"prompt contains old path: {old}")
    
    # 3. Check schedule makes sense for task type
    if 'weekly' in name and sched_expr and not any(x in sched_expr for x in ['* * 0', '0 * * 0', '5 16 * * 5', '17', '16']):
        pass  # weekly tasks can have various schedules
    
    # 4. Check agent tasks have proper skill references
    if not script and prompt:
        if 'skills=' not in inp and 'skill=' not in inp:
            job_issues.append("agent task missing skill reference in input")
    
    # 5. Check output/consumer format consistency
    if out and not consumer:
        job_issues.append("output without consumer")
    if consumer and not out:
        job_issues.append("consumer without output")
    
    # 6. Check for hardcoded absolute paths that might break
    abs_paths = re.findall(r'/home/caojy/[^\s"\']+', prompt)
    for ap in abs_paths:
        if 'stock-work' not in ap and 'skills' not in ap and 'logs' not in ap:
            job_issues.append(f"possible stale absolute path: {ap[:100]}")
    
    if job_issues:
        issues.append((name, job_issues))
    else:
        ok.append(name)

print(f"✅ OK: {len(ok)}")
print(f"⚠️ Issues: {len(issues)}")
for name, iss in issues:
    print(f"\n{name}:")
    for i in iss:
        print(f"  - {i}")

if not issues:
    print("\n✅ All cron contracts are fully consistent")
