#!/usr/bin/env python3
"""
shadow_decision_runner.py — Shadow Decision Assembly Runner
============================================================
Orchestrates the full Shadow Decision Pipeline in Research Plane.

Pipeline:
  MarketContextSnapshot
      ↓
  StrategyEligibilityAssessment
      ↓
  OpportunityAssessment (from OpportunityEngine)
      ↓
  TradabilityAssessment
      ↓
  EntryTimingAssessment
      ↓
  RiskAssessment
      ↓
  TradingPermission (from existing Trading Permission Gate, read-only)
      ↓
  PortfolioConstraints (from existing Portfolio Decision Layer, read-only)
      ↓
  PositionSizingAssessment
      ↓
  ShadowDecision

Constraints:
- PRODUCTION_CONNECTED = NO
- No production DB writes
- No DecisionEngine mutation
- No auto-trading
- Research-only strategies remain research-only
- Future outcome data cannot influence action generation
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from core.research.decision_shadow.shadow_decision_engine import ShadowDecisionEngine
from core.research.decision_shadow.shadow_decision_schema import (
    MarketContextSnapshot,
    StrategyEligibilityAssessment,
    StrategyEligibilityStatus,
    TradabilityAssessment,
    TradabilityStatus,
    EntryTimingAssessment,
    EntryTimingState,
    RiskAssessment,
    RiskState,
    PortfolioConstraints,
    PositionSizingAssessment,
    ExitAssessment,
    ShadowDecisionRecord,
    DecisionCoverageMatrix,
)

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
STOCK_WORK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESEARCH_DATA_DIR = os.path.join(STOCK_WORK_ROOT, "data", "research", "decision_shadow")


# ------------------------------------------------------------------
# Adapters / Mocks (V1: minimal implementation, research-safe)
# ------------------------------------------------------------------
@dataclass
class StrategyRegistration:
    strategy_id: str
    strategy_version: str
    qualification_status: str
    research_only: bool
    preferred_regime: List[str]
    forbidden_regime: List[str]


class StrategyRegistryReader:
    """Read-only view of strategy registry. Does not modify production."""

    def __init__(self, registrations: List[StrategyRegistration]):
        self._registrations = {r.strategy_id: r for r in registrations}

    def get(self, strategy_id: str) -> Optional[StrategyRegistration]:
        return self._registrations.get(strategy_id)

    def all(self) -> List[StrategyRegistration]:
        return list(self._registrations.values())


class PermissionGateReader:
    """Read-only adapter for existing Trading Permission Gate."""

    def evaluate(self, *, decision_time: str, stock_code: str, has_position: bool) -> Dict[str, Any]:
        # V1 shadow: placeholder until production permission module is read-only accessible.
        # Returns conservative default.
        return {
            "permission_status": "ALLOW",
            "new_entry": "ALLOW" if not has_position else "UNUSED",
            "reduce_position": "ALLOW",
            "exit_position": "ALLOW",
            "reason_codes": ["PERMISSION_SHADOW_DEFAULT"],
            "provenance": {"source": "permission_gate_reader_v1", "decision_time": decision_time},
        }


class PortfolioDecisionReader:
    """Read-only adapter for existing Portfolio Decision Layer."""

    def evaluate(
        self,
        *,
        decision_time: str,
        stock_code: str,
        opportunity_score: Optional[float],
        risk_state: str,
        current_position_pct: Optional[float],
    ) -> PortfolioConstraints:
        # V1 shadow: conservative defaults when real portfolio truth is unavailable.
        max_position = 0.10
        max_sector_count = 5
        cash_available = None
        total_asset = None
        drawdown = None
        drawdown_status = "UNKNOWN"
        position_size_status = "UNKNOWN"
        allowed_position_range = [0.05, 0.08] if opportunity_score is not None and opportunity_score >= 0.7 else None

        return PortfolioConstraints(
            decision_time=decision_time,
            max_position=max_position,
            max_sector_count=max_sector_count,
            current_sector_exposure={},
            cash_available=cash_available,
            total_asset=total_asset,
            current_position_count=0,
            current_position_pct=current_position_pct,
            drawdown=drawdown,
            drawdown_status=drawdown_status,
            position_size_status=position_size_status,
            allowed_position_range=allowed_position_range,
            reason_codes=["PORTFOLIO_SHADOW_DEFAULT"],
            provenance={"source": "portfolio_decision_reader_v1", "decision_time": decision_time},
        )


class TradabilityGateReader:
    """Minimal tradability assessment for Shadow."""

    def evaluate(self, *, decision_time: str, stock_code: str) -> TradabilityAssessment:
        # V1 shadow: default UNKNOWN (conservative).
        # Real implementation should check: data freshness, price availability, liquidity, suspension, abnormal trading.
        return TradabilityAssessment(
            stock_code=stock_code,
            decision_time=decision_time,
            tradability=TradabilityStatus.UNKNOWN.value,
            tradability_score="UNKNOWN",
            reason_codes=["TRADABILITY_V1_UNKNOWN"],
            confidence="LOW",
            checks={"data_freshness": "UNKNOWN", "price_availability": "UNKNOWN", "liquidity": "UNKNOWN"},
            provenance={"source": "tradability_gate_reader_v1", "decision_time": decision_time},
        )


class EntryTimingReader:
    """Minimal entry timing assessment for Shadow."""

    def evaluate(
        self,
        *,
        decision_time: str,
        stock_code: str,
        opportunity_score: Optional[float],
        risk_state: str,
    ) -> EntryTimingAssessment:
        # V1 shadow: conservative timing.
        if opportunity_score is None:
            state = EntryTimingState.UNKNOWN.value
            score = None
            conf = "LOW"
            codes = ["OPPORTUNITY_SCORE_MISSING"]
        elif opportunity_score >= 0.7 and risk_state != RiskState.HIGH.value:
            state = EntryTimingState.NOW.value
            score = 0.7
            conf = "MEDIUM"
            codes = ["HIGH_OPPORTUNITY_TIMING_NOW"]
        elif opportunity_score >= 0.5:
            state = EntryTimingState.WAIT.value
            score = 0.4
            conf = "LOW"
            codes = ["MODERATE_OPPORTUNITY_TIMING_WAIT"]
        else:
            state = EntryTimingState.NO_ENTRY.value
            score = 0.0
            conf = "MEDIUM"
            codes = ["LOW_OPPORTUNITY_NO_ENTRY"]

        return EntryTimingAssessment(
            stock_code=stock_code,
            decision_time=decision_time,
            entry_timing_state=state,
            timing_score=score,
            confidence=conf,
            reason_codes=codes,
            provenance={"source": "entry_timing_reader_v1", "decision_time": decision_time},
        )


class RiskAssessmentReader:
    """Minimal risk assessment for Shadow."""

    def evaluate(
        self,
        *,
        decision_time: str,
        stock_code: str,
        market_context: MarketContextSnapshot,
    ) -> RiskAssessment:
        # V1 shadow: derive risk from market context only.
        market_risk = market_context.risk_state
        stock_risk = RiskState.UNKNOWN.value
        sector_risk = RiskState.UNKNOWN.value
        volatility_risk = market_context.tactical_state
        liquidity_risk = "UNKNOWN"
        event_risk = "UNKNOWN"
        portfolio_risk = RiskState.UNKNOWN.value

        risk_state = market_context.risk_state
        risk_score = 0.0
        risk_penalty = 0.0
        if risk_state == RiskState.HIGH.value:
            risk_score = 0.8
            risk_penalty = 0.25
        elif risk_state == RiskState.MEDIUM.value:
            risk_score = 0.5
            risk_penalty = 0.1
        elif risk_state == RiskState.LOW.value:
            risk_score = 0.2
            risk_penalty = 0.0
        else:
            risk_score = None
            risk_penalty = None

        return RiskAssessment(
            stock_code=stock_code,
            decision_time=decision_time,
            market_risk=market_risk,
            stock_risk=stock_risk,
            sector_risk=sector_risk,
            volatility_risk=volatility_risk,
            liquidity_risk=liquidity_risk,
            event_risk=event_risk,
            portfolio_risk=portfolio_risk,
            risk_score=risk_score,
            risk_state=risk_state,
            risk_penalty=risk_penalty,
            reason_codes=["RISK_V1_MARKET_CONTEXT_ONLY"],
            provenance={"source": "risk_assessment_reader_v1", "decision_time": decision_time},
        )


class OpportunityEngineReader:
    """Read-only adapter for existing OpportunityEngine."""

    def __init__(self, opportunity_engine):
        self._engine = opportunity_engine

    def build_opportunity(
        self,
        *,
        context: MarketContextSnapshot,
        stock_code: str,
    ) -> Optional[Dict[str, Any]]:
        # V1 shadow: placeholder until full opportunity engine is integrated.
        # Returns a synthetic opportunity to allow pipeline assembly.
        return {
            "stock_code": stock_code,
            "decision_time": context.decision_time,
            "market_context_id": context.context_id,
            "opportunity_score": None,
            "eligibility": "UNKNOWN",
            "reason_codes": ["OPPORTUNITY_ENGINE_READER_V1_PLACEHOLDER"],
            "signal_confidence": "UNKNOWN",
            "research_only": True,
            "provenance": {"source": "opportunity_engine_reader_v1", "decision_time": context.decision_time},
        }


# ------------------------------------------------------------------
# Main Runner
# ------------------------------------------------------------------
class ShadowDecisionRunner:
    """
    Orchestrates a full shadow decision run for one or more stocks at a given decision_time.
    """

    def __init__(
        self,
        *,
        strategy_registry: StrategyRegistryReader,
        permission_gate: PermissionGateReader,
        portfolio_decision: PortfolioDecisionReader,
        tradability_gate: TradabilityGateReader,
        entry_timing_reader: EntryTimingReader,
        risk_reader: RiskAssessmentReader,
        opportunity_reader: OpportunityEngineReader,
        decision_engine: ShadowDecisionEngine,
        output_dir: str = RESEARCH_DATA_DIR,
        decision_policy_version: str = "shadow_v1",
    ):
        self.strategy_registry = strategy_registry
        self.permission_gate = permission_gate
        self.portfolio_decision = portfolio_decision
        self.tradability_gate = tradability_gate
        self.entry_timing_reader = entry_timing_reader
        self.risk_reader = risk_reader
        self.opportunity_reader = opportunity_reader
        self.decision_engine = decision_engine
        self.output_dir = output_dir
        self.decision_policy_version = decision_policy_version

    def run_for_stock(
        self,
        *,
        decision_time: str,
        data_cutoff: str,
        stock_code: str,
        market_context: MarketContextSnapshot,
        current_position: Optional[Dict[str, Any]] = None,
    ) -> tuple[ShadowDecision, ShadowDecisionRecord, DecisionCoverageMatrix]:
        """
        Execute full shadow pipeline for a single stock.
        """
        # 1. Strategy Eligibility
        strategy_assessments = self._build_strategy_eligibility(
            decision_time=decision_time,
            market_context=market_context,
        )

        # 2. Opportunity
        opportunity = self.opportunity_reader.build_opportunity(
            context=market_context,
            stock_code=stock_code,
        )

        # 3. Tradability
        tradability = self.tradability_gate.evaluate(
            decision_time=decision_time,
            stock_code=stock_code,
        )

        # 4. Risk
        risk = self.risk_reader.evaluate(
            decision_time=decision_time,
            stock_code=stock_code,
            market_context=market_context,
        )

        # 5. Entry Timing (uses opportunity + risk)
        entry_timing = self.entry_timing_reader.evaluate(
            decision_time=decision_time,
            stock_code=stock_code,
            opportunity_score=opportunity.get("opportunity_score") if opportunity else None,
            risk_state=risk.risk_state if risk else RiskState.UNKNOWN.value,
        )

        # 6. Trading Permission (existing gate, read-only)
        has_position = bool(current_position and current_position.get("quantity", 0) > 0)
        trading_permission = self.permission_gate.evaluate(
            decision_time=decision_time,
            stock_code=stock_code,
            has_position=has_position,
        )

        # 7. Portfolio Constraints (existing layer, read-only)
        current_position_pct = (current_position or {}).get("position_pct")
        portfolio_constraints = self.portfolio_decision.evaluate(
            decision_time=decision_time,
            stock_code=stock_code,
            opportunity_score=opportunity.get("opportunity_score") if opportunity else None,
            risk_state=risk.risk_state if risk else RiskState.UNKNOWN.value,
            current_position_pct=current_position_pct,
        )

        # 8. Position Sizing
        position_sizing = self._build_position_sizing(
            decision_time=decision_time,
            stock_code=stock_code,
            opportunity=opportunity,
            risk=risk,
            portfolio_constraints=portfolio_constraints,
        )

        # 9. Shadow Decision
        decision_id = f"shadow:{decision_time}:{stock_code}:{datetime.now(timezone.utc).strftime('%H%M%S')}"
        decision_data = self.decision_engine.build_decision(
            decision_id=decision_id,
            decision_time=decision_time,
            stock_code=stock_code,
            market_context=market_context,
            strategy_assessments=strategy_assessments,
            opportunity=opportunity,
            tradability=tradability,
            entry_timing=entry_timing,
            risk=risk,
            trading_permission=trading_permission,
            portfolio_constraints=portfolio_constraints,
            position_sizing=position_sizing,
            current_position=current_position,
        )

        decision = decision_data["decision"]
        record = decision_data["record"]
        coverage = decision_data["coverage"]

        return decision, record, coverage

    def _build_strategy_eligibility(
        self,
        *,
        decision_time: str,
        market_context: MarketContextSnapshot,
    ) -> List[StrategyEligibilityAssessment]:
        assessments: List[StrategyEligibilityAssessment] = []
        for reg in self.strategy_registry.all():
            status = StrategyEligibilityStatus.ACTIVE_FOR_SHADOW
            reason_codes: List[str] = []

            if reg.qualification_status in ("BLOCKED", "FAILED"):
                status = StrategyEligibilityStatus.BLOCKED
                reason_codes.append(f"qualification_status={reg.qualification_status}")

            if market_context.risk_state == RiskState.HIGH.value and "risk_state=HIGH" in reg.forbidden_regime:
                status = StrategyEligibilityStatus.INCOMPATIBLE
                reason_codes.append("regime_forbidden_risk_high")

            if status == StrategyEligibilityStatus.ACTIVE_FOR_SHADOW and reg.qualification_status in (
                "RESEARCH_CANDIDATE",
                "INSUFFICIENT_EVIDENCE",
            ):
                reason_codes.append("research_only_due_to_evidence")

            assessments.append(
                StrategyEligibilityAssessment(
                    strategy_id=reg.strategy_id,
                    strategy_version=reg.strategy_version,
                    status=status.value,
                    qualification_status=reg.qualification_status,
                    research_only=reg.research_only,
                    reason_codes=reason_codes,
                    provenance={
                        "source": "strategy_registry_reader_v1",
                        "decision_time": decision_time,
                        "market_context_risk_state": market_context.risk_state,
                    },
                )
            )
        return assessments

    def _build_position_sizing(
        self,
        *,
        decision_time: str,
        stock_code: str,
        opportunity: Optional[Dict[str, Any]],
        risk: Optional[RiskAssessment],
        portfolio_constraints: PortfolioConstraints,
    ) -> PositionSizingAssessment:
        opp_score = opportunity.get("opportunity_score") if opportunity else None
        confidence = "LOW"
        recommended_range: Optional[List[float]] = None
        allowed_range = portfolio_constraints.allowed_position_range

        if opp_score is not None and risk and risk.risk_penalty is not None:
            confidence = "MEDIUM"
            base_low = 0.03
            base_high = 0.06
            if opp_score >= 0.8:
                base_low, base_high = 0.06, 0.10
            elif opp_score >= 0.6:
                base_low, base_high = 0.04, 0.08
            risk_adj = risk.risk_penalty
            recommended_range = [
                max(0.01, round(base_low - risk_adj, 4)),
                max(0.02, round(base_high - risk_adj, 4)),
            ]

        return PositionSizingAssessment(
            stock_code=stock_code,
            decision_time=decision_time,
            recommended_position_range=recommended_range,
            allowed_position_range=allowed_range,
            sizing_score=opp_score,
            confidence=confidence,
            reason_codes=["POSITION_SIZING_V1_RESEARCH_ONLY"],
            provenance={"source": "shadow_position_sizing_v1", "decision_time": decision_time},
        )
