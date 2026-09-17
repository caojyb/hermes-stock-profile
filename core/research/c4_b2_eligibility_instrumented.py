#!/usr/bin/env python3
"""
c4_b2_eligibility_instrumented.py — instrumented strategy run for 2025-03-14.
Records universe, kline_loader behavior, and per-symbol eligibility.
"""
from __future__ import annotations

import sqlite3, json, os, sys, time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.research.walk_forward_validation import WalkForwardEngine
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

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

def main():
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
    fold = folds[0]
    universe = universe_fetcher(fold.validation_start)

    strategy = TrendStrategy(lookback=60)
    baseline = NaiveBaselineStrategy(seed=42)
    engine._inject_strategy_dependencies(strategy)
    engine._inject_strategy_dependencies(baseline)

    print('fold_id:', fold.fold_id, 'validation_start:', fold.validation_start, 'universe_size:', len(universe), flush=True)
    print('strategy.kline_loader is None:', strategy.kline_loader is None, flush=True)

    # Instrumented run: call strategy.run and then compute eligibility manually for first 20 symbols
    signals = strategy.run(universe, fold.validation_start)
    print('total signals:', len(signals), flush=True)

    sample = []
    for stock, signal in zip(universe[:20], signals[:20]):
        klines = kline_loader(stock['code'], '', '')
        decision_idx = -1
        for i, k in enumerate(klines):
            if k['date'] == fold.validation_start:
                decision_idx = i
                break
        sample.append({
            'symbol': stock['code'],
            'decision_time': fold.validation_start,
            'lookback_required': 60,
            'bars_received': len(klines),
            'decision_idx': decision_idx,
            'eligibility': signal.eligibility,
            'reason_code': signal.reason_code,
            'raw_score': signal.raw_score,
        })

    summary = {
        'fold_id': fold.fold_id,
        'validation_start': fold.validation_start,
        'universe_size': len(universe),
        'signal_count': len(signals),
        'eligible_count': sum(1 for s in signals if s.eligibility),
        'ineligible_count': sum(1 for s in signals if not s.eligibility),
        'reason_distribution': {
            reason: sum(1 for s in signals if s.reason_code == reason)
            for reason in sorted(set(s.reason_code for s in signals))
        },
        'sample_symbols': sample,
        'elapsed_seconds': round(time.time() - t0, 3),
    }
    out = ARTIFACT_DIR / 'c4_b2_strategy_eligibility_trace.json'
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
