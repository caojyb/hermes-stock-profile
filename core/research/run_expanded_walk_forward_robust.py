#!/usr/bin/env python3
"""
run_expanded_walk_forward_robust.py — Robust expanded walk-forward validation.
Runs variants sequentially with per-variant timeout and incremental result writing.
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlite3
import json
import signal
from typing import List, Dict, Any

from core.research.expanded_walk_forward_validation import ExpandedWalkForwardValidator


TEST_DB = "/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"
RESULTS_PATH = "/home/caojy/.hermes/profiles/stock/stock-work/docs/M9_1_D7_C4_B1_EXPANDED_WALK_FORWARD_RESULTS.md"


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


def kline_loader(symbol: str, start_date: str, end_date: str) -> List[dict]:
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
            return result
    con.close()
    return []


def universe_fetcher(decision_date: str) -> List[dict]:
    return load_sample_universe(200)


class TimeoutException(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutException("Variant execution timed out")


def main():
    # Set 5-minute timeout per variant
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(300)

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

    variants = validator.build_variant_catalog()
    results = []

    for variant in variants:
        print(f"Running variant: {variant.strategy_id}")
        validator._register_experiment(variant)
        try:
            signal.alarm(300)  # Reset 5-minute alarm
            summary = validator.run_variant(variant)
            results.append({
                "variant": variant.strategy_id,
                "family": variant.family,
                "status": "COMPLETED",
                "result": summary,
            })
            print(f"  -> {summary.get('status')}: valid={summary.get('valid_fold_count')} low_sample={summary.get('low_sample_fold_count')} blocked={summary.get('blocked_fold_count')}")
        except TimeoutException:
            results.append({
                "variant": variant.strategy_id,
                "family": variant.family,
                "status": "TIMEOUT",
                "error": "Variant execution exceeded 5-minute timeout",
            })
            print(f"  -> TIMEOUT after 5 minutes")
        except Exception as exc:
            results.append({
                "variant": variant.strategy_id,
                "family": variant.family,
                "status": "ERROR",
                "error": str(exc),
                "type": type(exc).__name__,
            })
            print(f"  -> ERROR: {exc}")

    signal.alarm(0)  # Cancel alarm

    validator._aggregate_families()
    validator._update_multiple_testing()
    report = validator.report()
    report["per_variant_results"] = results

    print("\n=== Expanded Walk-Forward Validation Report ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        f.write("# M9_1_D7_C4_B1_EXPANDED_WALK_FORWARD_RESULTS.md\n\n")
        f.write("```json\n")
        f.write(json.dumps(report, indent=2, ensure_ascii=False))
        f.write("\n```\n")
    print(f"\nResults written to: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
