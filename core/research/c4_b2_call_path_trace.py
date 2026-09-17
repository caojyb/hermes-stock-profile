#!/usr/bin/env python3
"""
c4_b2_call_path_trace.py — M9.1-C4-B2-C/D Call-Path Instrumentation
========================================================================
Bounded instrumentation:
  trend_v1 × 2025-06-03 × 5D
through the actual WalkForwardRunner path.

Read-only. No DB writes, no engine changes.
"""
from __future__ import annotations

import os, sys, sqlite3, json, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy
from core.research.target_engine import TargetEngine, TARGET_STATUS_VALID
from core.research.reference_benchmark import ReferenceBenchmark, ReferenceReturnResult

DECISION_TIME = '2025-06-03'
HORIZON = 5
UNIVERSE_N = 200

_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")


def load_sample_universe(n: int = UNIVERSE_N) -> List[dict]:
    cur = _con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER by code LIMIT ?",
        (n,),
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
    return load_sample_universe(UNIVERSE_N)


# ----------------------------- instrumentation -----------------------------

_ref_trace = []
_price_trace = []
_target_trace = []


def trace_ref_compute_reference(original):
    def wrapper(self, decision_time, horizon, method="UNIVERSE_MEDIAN", **kwargs):
        entry = {
            "event": "compute_reference_entry",
            "decision_time": decision_time,
            "horizon": horizon,
            "method": method,
            "kwargs_keys": list(kwargs.keys()),
            "universe_fetcher_present": getattr(self, "universe_fetcher", None) is not None,
            "kline_loader_present": getattr(self, "kline_loader", None) is not None,
            "price_basis": getattr(self, "price_basis", None),
            "universe_version": getattr(self, "universe_version", None),
            "dataset_version": getattr(self, "dataset_version", None),
        }
        try:
            result = original(self, decision_time, horizon, method, **kwargs)
            exit = {
                "event": "compute_reference_exit",
                "decision_time": decision_time,
                "horizon": horizon,
                "method": method,
                "reference_return": getattr(result, "reference_return", None),
                "reference_valid_count": getattr(result, "reference_valid_count", None),
                "reference_total_count": getattr(result, "reference_total_count", None),
                "reference_valid_ratio": getattr(result, "reference_valid_ratio", None),
                "notes": getattr(result, "notes", None),
                "returned_type": type(result).__name__,
            }
            _ref_trace.append({"entry": entry, "exit": exit})
            return result
        except Exception as e:
            exit = {"event": "compute_reference_exit", "decision_time": decision_time, "horizon": horizon, "exception": str(e)}
            _ref_trace.append({"entry": entry, "exit": exit})
            raise
    return wrapper


def trace_get_entry_exit_prices(original):
    def wrapper(self, symbol, decision_time, horizon):
        entry = {
            "event": "_get_entry_exit_prices_entry",
            "symbol": symbol,
            "decision_time": decision_time,
            "horizon": horizon,
        }
        try:
            result = original(self, symbol, decision_time, horizon)
            exit = {
                "event": "_get_entry_exit_prices_exit",
                "symbol": symbol,
                "decision_time": decision_time,
                "horizon": horizon,
                "entry_price": result[0],
                "exit_price": result[1],
                "returned_type": type(result).__name__,
            }
            _price_trace.append({"entry": entry, "exit": exit})
            return result
        except Exception as e:
            exit = {"event": "_get_entry_exit_prices_exit", "symbol": symbol, "decision_time": decision_time, "horizon": horizon, "exception": str(e)}
            _price_trace.append({"entry": entry, "exit": exit})
            raise
    return wrapper


def trace_compute_target(original):
    def wrapper(self, candidate, decision_time):
        entry = {
            "event": "compute_target_entry",
            "candidate": candidate,
            "decision_time": decision_time,
        }
        try:
            result = original(self, candidate, decision_time)
            exit = {
                "event": "compute_target_exit",
                "candidate": candidate,
                "decision_time": decision_time,
                "target_status": getattr(result, "target_status", None),
                "excess_return": getattr(result, "excess_return", None),
                "benchmark_return": getattr(result, "benchmark_return", None),
                "entry_price": getattr(result, "entry_price", None),
                "exit_price": getattr(result, "exit_price", None),
                "notes": getattr(result, "notes", None),
                "returned_type": type(result).__name__,
            }
            _target_trace.append({"entry": entry, "exit": exit})
            return result
        except Exception as e:
            exit = {"event": "compute_target_exit", "candidate": candidate, "decision_time": decision_time, "exception": str(e)}
            _target_trace.append({"entry": entry, "exit": exit})
            raise
    return wrapper


