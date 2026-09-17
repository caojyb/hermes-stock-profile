#!/usr/bin/env python3
"""
run_expanded_walk_forward_stage2_cached.py — Stage 2 cache diagnostics.
Adds bounded kline/universe/reference caches at the runner level only.
Does NOT modify strategy, target engine, normalization, or DB schema.
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlite3
import json
import time
from typing import List, Dict, Any, Tuple

from core.research.expanded_walk_forward_validation import ExpandedWalkForwardValidator
from core.research.walk_forward_validation import WalkForwardEngine


TEST_DB = "/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"


def load_sample_universe(n: int = 200) -> List[dict]:
    con = sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        """
        SELECT code, name FROM stocks
        WHERE code NOT LIKE '688%' AND code NOT LIKE '787%'
        ORDER BY code
        LIMIT ?
        """,
        (n,),
    )
    rows = cur.fetchall()
    con.close()
    return [{"code": r[0], "name": r[1]} for r in rows]


# Runner-level caches only
_kline_cache: Dict[Tuple[str, str, str], List[dict]] = {}
_universe_cache: Dict[str, List[dict]] = {}


def kline_loader(symbol: str, start_date: str, end_date: str) -> List[dict]:
    key = (symbol, start_date or "", end_date or "")
    if key in _kline_cache:
        return _kline_cache[key]
    con = sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)
    cur = con.cursor()
    base = symbol.split(".")[0] if "." in symbol else symbol
    candidates = [symbol, base, base + ".SH", base + ".SZ"]
    seen = set()
    for code in candidates:
        if code in seen:
            continue
        seen.add(code)
        if start_date and end_date:
            cur.execute(
                """
                SELECT date, open, close, high, low, volume
                FROM klines
                WHERE code=? AND date>=? AND date<=?
                ORDER BY date
                """,
                (code, start_date, end_date),
            )
        else:
            cur.execute(
                "SELECT date, open, close, high, low, volume FROM klines WHERE code=? ORDER BY date",
                (code,),
            )
        rows = cur.fetchall()
        if rows:
            result = [
                {
                    "date": r[0],
                    "open": r[1],
                    "close": r[2],
                    "high": r[3],
                    "low": r[4],
                    "volume": r[5],
                }
                for r in rows
            ]
            con.close()
            _kline_cache[key] = result
            return result
    con.close()
    _kline_cache[key] = []
    return []


def universe_fetcher(decision_date: str) -> List[dict]:
    if decision_date in _universe_cache:
        return _universe_cache[decision_date]
    data = load_sample_universe(200)
    _universe_cache[decision_date] = data
    return data


def main():
    start_time = time.time()
    validator = ExpandedWalkForwardValidator(
        db_path=TEST_DB,
        universe_fetcher=universe_fetcher,
        kline_loader=kline_loader,
        dataset_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        target_version="v1",
        fold_policy="anchored_expanding",
        min_folds=5,
        max_folds=8,
        train_window_days=252,
        validation_window_days=63,
        embargo_days=5,
        horizons=[5, 10, 20],
    )

    catalog = validator.build_variant_catalog()
    target_variant = next(v for v in catalog if v.strategy_id == "trend_v1")
    validator._register_experiment(target_variant)

    print(f"=== Stage 2 cached: 1 variant x all folds x all horizons ===")
    summary = validator.run_variant(target_variant)
    elapsed = time.time() - start_time

    report = {
        "stage": "Stage 2 cached",
        "variant": target_variant.strategy_id,
        "family": target_variant.family,
        "elapsed_seconds": round(elapsed, 2),
        "kline_cache_size": len(_kline_cache),
        "universe_cache_size": len(_universe_cache),
        "result": summary,
    }

    print("\n=== Stage 2 Cached Report ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    output_path = (
        "/home/caojy/.hermes/profiles/stock/stock-work/docs/"
        "M9_1_D7_C4_B1_R_RUNTIME_REMEDIATION.md"
    )
    with open(output_path, "a", encoding="utf-8") as f:
        f.write("\n\n```json\n")
        f.write(json.dumps(report, indent=2, ensure_ascii=False))
        f.write("\n```\n")
    print(f"\nResults appended to: {output_path}")


if __name__ == "__main__":
    main()
