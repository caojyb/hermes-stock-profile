#!/usr/bin/env python3
"""
momentum_strategy_variants.py — Momentum Family Variants
=========================================================
Medium-term momentum and risk-adjusted momentum.

Variants:
- momentum_medium_v1: 60-day momentum
- momentum_risk_adjusted_v1: momentum divided by volatility
"""

from __future__ import annotations

from typing import List, Optional

from ..base_strategy import BaseStrategy, Signal


class MomentumMediumStrategy(BaseStrategy):
    strategy_id = "momentum_medium_v1"
    strategy_version = "v1"
    family = "Momentum"
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

        raw_score = price_t / price_t_lookback - 1.0
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


class MomentumRiskAdjustedStrategy(BaseStrategy):
    strategy_id = "momentum_risk_adjusted_v1"
    strategy_version = "v1"
    family = "Momentum"
    required_inputs = ["daily_price"]
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = True

    def __init__(self, lookback: int = 60, vol_lookback: int = 20, **kwargs):
        super().__init__(**kwargs)
        self.lookback = lookback
        self.vol_lookback = vol_lookback

    def generate_signal(self, stock: dict, decision_time: str,
                        context: dict = None) -> Optional[Signal]:
        symbol = stock.get("code") or stock.get("symbol")
        if not symbol or self.kline_loader is None:
            return None

        try:
            klines = self.kline_loader(symbol, "", "")
        except Exception:
            return None

        if not klines or len(klines) <= max(self.lookback, self.vol_lookback):
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

        momentum = price_t / price_t_lookback - 1.0

        vol_start = decision_idx - self.vol_lookback + 1
        if vol_start < 0:
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

        closes = [klines[i]["close"] for i in range(vol_start, decision_idx + 1)]
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
        vol = max(vol, 1e-12)

        raw_score = momentum / vol
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
