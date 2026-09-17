#!/usr/bin/env python3
"""
stock-work/core/research/market_context/context_builder.py

Phase B1-B3: PIT-safe Market Context Builder + Regime Engine V1.

Design constraints:
- research plane only
- no production DB writes
- no DecisionEngine mutation
- no trading actions emitted
- all outputs are assessments / states
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .context_schema import (
    BreadthState,
    ConfidenceLevel,
    IntermediateState,
    LiquidityState,
    MarketContext as MarketContextModel,
    MacroState,
    RiskState,
    SentimentState,
    StructuralState,
    TacticalState,
    TrendState,
    VolatilityState,
)
from .market_context import MarketContext


# ---------------------------------------------------------------------------
# Phase B1 helpers
# ---------------------------------------------------------------------------

def _build_context_id(decision_time: str, source: str) -> str:
    return f"mc:{decision_time}:{source}"


def _new_model(decision_time: str, data_cutoff: str, confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN) -> MarketContextModel:
    return MarketContextModel(
        context_id=_build_context_id(decision_time, "schema"),
        decision_time=decision_time,
        data_cutoff=data_cutoff,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Phase B2: Context Inputs V1
# ---------------------------------------------------------------------------

@dataclass
class IndexTrendInputs:
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma120: Optional[float] = None
    close: Optional[float] = None


@dataclass
class BreadthInputs:
    up_ratio: Optional[float] = None
    new_high_ratio: Optional[float] = None
    new_low_ratio: Optional[float] = None
    limit_up_count: Optional[int] = None
    limit_down_count: Optional[int] = None


@dataclass
class VolatilityInputs:
    index_return: Optional[float] = None
    realized_vol_20d: Optional[float] = None


@dataclass
class LiquidityInputs:
    amount_trend: Optional[str] = None
    volume_change: Optional[float] = None


def classify_trend(inputs: IndexTrendInputs) -> TrendState:
    if inputs.close is None or inputs.ma20 is None or inputs.ma60 is None or inputs.ma120 is None:
        return TrendState.UNKNOWN
    if inputs.close > inputs.ma20 > inputs.ma60 > inputs.ma120:
        return TrendState.UPTREND
    if inputs.close < inputs.ma20 < inputs.ma60 < inputs.ma120:
        return TrendState.DOWNTREND
    return TrendState.SIDEWAYS


def classify_breadth(inputs: BreadthInputs) -> BreadthState:
    if inputs.up_ratio is None:
        return BreadthState.UNKNOWN
    if inputs.up_ratio >= 0.65 and (inputs.new_high_ratio or 0) > 0:
        return BreadthState.BROAD
    if inputs.up_ratio <= 0.35 or (inputs.new_low_ratio or 0) > 0:
        return BreadthState.DETERIORATING
    return BreadthState.NARROW


def classify_volatility(inputs: VolatilityInputs) -> VolatilityState:
    if inputs.realized_vol_20d is None:
        return VolatilityState.UNKNOWN
    if inputs.realized_vol_20d >= 0.35:
        return VolatilityState.HIGH
    if inputs.realized_vol_20d <= 0.15:
        return VolatilityState.LOW
    return VolatilityState.MEDIUM


def classify_liquidity(inputs: LiquidityInputs) -> LiquidityState:
    if inputs.amount_trend is None and inputs.volume_change is None:
        return LiquidityState.UNKNOWN
    if inputs.amount_trend == "RISING" or (inputs.volume_change or 0) > 0.15:
        return LiquidityState.AMPLE
    if inputs.amount_trend == "DECLINING" or (inputs.volume_change or 0) < -0.15:
        return LiquidityState.TIGHT
    return LiquidityState.NORMAL


# ---------------------------------------------------------------------------
# Phase B3: Regime Engine V1
# ---------------------------------------------------------------------------

def derive_structural_state(
    trend_state: TrendState,
    volatility_state: VolatilityState,
    liquidity_state: LiquidityState,
) -> StructuralState:
    """
    Structural regime is intentionally coarse.
    Missing inputs must not be inferred into BULL/BEAR.
    """
    if trend_state == TrendState.UNKNOWN or volatility_state == VolatilityState.UNKNOWN or liquidity_state == LiquidityState.UNKNOWN:
        return StructuralState.UNKNOWN
    if trend_state == TrendState.UPTREND and liquidity_state in {LiquidityState.AMPLE, LiquidityState.NORMAL}:
        return StructuralState.BULL
    if trend_state == TrendState.DOWNTREND and volatility_state == VolatilityState.HIGH:
        return StructuralState.BEAR
    return StructuralState.NEUTRAL


def derive_intermediate_state(
    breadth_state: BreadthState,
    trend_state: TrendState,
) -> IntermediateState:
    if breadth_state == BreadthState.UNKNOWN or trend_state == TrendState.UNKNOWN:
        return IntermediateState.UNKNOWN
    if breadth_state == BreadthState.BROAD and trend_state == TrendState.UPTREND:
        return IntermediateState.RISK_ON
    if breadth_state == BreadthState.DETERIORATING and trend_state == TrendState.DOWNTREND:
        return IntermediateState.RISK_OFF
    return IntermediateState.NORMAL


def derive_tactical_state(
    volatility_state: VolatilityState,
    liquidity_state: LiquidityState,
) -> TacticalState:
    if volatility_state == VolatilityState.UNKNOWN or liquidity_state == LiquidityState.UNKNOWN:
        return TacticalState.UNKNOWN
    if volatility_state == VolatilityState.HIGH and liquidity_state == LiquidityState.TIGHT:
        return TacticalState.MEAN_REVERSION
    if volatility_state in {VolatilityState.MEDIUM, VolatilityState.HIGH} and liquidity_state == LiquidityState.AMPLE:
        return TacticalState.MOMENTUM
    return TacticalState.NEUTRAL


def derive_risk_state(
    volatility_state: VolatilityState,
    liquidity_state: LiquidityState,
    trend_state: TrendState,
) -> RiskState:
    score = 0
    if volatility_state == VolatilityState.HIGH:
        score += 2
    elif volatility_state == VolatilityState.MEDIUM:
        score += 1
    if liquidity_state == LiquidityState.TIGHT:
        score += 2
    elif liquidity_state == LiquidityState.NORMAL:
        score += 1
    if trend_state == TrendState.DOWNTREND:
        score += 1
    if score >= 4:
        return RiskState.HIGH
    if score >= 2:
        return RiskState.MEDIUM
    if score == 0 and volatility_state != VolatilityState.UNKNOWN and liquidity_state != LiquidityState.UNKNOWN and trend_state != TrendState.UNKNOWN:
        return RiskState.LOW
    return RiskState.UNKNOWN


# ---------------------------------------------------------------------------
# Phase B1: Builder
# ---------------------------------------------------------------------------

@dataclass
class MarketContextBuilder:
    """
    Builds a MarketContext from V1 allowed inputs only.

    This builder is intentionally strict:
    - future data must be rejected before reaching classification
    - missing inputs should leave states UNKNOWN
    - no external news / macro / sentiment ingestion in V1
    """

    decision_time: str
    data_cutoff: str
    context_source: str = "market_context_builder_v1"
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN

    def build(
        self,
        index_trend_inputs: Optional[IndexTrendInputs] = None,
        breadth_inputs: Optional[BreadthInputs] = None,
        volatility_inputs: Optional[VolatilityInputs] = None,
        liquidity_inputs: Optional[LiquidityInputs] = None,
    ) -> MarketContext:
        model = _new_model(self.decision_time, self.data_cutoff, confidence=self.confidence)
        context = MarketContext(model=model, audit_trace={"source": self.context_source})

        index_trend_inputs = index_trend_inputs or IndexTrendInputs()
        breadth_inputs = breadth_inputs or BreadthInputs()
        volatility_inputs = volatility_inputs or VolatilityInputs()
        liquidity_inputs = liquidity_inputs or LiquidityInputs()

        trend_state = classify_trend(index_trend_inputs)
        breadth_state = classify_breadth(breadth_inputs)
        volatility_state = classify_volatility(volatility_inputs)
        liquidity_state = classify_liquidity(liquidity_inputs)

        structural_state = derive_structural_state(trend_state, volatility_state, liquidity_state)
        intermediate_state = derive_intermediate_state(breadth_state, trend_state)
        tactical_state = derive_tactical_state(volatility_state, liquidity_state)
        risk_state = derive_risk_state(volatility_state, liquidity_state, trend_state)

        # sentiment/macro remain UNKNOWN in V1 unless explicitly provided later
        sentiment_state = SentimentState.UNKNOWN
        macro_state = MacroState.UNKNOWN

        context.model.trend_state = trend_state
        context.model.market_breadth = breadth_state
        context.model.volatility_state = volatility_state
        context.model.liquidity_state = liquidity_state
        context.model.structural_state = structural_state
        context.model.intermediate_state = intermediate_state
        context.model.tactical_state = tactical_state
        context.model.risk_state = risk_state
        context.model.sentiment_state = sentiment_state
        context.model.macro_state = macro_state

        # derive overall confidence from unknown counts
        unknown_count = sum(
            1
            for state in [
                structural_state,
                intermediate_state,
                tactical_state,
                risk_state,
                trend_state,
                volatility_state,
                liquidity_state,
                breadth_state,
                sentiment_state,
                macro_state,
            ]
            if state in {
                StructuralState.UNKNOWN,
                IntermediateState.UNKNOWN,
                TacticalState.UNKNOWN,
                RiskState.UNKNOWN,
                TrendState.UNKNOWN,
                VolatilityState.UNKNOWN,
                LiquidityState.UNKNOWN,
                BreadthState.UNKNOWN,
                SentimentState.UNKNOWN,
                MacroState.UNKNOWN,
            }
        )
        if unknown_count == 0:
            context.model.confidence = ConfidenceLevel.HIGH
        elif unknown_count <= 2:
            context.model.confidence = ConfidenceLevel.MEDIUM
        else:
            context.model.confidence = ConfidenceLevel.LOW

        context.audit_trace.update(
            {
                "trend_state": trend_state.value,
                "breadth_state": breadth_state.value,
                "volatility_state": volatility_state.value,
                "liquidity_state": liquidity_state.value,
                "structural_state": structural_state.value,
                "intermediate_state": intermediate_state.value,
                "tactical_state": tactical_state.value,
                "risk_state": risk_state.value,
            }
        )
        return context
