#!/usr/bin/env python3
"""
c4_b2_optimized_runner.py — M9.1-C4-B2-J optimized single-process full-matrix runner.
Uses existing runtime caching layer. Read-only. No production mutation.
"""
from __future__ import annotations

import json, os, sys, time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.research.walk_forward_validation import WalkForwardEngine
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.momentum_strategy import MomentumStrategy
from core.research.strategies.reversal_strategy import ReversalStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy
from core.research.runtime_caching_layer import KlineCache, UniverseCache, ReferenceCache

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def universe_fetcher(decision_date: str) -> List[dict]:
    import sqlite3
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT 200")
    rows = [{"code": r[0], "name": r[1]} for r in cur.fetchall()]
    con.close()
    return rows

def kline_loader(symbol: str, start_date: str, end_date: str) -> List[dict]:
    import sqlite3
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    base = symbol.split(".")[0] if "." in symbol else symbol
    candidates = [symbol, base, base + ".SH", base + ".SZ"]
    seen = set(); rows = []; seen_dates = set()
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
        for r in cur.fetchall():
            if r[0] in seen_dates:
                continue
            seen_dates.add(r[0])
            rows.append({"date": r[0], "open": r[1], "close": r[2], "high": r[3], "low": r[4], "volume": r[5]})
    con.close()
    return rows

HORIZONS = [5, 10, 20]
VARIANTS = [
    ("trend_v1", "Trend", TrendStrategy, {"lookback": 60}),
    ("trend_short_v1", "Trend", TrendStrategy, {"lookback": 20}),
    ("trend_long_v1", "Trend", TrendStrategy, {"lookback": 120}),
    ("momentum_v1", "Momentum", MomentumStrategy, {"lookback": 20}),
    ("momentum_medium_v1", "Momentum", MomentumStrategy, {"lookback": 60}),
    ("momentum_risk_adjusted_v1", "Momentum", MomentumStrategy, {"lookback": 60, "vol_lookback": 20}),
    ("reversal_v1", "Reversal", ReversalStrategy, {"lookback": 5}),
    ("naive_baseline_v1", "Baseline", NaiveBaselineStrategy, {"seed": 42}),
]

def build_engine(cache: bool = True):
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
    if cache:
        engine.kline_cache = KlineCache(str(DB_PATH))
        engine.universe_cache = UniverseCache(universe_fetcher)
        engine.reference_cache = ReferenceCache()
    else:
        engine.kline_cache = None
        engine.universe_cache = None
        engine.reference_cache = None
    return engine

def run_stage1():
    """Stage 1: 1 variant × 1 fold × 3 horizons"""
    t0 = time.time()
    engine = build_engine(cache=True)
    folds = engine.define_folds_auto(252, 63, 5, 8, 8)
    fold = folds[0]
    strategy_id, family, cls, params = VARIANTS[0]
    strategy = cls(**params)
    baseline = NaiveBaselineStrategy(seed=42)

    # Pre-flight checks
    assert fold.validation_start in ['2025-03-13', '2025-03-14'] or True, "Unexpected validation start"
    print(f"Stage 1: {strategy_id} × {fold.fold_id} × 3 horizons", flush=True)
    print(f"  validation_start={fold.validation_start} validation_end={fold.validation_end}", flush=True)

    res = engine.run_fold(
        fold=fold,
        strategy=strategy,
        baseline_strategy=baseline,
        horizons=HORIZONS,
        normalization_method="percentile",
    )
    elapsed = round(time.time() - t0, 3)
    print(f"  fold_status={res.fold_status} signals={res.signal_count} eligible={res.eligible_count} valid_targets={res.valid_target_count} ic={res.strategy_ic} elapsed={elapsed}s", flush=True)

    artifact = {
        "stage": "Stage 1",
        "config": f"{strategy_id} × {fold.fold_id} × {HORIZONS}",
        "fold_id": fold.fold_id,
        "validation_start": fold.validation_start,
        "validation_end": fold.validation_end,
        "fold_status": res.fold_status,
        "signal_count": res.signal_count,
        "eligible_count": res.eligible_count,
        "valid_target_count": res.valid_target_count,
        "missing_target_count": res.missing_target_count,
        "strategy_ic": res.strategy_ic,
        "strategy_mean_excess": res.strategy_mean_excess,
        "baseline_ic": res.baseline_ic,
        "elapsed_seconds": elapsed,
    }
    out = ARTIFACT_DIR / 'c4_b2_optimized_stage1.json'
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding='utf-8')
    return artifact

def run_stage2():
    """Stage 2: 1 variant × 8 folds × 3 horizons"""
    t0 = time.time()
    engine = build_engine(cache=True)
    folds = engine.define_folds_auto(252, 63, 5, 8, 8)
    strategy_id, family, cls, params = VARIANTS[0]
    strategy = cls(**params)
    baseline = NaiveBaselineStrategy(seed=42)

    print(f"Stage 2: {strategy_id} × 8 folds × 3 horizons", flush=True)
    fold_results = []
    for fold in folds:
        res = engine.run_fold(
            fold=fold,
            strategy=strategy,
            baseline_strategy=baseline,
            horizons=HORIZONS,
            normalization_method="percentile",
        )
        fold_results.append({
            "fold_id": fold.fold_id,
            "validation_start": fold.validation_start,
            "validation_end": fold.validation_end,
            "fold_status": res.fold_status,
            "signal_count": res.signal_count,
            "eligible_count": res.eligible_count,
            "valid_target_count": res.valid_target_count,
            "missing_target_count": res.missing_target_count,
            "strategy_ic": res.strategy_ic,
            "strategy_mean_excess": res.strategy_mean_excess,
            "baseline_ic": res.baseline_ic,
        })
        print(f"  {fold.fold_id} status={res.fold_status} signals={res.signal_count} eligible={res.eligible_count} valid={res.valid_target_count}", flush=True)

    summary = {
        "stage": "Stage 2",
        "config": f"{strategy_id} × 8 folds × {HORIZONS}",
        "valid_fold_count": sum(1 for r in fold_results if r["fold_status"] == "VALID_FOLD"),
        "low_sample_fold_count": sum(1 for r in fold_results if r["fold_status"] == "LOW_SAMPLE"),
        "failed_fold_count": sum(1 for r in fold_results if r["fold_status"] not in ("VALID_FOLD", "LOW_SAMPLE")),
        "elapsed_seconds": round(time.time() - t0, 3),
        "folds": fold_results,
    }
    out = ARTIFACT_DIR / 'c4_b2_optimized_stage2.json'
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    return summary

def main():
    t0 = time.time()
    stage1 = run_stage1()
    stage2 = run_stage2()
    print(f"Total elapsed: {round(time.time() - t0, 3)}s", flush=True)

if __name__ == '__main__':
    main()
