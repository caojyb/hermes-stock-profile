#!/usr/bin/env python3
"""
c4_b2_stage2_trend_8fold.py — M9.1-C4-B2-F Trend Full Walk-Forward Target Validation
=====================================================================================
Bounded execution: trend_v1 × 8 folds × 3 horizons [5, 10, 20].
Read-only audit of fold-level funnel and target availability.
"""
from __future__ import annotations

import os, sys, sqlite3, json
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

from core.research.walk_forward_validation import WalkForwardEngine
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy

HORIZONS = [5, 10, 20]
UNIVERSE_N = 200

_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")


def load_sample_universe(n: int = UNIVERSE_N) -> List[dict]:
    cur = _con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT ?",
        (200,),
    )
    return [{"code": r[0], "name": r[1]} for r in cur.fetchall()]


def kline_loader(symbol: str, start_date: str, end_date: str) -> List[dict]:
    cur = _con.cursor()
    base = symbol.split(".")[0] if "." in symbol else symbol
    candidates = [symbol, base, base + ".SH", base + ".SZ"]
    seen = set()
    rows = []
    seen_dates = set()
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


def run_fold_with_funnel(engine, fold, strategy, baseline) -> Dict[str, Any]:
    fold_result = engine.run_fold(
        fold=fold,
        strategy=strategy,
        baseline_strategy=baseline,
        horizons=HORIZONS,
        normalization_method="percentile",
    )
    # Rebuild candidate funnel from strategy signals for visibility
    universe = universe_fetcher(fold.validation_start)
    signals = strategy.run(universe, fold.validation_start)
    eligible = [s for s in signals if getattr(s, "eligibility", False)]
    candidates = [
        {
            "symbol": s.stock_code,
            "candidate_date": fold.validation_start,
            "entry_price": getattr(s, "entry_price", None),
            "entry_date": getattr(s, "entry_date", None),
        }
        for s in eligible
    ]
    return {
        "fold_id": fold_result.fold_id,
        "fold_status": fold_result.fold_status,
        "valid_target_count": fold_result.valid_target_count,
        "missing_target_count": fold_result.missing_target_count,
        "strategy_ic": fold_result.strategy_ic,
        "strategy_mean_excess": fold_result.strategy_mean_excess,
        "baseline_ic": fold_result.baseline_ic,
        "baseline_mean_excess": fold_result.baseline_mean_excess,
        "signal_count": len(signals),
        "eligible_count": len(eligible),
        "candidate_count": len(candidates),
        "universe_count": len(universe),
        "train_start": fold.train_start,
        "train_end": fold.train_end,
        "validation_start": fold.validation_start,
        "validation_end": fold.validation_end,
        "fold_policy": fold.fold_policy,
    }


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
        min_folds=8,
        max_folds=8,
    )
    strategy = TrendStrategy(lookback=60)
    baseline = NaiveBaselineStrategy(seed=42)

    fold_results = []
    for fold in folds:
        res = run_fold_with_funnel(engine, fold, strategy, baseline)
        fold_results.append(res)

    valid_folds = [r for r in fold_results if r["fold_status"] == "VALID_FOLD"]
    low_sample_folds = [r for r in fold_results if r["fold_status"] == "LOW_SAMPLE"]
    failed_folds = [r for r in fold_results if r["fold_status"] not in ("VALID_FOLD", "LOW_SAMPLE")]

    report = {
        "decision_time": "2025-06-03",
        "strategy": "trend_v1",
        "baseline": "naive_baseline_v1",
        "total_folds": len(fold_results),
        "valid_fold_count": len(valid_folds),
        "low_sample_fold_count": len(low_sample_folds),
        "failed_fold_count": len(failed_folds),
        "folds": fold_results,
        "aggregate": {
            "total_signals": sum(r["signal_count"] for r in fold_results),
            "total_candidates": sum(r["candidate_count"] for r in fold_results),
            "total_valid_targets": sum(r["valid_target_count"] for r in fold_results),
            "total_missing_targets": sum(r["missing_target_count"] for r in fold_results),
            "horizon_coverage": {
                "5d": {
                    "folds_with_targets": sum(1 for r in fold_results if r["valid_target_count"] > 0),
                    "total_targets": sum(r["valid_target_count"] for r in fold_results),
                },
                "10d": {
                    "folds_with_targets": sum(1 for r in fold_results if r["valid_target_count"] > 0),
                    "total_targets": sum(r["valid_target_count"] for r in fold_results),
                },
                "20d": {
                    "folds_with_targets": sum(1 for r in fold_results if r["valid_target_count"] > 0),
                    "total_targets": sum(r["valid_target_count"] for r in fold_results),
                },
            },
        },
    }
    out_path = ARTIFACT_DIR / 'c4_b2_stage2_trend_8fold.json'
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    report = main()
    print(json.dumps({
        "total_folds": report["total_folds"],
        "valid_fold_count": report["valid_fold_count"],
        "low_sample_fold_count": report["low_sample_fold_count"],
        "failed_fold_count": report["failed_fold_count"],
        "total_valid_targets": report["aggregate"]["total_valid_targets"],
        "total_missing_targets": report["aggregate"]["total_missing_targets"],
        "folds": [
            {
                "fold_id": r["fold_id"],
                "fold_status": r["fold_status"],
                "valid_target_count": r["valid_target_count"],
                "signal_count": r["signal_count"],
                "candidate_count": r["candidate_count"],
                "strategy_ic": r["strategy_ic"],
                "strategy_mean_excess": r["strategy_mean_excess"],
            }
            for r in report["folds"]
        ],
    }, indent=2, ensure_ascii=False))
