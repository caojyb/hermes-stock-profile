#!/usr/bin/env python3
"""
test_c4_b2_runner_fix.py — M9.1-C4-B2-E regression tests for WalkForward dependency injection.
"""
from __future__ import annotations

import os, sys, sqlite3, json
from pathlib import Path
from typing import List, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'

from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy


def load_sample_universe(n: int = 50) -> List[dict]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT ?",
        (int(n),),
    )
    rows = cur.fetchall()
    con.close()
    return [{"code": r[0], "name": r[1]} for r in rows]


def kline_loader(symbol: str, start_date: str, end_date: str) -> List[dict]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
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
    con.close()
    return rows


def test_strategy_dependencies_injected():
    engine = WalkForwardEngine(
        universe_fetcher=load_sample_universe,
        kline_loader=kline_loader,
        db_path=str(DB_PATH),
        dataset_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        target_version="v1",
        pit_policy="PIT_RESEARCH_V1",
        fold_policy="anchored_expanding",
    )
    strategy = TrendStrategy(lookback=60)
    baseline = NaiveBaselineStrategy(seed=42)
    engine._inject_strategy_dependencies(strategy)
    engine._inject_strategy_dependencies(baseline)
    assert strategy.kline_loader is not None
    assert baseline.kline_loader is not None
    assert strategy.universe_fetcher is not None
    assert baseline.universe_fetcher is not None
    assert strategy.db_path == str(DB_PATH)
    assert baseline.db_path == str(DB_PATH)


def test_runner_produces_signals_and_targets():
    fold = FoldDefinition(
        fold_id="fold_001",
        train_start="2019-07-22",
        train_end="2025-05-27",
        validation_start="2025-06-03",
        validation_end="2025-08-05",
        fold_index=1,
        fold_policy="anchored_expanding",
    )
    strategy = TrendStrategy(lookback=60)
    baseline = NaiveBaselineStrategy(seed=42)
    engine = WalkForwardEngine(
        universe_fetcher=lambda decision_date: load_sample_universe(200),
        kline_loader=kline_loader,
        db_path=str(DB_PATH),
        dataset_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        target_version="v1",
        pit_policy="PIT_RESEARCH_V1",
        fold_policy="anchored_expanding",
    )
    result = engine.run_fold(
        fold=fold,
        strategy=strategy,
        baseline_strategy=baseline,
        horizons=[5, 10, 20],
        normalization_method="percentile",
    )
    assert result.valid_target_count > 0, f"Expected valid targets > 0, got {result.valid_target_count}"
    assert result.fold_status == "VALID_FOLD", f"Expected VALID_FOLD, got {result.fold_status}"
    assert result.strategy_ic is not None


if __name__ == '__main__':
    test_strategy_dependencies_injected()
    test_runner_produces_signals_and_targets()
    print(json.dumps({
        'status': 'PASS',
        'tests': [
            'test_strategy_dependencies_injected',
            'test_runner_produces_signals_and_targets',
        ]
    }, indent=2))
