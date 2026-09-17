#!/usr/bin/env python3
"""
target_store.py — Research Target Store
========================================
Stores/retrieves future_excess_return targets in SQLite under stock-work/data/research/.

Schema includes provenance, universe version, reference version, target version,
price basis, PIT metadata, and target status.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


TARGET_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS future_excess_return_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    decision_time TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    stock_return REAL NOT NULL,
    benchmark_id TEXT,
    benchmark_version TEXT,
    benchmark_return REAL,
    excess_return REAL,
    reference_method TEXT,
    reference_return REAL,
    target_status TEXT NOT NULL,
    price_basis TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    universe_version TEXT NOT NULL,
    target_version TEXT NOT NULL,
    reference_version TEXT,
    run_id TEXT,
    pit_policy TEXT,
    available_time TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(stock_code, decision_time, horizon, target_version)
);
"""


@dataclass(frozen=True)
class FutureExcessReturnTarget:
    stock_code: str
    decision_time: str
    horizon: int
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stock_return: float
    benchmark_id: Optional[str]
    benchmark_version: Optional[str]
    benchmark_return: Optional[float]
    excess_return: Optional[float]
    reference_method: Optional[str]
    reference_return: Optional[float]
    target_status: str
    price_basis: str
    dataset_version: str
    universe_version: str
    target_version: str
    reference_version: Optional[str]
    run_id: Optional[str]
    pit_policy: Optional[str]
    available_time: Optional[str]
    created_at: str


class TargetStore:
    """Persist and retrieve future excess return targets."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialize()

    def _initialize(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(TARGET_TABLE_DDL)
        con.commit()
        con.close()

    def store_target(self, target: FutureExcessReturnTarget) -> int:
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO future_excess_return_targets (
                stock_code, decision_time, horizon, entry_date, exit_date,
                entry_price, exit_price, stock_return, benchmark_id, benchmark_version,
                benchmark_return, excess_return, reference_method, reference_return,
                target_status, price_basis, dataset_version, universe_version,
                target_version, reference_version, run_id, pit_policy, available_time, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target.stock_code,
                target.decision_time,
                target.horizon,
                target.entry_date,
                target.exit_date,
                target.entry_price,
                target.exit_price,
                target.stock_return,
                target.benchmark_id,
                target.benchmark_version,
                target.benchmark_return,
                target.excess_return,
                target.reference_method,
                target.reference_return,
                target.target_status,
                target.price_basis,
                target.dataset_version,
                target.universe_version,
                target.target_version,
                target.reference_version,
                target.run_id,
                target.pit_policy,
                target.available_time,
                target.created_at,
            ),
        )
        con.commit()
        row_id = cur.lastrowid
        con.close()
        return row_id

    def query_targets(self, decision_time: str, horizon: int):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            "SELECT * FROM future_excess_return_targets WHERE decision_time=? AND horizon=? ORDER BY stock_code",
            (decision_time, horizon),
        )
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description]
        con.close()
        return [dict(zip(columns, row)) for row in rows]
