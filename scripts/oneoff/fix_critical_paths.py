#!/usr/bin/env python3
"""
Fix remaining hardcoded paths in CRITICAL runtime files.
Targets:
- skills/stock/stock-expert/*.py
- skills/stock/stock-expert/skills/feishu-bitable/*.py
- scripts/*.py
- scripts/cron/*.py and *.sh
- cron/jobs.json
Does NOT touch:
- docs/
- cron/output/ (historical)
- skills/*/SKILL.md (documentation)
"""
import re
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
BACKUP = PROFILE / "stock-work/data/snapshots/migrations" / f"PATHFIX_CRITICAL_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# Exact broken tokens from find_broken_paths.py
BROKEN_TOKENS = [
    # Old absolute paths
    "/home/caojy/.hermes/profiles/stock/scripts/cron/",
    "/home/caojy/.hermes/profiles/stock/data/",
    "~/.hermes/profiles/stock/scripts/cron/",
    "~/.hermes/profiles/stock/data/",
    # Bad symbolic replacements from earlier rewrite
    "PROFILE / 'stock-work/production/scripts/cron'",
    "PROFILE / 'stock-work/production/data'",
    "PROFILE / \"stock-work/production/",
]

NEW_TOKENS = {
    "/home/caojy/.hermes/profiles/stock/data/": "/home/caojy/.hermes/profiles/stock/stock-work/data/production/",
    "~/.hermes/profiles/stock/data/": "/home/caojy/.hermes/profiles/stock/stock-work/data/production/",
    "/home/caojy/.hermes/profiles/stock/scripts/cron/": "/home/caojy/.hermes/profiles/stock/scripts/cron/",
    "~/.hermes/profiles/stock/scripts/cron/": "/home/caojy/.hermes/profiles/stock/scripts/cron/",
}

SCAN_ROOTS = [
    PROFILE / "skills/stock/stock-expert",
    PROFILE / "scripts",
    PROFILE / "stock-work/production/scripts/cron",
    PROFILE / "cron/jobs.json",
]

EXCLUDE_DIRS = {"__pycache__", ".git", "sessions", "cache", "snapshots", "recovery", "quarantine", "archive", "outputs", "logs"}

def rel(p):
    return str(p.relative_to(PROFILE))

def backup_file(p: Path):
    dst = BACKUP / rel(p)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(p.read_bytes())
    return dst

def should_scan(p: Path):
    parts = p.relative_to(PROFILE).parts
    if any(x in parts for x in EXCLUDE_DIRS):
        return False
    return True

def fix_content(content: str):
    original = content
    for old, new in NEW_TOKENS.items():
        content = content.replace(old, new)
    # Also clean up broken symbolic replacements
    content = content.replace("PROFILE / 'stock-work/production/scripts/cron'", "/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron")
    content = content.replace("PROFILE / 'stock-work/production/data'", "/home/caojy/.hermes/profiles/stock/stock-work/production/data")
    content = content.replace('PROFILE / "stock-work/production/', "/home/caojy/.hermes/profiles/stock/stock-work/production/")
    return content if content != original else None

def process_file(path: Path):
    if not path.is_file():
        return False
    if path.suffix.lower() not in {'.py', '.sh', '.json'}:
        return False
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return False
    
    new_content = fix_content(content)
    if new_content is None:
        return False
    
    backup_file(path)
    path.write_text(new_content, encoding='utf-8')
    print(f"  FIXED: {rel(path)}")
    return True

print("=" * 80)
print("FIX CRITICAL RUNTIME PATHS")
print("=" * 80)
print(f"BACKUP: {BACKUP}\n")

fixed = 0
for root in SCAN_ROOTS:
    if not root.exists():
        continue
    print(f"\n[Scanning {rel(root)}]")
    if root.is_file():
        if process_file(root):
            fixed += 1
    else:
        for path in root.rglob("*"):
            if not should_scan(path):
                continue
            if process_file(path):
                fixed += 1

print(f"\nFixed {fixed} critical files")
print(f"Backup: {BACKUP}")
print("=" * 80)
