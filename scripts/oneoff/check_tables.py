#!/usr/bin/env python3
import sys
from pathlib import Path

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
sys.path.insert(0, str(PROFILE / "stock-work"))

from core.compat_paths import MARKET_DB, SIMULATION_DB, RECOMMENDATION_POOL_DB

import sqlite3

for name, db_path in [("MARKET_DB", MARKET_DB), ("SIMULATION_DB", SIMULATION_DB), ("RECOMMENDATION_POOL_DB", RECOMMENDATION_POOL_DB)]:
    print(f"{name}: {db_path}")
    if Path(db_path).exists():
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"  Tables ({len(tables)}): {tables}")
        for t in ['financial_data', 'double_up_scores', 'klines', 'recommendation_pool']:
            print(f"    {t}: {'EXISTS' if t in tables else 'MISSING'}")
    else:
        print(f"  FILE NOT FOUND")
