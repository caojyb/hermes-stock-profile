#!/usr/bin/env python3
"""
trend_strategy.py — Trend Strategy
====================================
Simple trend-following baseline using moving average crossover.

Parameters (fixed, not optimized):
- lookback: 60 trading days
- ma_type: simple moving average
- signal: price / MA - 1
"""

from __future__ import annotations

from typing import List, Optional

from ..base_strategy import BaseStrategy, Signal


class TrendStrategy(BaseStrategy):
    strategy_id = "trend_v1"
    strategy_version = "v1"
    family = "Trend"
    required_inputs = ["daily_price"]
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = True

    def __init__(self, lookback: int = 60, **kwargs):
        super().__init__(**kwargs)
        self.lookback = lookback

    def generate_signal(self, stock: dict, decision_time: str,
                        context: dict = None) -> Optional[Signal]:
        symbol = stock.get("code") or stock.get("symbol")
        if not symbol or self.kline_loader is None:
            return None

        try:
            klines = self.kline_loader(symbol, "", "")
        except Exception:
            return None

        if not klines or len(klines) < self.lookback + 1:
            return Signal(
                stock_code=symbol,
                decision_time=decision_time,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                raw_score=0.0,
                normalized_score=None,
                eligibility=False,
                reason_code="INSUFFICIENT_HISTORY",
                horizon=self.horizon,
                family=self.family,
            )

        # Find decision_time index
        decision_idx = -1
        for i, k in enumerate(klines):
            if k["date"] == decision_time:
                decision_idx = i
                break
        if decision_idx < 0:
            return Signal(
                stock_code=symbol,
                decision_time=decision_time,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                raw_score=0.0,
                normalized_score=None,
                eligibility=False,
                reason_code="DECISION_DATE_NOT_FOUND",
                horizon=self.horizon,
                family=self.family,
            )

        # Need lookback days before decision_time + decision_time itself
        start_idx = decision_idx - self.lookback + 1
        if start_idx < 0:
            return Signal(
                stock_code=symbol,
                decision_time=decision_time,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                raw_score=0.0,
                normalized_score=None,
                eligibility=False,
                reason_code="INSUFFICIENT_HISTORY",
                horizon=self.horizon,
                family=self.family,
            )

        # Compute simple moving average over lookback period ending at decision_time
        closes = [klines[i]["close"] for i in range(start_idx, decision_idx + 1)]
        if any(c is None or c <= 0 for c in closes):
            return Signal(
                stock_code=symbol,
                decision_time=decision_time,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                raw_score=0.0,
                normalized_score=None,
                eligibility=False,
                reason_code="INVALID_PRICE",
                horizon=self.horizon,
                family=self.family,
            )

        ma = sum(closes) / len(closes)
        price = klines[decision_idx]["close"]
        raw_score = price / ma - 1.0 if ma > 0 else 0.0

        return Signal(
            stock_code=symbol,
            decision_time=decision_time,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            raw_score=raw_score,
            normalized_score=None,
            eligibility=True,
            reason_code="OK",
            horizon=self.horizon,
            family=self.family,
        )
