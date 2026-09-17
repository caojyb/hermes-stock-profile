#!/usr/bin/env python3
"""
c4_b2_full_matrix_runner.py — M9.1-C4-B2-H clean full-matrix regeneration.
Runs: 14 variants × 8 folds × 3 horizons using repaired WalkForwardEngine.
Read-only DB access. No production mutation.
"""
from __future__ import annotations

import sqlite3, json, os, sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.research.walk_forward_validation import WalkForwardEngine
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.momentum_strategy import MomentumStrategy
from core.research.strategies.momentum_strategy_variants import MomentumRiskAdjustedStrategy
from core.research.strategies.reversal_strategy import ReversalStrategy
from core.research.strategies.breakout_strategy import BreakoutStrengthStrategy, BreakoutConfirmationStrategy
from core.research.strategies.volatility_strategy import VolatilityLevelStrategy, VolatilityChangeStrategy
from core.research.strategies.price_volume_strategy import VolumeTrendStrategy, VolumePriceCorrelationStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")

def load_sample_universe(n: int = 200) -> List[dict]:
    cur = _con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT ?",
        (n,),
    )
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

def universe_fetcher(decision_date: str) -> List[dict]:
    return load_sample_universe(200)

HORIZONS = [5, 10, 20]
FOLDS = 8

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

folds = engine.define_folds_auto(252, 63, 5, FOLDS, FOLDS)

variants = [
    ("trend_v1", "Trend", TrendStrategy, {"lookback": 60}),
    ("trend_short_v1", "Trend", TrendStrategy, {"lookback": 20}),
    ("trend_long_v1", "Trend", TrendStrategy, {"lookback": 120}),
    ("momentum_v1", "Momentum", MomentumStrategy, {"lookback": 20}),
    ("momentum_medium_v1", "Momentum", MomentumStrategy, {"lookback": 60}),
    ("momentum_risk_adjusted_v1", "Momentum", MomentumRiskAdjustedStrategy, {"lookback": 60, "vol_lookback": 20}),
    ("reversal_v1", "Reversal", ReversalStrategy, {"lookback": 5}),
    ("breakout_strength_v1", "Breakout", BreakoutStrengthStrategy, {"lookback": 20}),
    ("breakout_confirmation_v1", "Breakout", BreakoutConfirmationStrategy, {"lookback": 20}),
    ("volatility_level_v1", "Volatility", VolatilityLevelStrategy, {"lookback": 20}),
    ("volatility_change_v1", "Volatility", VolatilityChangeStrategy, {"lookback_short": 10, "lookback_long": 30}),
    ("volume_trend_v1", "PriceVolume", VolumeTrendStrategy, {"lookback": 20}),
    ("volume_price_correlation_v1", "PriceVolume", VolumePriceCorrelationStrategy, {"lookback": 20}),
    ("naive_baseline_v1", "Baseline", NaiveBaselineStrategy, {"seed": 42}),
]

results: List[Dict[str, Any]] = []
for strategy_id, family, cls, params in variants:
    strategy = cls(**params)
    baseline = NaiveBaselineStrategy(seed=42)
    for fold in folds:
        fold_result = engine.run_fold(
            fold=fold,
            strategy=strategy,
            baseline_strategy=baseline,
            horizons=HORIZONS,
            normalization_method="percentile",
        )
        entry = {
            "strategy_id": strategy_id,
            "family": family,
            "variant_id": strategy_id,
            "fold_id": fold.fold_id,
            "fold_status": fold_result.fold_status,
            "train_start": fold.train_start,
            "train_end": fold.train_end,
            "validation_start": fold.validation_start,
            "validation_end": fold.validation_end,
            "signal_count": fold_result.signal_count,
            "eligible_count": fold_result.eligible_count,
            "valid_target_count": fold_result.valid_target_count,
            "missing_target_count": fold_result.missing_target_count,
            "strategy_ic": fold_result.strategy_ic,
            "strategy_rank_ic": fold_result.strategy_rank_ic,
            "strategy_mean_excess": fold_result.strategy_mean_excess,
            "strategy_hit_rate": fold_result.strategy_hit_rate,
            "baseline_ic": fold_result.baseline_ic,
            "baseline_rank_ic": fold_result.baseline_rank_ic,
            "baseline_mean_excess": fold_result.baseline_mean_excess,
            "ic_delta": fold_result.ic_delta,
            "mean_excess_delta": fold_result.mean_excess_delta,
            "market_period": fold_result.market_period,
            "dataset_version": "v1",
            "universe_version": "RESEARCH_UNIVERSE_V1",
            "target_version": "v1",
            "pit_policy": "PIT_RESEARCH_V1",
            "fold_policy": "anchored_expanding",
        }
        results.append(entry)

summary = {
    "total_variants": len(variants),
    "total_folds": FOLDS,
    "total_horizons": len(HORIZONS),
    "total_experiments": len(variants) * FOLDS * len(HORIZONS),
    "completed_experiments": len(results),
    "valid_fold_count": sum(1 for r in results if r["fold_status"] == "VALID_FOLD"),
    "low_sample_fold_count": sum(1 for r in results if r["fold_status"] == "LOW_SAMPLE"),
    "data_failure_count": sum(1 for r in results if r["fold_status"] == "DATA_FAILURE"),
    "engine_failure_count": sum(1 for r in results if r["fold_status"] == "ENGINE_FAILURE"),
}

payload = {
    "summary": summary,
    "experiments": results,
}

(ARTIFACT_DIR / 'c4_b2_full_matrix_regenerated.json').write_text(
    json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8'
)
(BASE / 'data/research/strategy' / 'c4_b2_full_matrix_summary.json').write_text(
    json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8'
)

print(json.dumps(summary, indent=2, ensure_ascii=False))
