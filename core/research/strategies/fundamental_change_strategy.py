#!/usr/bin/env python3
"""
fundamental_change_strategy.py — Fundamental Change Alpha Strategy.

Uses point-in-time fundamental data to detect:
- Revenue growth acceleration/deceleration
- Profit growth acceleration/deceleration
- ROE change

PIT Policy:
- available_time = report_date + conservative_publication_lag
- Only uses fundamental records where available_time <= decision_time
- Focuses on changes between consecutive periods, not static levels

Parameters (fixed, not optimized):
- lookback_periods: number of historical periods to compare
- min_available_records: minimum records needed for change calculation
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

from core.research.base_strategy import BaseStrategy, Signal


REPORT_LAG_DAYS = {
    "Q1": 30, "Q2": 30, "Q3": 30,
    "YEAR": 90, "SEMI": 60, "UNKNOWN": 60,
}


def infer_period_type(report_date: str) -> str:
    try:
        parts = report_date.split("-")
        month, day = int(parts[1]), int(parts[2])
        if month == 3 and day == 31:
            return "Q1"
        elif month == 6 and day == 30:
            return "SEMI"
        elif month == 9 and day == 30:
            return "Q3"
        elif month == 12 and day == 31:
            return "YEAR"
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def conservative_available_time(report_date: str) -> str:
    period_type = infer_period_type(report_date)
    lag = REPORT_LAG_DAYS.get(period_type, 60)
    try:
        dt = __import__("datetime").datetime.strptime(report_date, "%Y-%m-%d")
        return (dt + __import__("datetime").timedelta(days=lag)).strftime("%Y-%m-%d")
    except Exception:
        return report_date


@dataclass(frozen=True)
class FundamentalRecord:
    code: str
    report_date: str
    available_time: str
    fetched_at: str
    roe: Optional[float]
    eps: Optional[float]
    revenue_growth: Optional[float]
    profit_growth: Optional[float]
    debt_ratio: Optional[float]
    net_margin: Optional[float]
    gross_margin: Optional[float]
    op_margin: Optional[float]
    bps: Optional[float]
    equity_ratio: Optional[float]


class FundamentalChangeStrategy(BaseStrategy):
    strategy_id = "fundamental_change_v1"
    strategy_version = "v1"
    family = "Fundamental"
    required_inputs = ["financial_data"]
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = True

    def __init__(
        self,
        db_path: Optional[str] = None,
        lookback_periods: int = 2,
        min_available_records: int = 2,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.db_path = db_path or str(Path(__file__).resolve().parents[3] / "data/production/market_cache.db")
        self.lookback_periods = lookback_periods
        self.min_available_records = min_available_records

    def _connect(self):
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def _fetch_fundamental_records(self, symbol: str, decision_time: str) -> List[FundamentalRecord]:
        con = self._connect()
        cur = con.cursor()
        cur.execute("""
            SELECT code, report_date, fetched_at, roe, eps, revenue_growth, profit_growth,
                   debt_ratio, net_margin, gross_margin, op_margin, bps, equity_ratio
            FROM financial_data
            WHERE code = ?
              AND report_date IS NOT NULL
            ORDER BY report_date ASC
        """, (symbol,))
        rows = cur.fetchall()
        con.close()

        records = []
        for row in rows:
            code, report_date, fetched_at, roe, eps, rev_growth, profit_growth, debt_ratio, net_margin, gross_margin, op_margin, bps, equity_ratio = row
            available_time = conservative_available_time(report_date)
            if available_time <= decision_time:
                records.append(FundamentalRecord(
                    code=code, report_date=report_date, available_time=available_time,
                    fetched_at=fetched_at, roe=roe, eps=eps, revenue_growth=rev_growth,
                    profit_growth=profit_growth, debt_ratio=debt_ratio, net_margin=net_margin,
                    gross_margin=gross_margin, op_margin=op_margin, bps=bps, equity_ratio=equity_ratio,
                ))
        return records

    def _compute_change_signal(self, records: List[FundamentalRecord]) -> Optional[float]:
        if len(records) < self.min_available_records:
            return None

        recent = records[-1]
        prior = records[-2] if len(records) >= 2 else None
        if prior is None:
            return None

        metrics = []
        for curr, prev in [
            (recent.revenue_growth, prior.revenue_growth),
            (recent.profit_growth, prior.profit_growth),
            (recent.roe, prior.roe),
            (recent.net_margin, prior.net_margin),
            (recent.op_margin, prior.op_margin),
        ]:
            if curr is not None and prev is not None and prev != 0:
                metrics.append((curr - prev) / abs(prev))

        if not metrics:
            return None

        return sum(metrics) / len(metrics)

    def generate_signal(self, stock: dict, decision_time: str, context: dict = None) -> Optional[Signal]:
        symbol = stock.get("code") or stock.get("symbol")
        if not symbol:
            return None

        try:
            records = self._fetch_fundamental_records(symbol, decision_time)
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
                reason_code="NO_FUNDAMENTAL_RECORD", horizon=self.horizon, family=self.family,
            )

        raw_score = self._compute_change_signal(records)
        if raw_score is None:
            return Signal(
                stock_code=symbol, decision_time=decision_time,
                strategy_id=self.strategy_id, strategy_version=self.strategy_version,
                raw_score=0.0, normalized_score=None, eligibility=False,
                reason_code="INSUFFICIENT_PERIODS", horizon=self.horizon, family=self.family,
            )

        return Signal(
            stock_code=symbol, decision_time=decision_time,
            strategy_id=self.strategy_id, strategy_version=self.strategy_version,
            raw_score=raw_score, normalized_score=None, eligibility=True,
            reason_code="OK", horizon=self.horizon, family=self.family,
            metadata={
                "source": "financial_data",
                "available_records": len(records),
                "latest_report_date": records[-1].report_date,
                "latest_available_time": records[-1].available_time,
            },
        )
