#!/usr/bin/env python3
"""
c4_b2_stage3_missing_variants.py — M9.1-C4-B2-M missing 6 variants runner.
Runs only: breakout_strength_v1, breakout_confirmation_v1, volatility_level_v1,
           volatility_change_v1, volume_trend_v1, volume_price_correlation_v1
Uses same optimized path as Stage 3. Read-only. No production mutation.
"""
from __future__ import annotations

import json, os, sys, time, hashlib
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.research.walk_forward_validation import WalkForwardEngine
from core.research.strategies.breakout_strategy import BreakoutStrengthStrategy, BreakoutConfirmationStrategy
from core.research.strategies.volatility_strategy import VolatilityLevelStrategy, VolatilityChangeStrategy
from core.research.strategies.price_volume_strategy import VolumeTrendStrategy, VolumePriceCorrelationStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy
from core.research.runtime_caching_layer import KlineCache, UniverseCache, ReferenceCache

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/strategy'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

import sqlite3
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
    return rows

HORIZONS = [5, 10, 20]
FOLDS_COUNT = 8

VARIANTS = [
    ("breakout_strength_v1", "Breakout", BreakoutStrengthStrategy, {"lookback": 20}),
    ("breakout_confirmation_v1", "Breakout", BreakoutConfirmationStrategy, {"lookback": 20}),
    ("volatility_level_v1", "Volatility", VolatilityLevelStrategy, {"lookback": 20}),
    ("volatility_change_v1", "Volatility", VolatilityChangeStrategy, {"lookback_short": 10, "lookback_long": 30}),
    ("volume_trend_v1", "PriceVolume", VolumeTrendStrategy, {"lookback": 20}),
    ("volume_price_correlation_v1", "PriceVolume", VolumePriceCorrelationStrategy, {"lookback": 20}),
]

def build_engine():
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
    engine.kline_cache = KlineCache(str(DB_PATH))
    engine.universe_cache = UniverseCache(universe_fetcher)
    engine.reference_cache = ReferenceCache()
    return engine

def deterministic_cache_key(fold_id: str, strategy_id: str, horizon: int) -> str:
    key = f"stage3/v1/{fold_id}/{strategy_id}/horizon={horizon}/universe=RESEARCH_UNIVERSE_V1/db={DB_PATH.name}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

def run_chunk(variant_index: int) -> Dict[str, Any]:
    t0 = time.time()
    strategy_id, family, cls, params = VARIANTS[variant_index]
    engine = build_engine()
    folds = engine.define_folds_auto(252, 63, 5, FOLDS_COUNT, FOLDS_COUNT)
    strategy = cls(**params)

    experiments = []
    cache_hits = 0
    cache_misses = 0
    failure_counts: Dict[str, int] = {}

    for fold in folds:
        for horizon in HORIZONS:
            cache_key = deterministic_cache_key(fold.fold_id, strategy_id, horizon)
            try:
                res = engine.run_fold(
                    fold=fold,
                    strategy=strategy,
                    baseline_strategy=NaiveBaselineStrategy(seed=42),
                    horizons=[horizon],
                    normalization_method="percentile",
                )
                cache_hits += getattr(res, "cache_hits", 0)
                cache_misses += getattr(res, "cache_misses", 0)
                failure_counts[res.fold_status] = failure_counts.get(res.fold_status, 0) + 1
            except AssertionError as e:
                status = "NON_TRADING_DECISION_DATE" if "NON_TRADING_DECISION_DATE" in str(e) else "INVALID_FOLD_BOUNDARY"
                failure_counts[status] = failure_counts.get(status, 0) + 1
                experiments.append({
                    "strategy_id": strategy_id,
                    "family": family,
                    "variant_id": strategy_id,
                    "fold_id": fold.fold_id,
                    "horizon": horizon,
                    "fold_status": status,
                    "cache_key": cache_key,
                })
                continue
            except Exception as e:
                status = "ENGINE_FAILURE"
                failure_counts[status] = failure_counts.get(status, 0) + 1
                experiments.append({
                    "strategy_id": strategy_id,
                    "family": family,
                    "variant_id": strategy_id,
                    "fold_id": fold.fold_id,
                    "horizon": horizon,
                    "fold_status": status,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "cache_key": cache_key,
                })
                continue

            entry = {
                "experiment_id": f"stage3/{strategy_id}/{fold.fold_id}/horizon={horizon}",
                "strategy_id": strategy_id,
                "family": family,
                "variant_id": strategy_id,
                "fold_id": fold.fold_id,
                "horizon": horizon,
                "fold_start": fold.train_start,
                "fold_end": fold.validation_end,
                "decision_dates": {
                    "train_start": fold.train_start,
                    "train_end": fold.train_end,
                    "validation_start": fold.validation_start,
                    "validation_end": fold.validation_end,
                },
                "fold_status": res.fold_status,
                "signal_count": res.signal_count,
                "eligible_count": res.eligible_count,
                "candidate_count": res.eligible_count,
                "reference_valid_count": getattr(res, "reference_valid_count", 0),
                "valid_target_count": res.valid_target_count,
                "missing_target_count": res.missing_target_count,
                "strategy_ic": res.strategy_ic,
                "strategy_mean_excess": res.strategy_mean_excess,
                "strategy_median_excess": getattr(res, "strategy_median_excess", None),
                "strategy_hit_rate": getattr(res, "strategy_hit_rate", None),
                "baseline_ic": res.baseline_ic,
                "dataset_version": "v1",
                "universe_version": "RESEARCH_UNIVERSE_V1",
                "target_version": "v1",
                "pit_policy": "PIT_RESEARCH_V1",
                "fold_policy": "anchored_expanding",
                "cache_key": cache_key,
            }
            experiments.append(entry)

    chunk = {
        "strategy_id": strategy_id,
        "family": family,
        "variant_index": variant_index,
        "total_experiments": len(folds) * len(HORIZONS),
        "completed_experiments": len(experiments),
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "failure_counts": failure_counts,
        "elapsed_seconds": round(time.time() - t0, 3),
        "experiments": experiments,
    }
    return chunk

def main():
    t0 = time.time()
    print(f"Stage 3 missing variants: {len(VARIANTS)} variants × {FOLDS_COUNT} folds × {len(HORIZONS)} horizons = {len(VARIANTS) * FOLDS_COUNT * len(HORIZONS)} experiments", flush=True)

    variant_summaries = []
    for idx in range(len(VARIANTS)):
        strategy_id, family, cls, params = VARIANTS[idx]
        print(f"Chunk {idx+1}/{len(VARIANTS)}: {strategy_id}", flush=True)
        chunk = run_chunk(idx)
        chunk_file = ARTIFACT_DIR / f"c4_b2_stage3_chunk_{idx:02d}_{strategy_id}.json"
        chunk_file.write_text(json.dumps(chunk, indent=2, ensure_ascii=False), encoding="utf-8")
        variant_summaries.append({
            "strategy_id": strategy_id,
            "family": family,
            "total_experiments": chunk["total_experiments"],
            "completed_experiments": chunk["completed_experiments"],
            "cache_hits": chunk["cache_hits"],
            "cache_misses": chunk["cache_misses"],
            "failure_counts": chunk["failure_counts"],
            "elapsed_seconds": chunk["elapsed_seconds"],
        })

    print(json.dumps(variant_summaries, indent=2, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
