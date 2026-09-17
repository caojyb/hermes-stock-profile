#!/usr/bin/env python3
"""
Stock profile restructure migration.
Moves:
  scripts/cron -> stock-work/production/scripts/cron
  data -> stock-work/production/data
Keeps:
  skills/stock/ -> profile skills (Hermes managed)
Updates:
  All hardcoded paths in .py/.sh/.json/.yaml/.yml/.md
  cron/jobs.json script paths
"""
import os
import re
import shutil
import json
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
BACKUP = PROFILE / "stock-work" / "data" / "snapshots" / "migrations" / f"RESTRUCTURE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
LOG = PROFILE / "stock-work" / "data" / "snapshots" / "migrations" / f"restructure_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

OLD_SCRIPT = PROFILE / "scripts/cron"
NEW_SCRIPT = PROFILE / "stock-work/production/scripts/cron"
OLD_DATA = PROFILE / "data"
NEW_DATA = PROFILE / "stock-work/production/data"

REWRITE_MAP = {
    # Data paths
    "/home/caojy/.hermes/profiles/stock/data/": "PROFILE / 'stock-work/production/data' / ",
    "~/.hermes/profiles/stock/data/": "PROFILE / 'stock-work/production/data' / ",
    # Script paths
    "/home/caojy/.hermes/profiles/stock/scripts/cron/": "PROFILE / 'stock-work/production/scripts/cron' / ",
    "~/.hermes/profiles/stock/scripts/cron/": "PROFILE / 'stock-work/production/scripts/cron' / ",
    "/home/caojy/.hermes/profiles/stock/scripts/cron": "PROFILE / 'stock-work/production/scripts/cron'",
    "~/.hermes/profiles/stock/scripts/cron": "PROFILE / 'stock-work/production/scripts/cron'",
}

SCAN_ROOTS = [
    PROFILE / "scripts",
    PROFILE / "skills",
    PROFILE / "stock-work",
    PROFILE / "cron",
    PROFILE / "data",
]

EXCLUDE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", "sessions", "cache", 
    "memories", "logs", "runtime", "quarantine", "archive", "outputs",
    "snapshots", str(BACKUP.relative_to(PROFILE)), str(LOG.relative_to(PROFILE))
}

def rel(p):
    return str(p.relative_to(PROFILE))

def backup_file(p: Path):
    dst = BACKUP / rel(p)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)
    return dst

def should_scan(p: Path):
    parts = p.relative_to(PROFILE).parts
    if any(x in parts for x in EXCLUDE_DIRS):
        return False
    # Skip recovery dirs and other restricted dirs
    if 'recovery' in parts or 'quarantine' in parts:
        return False
    return True

def rewrite_content(content: str, path: Path):
    original = content
    changed = False
    changes = []
    
    for old, new in REWRITE_MAP.items():
        if old in content:
            content = content.replace(old, new)
            if content != original:
                changed = True
                changes.append(f"  {old} -> {new}")
    
    # Special case: scripts/cron references in skills SKILL.md files
    # These are documentation, not code, but should still be updated
    if path.suffix == '.md' and 'scripts/cron' in content:
        content = content.replace('scripts/cron', 'stock-work/production/scripts/cron')
        changed = True
        changes.append("  docs: scripts/cron -> stock-work/production/scripts/cron")
    
    return content, changed, changes

def process_file(path: Path):
    if not should_scan(path):
        return []
    
    if path.suffix.lower() not in {'.py', '.sh', '.json', '.yaml', '.yml', '.md', '.toml', '.ini'}:
        return []
    
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []
    
    new_content, changed, changes = rewrite_content(content, path)
    
    if not changed:
        return []
    
    # Backup original
    backup_file(path)
    
    # Write modified
    path.write_text(new_content, encoding='utf-8')
    
    print(f"  REWRITE: {rel(path)}")
    for c in changes:
        print(c)
    
    return changes

