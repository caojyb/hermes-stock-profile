#!/usr/bin/env python3
"""
stock-work/core/research/market_context/context_schema.py

Market Context Contract schema definitions.

All fields are intentionally explicit so that:
- each field has a source
- each field has time semantics
- each field is replayable
- each field is auditable

This module does NOT perform any data access or DB queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class StructuralState(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class IntermediateState(str, Enum):
    RISK_ON = "RISK_ON"
    NORMAL = "NORMAL"
    RISK_OFF = "RISK_OFF"
    UNKNOWN = "UNKNOWN"


class TacticalState(str, Enum):
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class RiskState(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class TrendState(str, Enum):
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


class VolatilityState(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class LiquidityState(str, Enum):
    TIGHT = "TIGHT"
    NORMAL = "NORMAL"
    AMPLE = "AMPLE"
    UNKNOWN = "UNKNOWN"


class SentimentState(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class MacroState(str, Enum):
    EASY = "EASY"
    NORMAL = "NORMAL"
    TIGHT = "TIGHT"
    CRISIS = "CRISIS"
    UNKNOWN = "UNKNOWN"


class BreadthState(str, Enum):
    BROAD = "BROAD"
    NARROW = "NARROW"
    DETERIORATING = "DETERIORATING"
    UNKNOWN = "UNKNOWN"


@dataclass
class MarketContext:
    """
    PIT-safe market context snapshot.

    Fields are intentionally flat and typed to support:
    - serialization
    - replay determinism
    - auditability
    - no future-data leakage
    """

    context_id: str
    decision_time: str
    data_cutoff: str
    structural_state: StructuralState = StructuralState.UNKNOWN
    intermediate_state: IntermediateState = IntermediateState.UNKNOWN
    tactical_state: TacticalState = TacticalState.UNKNOWN
    risk_state: RiskState = RiskState.UNKNOWN
    market_breadth: BreadthState = BreadthState.UNKNOWN
    trend_state: TrendState = TrendState.UNKNOWN
    volatility_state: VolatilityState = VolatilityState.UNKNOWN
    liquidity_state: LiquidityState = LiquidityState.UNKNOWN
    sentiment_state: SentimentState = SentimentState.UNKNOWN
    macro_state: MacroState = MacroState.UNKNOWN
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "context_id": self.context_id,
            "decision_time": self.decision_time,
            "data_cutoff": self.data_cutoff,
            "structural_state": self.structural_state.value,
            "intermediate_state": self.intermediate_state.value,
            "tactical_state": self.tactical_state.value,
            "risk_state": self.risk_state.value,
            "market_breadth": self.market_breadth.value,
            "trend_state": self.trend_state.value,
            "volatility_state": self.volatility_state.value,
            "liquidity_state": self.liquidity_state.value,
            "sentiment_state": self.sentiment_state.value,
            "macro_state": self.macro_state.value,
            "confidence": self.confidence.value,
            "provenance": self.provenance,
        }
