#!/usr/bin/env python3
"""
c4_b2_runner_signal_trace.py — M9.1-C4-B2-D Runner Signal Stage Trace
========================================================================
Trace why runner produces 0 candidates while standalone probe gets 196/200.
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
from core.research.signal_normalization import NormalizationLayer

DECISION_TIME = '2025-06-03'
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
    universe = universe_fetcher(DECISION_TIME)
    strategy = TrendStrategy(lookback=60)
    baseline = NaiveBaselineStrategy(seed=42)
    norm = NormalizationLayer(method="percentile")

    # Simulate runner path: fit on train universe, then run on validation universe
    train_universe = universe
    train_signals = strategy.run(train_universe, DECISION_TIME)
    eligible_train = [s for s in train_signals if s.eligibility]
    if eligible_train:
        norm.normalize(eligible_train)
        strategy.normalization_layer = norm
    else:
        strategy.normalization_layer = norm

    signals = strategy.run(universe, DECISION_TIME)
    eligible = [s for s in signals if s.eligibility]

    report = {
        "decision_time": DECISION_TIME,
        "universe_count": len(universe),
        "train_signals_count": len(train_signals),
        "train_eligible_count": len(eligible_train),
        "validation_signals_count": len(signals),
        "validation_eligible_count": len(eligible),
        "sample_signals": [
            {
                "symbol": s.stock_code,
                "raw_score": s.raw_score,
                "normalized_score": s.normalized_score,
                "eligibility": s.eligibility,
                "reason_code": s.reason_code,
            }
            for s in signals[:10]
        ],
        "sample_eligible": [
            {
                "symbol": s.stock_code,
                "raw_score": s.raw_score,
                "normalized_score": s.normalized_score,
                "eligibility": s.eligibility,
                "reason_code": s.reason_code,
            }
            for s in eligible[:10]
        ],
    }
    out_path = ARTIFACT_DIR / 'c4_b2_runner_signal_trace.json'
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    report = main()
    print(json.dumps({
        "universe_count": report["universe_count"],
        "validation_signals_count": report["validation_signals_count"],
        "validation_eligible_count": report["validation_eligible_count"],
        "sample_signals": report["sample_signals"][:5],
        "sample_eligible": report["sample_eligible"][:5],
    }, indent=2, ensure_ascii=False))
