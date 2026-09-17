#!/usr/bin/env python3
"""
Find remaining broken path references after migration.
"""
import re
from pathlib import Path

PROFILE = Path("/home/caojy/.hermes/profiles/stock")

# Patterns that indicate broken paths
BROKEN_PATTERNS = [
    "PROFILE / 'stock-work/production/scripts/cron'",
    "PROFILE / 'stock-work/production/data'",
    "/home/caojy/.hermes/profiles/stock/scripts/cron/",
    "/home/caojy/.hermes/profiles/stock/data/",
    "~/.hermes/profiles/stock/scripts/cron/",
    "~/.hermes/profiles/stock/data/",
]

SCAN_ROOTS = [
    PROFILE / "stock-work/production/scripts/cron",
    PROFILE / "scripts",
    PROFILE / "skills",
    PROFILE / "stock-work",
    PROFILE / "cron",
]

EXCLUDE = {"__pycache__", ".git", "sessions", "cache", "snapshots", "recovery", "quarantine"}

def should_scan(p: Path):
    parts = p.relative_to(PROFILE).parts
    return not any(x in parts for x in EXCLUDE)

print("=== FINDING REMAINING BROKEN PATHS ===\n")

found = []
for root in SCAN_ROOTS:
    if not root.exists():
        continue
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if not should_scan(path):
            continue
        if path.suffix.lower() not in {'.py', '.sh', '.json', '.yaml', '.yml', '.md', '.toml', '.ini'}:
            continue
        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for pattern in BROKEN_PATTERNS:
            if pattern in content:
                found.append((str(path.relative_to(PROFILE)), pattern))

if found:
    print(f"Found {len(found)} broken path references:\n")
    for file, pattern in found:
        print(f"  {file}: contains '{pattern}'")
else:
    print("No broken path references found.")
