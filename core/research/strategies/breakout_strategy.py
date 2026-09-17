#!/usr/bin/env python3
"""
breakout_strategy.py — Breakout Strategy Family
================================================
Research hypothesis: "Whether recent breakout from historical price range
has cross-sectional excess-return predictive power."

Variants:
- breakout_strength_v1: Price position relative to N-day high/low
- breakout_confirmation_v1: Breakout with volume confirmation

PIT-safe inputs: daily_price, daily_volume
Required EOD policy: Yes
"""

from __future__ import annotations

from typing import List, Optional

from ..base_strategy import BaseStrategy, Signal


class BreakoutStrengthStrategy(BaseStrategy):
    strategy_id = "breakout_strength_v1"
    strategy_version = "v1"
    family = "Breakout"
    required_inputs = ["daily_price"]
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = True

    def __init__(self, lookback: int = 20, **kwargs):
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

        highs = [klines[i]["high"] for i in range(start_idx, decision_idx + 1)]
        lows = [klines[i]["low"] for i in range(start_idx, decision_idx + 1)]
        close = klines[decision_idx]["close"]

        if any(h is None or h <= 0 for h in highs) or any(l is None or l <= 0 for l in lows) or close is None or close <= 0:
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

        high_max = max(highs)
        low_min = min(lows)
        range_width = high_max - low_min
        if range_width <= 0:
            raw_score = 0.0
        else:
            raw_score = (close - low_min) / range_width

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


class BreakoutConfirmationStrategy(BaseStrategy):
    strategy_id = "breakout_confirmation_v1"
    strategy_version = "v1"
    family = "Breakout"
    required_inputs = ["daily_price", "daily_volume"]
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = True

    def __init__(self, lookback: int = 20, **kwargs):
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

        highs = [klines[i]["high"] for i in range(start_idx, decision_idx + 1)]
        lows = [klines[i]["low"] for i in range(start_idx, decision_idx + 1)]
        volumes = [klines[i].get("volume") for i in range(start_idx, decision_idx + 1)]
        close = klines[decision_idx]["close"]
        current_volume = klines[decision_idx].get("volume")

        if any(h is None or h <= 0 for h in highs) or any(l is None or l <= 0 for l in lows) or close is None or close <= 0:
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

        high_max = max(highs)
        low_min = min(lows)
        range_width = high_max - low_min
        if range_width <= 0 or current_volume is None or current_volume <= 0:
            raw_score = 0.0
        else:
            price_position = (close - low_min) / range_width
            avg_volume = sum(v for v in volumes if v is not None and v > 0) / max(1, sum(1 for v in volumes if v is not None and v > 0))
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            raw_score = price_position * min(volume_ratio, 2.0)

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
