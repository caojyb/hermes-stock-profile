#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

JOBS = Path("/home/caojy/.hermes/profiles/stock/cron/jobs.json")
BACKUP = Path("/home/caojy/.hermes/profiles/stock/stock-work/data/snapshots/migrations") / f"CRON_JSON_FIX_{datetime.now():%Y%m%d_%H%M%S}"
BACKUP.mkdir(parents=True, exist_ok=True)

with open(JOBS) as f:
    content = f.read()

import shutil
shutil.copy2(JOBS, BACKUP / "jobs.json")

# Direct literal replacements
repls = {
    "stock-work/production/scripts/stock-work/production/scripts/": "stock-work/production/scripts/",
    '"script": null,': '"script": null,',  # keep as-is
}
for old, new in repls.items():
    content = content.replace(old, new)

# Also fix old cron/ prefix
content = content.replace('"script": "cron/', '"script": "scripts/cron/')
content = content.replace('"input": "script=cron/', '"input": "script=scripts/cron/')

with open(JOBS, 'w') as f:
    f.write(content)

# Verify
with open(JOBS) as f:
    data = json.load(f)
count = sum(1 for j in data['jobs'] if 'stock-work/production/scripts/stock-work' in (j.get('script') or ''))
print(f"Remaining broken script paths: {count}")
print(f"Backup: {BACKUP / 'jobs.json'}")
