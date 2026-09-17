#!/usr/bin/env python3
"""
target_availability_probe.py — Bounded 1-strategy/1-fold/1-horizon probe
for M9.1-C4-B2 Target Availability Closure.

Read-only probe. Writes a single JSON artifact under
data/research/target_availability/c4_b2_probe_trend_v1_fold1_horizons.json
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Dict, Any
import json

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
sys.path.insert(0, str(BASE))
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

from core.research.walk_forward_validation import WalkForwardEngine
from core.research.strategies.trend_strategy import TrendStrategy
import sqlite3


def load_sample_universe(n: int = 200) -> List[dict]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT ?",
        (n,),
    )
    rows = cur.fetchall()
    con.close()
    return [{"code": r[0], "name": r[1]} for r in rows]


def kline_loader(symbol: str, start_date: str, end_date: str) -> List[dict]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    base = symbol.split(".")[0] if "." in symbol else symbol
    candidates = [symbol, base, base + ".SH", base + ".SZ"]
    seen = set()
    for code in candidates:
        if code in seen:
            continue
        seen.add(code)
        if start_date and end_date:
            cur.execute(
                "SELECT date, open, close, high, low, volume FROM klines WHERE code=? AND date>=? AND date<=? ORDER BY date",
                (code, start_date, end_date),
            )
        else:
            cur.execute("SELECT date, open, close, high, low, volume FROM klines WHERE code=? ORDER BY date", (code,))
        rows = cur.fetchall()
        if rows:
            result = [{"date": r[0], "open": r[1], "close": r[2], "high": r[3], "low": r[4], "volume": r[5]} for r in rows]
            con.close()
            return result
    con.close()
    return []


def universe_fetcher(decision_date: str) -> List[dict]:
    return load_sample_universe(200)


def asdict(obj):
    if hasattr(obj, '__dataclass_fields__'):
        return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
    return str(obj)


def main() -> Dict[str, Any]:
    engine = WalkForwardEngine(
        universe_fetcher=universe_fetcher,
        kline_loader=kline_loader,
        db_path=str(DB_PATH),
        dataset_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        target_version="v1",
        pit_policy="PIT_RESEARCH_V1",
        fold_policy="anchored_expanding",
    )
    folds = engine.define_folds_auto(
        train_window_days=252,
        validation_window_days=63,
        embargo_days=5,
        min_folds=1,
        max_folds=1,
    )
    fold = folds[0]
    strategy = TrendStrategy(lookback=60)
    baseline_strategy = None
    # Try to load a baseline for parity; if unavailable, use same trend strategy as placeholder.
    try:
        from core.research.strategies.naive_baseline import NaiveBaselineStrategy
        baseline_strategy = NaiveBaselineStrategy(seed=42)
    except Exception:
        baseline_strategy = TrendStrategy(lookback=60)

    fold_result = engine.run_fold(
        fold=fold,
        strategy=strategy,
        baseline_strategy=baseline_strategy,
        horizons=[5, 10, 20],
        normalization_method="percentile",
    )
    out = {
        'probe': 'trend_v1 x fold_001 x horizons[5,10,20]',
        'fold': asdict(fold),
        'fold_result': asdict(fold_result),
        'artifact_path': str(ARTIFACT_DIR / 'c4_b2_probe_trend_v1_fold1_horizons.json'),
    }
    path = ARTIFACT_DIR / 'c4_b2_probe_trend_v1_fold1_horizons.json'
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


if __name__ == '__main__':
    print(json.dumps(main(), indent=2, ensure_ascii=False))
