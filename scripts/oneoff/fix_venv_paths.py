#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
SCRIPTS_DIR = PROFILE / "stock-work/production/scripts/cron"
BACKUP = PROFILE / "stock-work/data/snapshots/migrations" / f"VENV_FIX_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BACKUP.mkdir(parents=True, exist_ok=True)

import shutil

fixed = 0
for script in SCRIPTS_DIR.rglob("*"):
    if not script.is_file():
        continue
    if script.suffix not in {'.sh', '.py'}:
        continue
    try:
        content = script.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue
    original = content
    content = content.replace('/home/caojy/.hermes/profiles/stock/venv/bin/python3', '/home/caojy/.hermes/profiles/stock/.venv/bin/python3')
    if script.name == 'market_env_report.sh' and 'PYTHONPATH' not in content:
        content = content.replace('cd "$SCRIPT_DIR"', 'cd "$SCRIPT_DIR"\nexport PYTHONPATH="/home/caojy/.hermes/profiles/stock/stock-work:${PYTHONPATH:-}"')
    if content != original:
        dst = BACKUP / script.relative_to(PROFILE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(script, dst)
        script.write_text(content, encoding='utf-8')
        fixed += 1
        print(f"  FIXED: {script.relative_to(PROFILE)}")
print(f"\nFixed {fixed} scripts")
print(f"Backup: {BACKUP}")
