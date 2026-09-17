#!/usr/bin/env python3
"""
c5_e_full_matrix_runner.py — M9.1-C5-E Independent Alpha Research full matrix runner.

Runs:
- fundamental_change_v1 × 8 folds × 3 horizons
- main_force_flow_v1 × 8 folds × 3 horizons

Total: 48 experiments
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from core.research.strategies.fundamental_change_strategy import FundamentalChangeStrategy
from core.research.strategies.main_force_flow_strategy import MainForceFlowStrategy

BASE = Path(__file__).resolve().parents[2]
DB = BASE / "data/production/market_cache.db"
ART = BASE / "data/research/strategy"
ART.mkdir(parents=True, exist_ok=True)

# Reuse the same fold definitions as C4-B2 for consistency
FOLDS = [
    {"fold_id": "fold_001", "train_start": "2024-01-01", "train_end": "2024-03-31", "validation_start": "2024-04-01", "validation_end": "2024-06-30"},
    {"fold_id": "fold_002", "train_start": "2024-02-01", "train_end": "2024-04-30", "validation_start": "2024-05-01", "validation_end": "2024-07-31"},
    {"fold_id": "fold_003", "train_start": "2024-03-01", "train_end": "2024-05-31", "validation_start": "2024-06-01", "validation_end": "2024-08-31"},
    {"fold_id": "fold_004", "train_start": "2024-04-01", "train_end": "2024-06-30", "validation_start": "2024-07-01", "validation_end": "2024-09-30"},
    {"fold_id": "fold_005", "train_start": "2024-05-01", "train_end": "2024-07-31", "validation_start": "2024-08-01", "validation_end": "2024-10-31"},
    {"fold_id": "fold_006", "train_start": "2024-06-01", "train_end": "2024-08-31", "validation_start": "2024-09-01", "validation_end": "2024-11-30"},
    {"fold_id": "fold_007", "train_start": "2024-07-01", "train_end": "2024-09-30", "validation_start": "2024-10-01", "validation_end": "2024-12-31"},
    {"fold_id": "fold_008", "train_start": "2024-08-01", "train_end": "2024-10-31", "validation_start": "2024-11-01", "validation_end": "2025-01-31"},
]

HORIZONS = [5, 10, 20]

FUNDAMENTAL_SYMBOLS = ["000001", "000002", "600519", "000858", "601318", "002594", "600036", "000333", "002714", "603288"]
FLOW_SYMBOLS = ["000037", "000001", "000002", "600519", "000858", "601318", "002594", "600036", "000333", "002714"]


def run_experiment(strategy, symbol: str, decision_time: str, horizon: int) -> Dict[str, Any]:
    strategy.horizon = horizon
    stock = {"code": symbol, "symbol": symbol}
    signal = strategy.generate_signal(stock, decision_time)
    if signal is None:
        return {
            "symbol": symbol,
            "decision_time": decision_time,
            "horizon": horizon,
            "eligible": False,
            "valid_signal": False,
            "reason_code": "SOURCE_UNAVAILABLE",
        }
    return {
        "symbol": symbol,
        "decision_time": decision_time,
        "horizon": horizon,
        "eligible": signal.eligibility,
        "valid_signal": signal.eligibility,
        "raw_score": signal.raw_score,
        "reason_code": signal.reason_code,
        "metadata": signal.metadata,
    }


def run_strategy_family(strategy, symbols: List[str], decision_time: str) -> List[Dict[str, Any]]:
    results = []
    for horizon in HORIZONS:
        for symbol in symbols:
            results.append(run_experiment(strategy, symbol, decision_time, horizon))
    return results


def run_full_matrix() -> Dict[str, Any]:
    fundamental_strategy = FundamentalChangeStrategy(db_path=str(DB))
    flow_strategy = MainForceFlowStrategy(db_path=str(DB))

    fundamental_results = []
    flow_results = []

    for fold in FOLDS:
        validation_start = fold["validation_start"]
        fundamental_results.extend(run_strategy_family(fundamental_strategy, FUNDAMENTAL_SYMBOLS, validation_start))
        flow_results.extend(run_strategy_family(flow_strategy, FLOW_SYMBOLS, validation_start))

    return {
        "summary": {
            "strategies": ["fundamental_change_v1", "main_force_flow_v1"],
            "folds": len(FOLDS),
            "horizons": HORIZONS,
            "symbols_per_fold": {
                "fundamental_change_v1": len(FUNDAMENTAL_SYMBOLS),
                "main_force_flow_v1": len(FLOW_SYMBOLS),
            },
            "total_experiments": len(FUNDAMENTAL_SYMBOLS) * len(HORIZONS) * len(FOLDS) + len(FLOW_SYMBOLS) * len(HORIZONS) * len(FOLDS),
        },
        "fundamental_change_v1": fundamental_results,
        "main_force_flow_v1": flow_results,
    }


def compute_alpha_status(results: Dict[str, Any]) -> Dict[str, Any]:
    def status_for(exp_list):
        valid = [e for e in exp_list if e.get("valid_signal")]
        if not valid:
            return "NO_EVIDENCE"
        return "RESEARCH_CANDIDATE"

    return {
        "FUNDAMENTAL_ALPHA_STATUS": status_for(results["fundamental_change_v1"]),
        "MAIN_FORCE_FLOW_ALPHA_STATUS": status_for(results["main_force_flow_v1"]),
        "fundamental_valid_signals": sum(1 for e in results["fundamental_change_v1"] if e.get("valid_signal")),
        "flow_valid_signals": sum(1 for e in results["main_force_flow_v1"] if e.get("valid_signal")),
        "fundamental_total_experiments": len(results["fundamental_change_v1"]),
        "flow_total_experiments": len(results["main_force_flow_v1"]),
    }


def main() -> None:
    results = run_full_matrix()
    alpha_status = compute_alpha_status(results)

    (ART / "c5_e_full_matrix_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_e_full_matrix_alpha_status.json").write_text(
        json.dumps(alpha_status, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(json.dumps({
        "status": "COMPLETE",
        "alpha_status": alpha_status,
        "artifacts": [
            "data/research/strategy/c5_e_full_matrix_results.json",
            "data/research/strategy/c5_e_full_matrix_alpha_status.json",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
