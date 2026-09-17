#!/usr/bin/env python3
"""
run_expanded_walk_forward_instrumented.py — Instrumented expanded walk-forward validation.
Adds stage timing, progress reporting, and bounded execution.
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlite3
import json
import time
from typing import List, Dict, Any

from core.research.expanded_walk_forward_validation import ExpandedWalkForwardValidator


TEST_DB = "/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"
RESULTS_PATH = "/home/caojy/.hermes/profiles/stock/stock-work/docs/M9_1_D7_C4_B1_EXPANDED_WALK_FORWARD_RESULTS.md"


class StageTimer:
    """Records stage timing."""

    def __init__(self):
        self.stages: List[Dict[str, Any]] = []
        self._current_start: float = 0.0

    def start(self, name: str):
        self._current_start = time.time()
        print(f"[STAGE] {name} ...")

    def stop(self, name: str, **kwargs):
        elapsed = time.time() - self._current_start
        record = {"stage": name, "elapsed": elapsed, **kwargs}
        self.stages.append(record)
        print(f"[STAGE] {name} done in {elapsed:.2f}s")
        return record

    def summary(self) -> Dict[str, Any]:
        return {"stages": self.stages}


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


def main():
    timer = StageTimer()
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
    folds = validator.run_variant.__wrapped__ if hasattr(validator.run_variant, "__wrapped__") else None

    print(f"=== Stage 1: 1 variant x 1 fold x 1 horizon ===")
    print(f"Variant: {target_variant.strategy_id}, Family: {target_variant.family}")

    timer.start("variant_setup")
    validator._register_experiment(target_variant)
    timer.stop("variant_setup", variant=target_variant.strategy_id)

    # Manually run one fold with timing
    from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition
    from core.research.strategies.naive_baseline import NaiveBaselineStrategy

    engine = WalkForwardEngine(
        universe_fetcher=universe_fetcher,
        kline_loader=kline_loader,
        db_path=TEST_DB,
        fold_policy="anchored_expanding",
    )
    folds = engine.define_folds_auto(min_folds=1, max_folds=1)
    fold = folds[0]

    timer.start("fold_definition")
    print(f"Fold: {fold.fold_id}, val={fold.validation_start}..{fold.validation_end}")
    timer.stop("fold_definition", fold_id=fold.fold_id)

    timer.start("universe_construction")
    universe = universe_fetcher(fold.validation_start)
    timer.stop("universe_construction", universe_size=len(universe))

    strategy = target_variant.strategy_cls(**target_variant.parameters)
    baseline = NaiveBaselineStrategy(seed=42)

    timer.start("run_fold")
    result = engine.run_fold(fold, strategy, baseline, horizons=[5])
    timer.stop("run_fold", fold_status=result.fold_status, valid_targets=result.valid_target_count)

    report = {
        "stage_timing": timer.summary(),
        "variant": target_variant.strategy_id,
        "fold_id": fold.fold_id,
        "fold_status": result.fold_status,
        "valid_target_count": result.valid_target_count,
        "strategy_ic": result.strategy_ic,
        "baseline_ic": result.baseline_ic,
    }

    print("\n=== Stage Timing Report ===")
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
