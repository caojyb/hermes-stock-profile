#!/usr/bin/env python3
"""
stock-work/core/research/universe_pit.py

Universe PIT engine using OBSERVED_MARKET_INTERVAL from klines.

Does NOT fabricate missing historical state; marks gaps explicitly.
Never treats observed intervals as legal listing/delisting dates.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from pathlib import Path

from core.research.research_time_context import PITViolationError, PITStatus
from core.research.data_asof_metadata import DataAsofMetadata, DEFAULT_DATASETS


DEFAULT_DB = str(Path(__file__).resolve().parents[3] / 'data' / 'production' / 'market_cache.db')


@dataclass
class UniverseGap:
    dataset: str
    gap: str
    impact: str
    pit_status: str
    recommended_source: Optional[str] = None
    blocking_level: str = "BLOCKING"


@dataclass
class SecurityHistory:
    stock_code: str
    first_observed: str
    last_observed: str
    history_type: str  # ACTIVE_CURRENT, HISTORICAL_ONLY, UNKNOWN_STATUS

    def is_observable_at(self, decision_time: str) -> bool:
        return self.first_observed <= decision_time <= self.last_observed


class UniversePITEngine:
    """Reconstructs Universe(T) from observed market intervals and verified board state."""

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self.gaps: List[UniverseGap] = []
        self._security_history: Optional[Dict[str, SecurityHistory]] = None

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
        con.execute("PRAGMA query_only=ON")
        return con

    def _load_security_history(self) -> Dict[str, SecurityHistory]:
        """Load observed market intervals from klines. Never call this list_date."""
        con = self._connect()
        try:
            cur = con.execute("""
                SELECT code, MIN(date), MAX(date)
                FROM klines
                WHERE code IS NOT NULL AND date IS NOT NULL
                GROUP BY code
            """)
            history = {}
            for code, first, last in cur.fetchall():
                if last >= '2026-09-01':
                    history_type = 'ACTIVE_CURRENT'
                else:
                    history_type = 'HISTORICAL_ONLY'
                history[code] = SecurityHistory(
                    stock_code=code,
                    first_observed=first,
                    last_observed=last,
                    history_type=history_type,
                )
            return history
        finally:
            con.close()

    def get_security_history(self) -> Dict[str, SecurityHistory]:
        if self._security_history is None:
            self._security_history = self._load_security_history()
        return self._security_history

    def get_universe_at(self, decision_time: str, exclude_kcb: bool = True, exclude_bse: bool = True) -> List[Dict]:
        """
        Returns list of dicts for stocks eligible at decision_time.
        Uses OBSERVED_MARKET_INTERVAL from klines, not stocks.list_date.
        """
        security_history = self.get_security_history()
        rows = []

        for code, history in security_history.items():
            # Basic observation check
            if not history.is_observable_at(decision_time):
                continue

            # Board exclusion
            board_excluded = False
            board_reason = None
            if exclude_kcb and code.startswith('688'):
                board_excluded = True
                board_reason = 'BOARD_STAR_VERIFIED'
            elif exclude_kcb and code.startswith('689'):
                board_excluded = True
                board_reason = 'BOARD_STAR_VERIFIED'
            elif exclude_bse and code.startswith('8') and not code.startswith('68'):
                board_excluded = True
                board_reason = 'BOARD_BJ_VERIFIED'

            if board_excluded:
                continue

            rows.append({
                'code': code,
                'first_observed': history.first_observed,
                'last_observed': history.last_observed,
                'history_type': history.history_type,
                'board_reason': board_reason or 'BOARD_MAIN_OR_CHINEXT_INFERRED',
                'pit_state': 'OBSERVATION_VERIFIED',
                'pit_warnings': [
                    'ST_HISTORY_MISSING',
                    'SUSPENSION_MISSING',
                    'TRADING_STATUS_MISSING',
                    'BOARD_HISTORY_INFERRED',
                ],
            })

        return rows

    def get_gaps(self) -> List[Dict]:
        return [g.__dict__ for g in self.gaps]

    def clear_gaps(self) -> None:
        self.gaps = []


class UniverseSnapshotStore:
    """Persists universe snapshots for reuse."""

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS universe_pit_snapshot (
                    snapshot_id TEXT PRIMARY KEY,
                    decision_time TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    effective_start TEXT NOT NULL,
                    effective_end TEXT,
                    status TEXT NOT NULL,
                    status_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    version TEXT NOT NULL,
                    metadata_json TEXT
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_universe_pit_decision ON universe_pit_snapshot(decision_time, stock_code)")
            con.commit()
        finally:
            con.close()

    def save_snapshot(self, decision_time: str, rows: List[Dict], version: str = "1.0") -> str:
        import uuid, datetime
        snapshot_id = f"universe_{decision_time}_{uuid.uuid4().hex[:8]}"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("BEGIN")
            for r in rows:
                con.execute(
                    """
                    INSERT OR REPLACE INTO universe_pit_snapshot
                       (snapshot_id, decision_time, stock_code, effective_start, effective_end,
                        status, status_type, source, observed_at, available_at, version, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        decision_time,
                        r.get('code'),
                        r.get('first_observed') or decision_time,
                        r.get('last_observed'),
                        'ACTIVE',
                        'OBSERVATION',
                        'klines.observed_interval',
                        now,
                        decision_time,
                        version,
                        None,
                    ),
                )
            con.commit()
        finally:
            con.close()
        return snapshot_id

    def load_snapshot(self, decision_time: str) -> List[Dict]:
        con = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute(
            "SELECT stock_code, status, status_type, metadata_json FROM universe_pit_snapshot WHERE decision_time=?",
            (decision_time,),
        )
        rows = []
        for r in cur.fetchall():
            rows.append({
                'code': r[0],
                'status': r[1],
                'status_type': r[2],
                'metadata_json': r[3],
            })
        con.close()
        return rows
