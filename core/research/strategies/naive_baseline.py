#!/usr/bin/env python3
"""
naive_baseline.py — Naive Baseline Strategy
=============================================
Provides the most basic research baseline: equal-weight random or uniform signal.
Used as a no-skill benchmark for strategy evaluation.
"""

from __future__ import annotations

import random
from typing import List, Optional

from ..base_strategy import BaseStrategy, Signal


class NaiveBaselineStrategy(BaseStrategy):
    strategy_id = "naive_baseline_v1"
    strategy_version = "v1"
    family = "Baseline"
    required_inputs = []
    horizon = 5
    decision_time_policy = "T_END_OF_DAY"
    requires_eod_policy = False

    def __init__(self, seed: int = 42, **kwargs):
        super().__init__(**kwargs)
        self.seed = seed
        self._rng = random.Random(seed)

    def generate_signal(self, stock: dict, decision_time: str,
                        context: dict = None) -> Optional[Signal]:
        symbol = stock.get("code") or stock.get("symbol")
        if not symbol:
            return None

        # Uniform random score in [-0.5, 0.5] as no-skill baseline
        raw_score = self._rng.uniform(-0.5, 0.5)

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