# Monkey-patch
ReferenceBenchmark.compute_reference = trace_ref_compute_reference(ReferenceBenchmark.compute_reference)
ReferenceBenchmark._get_entry_exit_prices = trace_get_entry_exit_prices(ReferenceBenchmark._get_entry_exit_prices)
TargetEngine.compute_target = trace_compute_target(TargetEngine.compute_target)


def run_bounded_runner_trace() -> Dict[str, Any]:
    # Build a single fold exactly at DECISION_TIME
    fold = FoldDefinition(
        fold_id="fold_001",
        train_start="2019-07-22",
        train_end="2025-05-27",
        validation_start=DECISION_TIME,
        validation_end="2025-08-05",
        fold_index=1,
        fold_policy="anchored_expanding",
        notes="C4-B2-C/D bounded trace",
    )
    strategy = TrendStrategy(lookback=60)
    baseline = NaiveBaselineStrategy(seed=42)
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
    fold_result = engine.run_fold(
        fold=fold,
        strategy=strategy,
        baseline_strategy=baseline,
        horizons=[HORIZON],
        normalization_method="percentile",
    )
    return {
        "fold_result": {
            "fold_id": fold_result.fold_id,
            "fold_status": fold_result.fold_status,
            "valid_target_count": fold_result.valid_target_count,
            "missing_target_count": fold_result.missing_target_count,
            "strategy_ic": fold_result.strategy_ic,
            "strategy_mean_excess": fold_result.strategy_mean_excess,
        },
        "ref_trace_count": len(_ref_trace),
        "price_trace_count": len(_price_trace),
        "target_trace_count": len(_target_trace),
    }


def run_independent_baseline() -> Dict[str, Any]:
    rb = ReferenceBenchmark(universe_fetcher=universe_fetcher, kline_loader=kline_loader)
    result = rb.compute_reference(DECISION_TIME, HORIZON, "UNIVERSE_MEDIAN", min_coverage_ratio=0.5)
    return {
        "decision_time": DECISION_TIME,
        "horizon": HORIZON,
        "reference_return": result.reference_return,
        "reference_valid_count": result.reference_valid_count,
        "reference_total_count": result.reference_total_count,
        "reference_valid_ratio": result.reference_valid_ratio,
        "notes": result.notes,
    }


def main() -> Dict[str, Any]:
    independent = run_independent_baseline()
    runner = run_bounded_runner_trace()

    # Summarize first reference call from runner
    first_ref = _ref_trace[0] if _ref_trace else {}
    first_ref_exit = first_ref.get("exit", {}) if first_ref else {}

    report = {
        "decision_time": DECISION_TIME,
        "horizon": HORIZON,
        "independent_baseline": independent,
        "runner_summary": runner,
        "first_reference_call": first_ref_exit,
        "first_price_calls": [_price_trace[0]] if _price_trace else [],
        "first_target_calls": [_target_trace[0]] if _target_trace else [],
        "ref_trace": _ref_trace,
        "price_trace": _price_trace[:20],
        "target_trace": _target_trace[:20],
        "first_divergence_point": _detect_first_divergence(independent, first_ref_exit),
    }
    out_path = ARTIFACT_DIR / 'c4_b2_call_path_trace.json'
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


def _detect_first_divergence(independent: Dict[str, Any], first_ref_exit: Dict[str, Any]) -> Optional[str]:
    if not first_ref_exit:
        return "NO_REFERENCE_CALL_RECORDED"
    if independent.get("reference_valid_count", 0) > 0 and first_ref_exit.get("reference_valid_count") == 0:
        return "REFERENCE_CALL_PATH_DIVERGENCE: independent valid > 0, runner path valid = 0"
    if independent.get("reference_return") is not None and first_ref_exit.get("reference_return") is None:
        return "REFERENCE_RETURN_PROPAGATION_LOSS: independent has return, runner path returned None"
    return "NO_DIVERGENCE_DETECTED_IN_FIRST_CALL"


if __name__ == '__main__':
    report = main()
    print(json.dumps({
        "first_divergence_point": report.get("first_divergence_point"),
        "independent_reference_valid_count": report.get("independent_baseline", {}).get("reference_valid_count"),
        "runner_first_reference_valid_count": report.get("first_reference_call", {}).get("reference_valid_count"),
        "runner_fold_status": report.get("runner_summary", {}).get("fold_result", {}).get("fold_status"),
        "runner_valid_target_count": report.get("runner_summary", {}).get("fold_result", {}).get("valid_target_count"),
    }, indent=2, ensure_ascii=False))
