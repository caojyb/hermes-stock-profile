#!/usr/bin/env python3
"""Fix broken sys.path injection in cron scripts."""
from __future__ import annotations

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

SYS_PATH_BLOCK = '''import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "stock-work"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/stock/stock-expert"))
'''


def fix_file(rel_path: str) -> None:
    p = ROOT / rel_path
    if not p.exists():
        print(f'MISSING: {rel_path}')
        return

    lines = p.read_text().splitlines()
    # Remove any broken injected lines from inside docstrings
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped == 'from pathlib import Path' and cleaned and cleaned[-1].strip() == 'import sys':
            # Remove the import sys line too if it's part of the broken injection
            cleaned.pop()
            continue
        if stripped.startswith('sys.path.insert(0, str(Path(__file__).resolve().parents[5]'):
            continue
        cleaned.append(line)

    # Find the first real import line after docstring
    insert_idx = 0
    for i, line in enumerate(cleaned):
        s = line.strip()
        if s.startswith('#') or s == '' or s.startswith('"""') or s.startswith("'''"):
            continue
        if s.startswith('import ') or s.startswith('from '):
            insert_idx = i + 1
        else:
            insert_idx = i
            break

    # Remove duplicate import sys / from pathlib import Path if already there
    final_lines = cleaned[:insert_idx]
    tail = cleaned[insert_idx:]
    # Remove leading blank lines from tail
    while tail and tail[0].strip() == '':
        tail = tail[1:]
    # Skip duplicate import sys and from pathlib import Path at start of tail
    skip = set()
    if tail and tail[0].strip() == 'import sys':
        skip.add(0)
    if len(tail) > 1 and tail[1].strip() == 'from pathlib import Path':
        skip.add(1)
    tail = [line for idx, line in enumerate(tail) if idx not in skip]

    final_lines = final_lines + SYS_PATH_BLOCK.splitlines() + tail
    p.write_text('\n'.join(final_lines) + '\n')
    print(f'FIXED: {rel_path}')


def main() -> None:
    for rel in SCRIPTS:
        fix_file(rel)


if __name__ == '__main__':
    main()
