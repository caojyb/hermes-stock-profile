#!/usr/bin/env python3
"""
Fix remaining hardcoded paths in production scripts after migration.
Only targets scripts/cron/ and scripts/ directories.
"""
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
BACKUP = PROFILE / "stock-work" / "data" / "snapshots" / "migrations" / f"PATHFIX_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

REWRITES = [
    # Data paths
    ("/home/caojy/.hermes/profiles/stock/data/market_cache.db",
     "/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"),
    ("/home/caojy/.hermes/profiles/stock/data/simulation.db",
     "/home/caojy/.hermes/profiles/stock/stock-work/data/production/simulation.db"),
    ("/home/caojy/.hermes/profiles/stock/data/recommendation_pool.db",
     "/home/caojy/.hermes/profiles/stock/stock-work/data/production/recommendation_pool.db"),
    ("/home/caojy/.hermes/profiles/stock/data/lhb_cache.db",
     "/home/caojy/.hermes/profiles/stock/stock-work/data/production/lhb_cache.db"),
    # Script paths
    ("/home/caojy/.hermes/profiles/stock/scripts/cron/",
     "/home/caojy/.hermes/profiles/stock/scripts/cron/"),
    ("~/.hermes/profiles/stock/scripts/cron/",
     "/home/caojy/.hermes/profiles/stock/scripts/cron/"),
]

SCAN_ROOTS = [
    PROFILE / "stock-work/production/scripts/cron",
    PROFILE / "scripts",
]

EXCLUDE = {"__pycache__", ".git", "sessions", "cache", "snapshots", str(BACKUP.relative_to(PROFILE))}

def rel(p):
    return str(p.relative_to(PROFILE))

def backup_file(p: Path):
    dst = BACKUP / rel(p)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(p.read_bytes())
    return dst

def should_scan(p: Path):
    parts = p.relative_to(PROFILE).parts
    return not any(x in parts for x in EXCLUDE)

print("=" * 80)
print("PATH FIX FOR PRODUCTION SCRIPTS")
print("=" * 80)
print(f"BACKUP: {BACKUP}\n")

fixed = 0
for root in SCAN_ROOTS:
    if not root.exists():
        continue
    print(f"\n[Scanning {rel(root)}]")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if not should_scan(path):
            continue
        if path.suffix.lower() not in {'.py', '.sh', '.json', '.yaml', '.yml', '.md'}:
            continue
        
        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        
        original = content
        for old, new in REWRITES:
            if old in content:
                content = content.replace(old, new)
        
        if content != original:
            backup_file(path)
            path.write_text(content, encoding='utf-8')
            fixed += 1
            print(f"  FIXED: {rel(path)}")

print(f"\nFixed {fixed} files")
print(f"Backup: {BACKUP}")
print("=" * 80)
