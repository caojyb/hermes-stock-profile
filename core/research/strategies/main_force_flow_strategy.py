#!/usr/bin/env python3
"""
main_force_flow_strategy.py — Main Force Flow Alpha Strategy.

Uses point-in-time main force capital flow data to detect:
- Net flow intensity
- Flow acceleration
- Flow persistence

PIT Policy:
- available_time = trade_date + 1 day (CONSERVATIVE_NEXT_SESSION)
- Only uses flow records where available_time <= decision_time
- Does not use future flow information in signal generation

Parameters (fixed, not optimized):
- lookback: number of recent trading days to consider
- min_available_records: minimum records needed
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

from core.research.base_strategy import BaseStrategy, Signal


@dataclass(frozen=True)
class CapitalFlowRecord:
    code: str
    trade_date: str
    available_time: str
    net_amt: Optional[float]
    source: str


class MainForceFlowStrategy(BaseStrategy):
    strategy_id = "main_force_flow_v1"
    strategy_version = "v1"
    family = "CapitalFlow"
    required_inputs = ["main_fund_flow"]
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = True

    def __init__(
        self,
        db_path: Optional[str] = None,
        lookback: int = 5,
        min_available_records: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.db_path = db_path or str(Path(__file__).resolve().parents[2] / "data/production/market_cache.db")
        self.lookback = lookback
        self.min_available_records = min_available_records

    def _connect(self):
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def _fetch_flow_records(self, symbol: str, decision_time: str) -> List[CapitalFlowRecord]:
        con = self._connect()
        cur = con.cursor()
        cur.execute("""
            SELECT code, date, net_amt
            FROM main_fund_flow
            WHERE code = ?
              AND date IS NOT NULL
            ORDER BY date ASC
        """, (symbol,))
        rows = cur.fetchall()
        con.close()

        records = []
        for row in rows:
            code, trade_date, net_amt = row
            # Conservative PIT: trade_date T -> available at T+1
            try:
                dt = __import__("datetime").datetime.strptime(trade_date, "%Y-%m-%d")
                available_time = (dt + __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
            except Exception:
                available_time = trade_date

            if available_time <= decision_time:
                records.append(CapitalFlowRecord(
                    code=code, trade_date=trade_date, available_time=available_time,
                    net_amt=net_amt, source="main_fund_flow",
                ))
        return records

    def _compute_flow_signal(self, records: List[CapitalFlowRecord]) -> Optional[float]:
        if len(records) < self.min_available_records:
            return None

        recent = records[-self.lookback:]
        if len(recent) < self.min_available_records:
            return None

        net_amounts = [r.net_amt for r in recent if r.net_amt is not None]
        if not net_amounts:
            return None

        # Simple signal: average net flow intensity normalized by latest absolute flow
        avg_flow = sum(net_amounts) / len(net_amounts)
        latest_abs = abs(net_amounts[-1])
        if latest_abs == 0:
            return 0.0

        return avg_flow / latest_abs

    def generate_signal(self, stock: dict, decision_time: str, context: dict = None) -> Optional[Signal]:
        symbol = stock.get("code") or stock.get("symbol")
        if not symbol:
            return None

        try:
            records = self._fetch_flow_records(symbol, decision_time)
        except Exception:
            return Signal(
                stock_code=symbol, decision_time=decision_time,
                strategy_id=self.strategy_id, strategy_version=self.strategy_version,
                raw_score=0.0, normalized_score=None, eligibility=False,
                reason_code="SOURCE_UNAVAILABLE", horizon=self.horizon, family=self.family,
            )

        if not records:
            return Signal(
                stock_code=symbol, decision_time=decision_time,
                strategy_id=self.strategy_id, strategy_version=self.strategy_version,
                raw_score=0.0, normalized_score=None, eligibility=False,
                reason_code="NO_FLOW_RECORD", horizon=self.horizon, family=self.family,
            )

        raw_score = self._compute_flow_signal(records)
        if raw_score is None:
            return Signal(
                stock_code=symbol, decision_time=decision_time,
                strategy_id=self.strategy_id, strategy_version=self.strategy_version,
                raw_score=0.0, normalized_score=None, eligibility=False,
                reason_code="INSUFFICIENT_FLOW_HISTORY", horizon=self.horizon, family=self.family,
            )

        return Signal(
            stock_code=symbol, decision_time=decision_time,
            strategy_id=self.strategy_id, strategy_version=self.strategy_version,
            raw_score=raw_score, normalized_score=None, eligibility=True,
            reason_code="OK", horizon=self.horizon, family=self.family,
            metadata={
                "source": "main_fund_flow",
                "available_records": len(records),
                "latest_trade_date": records[-1].trade_date,
                "latest_available_time": records[-1].available_time,
            },
        )
