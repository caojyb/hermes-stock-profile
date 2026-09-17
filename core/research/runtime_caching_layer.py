#!/usr/bin/env python3
"""
runtime_caching_layer.py — Research runtime caching for walk-forward validation.
Provides bounded caches for klines, universe, reference, and targets.
Only affects research runtime; no strategy/target contract changes.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------- Kline Cache
class KlineCache:
    """Bounded per-symbol kline cache with date→index map."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._date_index: Dict[str, Dict[str, int]] = {}

    def get_klines(self, symbol: str, con_factory) -> List[Dict[str, Any]]:
        key = symbol.split(".")[0] if "." in symbol else symbol
        if key not in self._cache:
            rows = self._load_klines(con_factory, key)
            self._cache[key] = rows
            self._date_index[key] = {r["date"]: i for i, r in enumerate(rows)}
        return self._cache[key]

    def get_index(self, symbol: str, date: str) -> int:
        key = symbol.split(".")[0] if "." in symbol else symbol
        if key not in self._date_index:
            self.get_klines(symbol, self._con_factory)
        return self._date_index.get(key, {}).get(date, -1)

    def get_price(self, symbol: str, date: str, price_type: str = "close") -> Optional[float]:
        key = symbol.split(".")[0] if "." in symbol else symbol
        if key not in self._cache:
            return None
        idx = self._date_index.get(key, {}).get(date)
        if idx is None or idx < 0 or idx >= len(self._cache[key]):
            return None
        return self._cache[key][idx].get(price_type)

    def _load_klines(self, con_factory, base_symbol: str) -> List[Dict[str, Any]]:
        candidates = [base_symbol, base_symbol + ".SH", base_symbol + ".SZ"]
        seen = set()
        seen_dates = set()
        rows = []
        con = con_factory()
        try:
            for code in candidates:
                if code in seen:
                    continue
                seen.add(code)
                try:
                    cur = con.execute(
                        "SELECT date, open, close, high, low FROM klines WHERE code=? ORDER BY date",
                        (code,),
                    )
                    for r in cur.fetchall():
                        if r[0] not in seen_dates:
                            seen_dates.add(r[0])
                            rows.append({
                                "date": r[0],
                                "open": r[1],
                                "close": r[2],
                                "high": r[3],
                                "low": r[4],
                            })
                except sqlite3.Error:
                    continue
        finally:
            try:
                con.close()
            except Exception:
                pass
        return rows

    @staticmethod
    def _con_factory():
        raise NotImplementedError("Use db_path constructor instead")


# ---------------------------------------------------------------- Universe Cache
class UniverseCache:
    """Bounded per-decision_date universe cache."""

    def __init__(self, universe_fetcher: Callable[[str], List[dict]]):
        self._fetcher = universe_fetcher
        self._cache: Dict[str, List[dict]] = {}

    def get(self, decision_date: str, universe_version: str = "") -> List[dict]:
        key = f"{decision_date}:{universe_version}"
        if key not in self._cache:
            self._cache[key] = self._fetcher(decision_date)
        return self._cache[key]

    def invalidate(self, decision_date: str, universe_version: str = ""):
        key = f"{decision_date}:{universe_version}"
        self._cache.pop(key, None)


# ---------------------------------------------------------------- Reference Cache
class ReferenceCache:
    """Bounded reference return cache: key = (decision_time, horizon, method, universe_version)."""

    def __init__(self):
        self._cache: Dict[Tuple[str, int, str, str], Optional[float]] = {}

    def get(self, decision_time: str, horizon: int, method: str, universe_version: str) -> Optional[float]:
        return self._cache.get((decision_time, horizon, method, universe_version))

    def put(self, decision_time: str, horizon: int, method: str, universe_version: str, value: Optional[float]):
        self._cache[(decision_time, horizon, method, universe_version)] = value

    def invalidate(self, decision_time: str, horizon: int, method: str, universe_version: str):
        self._cache.pop((decision_time, horizon, method, universe_version), None)


# ---------------------------------------------------------------- Normalization Cache
class NormalizationCache:
    """Bounded normalization parameter cache: key = (fold_id, decision_time, method)."""

    def __init__(self):
        self._cache: Dict[Tuple[str, str, str], Any] = {}

    def get(self, fold_id: str, decision_time: str, method: str) -> Optional[Any]:
        return self._cache.get((fold_id, decision_time, method))

    def put(self, fold_id: str, decision_time: str, method: str, params: Any):
        self._cache[(fold_id, decision_time, method)] = params
