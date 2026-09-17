#!/usr/bin/env python3
"""
Fix contract inconsistencies in cron/jobs.json.
Updates prompts to use new paths, fixes input fields.
"""
import json
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
JOBS_FILE = PROFILE / "cron/jobs.json"
BACKUP = PROFILE / "stock-work/data/snapshots/migrations" / f"CONTRACT_FIX_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BACKUP.mkdir(parents=True, exist_ok=True)

with open(JOBS_FILE) as f:
    data = json.load(f)

import shutil
shutil.copy2(JOBS_FILE, BACKUP / "jobs.json")

fixed = 0

for job in data.get('jobs', []):
    name = job.get('name')
    changed = False
    
    if name == 'stock-weekly-screener':
        # Fix old paths in prompt
        old = job.get('prompt', '')
        new = old.replace('~/.hermes/scripts/cron', '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
        new = new.replace('cd /home/caojy/.hermes/profiles/stock/scripts/cron', 'cd /home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
        if new != old:
            job['prompt'] = new
            changed = True
    
    elif name == 'stock-pe-pb-weekly-refresh':
        old = job.get('prompt', '')
        new = old.replace('~/.hermes/scripts/cron', '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
        if new != old:
            job['prompt'] = new
            changed = True
    
    elif name == 'weekly-portfolio-summary':
        old = job.get('prompt', '')
        new = old.replace('~/.hermes/scripts/cron', '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
        if new != old:
            job['prompt'] = new
            changed = True
    
    elif name == 'deep-position-review':
        old = job.get('prompt', '')
        new = old.replace('~/.hermes/scripts/cron', '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
        if new != old:
            job['prompt'] = new
            changed = True
    
    elif name == 'double-pool-refresh':
        old = job.get('prompt', '')
        new = old.replace('~/.hermes/scripts/cron', '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
        if new != old:
            job['prompt'] = new
            changed = True
    
    elif name == 'hot-sector-scanner':
        # Fix input to reference script basename
        if job.get('input') == 'NONE':
            job['input'] = 'script=scripts/cron/hot_sector_scanner.py; commands=1 blocks'
            changed = True
        # Fix old path in prompt
        old = job.get('prompt', '')
        new = old.replace('~/.hermes/scripts/cron', '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
        if new != old:
            job['prompt'] = new
            changed = True
    
    if changed:
        fixed += 1

if fixed > 0:
    with open(JOBS_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Fixed {fixed} jobs")
    print(f"Backup: {BACKUP / 'jobs.json'}")
else:
    print("No changes needed")
