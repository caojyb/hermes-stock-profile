#!/usr/bin/env python3
"""
price_volume_strategy.py — Price-Volume Strategy Family
========================================================
Research hypothesis: "Whether price-volume interaction has cross-sectional
excess-return predictive power."

Variants:
- volume_trend_v1: Volume expansion/contraction trend
- volume_price_correlation_v1: Recent price-volume correlation / co-movement

PIT-safe inputs: daily_price, daily_volume
Required EOD policy: Yes
"""

from __future__ import annotations

from typing import List, Optional

from ..base_strategy import BaseStrategy, Signal


class VolumeTrendStrategy(BaseStrategy):
    strategy_id = "volume_trend_v1"
    strategy_version = "v1"
    family = "PriceVolume"
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

        closes = [klines[i]["close"] for i in range(start_idx, decision_idx + 1)]
        volumes = [klines[i].get("volume") for i in range(start_idx, decision_idx + 1)]

        if any(c is None or c <= 0 for c in closes) or any(v is None or v <= 0 for v in volumes):
            return Signal(
                stock_code=symbol,
                decision_time=decision_time,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                raw_score=0.0,
                normalized_score=None,
                eligibility=False,
                reason_code="INVALID_PRICE_OR_VOLUME",
                horizon=self.horizon,
                family=self.family,
            )

        price_change = closes[-1] / closes[0] - 1.0
        volume_change = volumes[-1] / volumes[0] - 1.0

        raw_score = price_change * volume_change
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


class VolumePriceCorrelationStrategy(BaseStrategy):
    strategy_id = "volume_price_correlation_v1"
    strategy_version = "v1"
    family = "PriceVolume"
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

        closes = [klines[i]["close"] for i in range(start_idx, decision_idx + 1)]
        volumes = [klines[i].get("volume") for i in range(start_idx, decision_idx + 1)]

        if any(c is None or c <= 0 for c in closes) or any(v is None or v <= 0 for v in volumes):
            return Signal(
                stock_code=symbol,
                decision_time=decision_time,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                raw_score=0.0,
                normalized_score=None,
                eligibility=False,
                reason_code="INVALID_PRICE_OR_VOLUME",
                horizon=self.horizon,
                family=self.family,
            )

        price_changes = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
        volume_changes = [volumes[i] / volumes[i - 1] - 1.0 for i in range(1, len(volumes))]

        mean_p = sum(price_changes) / len(price_changes)
        mean_v = sum(volume_changes) / len(volume_changes)
        cov = sum((p - mean_p) * (v - mean_v) for p, v in zip(price_changes, volume_changes)) / len(price_changes)
        var_p = sum((p - mean_p) ** 2 for p in price_changes) / len(price_changes)
        var_v = sum((v - mean_v) ** 2 for v in volume_changes) / len(volume_changes)

        if var_p <= 0 or var_v <= 0:
            raw_score = 0.0
        else:
            raw_score = cov / (var_p ** 0.5 * var_v ** 0.5)

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
