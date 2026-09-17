#!/usr/bin/env python3
"""
c4_b2_fold_alignment_audit.py — M9.1-C4-B2-G Pre-fix static audit of fold boundary generation.
"""
from __future__ import annotations

import os, sys, sqlite3, json
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition

_con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
_con.execute("PRAGMA query_only=ON")

_date_set = None

def _load_trading_dates() -> set:
    global _date_set
    if _date_set is None:
        cur = _con.cursor()
        cur.execute("SELECT DISTINCT date FROM klines WHERE date IS NOT NULL ORDER BY date")
        _date_set = {r[0] for r in cur.fetchall()}
    return _date_set


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
    cur = _con.cursor()
    cur.execute(
        "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT 200",
    )
    return [{"code": r[0], "name": r[1]} for r in cur.fetchall()]


def audit_raw_fold_generation() -> Dict[str, Any]:
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
    folds = engine.define_folds_auto(
        train_window_days=252,
        validation_window_days=63,
        embargo_days=5,
        min_folds=8,
        max_folds=8,
    )
    trading_dates = sorted(_load_trading_dates())
    trading_date_set = set(trading_dates)
    rows = []
    for f in folds:
        rows.append({
            "fold_id": f.fold_id,
            "train_start": f.train_start,
            "train_end": f.train_end,
            "validation_start": f.validation_start,
            "validation_end": f.validation_end,
            "train_start_is_trading_day": f.train_start in trading_date_set,
            "train_end_is_trading_day": f.train_end in trading_date_set,
            "validation_start_is_trading_day": f.validation_start in trading_date_set,
            "validation_end_is_trading_day": f.validation_end in trading_date_set,
        })
    return {
        "fold_count": len(folds),
        "trading_date_count": len(trading_dates),
        "trading_date_range": [trading_dates[0], trading_dates[-1]] if trading_dates else None,
        "folds": rows,
        "non_trading_folds": [
            r for r in rows
            if not r["validation_start_is_trading_day"] or not r["validation_end_is_trading_day"]
        ],
    }


def main() -> Dict[str, Any]:
    report = audit_raw_fold_generation()
    out_path = ARTIFACT_DIR / 'c4_b2_fold_alignment_audit.json'
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    report = main()
    print(json.dumps({
        "fold_count": report["fold_count"],
        "non_trading_folds": report["non_trading_folds"],
        "trading_date_range": report["trading_date_range"],
    }, indent=2, ensure_ascii=False))
