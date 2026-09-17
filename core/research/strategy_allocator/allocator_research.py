#!/usr/bin/env python3
"""
stock-work/core/research/strategy_allocator/allocator_research.py

Phase C3: Allocator Research Model.

Combines:
- Market Context regime compatibility
- Strategy Evidence Matrix performance data
- Risk state

Outputs descriptive allocation recommendations.
No trading actions. No weights. No automatic modifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from core.research.market_context.market_context import MarketContext
from core.research.market_context.context_schema import (
    IntermediateState,
    RiskState,
    StructuralState,
    TacticalState,
)
from core.research.market_context.strategy_context_analysis import CompatibilityAssessment, StrategyContextAnalyzer
from core.research.strategy_allocator.strategy_evidence_matrix import EvidenceMatrixCell, StrategyEvidenceMatrix


@dataclass(frozen=True)
class StrategyAllocationRecommendation:
    strategy_id: str
    compatibility_score: str
    evidence_score: str
    risk_score: str
    confidence: str
    rationale: str
    regime_state: str
    evidence_status: str


class AllocatorResearch:
    """
    Research-only allocator.

    Inputs:
    - market_context: current market context
    - evidence_matrix: strategy evidence matrix
    - registry: strategy registry (for compatibility analysis)

    Outputs:
    - list of StrategyAllocationRecommendation
    """

    def __init__(
        self,
        registry,
        evidence_matrix: StrategyEvidenceMatrix,
    ) -> None:
        self.registry = registry
        self.evidence_matrix = evidence_matrix
        self.context_analyzer = StrategyContextAnalyzer(registry)

    def recommend(self, context: MarketContext) -> List[StrategyAllocationRecommendation]:
        if context.action_safe():
            raise ValueError("MarketContext must be research-only; action_safe must be False")

        compatibility_assessments = {
            a.strategy_id: a
            for a in self.context_analyzer.assess_all(context)
        }
        evidence_cells = self.evidence_matrix.build()
        evidence_map: Dict[str, List[EvidenceMatrixCell]] = {}
        for cell in evidence_cells:
            evidence_map.setdefault(cell.strategy_id, []).append(cell)

        recommendations: List[StrategyAllocationRecommendation] = []
        for profile in self.registry.all_profiles():
            strategy_id = profile.strategy_id
            compatibility = compatibility_assessments.get(strategy_id)
            if compatibility is None:
                continue

            evidence_score = self._derive_evidence_score(strategy_id, evidence_map.get(strategy_id, []))
            risk_score = self._derive_risk_score(context, profile)
            overall_confidence = self._derive_confidence(compatibility.confidence, evidence_score)

            rationale_parts = []
            if compatibility.regime_match_score != "HIGH":
                rationale_parts.append(compatibility.reason)
            if evidence_score == "LOW":
                rationale_parts.append("insufficient historical evidence")
            if risk_score == "ELEVATED":
                rationale_parts.append("elevated risk regime")
            rationale = "; ".join(rationale_parts) if rationale_parts else "no major compatibility or evidence concerns"

            evidence_status = "NO_DATA"
            for cell in evidence_map.get(strategy_id, []):
                if cell.status in {"EVIDENCE", "PRELIMINARY"}:
                    evidence_status = cell.status
                    break

            recommendations.append(
                StrategyAllocationRecommendation(
                    strategy_id=strategy_id,
                    compatibility_score=compatibility.regime_match_score,
                    evidence_score=evidence_score,
                    risk_score=risk_score,
                    confidence=overall_confidence,
                    rationale=rationale,
                    regime_state=context.model.risk_state.value,
                    evidence_status=evidence_status,
                )
            )
        return recommendations

    def _derive_evidence_score(self, strategy_id: str, cells: List[EvidenceMatrixCell]) -> str:
        if not cells:
            return "UNKNOWN"
        statuses = {c.status for c in cells}
        if "NO_DATA" in statuses and len(statuses) == 1:
            return "UNKNOWN"
        if "PRELIMINARY" in statuses:
            return "LOW"
        return "MEDIUM"

    def _derive_risk_score(self, context: MarketContext, profile) -> str:
        risk = context.model.risk_state.value
        if risk == RiskState.HIGH.value:
            return "ELEVATED"
        if risk == RiskState.MEDIUM.value:
            return "MODERATE"
        if risk == RiskState.LOW.value:
            return "NORMAL"
        return "UNKNOWN"

    def _derive_confidence(self, compatibility_confidence: str, evidence_score: str) -> str:
        if compatibility_confidence == "LOW" or evidence_score == "UNKNOWN":
            return "LOW"
        if compatibility_confidence == "MEDIUM" and evidence_score == "LOW":
            return "LOW"
        return "MEDIUM"
