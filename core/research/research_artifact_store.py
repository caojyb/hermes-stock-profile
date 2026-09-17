#!/usr/bin/env python3
"""
research_artifact_store.py — Research Artifact Store
=====================================================
Stores strategy research run artifacts in SQLite under stock-work/data/research/.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any


RESEARCH_RUN_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS strategy_research_runs (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    decision_time TEXT NOT NULL,
    universe_version TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    target_version TEXT NOT NULL,
    pit_policy TEXT,
    input_datasets TEXT,
    rejected_datasets TEXT,
    signal_count INTEGER,
    eligible_count INTEGER,
    mean_signal REAL,
    mean_excess_return REAL,
    median_excess_return REAL,
    ic REAL,
    rank_ic REAL,
    hit_rate REAL,
    turnover_proxy REAL,
    missing_target_rate REAL,
    result_summary TEXT,
    created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class StrategyResearchRun:
    run_id: str
    strategy_id: str
    strategy_version: str
    decision_time: str
    universe_version: str
    dataset_version: str
    target_version: str
    pit_policy: Optional[str]
    input_datasets: Optional[str]
    rejected_datasets: Optional[str]
    signal_count: int
    eligible_count: int
    mean_signal: Optional[float]
    mean_excess_return: Optional[float]
    median_excess_return: Optional[float]
    ic: Optional[float]
    rank_ic: Optional[float]
    hit_rate: Optional[float]
    turnover_proxy: Optional[float]
    missing_target_rate: Optional[float]
    result_summary: Optional[str]
    created_at: str


class ResearchArtifactStore:
    """Persist strategy research run artifacts."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialize()

    def _initialize(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(RESEARCH_RUN_TABLE_DDL)
        con.commit()
        con.close()

    def store_run(self, run: StrategyResearchRun) -> None:
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO strategy_research_runs (
                run_id, strategy_id, strategy_version, decision_time,
                universe_version, dataset_version, target_version, pit_policy,
                input_datasets, rejected_datasets, signal_count, eligible_count,
                mean_signal, mean_excess_return, median_excess_return, ic, rank_ic,
                hit_rate, turnover_proxy, missing_target_rate, result_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.strategy_id,
                run.strategy_version,
                run.decision_time,
                run.universe_version,
                run.dataset_version,
                run.target_version,
                run.pit_policy,
                run.input_datasets,
                run.rejected_datasets,
                run.signal_count,
                run.eligible_count,
                run.mean_signal,
                run.mean_excess_return,
                run.median_excess_return,
                run.ic,
                run.rank_ic,
                run.hit_rate,
                run.turnover_proxy,
                run.missing_target_rate,
                run.result_summary,
                run.created_at,
            ),
        )
        con.commit()
        con.close()
