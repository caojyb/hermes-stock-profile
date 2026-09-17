#!/usr/bin/env python3
"""
c4_b2_runner_integration_trace.py — M9.1-C4-B2-D Runner Integration Trace
==========================================================================
Bounded rerun with explicit per-candidate reference/target accounting to
compare runner path against the earlier C4-B2-A probe.

Read-only. No engine changes.
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

from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy
from core.research.target_engine import TargetEngine, TARGET_STATUS_VALID
from core.research.reference_benchmark import ReferenceBenchmark

DECISION_TIME = '2025-06-03'
HORIZON = 5
UNIVERSE_N = 200

_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")


def load_sample_universe(n: int = UNIVERSE_N) -> List[dict]:
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


def main() -> Dict[str, Any]:
    fold = FoldDefinition(
        fold_id="fold_001",
        train_start="2019-07-22",
        train_end="2025-05-27",
        validation_start=DECISION_TIME,
        validation_end="2025-08-05",
        fold_index=1,
        fold_policy="anchored_expanding",
        notes="C4-B2-D integration trace",
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

    universe = universe_fetcher(DECISION_TIME)
    signals = strategy.run(universe, DECISION_TIME)
    eligible = [s for s in signals if getattr(s, "eligibility", False)]
    candidates = [
        {
            "symbol": s.stock_code,
            "candidate_date": DECISION_TIME,
            "entry_price": getattr(s, "entry_price", None),
            "entry_date": getattr(s, "entry_date", None),
        }
        for s in eligible
    ]

    target_engine = TargetEngine(universe_fetcher=universe_fetcher, kline_loader=kline_loader, db_path=str(DB_PATH))
    ref = ReferenceBenchmark(universe_fetcher=universe_fetcher, kline_loader=kline_loader).compute_reference(DECISION_TIME, HORIZON, "UNIVERSE_MEDIAN", min_coverage_ratio=0.5)
    per_candidate = []
    valid = 0
    invalid = 0
    for cand in candidates[:20]:
        t = target_engine.compute_target(cand, decision_time=DECISION_TIME)
        if t.target_status == TARGET_STATUS_VALID:
            valid += 1
        else:
            invalid += 1
        per_candidate.append({
            "symbol": cand.get("symbol"),
            "candidate_entry_price": cand.get("entry_price"),
            "candidate_entry_date": cand.get("entry_date"),
            "target_status": t.target_status,
            "excess_return": t.excess_return,
            "benchmark_return": t.benchmark_return,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "notes": t.notes,
        })

    report = {
        "decision_time": DECISION_TIME,
        "horizon": HORIZON,
        "fold_result": {
            "fold_id": fold_result.fold_id,
            "fold_status": fold_result.fold_status,
            "valid_target_count": fold_result.valid_target_count,
            "missing_target_count": fold_result.missing_target_count,
        },
        "reference": {
            "reference_return": ref.reference_return,
            "reference_valid_count": ref.reference_valid_count,
            "reference_total_count": ref.reference_total_count,
            "reference_valid_ratio": ref.reference_valid_ratio,
            "notes": ref.notes,
        },
        "candidate_count": len(candidates),
        "sample_candidates": per_candidate,
        "sample_valid_count": valid,
        "sample_invalid_count": invalid,
        "integration_note": _integration_note(fold_result, ref, candidates, per_candidate),
    }
    out_path = ARTIFACT_DIR / 'c4_b2_runner_integration_trace.json'
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


def _integration_note(fold_result, ref, candidates, per_candidate):
    if ref.reference_return is None:
        return "Reference unavailable at fold level."
    if not candidates:
        return "No candidates; cannot assess integration."
    valid = [c for c in per_candidate if c["target_status"] == TARGET_STATUS_VALID]
    if valid:
        return f"Integration path produces valid targets ({len(valid)}/{len(per_candidate)} sampled). Discrepancy likely in bounded probe candidate preparation or single/batch divergence, not canonical reference engine."
    return "Reference available, but sampled candidates produced no valid targets; inspect candidate entry_price/entry_date propagation."


if __name__ == '__main__':
    report = main()
    print(json.dumps({
        "fold_status": report["fold_result"]["fold_status"],
        "fold_valid_target_count": report["fold_result"]["valid_target_count"],
        "reference_valid_count": report["reference"]["reference_valid_count"],
        "reference_return": report["reference"]["reference_return"],
        "sample_valid_count": report["sample_valid_count"],
        "sample_invalid_count": report["sample_invalid_count"],
        "integration_note": report["integration_note"],
    }, indent=2, ensure_ascii=False))
