#!/usr/bin/env python3
"""
c4_b2_full_matrix_trace2.py — instrumented single-fold runner.
Prints fold boundaries, injected dependencies, and stage timing.
Read-only.
"""
from __future__ import annotations

import sqlite3, json, os, sys, time, traceback
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.research.walk_forward_validation import WalkForwardEngine
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")

def universe_fetcher(decision_date: str) -> List[dict]:
    cur = _con.cursor()
    cur.execute("SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT 200")
    return [{"code": r[0], "name": r[1]} for r in cur.fetchall()]

def kline_loader(symbol: str, start_date: str, end_date: str) -> List[dict]:
    cur = _con.cursor()
    base = symbol.split(".")[0] if "." in symbol else symbol
    candidates = [symbol, base, base + ".SH", base + ".SZ"]
    seen = set(); rows = []; seen_dates = set()
    for code in candidates:
        if code in seen:
            continue
        seen.add(code)
        cur.execute(
            "SELECT date, open, close, high, low, volume FROM klines WHERE code=? AND date>=? AND date<=? ORDER BY date",
            (code, start_date, end_date),
        )
        for r in cur.fetchall():
            if r[0] in seen_dates:
                continue
            seen_dates.add(r[0])
            rows.append({"date": r[0], "open": r[1], "close": r[2], "high": r[3], "low": r[4], "volume": r[5]})
    return rows

def main():
    t0 = time.time()
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
    print("engine ready:", round(time.time()-t0, 3), flush=True)

    folds = engine.define_folds_auto(252, 63, 5, 8, 8)
    print("folds:", [(f.fold_id, f.validation_start, f.validation_end, f.train_start, f.train_end) for f in folds], round(time.time()-t0, 3), flush=True)

    fold = folds[0]
    strategy = TrendStrategy(lookback=60)
    baseline = NaiveBaselineStrategy(seed=42)
    print("strategy kline_loader:", getattr(strategy, 'kline_loader', None), flush=True)
    print("baseline kline_loader:", getattr(baseline, 'kline_loader', None), flush=True)
    print("starting fold run", flush=True)
    try:
        res = engine.run_fold(fold=fold, strategy=strategy, baseline_strategy=baseline, horizons=[5,10,20], normalization_method="percentile")
    except Exception:
        print("EXC", traceback.format_exc(), flush=True)
        raise
    print("done:", round(time.time()-t0, 3), flush=True)
    print(json.dumps({
        "fold_id": fold.fold_id,
        "fold_status": res.fold_status,
        "signal_count": res.signal_count,
        "eligible_count": res.eligible_count,
        "valid_target_count": res.valid_target_count,
        "missing_target_count": res.missing_target_count,
        "strategy_ic": res.strategy_ic,
        "strategy_mean_excess": res.strategy_mean_excess,
        "baseline_ic": res.baseline_ic,
        "elapsed_seconds": round(time.time()-t0, 3),
    }, indent=2))

if __name__ == '__main__':
    main()
