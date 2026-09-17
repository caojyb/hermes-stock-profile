#!/usr/bin/env python3
"""
reversal_strategy.py — Reversal Strategy
==========================================
Simple short-term reversal baseline using past 5-day return.

Parameters (fixed, not optimized):
- lookback: 5 trading days
- signal: -(close[T] / close[T-lookback] - 1)  # negative of recent return
"""

from __future__ import annotations

from typing import List, Optional

from ..base_strategy import BaseStrategy, Signal


class ReversalStrategy(BaseStrategy):
    strategy_id = "reversal_v1"
    strategy_version = "v1"
    family = "Reversal"
    required_inputs = ["daily_price"]
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = True

    def __init__(self, lookback: int = 5, **kwargs):
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

        if not klines or len(klines) <= self.lookback:
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
        if decision_idx < self.lookback:
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

        price_t = klines[decision_idx]["close"]
        price_t_lookback = klines[decision_idx - self.lookback]["close"]

        if price_t is None or price_t <= 0 or price_t_lookback is None or price_t_lookback <= 0:
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

        recent_return = price_t / price_t_lookback - 1.0
        # Reversal: negative of recent return
        raw_score = -recent_return

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
