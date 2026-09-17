#!/usr/bin/env python3
"""Patch cron scripts to inject stock-work/skills into sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path('/home/caojy/.hermes/profiles/stock')
SCRIPTS = [
    'scripts/cron/double_monitor.py',
    'scripts/cron/double_refresh.py',
    'scripts/cron/intraday_cache.py',
    'scripts/cron/lhb_monitor.py',
    'scripts/cron/news_sentiment.py',
    'scripts/cron/daily_data_refresh.py',
    'scripts/cron/stock_opportunity_scan.py',
]

PREFIX = '''import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "stock-work"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/stock/stock-expert"))
'''


def patch_file(rel_path: str) -> None:
    p = ROOT / rel_path
    if not p.exists():
        print(f'MISSING: {rel_path}')
        return

    lines = p.read_text().splitlines()
    new_lines = []
    skip_next_sys = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('sys.path.insert(') or stripped.startswith('from pathlib import Path'):
            continue
        if stripped == 'import sys' and not skip_next_sys:
            skip_next_sys = True
            continue
        new_lines.append(line)

    insert_idx = 0
    for i, line in enumerate(new_lines):
        s = line.strip()
        if s.startswith('#') or s == '' or s.startswith('"""') or s.startswith("'''"):
            continue
        if s.startswith('import ') or s.startswith('from '):
            insert_idx = i + 1
        else:
            insert_idx = i
            break

    patched = new_lines[:insert_idx] + PREFIX.splitlines() + new_lines[insert_idx:]
    p.write_text('\n'.join(patched) + '\n')
    print(f'PATCHED: {rel_path}')


def main() -> None:
    for rel in SCRIPTS:
        patch_file(rel)


if __name__ == '__main__':
    main()
