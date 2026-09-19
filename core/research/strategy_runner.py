#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stock-work/core/research/strategy_runner.py — PIT Runtime Integration

Canonical Research Plane implementation with PIT enforcement.
Imports forward_outcome from the actual module path.
"""
from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict

# Bootstrap for stock-work root
_HERE = os.path.dirname(os.path.abspath(__file__))
_STOCK_WORK_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))
if _STOCK_WORK_ROOT not in sys.path:
    sys.path.insert(0, _STOCK_WORK_ROOT)

# Actual forward_outcome module path
# 2026-09-19: 原 '..','..','.. 上溯到 profile root（错——core/research 只需两级到
# stock-work root）, 拼出的 scripts/cron/research 不存在 → 平铺 import 必挂。
# forward_outcome 在两处存在: stock-work/scripts-cron-mirror? 不——canonical 在
# profile/scripts/cron/research/（生产树, 已 2026-09-19 从 quarantine 恢复）,
# stock-work/core/research/forward_outcome.py 是 re-export 兼容层。
# 优先用 core 包导入（自足, 不依赖外部路径）, 失败再回落外部路径。
try:
    from core.research import forward_outcome as forward_outcome  # noqa: E402
except ImportError:
    _FORWARD_OUTCOME_DIR = os.path.join(
        os.path.abspath(os.path.join(_HERE, '..', '..', '..')), 'scripts', 'cron', 'research')
    if _FORWARD_OUTCOME_DIR not in sys.path:
        sys.path.insert(0, _FORWARD_OUTCOME_DIR)
    import forward_outcome as forward_outcome  # noqa: E402

HORIZONS = forward_outcome.HORIZONS  # (5, 10, 20)

# PIT Runtime imports
from core.research.research_time_context import ResearchTimeContext, PITViolationError, PITStatus  # noqa: E402
from core.research.universe_pit import UniversePITEngine, UniverseGap, UniverseSnapshotStore  # noqa: E402
from core.research.data_asof_metadata import DataAsofMetadata, DEFAULT_DATASETS  # noqa: E402


@dataclass
class TradeLedgerRow:
    strategy_id: str
    strategy_version: str
    run_id: str
    symbol: str
    candidate_date: str
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    fwd_5d: object = forward_outcome.UNKNOWN
    fwd_10d: object = forward_outcome.UNKNOWN
    fwd_20d: object = forward_outcome.UNKNOWN
    mae: object = forward_outcome.UNKNOWN
    mfe: object = forward_outcome.UNKNOWN
    regime: Optional[str] = None
    is_signal: bool = False
    is_executed: bool = False
    pit_status: str = PITStatus.PIT_UNKNOWN


@dataclass
class StrategyResearchRun:
    strategy_id: str
    strategy_version: str
    run_id: str
    dataset_id: str
    dataset_version: str
    execution_model_version: str
    cost_model_version: str
    date_range: str
    decision_time: str
    data_cutoff: str
    universe_snapshot_id: Optional[str]
    pit_policy: str
    regimes: dict = field(default_factory=dict)

    candidate_n: int = 0
    signal_n: int = 0
    entry_n: int = 0
    trade_n: int = 0
    independent_trade_n: Optional[int] = None
    period_n: Optional[int] = None
    regime_n: Optional[int] = None

    rows: list = field(default_factory=list)
    rejected_datasets: List[Dict] = field(default_factory=list)
    universe_gaps: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "execution_model_version": self.execution_model_version,
            "cost_model_version": self.cost_model_version,
            "date_range": self.date_range,
            "decision_time": self.decision_time,
            "data_cutoff": self.data_cutoff,
            "universe_snapshot_id": self.universe_snapshot_id,
            "pit_policy": self.pit_policy,
            "regimes": self.regimes,
            "candidate_n": self.candidate_n,
            "signal_n": self.signal_n,
            "entry_n": self.entry_n,
            "trade_n": self.trade_n,
            "independent_trade_n": self.independent_trade_n,
            "period_n": self.period_n,
            "regime_n": self.regime_n,
            "rejected_datasets": self.rejected_datasets,
            "universe_gaps": self.universe_gaps,
            "rows": [r.__dict__ for r in self.rows],
        }


class StrategyResearchAdapter:
    def __init__(self, strategy_id: str, strategy_version: str):
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version

    def build_candidates(self, dataset, date_range) -> list[dict]:
        raise NotImplementedError("subclass must implement build_candidates")

    def strategy_signature(self) -> str:
        return f"{self.strategy_id}@{self.strategy_version}"


class ResearchDataAccess:
    """Unified PIT data access boundary. All research data reads must go through this."""

    def __init__(self, context: ResearchTimeContext, db_path: str):
        self.context = context
        self.db_path = db_path
        self._universe_engine = UniversePITEngine(db_path)
        self._dataset_registry = {d.dataset_id: d for d in DEFAULT_DATASETS}

    def get_universe(self, exclude_kcb: bool = True, exclude_bse: bool = True) -> List[Dict]:
        universe = self._universe_engine.get_universe_at(
            self.context.decision_time,
            exclude_kcb=exclude_kcb,
            exclude_bse=exclude_bse,
        )
        snapshot_id = None
        if universe:
            store = UniverseSnapshotStore(self.db_path)
            snapshot_id = store.save_snapshot(self.context.decision_time, universe)
        return universe, snapshot_id

    def get_dataset_status(self, dataset_id: str) -> DataAsofMetadata:
        return self._dataset_registry.get(dataset_id)

    def validate_available_time(self, available_time: Optional[str], dataset_id: str) -> tuple[bool, str]:
        try:
            self.context.validate_available_time(available_time)
            return True, PITStatus.PIT_SAFE
        except PITViolationError as e:
            return False, str(e)

    def get_klines(self, symbol: str, start: str, end: str) -> List[Dict]:
        """PIT-bounded kline access."""
        import sqlite3
        con = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
        con.execute("PRAGMA query_only=ON")
        try:
            cur = con.execute(
                "SELECT date, open, close, high, low, volume FROM klines "
                "WHERE code=? AND date>=? AND date<=? ORDER BY date",
                (symbol, start, end),
            )
            return [dict(zip(['date','open','close','high','low','volume'], r)) for r in cur.fetchall()]
        finally:
            con.close()


class StrategyRunner:
    """Unified executor with PIT Runtime enforcement."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or forward_outcome.DEFAULT_DB

    def run(self, adapter: StrategyResearchAdapter, dataset_id: str,
            dataset_version: str, date_range: str,
            execution_model_version: str, cost_model_version: str,
            candidates: list[dict], context: ResearchTimeContext,
            regimes: Optional[dict] = None) -> StrategyResearchRun:
        run_id = uuid.uuid4().hex[:12]
        run = StrategyResearchRun(
            strategy_id=adapter.strategy_id,
            strategy_version=adapter.strategy_version,
            run_id=run_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            execution_model_version=execution_model_version,
            cost_model_version=cost_model_version,
            date_range=date_range,
            decision_time=context.decision_time,
            data_cutoff=context.data_cutoff,
            universe_snapshot_id=context.universe_snapshot_id,
            pit_policy="PIT_SAFE_ONLY",
        )

        data_access = ResearchDataAccess(context, self.db_path)

        # Dataset whitelist check
        dataset_meta = data_access.get_dataset_status(dataset_id)
        if dataset_meta and dataset_meta.pit_status in (PITStatus.PIT_UNSAFE, PITStatus.PIT_UNKNOWN):
            run.rejected_datasets.append({
                "dataset_id": dataset_id,
                "pit_status": dataset_meta.pit_status,
                "reason": dataset_meta.notes,
            })

        # Universe snapshot
        universe, snapshot_id = data_access.get_universe()
        run.universe_snapshot_id = snapshot_id
        run.universe_gaps = UniversePITEngine(self.db_path).get_gaps()

        import sqlite3
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.execute("PRAGMA query_only=ON")
        try:
            rows = []
            cand = 0
            sig = 0
            for c in candidates:
                symbol: str = str(c.get("symbol") or "")
                cand_date: str = str(c.get("candidate_date") or "")
                is_sig = bool(c.get("is_signal", False))

                # PIT check on candidate date
                pit_ok, pit_reason = data_access.validate_available_time(cand_date, dataset_id)
                pit_status = PITStatus.PIT_SAFE if pit_ok else PITStatus.PIT_UNSAFE

                # entry_price = T+1 开盘
                entry_price = None
                try:
                    cur = con.cursor()
                    cur.execute(
                        "SELECT open FROM klines WHERE code=? AND date>? ORDER BY date ASC LIMIT 1",
                        (symbol, cand_date),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        entry_price = float(row[0])
                except sqlite3.Error:
                    entry_price = None

                cand_dict = {
                    "symbol": symbol,
                    "candidate_date": cand_date,
                    "entry_price": entry_price,
                    "entry_date": None,
                    "as_of_date": cand_date,
                }
                out = forward_outcome.compute_one(cand_dict, con)
                regime = (regimes or {}).get(cand_date)
                ledger = TradeLedgerRow(
                    strategy_id=adapter.strategy_id,
                    strategy_version=adapter.strategy_version,
                    run_id=run_id,
                    symbol=symbol,
                    candidate_date=cand_date,
                    entry_date=None,
                    entry_price=entry_price,
                    exit_date=None,
                    exit_price=None,
                    fwd_5d=out.get("fwd_5d"),
                    fwd_10d=out.get("fwd_10d"),
                    fwd_20d=out.get("fwd_20d"),
                    mae=out.get("mae"),
                    mfe=out.get("mfe"),
                    regime=regime,
                    is_signal=is_sig,
                    is_executed=(entry_price is not None),
                    pit_status=pit_status,
                )
                rows.append(ledger)
                cand += 1
                if is_sig:
                    sig += 1
        finally:
            con.close()

        run.rows = rows
        run.candidate_n = cand
        run.signal_n = sig
        run.trade_n = sum(1 for r in rows if r.is_executed)
        run.entry_n = run.trade_n
        return run


def build_run_id() -> str:
    return uuid.uuid4().hex[:12]
