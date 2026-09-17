#!/usr/bin/env python3
"""
volatility_strategy.py — Volatility Strategy Family
====================================================
Research hypothesis: "Whether historical volatility and volatility changes
have cross-sectional excess-return predictive power."

Note: This does NOT assume low volatility = better stock.
The hypothesis is empirical: volatility may predict returns positively,
negatively, or not at all.

Variants:
- volatility_level_v1: Historical volatility level
- volatility_change_v1: Volatility change/acceleration

PIT-safe inputs: daily_price
Required EOD policy: Yes
"""

from __future__ import annotations

from typing import List, Optional

from ..base_strategy import BaseStrategy, Signal


class VolatilityLevelStrategy(BaseStrategy):
    strategy_id = "volatility_level_v1"
    strategy_version = "v1"
    family = "Volatility"
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

        returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        vol = variance ** 0.5

        raw_score = vol
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


class VolatilityChangeStrategy(BaseStrategy):
    strategy_id = "volatility_change_v1"
    strategy_version = "v1"
    family = "Volatility"
    required_inputs = ["daily_price"]
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = True

    def __init__(self, lookback_short: int = 10, lookback_long: int = 30, **kwargs):
        super().__init__(**kwargs)
        self.lookback_short = lookback_short
        self.lookback_long = lookback_long

    def generate_signal(self, stock: dict, decision_time: str,
                        context: dict = None) -> Optional[Signal]:
        symbol = stock.get("code") or stock.get("symbol")
        if not symbol or self.kline_loader is None:
            return None

        try:
            klines = self.kline_loader(symbol, "", "")
        except Exception:
            return None

        if not klines or len(klines) < self.lookback_long + 1:
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

        def _vol_for_range(end_idx: int, lookback: int):
            start_idx = end_idx - lookback + 1
            if start_idx < 0:
                return None
            closes = [klines[i]["close"] for i in range(start_idx, end_idx + 1)]
            if any(c is None or c <= 0 for c in closes):
                return None
            returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            return variance ** 0.5

        short_vol = _vol_for_range(decision_idx, self.lookback_short)
        long_vol = _vol_for_range(decision_idx, self.lookback_long)

        if short_vol is None or long_vol is None or long_vol == 0:
            raw_score = 0.0
        else:
            raw_score = short_vol / long_vol - 1.0

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
