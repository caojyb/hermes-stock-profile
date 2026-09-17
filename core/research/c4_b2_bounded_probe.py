#!/usr/bin/env python3
"""
c4_b2_bounded_probe.py — M9.1-C4-B2-A Bounded Target Availability Probe
=========================================================================
Read-only. No DB writes, no engine changes.
Scope: 1 strategy x 1 fold x 3 horizons.
Outputs:
  - stock-work/data/research/target_availability/c4_b2_bounded_probe.json
  - stock-work/data/research/target_availability/c4_b2_funnel_trace.json
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlite3, json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

from core.research.strategies.trend_strategy import TrendStrategy
from core.research.target_engine import TargetEngine, TARGET_STATUS_VALID
from core.research.reference_benchmark import ReferenceBenchmark

# ----------------------------- config -----------------------------
STRATEGY = 'trend_v1'
STRATEGY_PARAMS = {'lookback': 60}
DECISION_TIME = '2025-06-03'
HORIZONS = [5, 10, 20]
UNIVERSE_N = 200
SAMPLE_SYMBOLS_N = 8


# ----------------------------- data helpers -----------------------------
_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")


def load_sample_universe(n: int = UNIVERSE_N) -> List[dict]:
    cur = _con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT ?",
        (n,),
    )
    return [{"code": r[0], "name": r[1]} for r in cur.fetchall()]


def kline_loader(symbol: str) -> List[dict]:
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
        cur.execute("SELECT date, open, close, high, low, volume FROM klines WHERE code=? ORDER BY date", (code,))
        for r in cur.fetchall():
            if r[0] in seen_dates:
                continue
            seen_dates.add(r[0])
            rows.append({"date": r[0], "open": r[1], "close": r[2], "high": r[3], "low": r[4], "volume": r[5]})
    return rows


def universe_fetcher(decision_date: str) -> List[dict]:
    return load_sample_universe(UNIVERSE_N)


def next_eligible_trading_day_from_klines(klines: List[dict], date: str) -> Optional[str]:
    for k in klines:
        if k["date"] > date and k.get("open") is not None:
            return k["date"]
    return None


def exit_for_horizon(klines: List[dict], entry_date: str, horizon: int):
    count = 0
    for k in klines:
        if k["date"] > entry_date and k.get("close") is not None:
            count += 1
            if count == horizon:
                return k["date"], k["close"]
    return None, None


# ----------------------------- signal stage -----------------------------
def run_signals(universe: List[dict], decision_time: str) -> List[dict]:
    strategy = TrendStrategy(**STRATEGY_PARAMS)
    signals = []
    for stock in universe:
        sym = stock.get("code") or stock.get("symbol")
        if not sym:
            continue
        klines = kline_loader(sym)
        if not klines or len(klines) <= strategy.lookback:
            signals.append({
                "symbol": sym,
                "decision_time": decision_time,
                "signal": None,
                "stage": "INSUFFICIENT_HISTORY",
                "klines_count": len(klines),
            })
            continue
        decision_idx = next((i for i, k in enumerate(klines) if k["date"] == decision_time), -1)
        if decision_idx < 0:
            signals.append({
                "symbol": sym,
                "decision_time": decision_time,
                "signal": None,
                "stage": "DECISION_DATE_NOT_IN_KLINES",
                "klines_count": len(klines),
            })
            continue
        if decision_idx < strategy.lookback:
            signals.append({
                "symbol": sym,
                "decision_time": decision_time,
                "signal": None,
                "stage": "INSUFFICIENT_HISTORY_AT_T",
                "klines_count": len(klines),
            })
            continue
        closes = [klines[i]["close"] for i in range(decision_idx - strategy.lookback + 1, decision_idx + 1)]
        if any(c is None or c <= 0 for c in closes):
            signals.append({
                "symbol": sym,
                "decision_time": decision_time,
                "signal": None,
                "stage": "INVALID_PRICE",
                "klines_count": len(klines),
            })
            continue
        ma = sum(closes) / len(closes)
        price = klines[decision_idx]["close"]
        raw_score = price / ma - 1.0 if ma > 0 else 0.0
        signals.append({
            "symbol": sym,
            "decision_time": decision_time,
            "signal": raw_score,
            "stage": "SIGNAL_GENERATED",
            "klines_count": len(klines),
            "price": price,
            "ma": ma,
        })
    return signals


# ----------------------------- funnel trace -----------------------------
def trace_target_funnel_for_symbol(symbol: str, decision_time: str, engine: TargetEngine, universe: List[dict]) -> Dict[str, Any]:
    klines = kline_loader(symbol)
    decision_idx = next((i for i, k in enumerate(klines) if k["date"] == decision_time), -1)
    row: Dict[str, Any] = {
        "symbol": symbol,
        "decision_time": decision_time,
        "signal": None,
        "signal_stage": None,
        "universe_snapshot_available": len(universe) > 0,
        "universe_symbol_count": len(universe),
        "symbol_in_universe": any((s.get("code") or s.get("symbol")) == symbol for s in universe),
        "entry_date": None,
        "entry_price": None,
        "exit_date_5d": None,
        "exit_price_5d": None,
        "exit_date_10d": None,
        "exit_price_10d": None,
        "exit_date_20d": None,
        "exit_price_20d": None,
        "reference_universe_size": None,
        "reference_valid_prices_5d": None,
        "reference_valid_prices_10d": None,
        "reference_valid_prices_20d": None,
        "reference_return_5d": None,
        "reference_return_10d": None,
        "reference_return_20d": None,
        "target_status_5d": None,
        "target_status_10d": None,
        "target_status_20d": None,
        "target_notes_5d": None,
        "target_notes_10d": None,
        "target_notes_20d": None,
        "failure_reason": None,
    }
    if decision_idx < 0:
        row["failure_reason"] = "DECISION_DATE_NOT_IN_KLINES"
        return row

    entry_date = next_eligible_trading_day_from_klines(klines, decision_time)
    if entry_date is None:
        row["failure_reason"] = "ENTRY_TRADE_DATE_MISSING"
        return row
    entry_idx = next((i for i, k in enumerate(klines) if k["date"] == entry_date), -1)
    entry_price = klines[entry_idx]["open"] if entry_idx >= 0 else None
    row["entry_date"] = entry_date
    row["entry_price"] = entry_price

    ed5, ep5 = exit_for_horizon(klines, entry_date, 5)
    ed10, ep10 = exit_for_horizon(klines, entry_date, 10)
    ed20, ep20 = exit_for_horizon(klines, entry_date, 20)
    row["exit_date_5d"] = ed5
    row["exit_price_5d"] = ep5
    row["exit_date_10d"] = ed10
    row["exit_price_10d"] = ep10
    row["exit_date_20d"] = ed20
    row["exit_price_20d"] = ep20

    rb = ReferenceBenchmark(universe_fetcher=universe_fetcher, kline_loader=kline_loader)
    ref5 = rb.compute_reference(decision_time, 5, "UNIVERSE_MEDIAN", min_coverage_ratio=0.5)
    ref10 = rb.compute_reference(decision_time, 10, "UNIVERSE_MEDIAN", min_coverage_ratio=0.5)
    ref20 = rb.compute_reference(decision_time, 20, "UNIVERSE_MEDIAN", min_coverage_ratio=0.5)
    row["reference_universe_size"] = ref5.reference_total_count
    row["reference_valid_prices_5d"] = ref5.reference_valid_count
    row["reference_valid_prices_10d"] = ref10.reference_valid_count
    row["reference_valid_prices_20d"] = ref20.reference_valid_count
    row["reference_return_5d"] = ref5.reference_return
    row["reference_return_10d"] = ref10.reference_return
    row["reference_return_20d"] = ref20.reference_return

    candidate = {"symbol": symbol, "candidate_date": decision_time, "entry_price": entry_price, "entry_date": entry_date}
    target5 = engine.compute_target(candidate, decision_time=decision_time)
    target10 = engine.compute_target(candidate, decision_time=decision_time)
    target20 = engine.compute_target(candidate, decision_time=decision_time)
    row["target_status_5d"] = target5.target_status
    row["target_status_10d"] = target10.target_status
    row["target_status_20d"] = target20.target_status
    row["target_notes_5d"] = target5.notes
    row["target_notes_10d"] = target10.notes
    row["target_notes_20d"] = target20.notes
    row["failure_reason"] = None if target5.target_status == TARGET_STATUS_VALID else (target5.notes or target5.target_status)
    return row


# ----------------------------- funnel aggregation -----------------------------
def first_failure_layer(traces: List[dict]) -> Optional[str]:
    if not traces:
        return "NO_SIGNALS"
    if all(r["entry_price"] is None for r in traces):
        return "ENTRY_PRICE"
    for h in HORIZONS:
        key = f"exit_price_{h}d"
        if any(r.get(key) is None for r in traces):
            return f"EXIT_PRICE_{h.upper()}"
    for h in HORIZONS:
        key = f"reference_return_{h}d"
        if any(r.get(key) is None for r in traces):
            return f"REFERENCE_{h}D"
    for h in HORIZONS:
        key = f"target_status_{h}d"
        if any(r.get(key) != TARGET_STATUS_VALID for r in traces):
            return f"TARGET_STATUS_{h}D"
    return None


def failure_pattern(traces: List[dict]) -> Dict[str, int]:
    reasons = {}
    for r in traces:
        reason = r.get("failure_reason")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def horizon_counts(traces: List[dict], horizon: int):
    entry_available = sum(1 for r in traces if r["entry_price"] is not None)
    exit_available = sum(1 for r in traces if r.get(f"exit_price_{horizon}d") is not None)
    ref_available = sum(1 for r in traces if r.get(f"reference_return_{horizon}d") is not None)
    valid = sum(1 for r in traces if r.get(f"target_status_{horizon}d") == TARGET_STATUS_VALID)
    return {
        "input_count": len(traces),
        "entry_available": entry_available,
        "exit_available": exit_available,
        "reference_available": ref_available,
        "valid_target_count": valid,
        "missing_target_count": len(traces) - valid,
    }


# ----------------------------- main -----------------------------
def main() -> Dict[str, Any]:
    probe_id = f"{STRATEGY}_{DECISION_TIME}_fold001_horizons"
    universe = load_sample_universe(UNIVERSE_N)
    signals = run_signals(universe, DECISION_TIME)
    generated = [s for s in signals if s["stage"] == "SIGNAL_GENERATED"]
    candidates = generated

    engine = TargetEngine(universe_fetcher=universe_fetcher, kline_loader=kline_loader, db_path=str(DB_PATH))
    sample_symbols = [c["symbol"] for c in candidates[:SAMPLE_SYMBOLS_N]]
    traces: List[Dict[str, Any]] = []
    for sym in sample_symbols:
        sig = next((s for s in signals if s["symbol"] == sym), {})
        row = trace_target_funnel_for_symbol(sym, DECISION_TIME, engine, universe)
        row["signal"] = sig.get("signal")
        row["signal_stage"] = sig.get("stage")
        traces.append(row)

    funnel = {
        "probe_id": probe_id,
        "decision_time": DECISION_TIME,
        "strategy": STRATEGY,
        "universe_count": len(universe),
        "signal_generated_count": len(generated),
        "candidate_count": len(candidates),
        "horizons": {
            "5d": horizon_counts(traces, 5),
            "10d": horizon_counts(traces, 10),
            "20d": horizon_counts(traces, 20),
        },
        "first_failure_layer": first_failure_layer(traces),
        "failure_pattern": failure_pattern(traces),
    }

    probe_doc = {
        "probe_id": probe_id,
        "decision_time": DECISION_TIME,
        "strategy": STRATEGY,
        "universe_count": len(universe),
        "traces": traces,
        "summary": {
            "signal_count": len(generated),
            "candidate_count": len(candidates),
            "horizon_5d_valid": funnel["horizons"]["5d"]["valid_target_count"],
            "horizon_10d_valid": funnel["horizons"]["10d"]["valid_target_count"],
            "horizon_20d_valid": funnel["horizons"]["20d"]["valid_target_count"],
        },
    }
    probe_path = ARTIFACT_DIR / 'c4_b2_bounded_probe.json'
    probe_path.write_text(json.dumps(probe_doc, indent=2, ensure_ascii=False), encoding='utf-8')
    funnel_path = ARTIFACT_DIR / 'c4_b2_funnel_trace.json'
    funnel_path.write_text(json.dumps(funnel, indent=2, ensure_ascii=False), encoding='utf-8')
    return probe_doc, funnel


if __name__ == '__main__':
    probe, funnel = main()
    print(json.dumps({
        "probe_path": str(ARTIFACT_DIR / 'c4_b2_bounded_probe.json'),
        "funnel_path": str(ARTIFACT_DIR / 'c4_b2_funnel_trace.json'),
        "first_failure_layer": funnel.get("first_failure_layer"),
        "failure_pattern": funnel.get("failure_pattern"),
        "horizons": funnel.get("horizons"),
    }, indent=2, ensure_ascii=False))
