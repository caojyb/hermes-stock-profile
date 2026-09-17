#!/usr/bin/env python3
"""
c4_b2_trading_calendar_alignment.py — M9.1-C4-B2-G trading-calendar-aligned fold boundaries.
"""
from __future__ import annotations

import os, sys, sqlite3, json
from pathlib import Path
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition

_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")

_cached_trading_dates: Optional[List[str]] = None
_cached_trading_date_set: Optional[set] = None


def _load_trading_dates() -> List[str]:
    global _cached_trading_dates, _cached_trading_date_set
    if _cached_trading_dates is None:
        cur = _con.cursor()
        cur.execute("SELECT DISTINCT date FROM klines WHERE date IS NOT NULL ORDER BY date")
        rows = cur.fetchall()
        _cached_trading_dates = [r[0] for r in rows]
        _cached_trading_date_set = set(_cached_trading_dates)
    return _cached_trading_dates


def _trading_date_index(target_date: str) -> int:
    dates = _load_trading_dates()
    for idx, d in enumerate(dates):
        if d == target_date:
            return idx
    return -1


def _prev_trading_day(date_str: str) -> str:
    dates = _load_trading_dates()
    idx = _trading_date_index(date_str)
    if idx > 0:
        return dates[idx - 1]
    if idx == 0:
        return date_str
    # Not in calendar; find nearest previous
    target = date_str
    found = [d for d in dates if d < target]
    return found[-1] if found else date_str


def _next_trading_day(date_str: str) -> str:
    dates = _load_trading_dates()
    idx = _trading_date_index(date_str)
    if idx >= 0 and idx + 1 < len(dates):
        return dates[idx + 1]
    target = date_str
    found = [d for d in dates if d > target]
    return found[0] if found else date_str


def _closest_trading_day(date_str: str, direction: str = "prev") -> str:
    dates = _load_trading_dates()
    idx = _trading_date_index(date_str)
    if idx >= 0:
        return date_str
    target = date_str
    if direction == "prev":
        candidates = [d for d in dates if d < target]
        return candidates[-1] if candidates else dates[0]
    candidates = [d for d in dates if d > target]
    return candidates[0] if candidates else dates[-1]


def align_to_trading_day(date_str: str, rule: str = "PREVIOUS_TRADING_DAY") -> Dict[str, Any]:
    dates = _load_trading_dates()
    date_set = set(dates)
    if date_str in date_set:
        return {
            "raw_boundary": date_str,
            "aligned_boundary": date_str,
            "alignment_applied": False,
            "alignment_rule": rule,
            "is_trading_day": True,
            "alignment_direction": "NONE",
        }
    if rule == "PREVIOUS_TRADING_DAY":
        aligned = _prev_trading_day(date_str)
    elif rule == "NEXT_TRADING_DAY":
        aligned = _next_trading_day(date_str)
    else:
        aligned = _closest_trading_day(date_str, direction="prev")
    return {
        "raw_boundary": date_str,
        "aligned_boundary": aligned,
        "alignment_applied": True,
        "alignment_rule": rule,
        "is_trading_day": True,
        "alignment_direction": "PREVIOUS" if aligned < date_str else ("NEXT" if aligned > date_str else "NONE"),
    }


def build_trading_aligned_folds(
    engine: WalkForwardEngine,
    train_window_days: int = 252,
    validation_window_days: int = 63,
    embargo_days: int = 5,
    min_folds: int = 5,
    max_folds: int = 8,
    boundary_rule: str = "PREVIOUS_TRADING_DAY",
) -> List[Dict[str, Any]]:
    raw_folds = engine.define_folds_auto(
        train_window_days=train_window_days,
        validation_window_days=validation_window_days,
        embargo_days=embargo_days,
        min_folds=min_folds,
        max_folds=max_folds,
    )
    aligned = []
    for f in raw_folds:
        train_start_align = align_to_trading_day(f.train_start, boundary_rule)
        train_end_align = align_to_trading_day(f.train_end, boundary_rule)
        val_start_align = align_to_trading_day(f.validation_start, boundary_rule)
        val_end_align = align_to_trading_day(f.validation_end, boundary_rule)
        aligned.append({
            "fold_id": f.fold_id,
            "fold_index": f.fold_index,
            "fold_policy": f.fold_policy,
            "raw": {
                "train_start": f.train_start,
                "train_end": f.train_end,
                "validation_start": f.validation_start,
                "validation_end": f.validation_end,
            },
            "aligned": {
                "train_start": train_start_align["aligned_boundary"],
                "train_end": train_end_align["aligned_boundary"],
                "validation_start": val_start_align["aligned_boundary"],
                "validation_end": val_end_align["aligned_boundary"],
            },
            "alignment": {
                "train_start": train_start_align,
                "train_end": train_end_align,
                "validation_start": val_start_align,
                "validation_end": val_end_align,
            },
            "boundary_rule": boundary_rule,
            "notes": f.notes,
        })
    return aligned


def main() -> Dict[str, Any]:
    engine = WalkForwardEngine(
        universe_fetcher=lambda d: [],
        kline_loader=lambda s, a, b: [],
        db_path=str(DB_PATH),
        dataset_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        target_version="v1",
        pit_policy="PIT_RESEARCH_V1",
        fold_policy="anchored_expanding",
    )
    report = {
        "boundary_rule": "PREVIOUS_TRADING_DAY",
        "folds": build_trading_aligned_folds(engine),
    }
    out_path = ARTIFACT_DIR / 'c4_b2_fold_boundary_before_after.json'
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    report = main()
    print(json.dumps(report, indent=2, ensure_ascii=False))
