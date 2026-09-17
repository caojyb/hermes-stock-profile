#!/usr/bin/env python3
"""
base_strategy.py — Base Strategy Interface
==========================================
Defines the unified strategy interface for the Strategy Research Pilot.

All strategies must inherit from BaseStrategy and implement generate_signal().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Signal:
    """Strategy signal output."""
    stock_code: str
    decision_time: str
    strategy_id: str
    strategy_version: str
    raw_score: float
    normalized_score: Optional[float]
    eligibility: bool
    reason_code: str
    horizon: int = 5
    family: str = "unknown"
    confidence: Optional[float] = None
    metadata: dict = field(default_factory=dict)


class BaseStrategy(ABC):
    """Base class for all research strategies."""

    strategy_id: str = "base"
    strategy_version: str = "v0"
    family: str = "unknown"
    required_inputs: List[str] = []
    horizon: int = 5
    decision_time_policy: str = "T_END_OF_DAY"

    def __init__(self, universe_fetcher=None, kline_loader=None,
                 normalization_layer=None, reference_benchmark=None):
        self.universe_fetcher = universe_fetcher
        self.kline_loader = kline_loader
        self.normalization_layer = normalization_layer
        self.reference_benchmark = reference_benchmark

    @abstractmethod
    def generate_signal(self, stock: dict, decision_time: str,
                        context: dict = None) -> Optional[Signal]:
        """Generate a signal for a single stock at decision_time."""

    def run(self, universe: List[dict], decision_time: str,
            context: dict = None) -> List[Signal]:
        """Run strategy over universe at decision_time."""
        signals = []
        for stock in universe:
            symbol = stock.get("code") or stock.get("symbol")
            if not symbol:
                continue
            signal = self.generate_signal(stock, decision_time, context)
            if signal is not None:
                signals.append(signal)
        # Apply normalization if available
        if self.normalization_layer is not None and signals:
            signals = self.normalization_layer.normalize(signals)
        return signals
