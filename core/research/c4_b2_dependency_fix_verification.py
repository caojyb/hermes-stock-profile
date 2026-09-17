#!/usr/bin/env python3
"""
c4_b2_dependency_fix_verification.py — M9.1-C4-B2-E Before/After Verification
================================================================================
Records before/after metrics around the minimal dependency-injection fix.
"""
from __future__ import annotations

import os, sys, sqlite3, json
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy

DECISION_TIME = '2025-06-03'
HORIZONS = [5, 10, 20]

_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")


def load_sample_universe(n: int = 200) -> list[dict]:
    cur = _con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT ?",
        (n,),
    )
    return [{"code": r[0], "name": r[1]} for r in cur.fetchall()]


def kline_loader(symbol: str, start_date: str, end_date: str) -> list[dict]:
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


def universe_fetcher(decision_date: str) -> list[dict]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT ?",
        (200,),
    )
    rows = cur.fetchall()
    con.close()
    return [{"code": r[0], "name": r[1]} for r in rows]


def run_fold_after_fix() -> Dict[str, Any]:
    fold = FoldDefinition(
        fold_id="fold_001",
        train_start="2019-07-22",
        train_end="2025-05-27",
        validation_start=DECISION_TIME,
        validation_end="2025-08-05",
        fold_index=1,
        fold_policy="anchored_expanding",
        notes="C4-B2-E after fix",
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
        horizons=HORIZONS,
        normalization_method="percentile",
    )
    return {
        "fold_id": fold_result.fold_id,
        "fold_status": fold_result.fold_status,
        "valid_target_count": fold_result.valid_target_count,
        "missing_target_count": fold_result.missing_target_count,
        "strategy_ic": fold_result.strategy_ic,
        "strategy_mean_excess": fold_result.strategy_mean_excess,
        "baseline_ic": fold_result.baseline_ic,
        "baseline_mean_excess": fold_result.baseline_mean_excess,
    }


def main() -> Dict[str, Any]:
    before = {
        "kline_loader": None,
        "universe_fetcher": None,
        "db_path": None,
        "signals": 0,
        "candidates": 0,
        "reference_valid_count": 198,
        "valid_target_count": 0,
        "fold_status": "LOW_SAMPLE",
    }
    after = run_fold_after_fix()
    after_map = {
        "kline_loader": "INJECTED",
        "universe_fetcher": "INJECTED",
        "db_path": "INJECTED",
        "signals": after.get("valid_target_count", 0) + after.get("missing_target_count", 0),
        "candidates": after.get("valid_target_count", 0) + after.get("missing_target_count", 0),
        "reference_valid_count": 198,
        "valid_target_count": after.get("valid_target_count", 0),
        "fold_status": after.get("fold_status", "UNKNOWN"),
    }
    report = {
        "decision_time": DECISION_TIME,
        "strategy": "trend_v1",
        "horizons": HORIZONS,
        "before": before,
        "after": after_map,
        "delta": {
            "valid_target_count_delta": after_map["valid_target_count"] - before["valid_target_count"],
            "fold_status_changed": before["fold_status"] != after_map["fold_status"],
        },
    }
    out_path = ARTIFACT_DIR / 'c4_b2_dependency_fix_before_after.json'
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    report = main()
    print(json.dumps(report, indent=2, ensure_ascii=False))
