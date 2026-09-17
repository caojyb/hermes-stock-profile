#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
JOBS_FILE = PROFILE / "cron/jobs.json"
BACKUP = PROFILE / "stock-work/data/snapshots/migrations" / f"CRON_JSON_FIX_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BACKUP.mkdir(parents=True, exist_ok=True)

with open(JOBS_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

fixed = 0
for job in data.get('jobs', []):
    changed = False
    
    def fix_path(p):
        if not isinstance(p, str):
            return p
        # Remove duplicate nested paths
        p = p.replace('stock-work/production/scripts/stock-work/production/scripts/', 'stock-work/production/scripts/')
        # Fix old cron/ prefix (relative)
        p = p.replace('cron/', 'scripts/cron/')
        # Fix absolute old path
        p = p.replace('/home/caojy/.hermes/profiles/stock/scripts/cron/', '/home/caojy/.hermes/profiles/stock/scripts/cron/')
        # Fix ~/.hermes/scripts/cron/ absolute path
        p = p.replace('~/.hermes/scripts/cron/', '/home/caojy/.hermes/profiles/stock/scripts/cron/')
        return p
    
    for key in ['script', 'input', 'prompt']:
        if key in job and isinstance(job[key], str):
            new = fix_path(job[key])
            if new != job[key]:
                job[key] = new
                changed = True
    
    if changed:
        fixed += 1

if fixed > 0:
    import shutil
    shutil.copy2(JOBS_FILE, BACKUP / "jobs.json")
    with open(JOBS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Fixed {fixed} jobs in cron/jobs.json")
    print(f"Backup: {BACKUP / 'jobs.json'}")
else:
    print("No changes needed in cron/jobs.json")
