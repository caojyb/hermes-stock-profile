#!/usr/bin/env python3
"""
stock-work/core/research/market_context/strategy_context_analysis.py

Phase B5: Strategy <-> Market Context compatibility analysis.

Outputs research-only compatibility assessments.
No trading actions, weights, or order instructions are produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from core.research.market_context.context_schema import (
    ConfidenceLevel,
    IntermediateState,
    LiquidityState,
    MacroState,
    RiskState,
    StructuralState,
    TacticalState,
    VolatilityState,
)
from core.research.market_context.market_context import MarketContext
from core.research.strategy_registry.strategy_registry import StrategyProfile


@dataclass(frozen=True)
class CompatibilityAssessment:
    strategy_id: str
    regime_match_score: str
    risk_adjustment: str
    confidence: str
    reason: str


class StrategyContextAnalyzer:
    """
    Computes compatibility between a strategy profile and current market context.

    Important:
    - this is research only
    - outputs are assessments, not orders
    - confidence is conservative when inputs are missing
    """

    def __init__(self, registry) -> None:
        self.registry = registry

    def assess(self, context: MarketContext, strategy_id: str) -> Optional[CompatibilityAssessment]:
        profile = self.registry.get(strategy_id)
        if profile is None:
            return None

        preferred = profile.preferred_regime
        forbidden = profile.forbidden_regime

        reasons: List[str] = []
        confidence = "MEDIUM"
        mismatch_count = 0

        # structural check
        structural = context.model.structural_state.value
        if "structural" in preferred and preferred["structural"] != structural:
            reasons.append(f"preferred_structural={preferred['structural']} actual={structural}")
            mismatch_count += 1
        if "structural" in forbidden and forbidden["structural"] == structural:
            reasons.append(f"forbidden_structural={structural}")
            mismatch_count += 1

        # intermediate check
        intermediate = context.model.intermediate_state.value
        if "intermediate" in preferred and preferred["intermediate"] != intermediate:
            reasons.append(f"preferred_intermediate={preferred['intermediate']} actual={intermediate}")
            mismatch_count += 1
        if "intermediate" in forbidden and forbidden["intermediate"] == intermediate:
            reasons.append(f"forbidden_intermediate={intermediate}")
            mismatch_count += 1

        # tactical check
        tactical = context.model.tactical_state.value
        if "tactical" in preferred and preferred["tactical"] != tactical:
            reasons.append(f"preferred_tactical={preferred['tactical']} actual={tactical}")
            mismatch_count += 1
        if "tactical" in forbidden and forbidden["tactical"] == tactical:
            reasons.append(f"forbidden_tactical={tactical}")
            mismatch_count += 1

        # risk_state check
        risk = context.model.risk_state.value
        if "risk_state" in preferred and preferred["risk_state"] != risk:
            reasons.append(f"preferred_risk_state={preferred['risk_state']} actual={risk}")
            mismatch_count += 1
        if "risk_state" in forbidden and forbidden["risk_state"] == risk:
            reasons.append(f"forbidden_risk_state={risk}")
            mismatch_count += 1

        # liquidity check
        liquidity = context.model.liquidity_state.value
        if "liquidity_state" in preferred and preferred["liquidity_state"] != liquidity:
            reasons.append(f"preferred_liquidity={preferred['liquidity_state']} actual={liquidity}")
            mismatch_count += 1
        if "liquidity_state" in forbidden and forbidden["liquidity_state"] == liquidity:
            reasons.append(f"forbidden_liquidity={liquidity}")
            mismatch_count += 1

        if mismatch_count == 0:
            regime_match_score = "HIGH"
            risk_adjustment = "NORMAL"
        elif mismatch_count <= 2:
            regime_match_score = "MEDIUM"
            risk_adjustment = "CAUTION"
        else:
            regime_match_score = "LOW"
            risk_adjustment = "ELEVATED"

        if context.model.confidence == ConfidenceLevel.UNKNOWN:
            confidence = "LOW"
        elif context.model.confidence == ConfidenceLevel.LOW:
            confidence = "LOW"
        elif confidence != "LOW":
            confidence = "MEDIUM"

        if not reasons:
            reason = "No preferred/forbidden regime mismatches detected."
        else:
            reason = "; ".join(reasons)

        return CompatibilityAssessment(
            strategy_id=strategy_id,
            regime_match_score=regime_match_score,
            risk_adjustment=risk_adjustment,
            confidence=confidence,
            reason=reason,
        )

    def assess_all(self, context: MarketContext) -> List[CompatibilityAssessment]:
        results: List[CompatibilityAssessment] = []
        for profile in self.registry.all_profiles():
            assessment = self.assess(context, profile.strategy_id)
            if assessment is not None:
                results.append(assessment)
        return results
