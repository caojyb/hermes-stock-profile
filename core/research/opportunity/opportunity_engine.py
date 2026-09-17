#!/usr/bin/env python3
"""
stock-work/core/research/opportunity/opportunity_engine.py

Phase D8-D: Stock Opportunity Engine.

Inputs:
- MarketContext
- eligible strategies
- current universe signals
- historical evidence
- normalization results

Outputs:
- ranked research opportunity list

Hard constraints:
- no BUY/SELL/ADD/REDUCE/EXIT/POSITION_SIZE
- no production writes
- no DecisionEngine connection
- PIT-safe only
- deterministic and versioned
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.research.market_context.context_schema import RiskState
from core.research.market_context.market_context import MarketContext
from core.research.market_context.strategy_context_analysis import CompatibilityAssessment, StrategyContextAnalyzer
from core.research.opportunity.opportunity_schema import (
    Eligibility,
    Opportunity,
    OpportunityScoreComponents,
    StrategyEvidenceSummary,
    StrategySignalSummary,
)
from core.research.strategy_allocator.strategy_evidence_matrix import StrategyEvidenceMatrix
from core.research.strategy_registry.strategy_registry import StrategyRegistry


@dataclass(frozen=True)
class OpportunityEngineConfig:
    normalization_version: str = "v1"
    opportunity_version: str = "v1"
    top_n: int = 20
    unknown_penalty: float = 0.0
    research_only_penalty: float = 0.0
    correlation_penalty: float = 0.0
    min_signal_confidence: str = "LOW"


class OpportunityEngine:
    """
    Research-only opportunity engine.

    Produces candidate pool from current market context, eligible strategies,
    current signals, historical evidence, and risk/data-quality adjustments.
    """

    def __init__(
        self,
        registry: StrategyRegistry,
        evidence_matrix: StrategyEvidenceMatrix,
        config: Optional[OpportunityEngineConfig] = None,
    ) -> None:
        self.registry = registry
        self.evidence_matrix = evidence_matrix
        self.config = config or OpportunityEngineConfig()
        self.context_analyzer = StrategyContextAnalyzer(registry)

    def build_opportunities(
        self,
        context: MarketContext,
        universe_signals: Dict[str, List[StrategySignalSummary]],
        evidence_by_strategy: Dict[str, StrategyEvidenceSummary],
        data_quality_by_stock: Dict[str, str],
        family_correlation_penalty: Optional[Dict[str, float]] = None,
    ) -> List[Opportunity]:
        if context.action_safe():
            raise ValueError("MarketContext must be research-only; action_safe must be False")

        compatibility_map = {a.strategy_id: a for a in self.context_analyzer.assess_all(context)}
        opportunities: List[Opportunity] = []

        for stock_code, signals in universe_signals.items():
            if not signals:
                continue

            eligible_signals = [s for s in signals if self._is_signal_eligible(s, evidence_by_strategy.get(s.strategy_id))]
            if not eligible_signals:
                continue

            strategy_ids = [s.strategy_id for s in eligible_signals]
            strategy_versions = {s.strategy_id: s.strategy_version for s in eligible_signals}

            context_compatibility = self._aggregate_context_compatibility(compatibility_map, strategy_ids)
            signal_strength = self._aggregate_signal_strength(eligible_signals)
            signal_confidence = self._aggregate_signal_confidence(eligible_signals)
            risk_penalty = self._compute_risk_penalty(context)
            data_quality = data_quality_by_stock.get(stock_code, "UNKNOWN")
            data_quality_score = self._map_data_quality_to_score(data_quality)
            correlation_penalty = self._aggregate_correlation_penalty(eligible_signals, family_correlation_penalty)
            evidence_component = self._aggregate_evidence_score(eligible_signals, evidence_by_strategy)

            score_components = OpportunityScoreComponents(
                historical_evidence=evidence_component,
                context_compatibility=context_compatibility,
                signal_strength=signal_strength,
                signal_confidence=signal_confidence,
                risk_penalty=risk_penalty,
                data_quality=data_quality_score,
                correlation_penalty=correlation_penalty,
                notes="deterministic composite score",
            )

            opportunity_score = self._compute_opportunity_score(score_components)
            eligibility = self._determine_eligibility(opportunity_score, signal_confidence, data_quality, risk_penalty)
            reason_codes = self._build_reason_codes(
                eligible_signals=eligible_signals,
                compatibility_map=compatibility_map,
                context_compatibility=context_compatibility,
                risk_penalty=risk_penalty,
                data_quality=data_quality,
                eligibility=eligibility,
            )

            opportunity = Opportunity(
                stock_code=stock_code,
                decision_time=context.model.decision_time,
                market_context_id=context.model.context_id,
                strategy_ids=strategy_ids,
                strategy_versions=strategy_versions,
                strategy_signal_summary=eligible_signals,
                strategy_evidence_summary=[evidence_by_strategy[sid] for sid in strategy_ids if sid in evidence_by_strategy],
                context_compatibility=self._score_to_label(context_compatibility),
                signal_strength=signal_strength,
                signal_confidence=signal_confidence,
                risk_penalty=risk_penalty,
                data_quality=data_quality,
                opportunity_score=opportunity_score,
                rank=None,
                eligibility=eligibility,
                reason_codes=reason_codes,
                score_components=score_components,
                provenance=self._build_provenance(context, eligible_signals),
                research_only=True,
                notes="opportunity engine v1 research output",
            )
            opportunities.append(opportunity)

        ranked = self._rank_opportunities(opportunities)
        return ranked

    def _is_signal_eligible(self, signal: StrategySignalSummary, evidence: Optional[StrategyEvidenceSummary]) -> bool:
        if signal.research_only:
            return True
        if evidence is None:
            return False
        if evidence.qualification_status in {"BLOCKED", "FAILED"}:
            return False
        return True

    def _aggregate_context_compatibility(self, compatibility_map: Dict[str, CompatibilityAssessment], strategy_ids: List[str]) -> Optional[float]:
        scores = []
        for sid in strategy_ids:
            assessment = compatibility_map.get(sid)
            if assessment is None:
                continue
            scores.append(self._compatibility_score_to_float(assessment.regime_match_score))
        if not scores:
            return None
        return sum(scores) / len(scores)

    def _aggregate_signal_strength(self, signals: List[StrategySignalSummary]) -> Optional[float]:
        values = [s.normalized_score for s in signals if s.normalized_score is not None]
        if not values:
            return None
        return sum(values) / len(values)

    def _aggregate_signal_confidence(self, signals: List[StrategySignalSummary]) -> str:
        confidences = [s.confidence for s in signals]
        if not confidences:
            return "UNKNOWN"
        if any(c == "UNKNOWN" for c in confidences):
            return "UNKNOWN"
        if any(c == "LOW" for c in confidences):
            return "LOW"
        if all(c == "HIGH" for c in confidences):
            return "HIGH"
        return "MEDIUM"

    def _aggregate_evidence_score(self, signals: List[StrategySignalSummary], evidence_by_strategy: Dict[str, StrategyEvidenceSummary]) -> Optional[float]:
        scores = []
        for s in signals:
            ev = evidence_by_strategy.get(s.strategy_id)
            if ev is None:
                if s.research_only:
                    scores.append(0.2)
                continue
            scores.append(self._evidence_strength_to_float(ev.evidence_strength))
        if not scores:
            return None
        return sum(scores) / len(scores)

    def _aggregate_correlation_penalty(self, signals: List[StrategySignalSummary], family_correlation_penalty: Optional[Dict[str, float]]) -> Optional[float]:
        if family_correlation_penalty is None:
            return None
        penalties = [family_correlation_penalty.get(s.family, 0.0) for s in signals if hasattr(s, "family")]
        if not penalties:
            return None
        return sum(penalties) / len(penalties)

    def _compute_risk_penalty(self, context: MarketContext) -> Optional[float]:
        mapping = {
            RiskState.LOW.value: 0.0,
            RiskState.MEDIUM.value: 0.1,
            RiskState.HIGH.value: 0.25,
            RiskState.UNKNOWN.value: None,
        }
        return mapping.get(context.model.risk_state.value)

    def _map_data_quality_to_score(self, data_quality: str) -> str:
        mapping = {
            "OK": "OK",
            "DEGRADED": "DEGRADED",
            "BROKEN": "BROKEN",
            "UNKNOWN": "UNKNOWN",
        }
        return mapping.get(data_quality, "UNKNOWN")

    def _compute_opportunity_score(self, components: OpportunityScoreComponents) -> Optional[float]:
        required = [
            components.historical_evidence,
            components.context_compatibility,
            components.signal_strength,
            components.signal_confidence,
            components.data_quality,
        ]
        if any(v is None for v in required):
            return None
        if components.data_quality != "OK":
            return None
        score = 0.0
        score += 0.25 * components.historical_evidence
        score += 0.20 * components.context_compatibility
        score += 0.25 * components.signal_strength
        confidence_component = {"HIGH": 1.0, "MEDIUM": 0.7, "LOW": 0.4, "UNKNOWN": 0.0}.get(components.signal_confidence, 0.0)
        score += 0.15 * confidence_component
        risk = components.risk_penalty if components.risk_penalty is not None else 0.0
        score -= 0.15 * risk
        if components.correlation_penalty is not None:
            score -= 0.10 * components.correlation_penalty
        return max(0.0, min(1.0, score))

    def _determine_eligibility(
        self,
        opportunity_score: Optional[float],
        signal_confidence: str,
        data_quality: str,
        risk_penalty: Optional[float],
    ) -> Eligibility:
        if opportunity_score is None or data_quality != "OK" or signal_confidence == "UNKNOWN":
            return Eligibility.REJECT
        if risk_penalty is None:
            return Eligibility.WATCH
        if opportunity_score >= 0.7 and risk_penalty <= 0.15 and signal_confidence in {"HIGH", "MEDIUM"}:
            return Eligibility.RESEARCH_OPPORTUNITY
        if opportunity_score >= 0.5:
            return Eligibility.RESEARCH_CANDIDATE
        return Eligibility.WATCH

    def _build_reason_codes(
        self,
        eligible_signals: List[StrategySignalSummary],
        compatibility_map: Dict[str, CompatibilityAssessment],
        context_compatibility: Optional[float],
        risk_penalty: Optional[float],
        data_quality: str,
        eligibility: Eligibility,
    ) -> List[str]:
        codes: List[str] = []
        families = {s.family for s in eligible_signals}
        if "Trend" in families:
            codes.append("TREND_SIGNAL_PRESENT")
        if "Momentum" in families:
            codes.append("MOMENTUM_SIGNAL_PRESENT")
        if "Reversal" in families:
            codes.append("REVERSAL_SIGNAL_PRESENT")
        if "Breakout" in families:
            codes.append("BREAKOUT_SIGNAL_PRESENT")
        if "Volatility" in families:
            codes.append("VOLATILITY_SIGNAL_PRESENT")
        if "PriceVolume" in families:
            codes.append("PRICEVOLUME_SIGNAL_PRESENT")

        if context_compatibility is not None and context_compatibility >= 0.7:
            codes.append("CONTEXT_COMPATIBLE")
        elif context_compatibility is not None and context_compatibility < 0.4:
            codes.append("CONTEXT_INCOMPATIBLE")

        if any(compatibility_map.get(s.strategy_id) and compatibility_map[s.strategy_id].regime_match_score == "HIGH" for s in eligible_signals):
            codes.append("MULTI_STRATEGY_ALIGNMENT")

        if risk_penalty is not None and risk_penalty <= 0.1:
            codes.append("LOW_RISK")
        elif risk_penalty is not None and risk_penalty >= 0.2:
            codes.append("HIGH_RISK")

        if data_quality != "OK":
            codes.append("DATA_LIMITATION")

        if eligibility == Eligibility.RESEARCH_OPPORTUNITY:
            codes.append("RESEARCH_OPPORTUNITY")
        elif eligibility == Eligibility.RESEARCH_CANDIDATE:
            codes.append("RESEARCH_CANDIDATE")
        elif eligibility == Eligibility.WATCH:
            codes.append("WATCH")
        elif eligibility == Eligibility.REJECT:
            codes.append("REJECT")

        return codes

    def _rank_opportunities(self, opportunities: List[Opportunity]) -> List[Opportunity]:
        def sort_key(o: Opportunity):
            score = o.opportunity_score if o.opportunity_score is not None else -1.0
            eligibility_order = {
                Eligibility.RESEARCH_OPPORTUNITY: 0,
                Eligibility.RESEARCH_CANDIDATE: 1,
                Eligibility.WATCH: 2,
                Eligibility.REJECT: 3,
                Eligibility.UNKNOWN: 4,
            }
            return (
                eligibility_order.get(o.eligibility, 5),
                -score,
                o.stock_code,
            )

        ranked = sorted(opportunities, key=sort_key)
        ranked_limited = ranked[: self.config.top_n]
        result = []
        for idx, o in enumerate(ranked_limited, start=1):
            result.append(Opportunity(**{**o.__dict__, "rank": idx}))
        return result

    def _compatibility_score_to_float(self, score: str) -> float:
        return {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.2, "UNKNOWN": 0.0}.get(score, 0.0)

    def _evidence_strength_to_float(self, strength: str) -> float:
        return {"ADEQUATE": 1.0, "PRELIMINARY": 0.6, "INSUFFICIENT": 0.2, "DATA_BLOCKED": 0.0}.get(strength, 0.0)

    def _score_to_label(self, score: Optional[float]) -> str:
        if score is None:
            return "UNKNOWN"
        if score >= 0.7:
            return "COMPATIBLE"
        if score >= 0.4:
            return "NEUTRAL"
        return "INCOMPATIBLE"

    def _build_provenance(self, context: MarketContext, signals: List[StrategySignalSummary]) -> Dict[str, str]:
        strategy_versions = {s.strategy_id: s.strategy_version for s in signals}
        return {
            "run_id": f"opportunity:{context.model.decision_time}:{context.model.context_id}",
            "decision_time": context.model.decision_time,
            "data_cutoff": context.model.data_cutoff,
            "context_version": context.model.provenance.get("context_version", "unknown"),
            "strategy_versions": str(strategy_versions),
            "normalization_version": self.config.normalization_version,
            "opportunity_version": self.config.opportunity_version,
            "provenance_fingerprint": context.provenance_fingerprint(),
        }
