#!/usr/bin/env python3
"""
c4_b2_reference_audit.py — M9.1-C4-B2-B ReferenceBenchmark Instrumented Audit
==============================================================================

Read-only. No DB writes, no engine changes.
Directly instruments ReferenceBenchmark._get_entry_exit_prices and
compute_reference for 2025-06-03 × 200-symbol universe × 3 horizons.
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlite3, json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

from core.research.reference_benchmark import ReferenceBenchmark, ReferenceReturnResult

DECISION_TIME = '2025-06-03'
HORIZONS = [5, 10, 20]
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


def instrumented_get_entry_exit_prices(symbol: str, decision_time: str, horizon: int) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
    klines = kline_loader(symbol, "", "")
    meta = {
        "symbol": symbol,
        "decision_time": decision_time,
        "horizon": horizon,
        "klines_loaded": len(klines),
        "decision_idx": -1,
        "entry_idx": -1,
        "exit_idx": -1,
        "entry_date": None,
        "exit_date": None,
        "entry_price": None,
        "exit_price": None,
        "failure_reason": None,
    }
    if not klines:
        meta["failure_reason"] = "NO_KLINES"
        return None, None, meta

    decision_idx = -1
    for i, k in enumerate(klines):
        if k["date"] == decision_time:
            decision_idx = i
            break
    meta["decision_idx"] = decision_idx
    if decision_idx < 0:
        meta["failure_reason"] = "DECISION_DATE_NOT_IN_KLINES"
        return None, None, meta

    entry_idx = decision_idx + 1
    meta["entry_idx"] = entry_idx
    if entry_idx >= len(klines):
        meta["failure_reason"] = "ENTRY_IDX_OUT_OF_RANGE"
        return None, None, meta

    entry_price = klines[entry_idx].get("open")
    meta["entry_date"] = klines[entry_idx].get("date")
    meta["entry_price"] = entry_price
    if entry_price is None or entry_price <= 0:
        meta["failure_reason"] = "INVALID_ENTRY_PRICE"
        return None, None, meta

    exit_idx = decision_idx + horizon
    meta["exit_idx"] = exit_idx
    if exit_idx >= len(klines):
        meta["failure_reason"] = "EXIT_IDX_OUT_OF_RANGE"
        return None, None, meta

    exit_price = klines[exit_idx].get("close")
    meta["exit_date"] = klines[exit_idx].get("date")
    meta["exit_price"] = exit_price
    if exit_price is None or exit_price <= 0:
        meta["failure_reason"] = "INVALID_EXIT_PRICE"
        return None, None, meta

    return float(entry_price), float(exit_price), meta


def audit_reference(universe: List[dict], decision_time: str, horizon: int) -> Dict[str, Any]:
    samples = []
    entry_none = 0
    entry_valid = 0
    exit_none = 0
    exit_valid = 0
    both_valid = 0
    returns: List[float] = []
    failure_reasons: Dict[str, int] = {}

    for stock in universe:
        symbol = stock.get("code") or stock.get("symbol")
        if not symbol:
            continue
        entry_price, exit_price, meta = instrumented_get_entry_exit_prices(symbol, decision_time, horizon)
        if len(samples) < 12:
            samples.append({
                "symbol": symbol,
                "decision_date": decision_time,
                "entry_date": meta.get("entry_date"),
                "entry_price": entry_price,
                "exit_date": meta.get("exit_date"),
                "exit_price": exit_price,
                "klines_loaded": meta.get("klines_loaded"),
                "decision_idx": meta.get("decision_idx"),
                "entry_idx": meta.get("entry_idx"),
                "exit_idx": meta.get("exit_idx"),
                "failure_reason": meta.get("failure_reason"),
            })
        if entry_price is None or entry_price <= 0:
            entry_none += 1
            reason = meta.get("failure_reason") or "ENTRY_PRICE_MISSING"
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            continue
        entry_valid += 1
        if exit_price is None or exit_price <= 0:
            exit_none += 1
            reason = meta.get("failure_reason") or "EXIT_PRICE_MISSING"
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            continue
        exit_valid += 1
        both_valid += 1
        returns.append(exit_price / entry_price - 1.0)

    valid_count = both_valid
    total_count = len(universe)
    valid_ratio = valid_count / total_count if total_count > 0 else 0.0
    min_coverage_ratio = 0.5
    accepted = valid_count > 0 and valid_ratio >= min_coverage_ratio
    rejection_reason = None
    if valid_count == 0:
        rejection_reason = "VALID_COUNT_ZERO"
    elif valid_ratio < min_coverage_ratio:
        rejection_reason = f"COVERAGE_REJECTION: valid_ratio={valid_ratio:.2%} < {min_coverage_ratio:.0%}"
    else:
        rejection_reason = "ACCEPTED"

    return {
        "decision_time": decision_time,
        "horizon": horizon,
        "universe_count": total_count,
        "entry_valid_count": entry_valid,
        "entry_none_count": entry_none,
        "exit_valid_count": exit_valid,
        "exit_none_count": exit_none,
        "both_valid_count": both_valid,
        "return_stats": {
            "count": len(returns),
            "min": min(returns) if returns else None,
            "max": max(returns) if returns else None,
            "median": float(__import__('statistics').median(returns)) if returns else None,
        } if returns else None,
        "valid_count": valid_count,
        "valid_ratio": round(valid_ratio, 6),
        "min_coverage_ratio": min_coverage_ratio,
        "accepted": accepted,
        "rejection_reason": rejection_reason,
        "failure_reasons": failure_reasons,
        "samples": samples,
    }


def compare_with_target_engine(universe: List[dict], decision_time: str, horizon: int) -> Dict[str, Any]:
    from core.research.target_engine import TargetEngine
    engine = TargetEngine(universe_fetcher=universe_fetcher, kline_loader=kline_loader, db_path=str(DB_PATH))
    comparisons = []
    for stock in universe[:8]:
        symbol = stock.get("code") or stock.get("symbol")
        _, _, ref_meta = instrumented_get_entry_exit_prices(symbol, decision_time, horizon)
        target = engine.compute_target({"symbol": symbol, "candidate_date": decision_time}, decision_time=decision_time)
        comparisons.append({
            "symbol": symbol,
            "ref_entry_price": ref_meta.get("entry_price"),
            "ref_exit_price": ref_meta.get("exit_price"),
            "ref_entry_date": ref_meta.get("entry_date"),
            "ref_exit_date": ref_meta.get("exit_date"),
            "target_status": target.target_status,
            "target_entry_price": target.entry_price,
            "target_exit_price": target.exit_price,
            "target_entry_date": target.entry_date,
            "target_exit_date": target.exit_date,
            "match": (
                ref_meta.get("entry_price") == target.entry_price and
                ref_meta.get("exit_price") == target.exit_price and
                target.target_status == "VALID"
            ),
        })
    return {"horizon": horizon, "comparisons": comparisons}


def main() -> Dict[str, Any]:
    universe = load_sample_universe(UNIVERSE_N)
    audit_by_horizon = {}
    for h in HORIZONS:
        audit_by_horizon[f"{h}d"] = audit_reference(universe, DECISION_TIME, h)

    comparisons = {}
    for h in HORIZONS:
        comparisons[f"{h}d"] = compare_with_target_engine(universe, DECISION_TIME, h)

    # Determine first failure layer from reference audit
    first_failure = None
    for h in HORIZONS:
        a = audit_by_horizon[f"{h}d"]
        if a["entry_none_count"] == len(universe):
            first_failure = f"ENTRY_PRICE_{h}D"
            break
        if a["exit_none_count"] == len(universe):
            first_failure = f"EXIT_PRICE_{h}D"
            break
        if a["both_valid_count"] == 0:
            first_failure = f"BOTH_VALID_ZERO_{h}D"
            break
        if not a["accepted"]:
            first_failure = f"COVERAGE_REJECTION_{h}D"
            break

    report = {
        "decision_time": DECISION_TIME,
        "universe_count": len(universe),
        "min_coverage_ratio": 0.5,
        "horizons": audit_by_horizon,
        "target_engine_comparison": comparisons,
        "first_failure_layer": first_failure,
        "root_cause_hypothesis": _hypothesis(audit_by_horizon),
    }
    out_path = ARTIFACT_DIR / 'c4_b2_reference_audit.json'
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    samples_path = ARTIFACT_DIR / 'c4_b2_reference_samples.json'
    samples = {
        "decision_time": DECISION_TIME,
        "universe_count": len(universe),
        "samples": [s for h in audit_by_horizon.values() for s in h.get("samples", [])[:4]],
    }
    samples_path.write_text(json.dumps(samples, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


def _hypothesis(audit_by_horizon: Dict[str, dict]) -> str:
    for h, a in audit_by_horizon.items():
        if a["entry_none_count"] == a["universe_count"]:
            return f"HYPOTHESIS: ENTRY_PRICE_LOOKUP_FAILURE for all {a['universe_count']} symbols at horizon {h}"
        if a["exit_none_count"] == a["universe_count"]:
            return f"HYPOTHESIS: EXIT_PRICE_LOOKUP_FAILURE for all {a['universe_count']} symbols at horizon {h}"
        if a["both_valid_count"] == 0 and a["entry_valid_count"] > 0:
            return f"HYPOTHESIS: EXIT_PRICE_LOOKUP_FAILURE (entry ok, exit missing) at horizon {h}"
        if a["both_valid_count"] == 0:
            return f"HYPOTHESIS: BOTH_ENTRY_AND_EXIT_MISSING at horizon {h}"
        if not a["accepted"] and a["both_valid_count"] > 0:
            return f"HYPOTHESIS: COVERAGE_REJECTION (valid_count={a['both_valid_count']}, ratio={a['valid_ratio']}) at horizon {h}"
    return "HYPOTHESIS: UNKNOWN — inspect sample-level failures"


if __name__ == '__main__':
    report = main()
    print(json.dumps({
        "first_failure_layer": report.get("first_failure_layer"),
        "root_cause_hypothesis": report.get("root_cause_hypothesis"),
        "horizons": {
            h: {
                "universe_count": a["universe_count"],
                "entry_valid": a["entry_valid_count"],
                "exit_valid": a["exit_valid_count"],
                "both_valid": a["both_valid_count"],
                "accepted": a["accepted"],
                "rejection_reason": a["rejection_reason"],
            }
            for h, a in report.get("horizons", {}).items()
        },
    }, indent=2, ensure_ascii=False))
