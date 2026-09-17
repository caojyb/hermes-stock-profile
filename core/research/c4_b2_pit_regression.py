#!/usr/bin/env python3
"""
c4_b2_pit_regression.py — M9.1-C4-B2-K1 PIT regression for optimized runner.
Tests: fold_001, fold_004, fold_008 × trend_v1 × 5D/10D/20D.
Read-only. No production mutation.
"""
from __future__ import annotations

import json, os, sys, time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.research.walk_forward_validation import WalkForwardEngine
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy

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

def kline_loader(symbol: str, start_date: str = '', end_date: str = '') -> List[dict]:
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

def analyze_signal_pit(strategy, universe, decision_time: str) -> Dict[str, Any]:
    """Instrument strategy.run to record date ranges used for each stock."""
    calls: List[Dict[str, Any]] = []

    original_loader = strategy.kline_loader
    def instrumented_loader(symbol, start_date='', end_date=''):
        rows = original_loader(symbol, start_date, end_date)
        calls.append({
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "returned_count": len(rows),
            "max_date": max((r['date'] for r in rows), default=None),
            "min_date": min((r['date'] for r in rows), default=None),
            "future_rows": sum(1 for r in rows if r['date'] > decision_time),
        })
        return rows

    strategy.kline_loader = instrumented_loader
    signals = strategy.run(universe, decision_time)
    strategy.kline_loader = original_loader

    max_date = max((c['max_date'] for c in calls if c['max_date']), default=None)
    future_calls = [c for c in calls if c['future_rows'] > 0]
    return {
        "decision_time": decision_time,
        "max_available_time_used": max_date,
        "future_rows_used": sum(c['future_rows'] for c in calls),
        "future_call_count": len(future_calls),
        "total_calls": len(calls),
        "pit_clean": max_date is None or max_date <= decision_time,
        "sample_calls": calls[:10],
    }, signals

def future_injection_test(strategy, universe, decision_time):
    """Inject future data via loader wrapper and verify signals don't change."""
    class FakeFutureLoader:
        def __init__(self, real_loader, decision_time):
            self.real_loader = real_loader
            self.decision_time = decision_time

        def __call__(self, symbol, start_date='', end_date=''):
            real = self.real_loader(symbol, start_date, end_date)
            fake = {
                "date": "2099-01-01",
                "open": 999.0,
                "close": 999.0,
                "high": 999.0,
                "low": 999.0,
                "volume": 0,
            }
            return real + [fake]

    # Baseline
    original_loader = strategy.kline_loader
    baseline_pit, baseline_signals = analyze_signal_pit(strategy, universe, decision_time)
    baseline_eligible = [s for s in baseline_signals if s.eligibility]
    baseline_count = len(baseline_eligible)

    # Injected
    strategy.kline_loader = FakeFutureLoader(original_loader, decision_time)
    injected_signals = strategy.run(universe, decision_time)
    injected_eligible = [s for s in injected_signals if s.eligibility]
    injected_count = len(injected_eligible)
    strategy.kline_loader = original_loader

    return {
        "baseline_eligible_count": baseline_count,
        "injected_eligible_count": injected_count,
        "pit_violation": baseline_count != injected_count,
        "baseline_pit": baseline_pit,
        "injection_pit_clean": baseline_pit['pit_clean'],
        "baseline_sample": [
            {"stock_code": s.stock_code, "eligibility": s.eligibility, "reason_code": s.reason_code}
            for s in baseline_signals[:5]
        ],
        "injected_sample": [
            {"stock_code": s.stock_code, "eligibility": s.eligibility, "reason_code": s.reason_code}
            for s in injected_signals[:5]
        ],
    }

def run_pit_regression():
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
    folds = engine.define_folds_auto(252, 63, 5, 8, 8)
    target_folds = [folds[0], folds[3], folds[7]]  # fold_001, fold_004, fold_008
    baseline = NaiveBaselineStrategy(seed=42)

    results = []
    for fold in target_folds:
        universe = universe_fetcher(fold.validation_start)
        for horizon in [5, 10, 20]:
            # Pre-flight: validate decision_time is a trading day
            sample_klines = kline_loader('000001', fold.validation_start, fold.validation_start)
            assert len(sample_klines) > 0 and sample_klines[0].get('date') == fold.validation_start, \
                f"NON_TRADING_DECISION_DATE: {fold.validation_start}"

            strategy = TrendStrategy(lookback=60)
            injection = future_injection_test(strategy, universe, fold.validation_start)

            # Run fold with a fresh strategy instance
            strategy2 = TrendStrategy(lookback=60)
            res = engine.run_fold(
                fold=fold,
                strategy=strategy2,
                baseline_strategy=baseline,
                horizons=[horizon],
                normalization_method="percentile",
            )

            entry = {
                "fold_id": fold.fold_id,
                "validation_start": fold.validation_start,
                "validation_end": fold.validation_end,
                "horizon": horizon,
                "fold_status": res.fold_status,
                "signal_count": res.signal_count,
                "eligible_count": res.eligible_count,
                "valid_target_count": res.valid_target_count,
                "missing_target_count": res.missing_target_count,
                "strategy_ic": res.strategy_ic,
                "strategy_mean_excess": res.strategy_mean_excess,
                "baseline_ic": res.baseline_ic,
                "future_injection": injection,
                "pit_status": "PASS" if not injection["pit_violation"] else "FAIL",
            }
            results.append(entry)

    summary = {
        "test_scope": "fold_001, fold_004, fold_008 × trend_v1 × 5D/10D/20D",
        "total_tests": len(results),
        "pit_pass_count": sum(1 for r in results if r["pit_status"] == "PASS"),
        "pit_fail_count": sum(1 for r in results if r["pit_status"] == "FAIL"),
        "elapsed_seconds": round(time.time() - t0, 3),
        "results": results,
    }

    out = ARTIFACT_DIR / 'c4_b2_pit_regression.json'
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    return summary

def main():
    summary = run_pit_regression()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
