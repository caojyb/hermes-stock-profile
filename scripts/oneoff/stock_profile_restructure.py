#!/usr/bin/env python3
"""
Stock profile restructure migration script.
READ ONLY / NO DB WRITE / NO CRON WRITE / AUTO_TRADING=OFF
"""
import os
import shutil
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
BACKUP = PROFILE / "stock-work" / "data" / "snapshots" / "migrations" / f"MIGRATION_BACKUP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

def rel(p):
    return str(p.relative_to(PROFILE))

def backup_file(p: Path):
    dst = BACKUP / rel(p)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)
    print(f"  BACKUP: {rel(p)} -> {rel(dst)}")

print("=" * 80)
print("STOCK PROFILE RESTRUCTURE MIGRATION")
print("=" * 80)
print(f"PROFILE: {PROFILE}")
print(f"BACKUP:  {BACKUP}")
print()

# Plan only
moves = [
    # (src, dst, description)
    (PROFILE / "scripts/cron", PROFILE / "stock-work/production/scripts/cron", "Production scripts"),
    (PROFILE / "data", PROFILE / "stock-work/production/data", "Production data"),
]

for src, dst, desc in moves:
    print(f"\n[{desc}]")
    print(f"  SRC:  {rel(src)}")
    print(f"  DST:  {rel(dst)}")
    if src.exists():
        print(f"  STATUS: EXISTS ({sum(1 for _ in src.rglob('*'))} items)")
    else:
        print(f"  STATUS: MISSING")
    if dst.exists():
        print(f"  CONFLICT: DST already exists")
    else:
        print(f"  READY: DST does not exist")

print("\n" + "=" * 80)
print("DRY RUN COMPLETE")
print("=" * 80)
print("\nNext: execute actual migration with backup + verification")