def move_dir(src: Path, dst: Path):
    if not src.exists():
        print(f"  SKIP: {rel(src)} does not exist")
        return False
    
    if dst.exists():
        print(f"  CONFLICT: {rel(dst)} already exists")
        return False
    
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    print(f"  MOVE: {rel(src)} -> {rel(dst)}")
    return True

def update_cron_jobs():
    jobs_file = PROFILE / "cron/jobs.json"
    if not jobs_file.exists():
        print("  SKIP: cron/jobs.json not found")
        return
    
    backup_file(jobs_file)
    
    with open(jobs_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    changed = False
    for job in data.get('jobs', []):
        if not isinstance(job, dict):
            continue
        script = job.get('script')
        if not script or not isinstance(script, str):
            continue
        if 'scripts/cron' in script:
            old = script
            # Only rewrite absolute paths that contain scripts/cron
            if old.startswith('/home/') or old.startswith('~/'):
                script = old.replace('/home/caojy/.hermes/profiles/stock/scripts/cron', '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
                script = script.replace('~/.hermes/profiles/stock/scripts/cron', '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron')
            if script != old:
                job['script'] = script
                changed = True
                print(f"  CRON: {old} -> {script}")
    
    if changed:
        with open(jobs_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  UPDATED: cron/jobs.json")
    else:
        print("  NO CHANGE: cron/jobs.json")

print("=" * 80)
print("STOCK PROFILE RESTRUCTURE MIGRATION")
print("=" * 80)
print(f"PROFILE: {PROFILE}")
print(f"BACKUP:  {BACKUP}")
print()

# Phase 1: Move directories
print("\n## Phase 1: Directory Migration ##\n")

print("\n[Moving scripts/cron -> stock-work/production/scripts/cron]")
if OLD_SCRIPT.exists():
    move_dir(OLD_SCRIPT, NEW_SCRIPT)
else:
    print(f"  SKIP: {rel(OLD_SCRIPT)} does not exist")

print("\n[Moving data -> stock-work/production/data]")
if OLD_DATA.exists():
    move_dir(OLD_DATA, NEW_DATA)
else:
    print(f"  SKIP: {rel(OLD_DATA)} does not exist")

# Phase 2: Rewrite paths in source files
print("\n## Phase 2: Path Rewriting ##\n")

total_changes = 0
for root in SCAN_ROOTS:
    if not root.exists():
        continue
    print(f"\n[Scanning {rel(root)}]")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        changes = process_file(path)
        total_changes += len(changes)

# Phase 3: Update cron jobs
print("\n## Phase 3: Cron Jobs ##\n")
update_cron_jobs()

# Phase 4: Verification
print("\n## Phase 4: Verification ##\n")

missing_old = []
for p in [OLD_SCRIPT, OLD_DATA]:
    if p.exists():
        missing_old.append(rel(p))

if missing_old:
    print(f"WARNING: Old paths still exist: {missing_old}")
else:
    print("OK: Old paths cleared")

print(f"\nTotal files rewritten: {total_changes}")
print(f"\nBackup location: {BACKUP}")
print(f"Log location: {LOG}")

# Write log
log_content = f"""# Stock Profile Restructure Log
Generated: {datetime.now().isoformat()}
Profile: {PROFILE}
Backup: {BACKUP}

## Actions
- Moved scripts/cron -> stock-work/production/scripts/cron
- Moved data -> stock-work/production/data
- Rewrote {total_changes} path references
- Updated cron/jobs.json

## Verification
- Old scripts/cron exists: {OLD_SCRIPT.exists()}
- Old data exists: {OLD_DATA.exists()}
- New scripts/cron exists: {NEW_SCRIPT.exists()}
- New data exists: {NEW_DATA.exists()}
"""

LOG.parent.mkdir(parents=True, exist_ok=True)
LOG.write_text(log_content, encoding='utf-8')

print("\n" + "=" * 80)
print("MIGRATION COMPLETE")
print("=" * 80)
