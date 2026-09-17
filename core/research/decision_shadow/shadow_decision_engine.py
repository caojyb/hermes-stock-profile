#!/usr/bin/env python3
"""
shadow_decision_engine.py — Shadow Decision Engine (Research Plane Only)
==========================================================================
Arbitrates final Shadow Action from upstream assessments.

Hard gate precedence (never override a hard gate with opportunity score):
  1. Data validity / PIT safety
  2. Trading Permission
  3. Tradability
  4. Portfolio hard constraints
  5. Risk hard constraints
  6. Opportunity
  7. Entry Timing
  8. Position sizing
  9. Final Shadow Action

Allowed actions:
  BUY / ADD / HOLD / REDUCE / EXIT / NO_ACTION

Hard rules:
- BUY/ADD only when all necessary hard gates pass.
- NO_NEW_ENTRY must not block HOLD / REDUCE / EXIT for existing positions.
- UNKNOWN tradability defaults to NO_ENTRY for new entries.
- Research-only strategies stay research-only; no auto-promotion.
- Outcome data must not participate in action generation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.research.decision_shadow.shadow_decision_schema import (
    EntryTimingAssessment,
    EntryTimingState,
    MarketContextSnapshot,
    PortfolioConstraints,
    PositionSizingAssessment,
    RiskAssessment,
    RiskState,
    ShadowAction,
    StrategyEligibilityAssessment,
    StrategyEligibilityStatus,
    TradabilityAssessment,
    TradabilityStatus,
)


# ------------------------------------------------------------------
# Core Engine
# ------------------------------------------------------------------
class ShadowDecisionEngine:
    """
    Research-only action arbiter for Shadow Decision Assembly.
    Does not write to production. Does not mutate DecisionEngine.
    """

    def __init__(self, *, decision_policy_version: str = "shadow_v1"):
        self.decision_policy_version = decision_policy_version

    def build_decision(
        self,
        *,
        decision_id: str,
        decision_time: str,
        stock_code: str,
        market_context: MarketContextSnapshot,
        strategy_assessments: List[StrategyEligibilityAssessment],
        opportunity: Optional[Dict[str, Any]],
        tradability: Optional[TradabilityAssessment],
        entry_timing: Optional[EntryTimingAssessment],
        risk: Optional[RiskAssessment],
        trading_permission: Optional[Dict[str, Any]],
        portfolio_constraints: Optional[PortfolioConstraints],
        position_sizing: Optional[PositionSizingAssessment],
        current_position: Optional[Dict[str, Any]],
        outcome: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Returns a dict representation of ShadowDecision + coverage + record.
        Outcome must not be provided at decision runtime.
        """
        if outcome is not None:
            raise ValueError("Outcome must not be provided at decision runtime.")

        if market_context is None:
            return {
                "decision": {
                    "decision_id": decision_id,
                    "decision_time": decision_time,
                    "stock_code": stock_code,
                    "action": ShadowAction.NO_ACTION.value,
                    "reason_codes": ["MARKET_CONTEXT_MISSING"],
                    "explanation": "Market context missing",
                    "research_only": True,
                    "production_eligible": False,
                    "decision_confidence": "UNKNOWN",
                    "market_context": None,
                    "strategy_assessment": [],
                    "opportunity": None,
                    "tradability": None,
                    "entry_timing": None,
                    "risk": None,
                    "trading_permission": None,
                    "portfolio_constraints": None,
                    "position_sizing": None,
                    "current_position": current_position,
                    "invalidation_conditions": ["market_context_available"],
                    "exit_conditions": None,
                    "provenance": {"decision_time": decision_time},
                    "coverage": {
                        "decision_time": decision_time,
                        "stock_code": stock_code,
                        "coverage_pct": 0.0,
                        "final_action_available": False,
                        "missing_components": ["market_context"],
                    },
                },
                "record": {
                    "stock_code": stock_code,
                    "decision_time": decision_time,
                    "action": ShadowAction.NO_ACTION.value,
                    "opportunity_score": None,
                    "timing_score": None,
                    "risk_score": None,
                    "permission": None,
                    "tradability": None,
                    "position_range": None,
                    "research_only": True,
                    "reason_codes": ["MARKET_CONTEXT_MISSING"],
                    "provenance": {"decision_time": decision_time},
                },
                "coverage": {
                    "decision_time": decision_time,
                    "stock_code": stock_code,
                    "coverage_pct": 0.0,
                    "final_action_available": False,
                    "missing_components": ["market_context"],
                },
            }

        has_position = bool(current_position and current_position.get("quantity", 0) > 0)

        # Hard gate precedence
        action, reason_codes, explanation, invalidation_conditions = self._arbitrate(
            market_context=market_context,
            strategy_assessments=strategy_assessments,
            opportunity=opportunity,
            tradability=tradability,
            entry_timing=entry_timing,
            risk=risk,
            trading_permission=trading_permission,
            portfolio_constraints=portfolio_constraints,
            position_sizing=position_sizing,
            has_position=has_position,
            current_position=current_position,
        )

        # Research-only separation
        all_research_only = (
            all(s.research_only for s in strategy_assessments) if strategy_assessments else True
        )
        production_eligible = not all_research_only

        # Decision confidence
        decision_confidence = self._decision_confidence(opportunity, risk, entry_timing, tradability)

        # Explanation structure
        explanation_map = self._build_explanation(
            action=action,
            opportunity=opportunity,
            entry_timing=entry_timing,
            risk=risk,
            portfolio_constraints=portfolio_constraints,
            position_sizing=position_sizing,
            reason_codes=reason_codes,
        )

        # Exit assessment
        exit_assessment = self._build_exit_assessment(
            stock_code=stock_code,
            decision_time=decision_time,
            action=action,
            opportunity=opportunity,
            risk=risk,
            portfolio_constraints=portfolio_constraints,
            tradability=tradability,
            has_position=has_position,
        )

        provenance = self._build_provenance(
            decision_time=decision_time,
            market_context=market_context,
            opportunity=opportunity,
            strategy_assessments=strategy_assessments,
        )

        # Coverage
        coverage = self._build_coverage(
            decision_time=decision_time,
            stock_code=stock_code,
            market_context_available=market_context is not None,
            strategy_signal_available=bool(strategy_assessments),
            opportunity_available=opportunity is not None,
            tradability_available=tradability is not None,
            timing_available=entry_timing is not None,
            risk_available=risk is not None,
            portfolio_truth_available=portfolio_constraints is not None
            and portfolio_constraints.position_size_status != "UNKNOWN",
            position_sizing_available=position_sizing is not None,
        )

        shadow_decision = {
            "decision_id": decision_id,
            "decision_time": decision_time,
            "stock_code": stock_code,
            "action": action,
            "market_context": {
                "context_id": market_context.context_id,
                "decision_time": market_context.decision_time,
                "data_cutoff": market_context.data_cutoff,
                "structural_state": market_context.structural_state,
                "intermediate_state": market_context.intermediate_state,
                "tactical_state": market_context.tactical_state,
                "risk_state": market_context.risk_state,
                "confidence": market_context.confidence,
                "context_version": market_context.context_version,
                "provenance": market_context.provenance,
            },
            "strategy_assessment": [
                {
                    "strategy_id": s.strategy_id,
                    "strategy_version": s.strategy_version,
                    "status": s.status,
                    "qualification_status": s.qualification_status,
                    "research_only": s.research_only,
                    "reason_codes": s.reason_codes,
                    "provenance": s.provenance,
                }
                for s in strategy_assessments
            ],
            "opportunity": opportunity,
            "tradability": {
                "stock_code": tradability.stock_code,
                "decision_time": tradability.decision_time,
                "tradability": tradability.tradability,
                "tradability_score": tradability.tradability_score,
                "reason_codes": tradability.reason_codes,
                "confidence": tradability.confidence,
                "checks": tradability.checks,
                "provenance": tradability.provenance,
            }
            if tradability
            else None,
            "entry_timing": {
                "stock_code": entry_timing.stock_code,
                "decision_time": entry_timing.decision_time,
                "entry_timing_state": entry_timing.entry_timing_state,
                "timing_score": entry_timing.timing_score,
                "confidence": entry_timing.confidence,
                "reason_codes": entry_timing.reason_codes,
                "provenance": entry_timing.provenance,
            }
            if entry_timing
            else None,
            "risk": {
                "stock_code": risk.stock_code,
                "decision_time": risk.decision_time,
                "market_risk": risk.market_risk,
                "stock_risk": risk.stock_risk,
                "sector_risk": risk.sector_risk,
                "volatility_risk": risk.volatility_risk,
                "liquidity_risk": risk.liquidity_risk,
                "event_risk": risk.event_risk,
                "portfolio_risk": risk.portfolio_risk,
                "risk_score": risk.risk_score,
                "risk_state": risk.risk_state,
                "risk_penalty": risk.risk_penalty,
                "reason_codes": risk.reason_codes,
                "provenance": risk.provenance,
            }
            if risk
            else None,
            "trading_permission": trading_permission,
            "portfolio_constraints": {
                "decision_time": portfolio_constraints.decision_time,
                "max_position": portfolio_constraints.max_position,
                "max_sector_count": portfolio_constraints.max_sector_count,
                "current_sector_exposure": portfolio_constraints.current_sector_exposure,
                "cash_available": portfolio_constraints.cash_available,
                "total_asset": portfolio_constraints.total_asset,
                "current_position_count": portfolio_constraints.current_position_count,
                "current_position_pct": portfolio_constraints.current_position_pct,
                "drawdown": portfolio_constraints.drawdown,
                "drawdown_status": portfolio_constraints.drawdown_status,
                "position_size_status": portfolio_constraints.position_size_status,
                "allowed_position_range": portfolio_constraints.allowed_position_range,
                "reason_codes": portfolio_constraints.reason_codes,
                "provenance": portfolio_constraints.provenance,
            }
            if portfolio_constraints
            else None,
            "position_sizing": {
                "stock_code": position_sizing.stock_code,
                "decision_time": position_sizing.decision_time,
                "recommended_position_range": position_sizing.recommended_position_range,
                "allowed_position_range": position_sizing.allowed_position_range,
                "sizing_score": position_sizing.sizing_score,
                "confidence": position_sizing.confidence,
                "reason_codes": position_sizing.reason_codes,
                "provenance": position_sizing.provenance,
            }
            if position_sizing
            else None,
            "current_position": current_position,
            "decision_confidence": decision_confidence,
            "research_only": all_research_only,
            "production_eligible": production_eligible,
            "reason_codes": reason_codes,
            "invalidation_conditions": invalidation_conditions,
            "exit_conditions": exit_assessment,
            "explanation": explanation_map,
            "provenance": provenance,
            "coverage": coverage,
        }

        record = {
            "stock_code": stock_code,
            "decision_time": decision_time,
            "action": action,
            "opportunity_score": opportunity.get("opportunity_score") if opportunity else None,
            "timing_score": entry_timing.timing_score if entry_timing else None,
            "risk_score": risk.risk_score if risk else None,
            "permission": trading_permission.get("permission_status") if trading_permission else None,
            "tradability": tradability.tradability if tradability else None,
            "position_range": position_sizing.allowed_position_range if position_sizing else None,
            "research_only": all_research_only,
            "reason_codes": reason_codes,
            "provenance": provenance,
        }

        return {
            "decision": shadow_decision,
            "record": record,
            "coverage": coverage,
        }

    # ------------------------------------------------------------------
    # Hard Gate Arbitration
    # ------------------------------------------------------------------
    def _arbitrate(
        self,
        *,
        market_context: MarketContextSnapshot,
        strategy_assessments: List[StrategyEligibilityAssessment],
        opportunity: Optional[Dict[str, Any]],
        tradability: Optional[TradabilityAssessment],
        entry_timing: Optional[EntryTimingAssessment],
        risk: Optional[RiskAssessment],
        trading_permission: Optional[Dict[str, Any]],
        portfolio_constraints: Optional[PortfolioConstraints],
        position_sizing: Optional[PositionSizingAssessment],
        has_position: bool,
        current_position: Optional[Dict[str, Any]],
    ) -> tuple[str, List[str], str, List[str]]:
        reason_codes: List[str] = []
        invalidation_conditions: List[str] = []

        # Gate 1: Market Context presence
        if market_context is None:
            return (
                ShadowAction.NO_ACTION.value,
                ["MARKET_CONTEXT_MISSING"],
                "Market context missing",
                ["market_context_available"],
            )

        # Gate 2: Strategy Eligibility
        active_strategies = [s for s in strategy_assessments if s.status == StrategyEligibilityStatus.ACTIVE_FOR_SHADOW]
        blocked_strategies = [s for s in strategy_assessments if s.status == StrategyEligibilityStatus.BLOCKED]
        if blocked_strategies and not active_strategies:
            return (
                ShadowAction.NO_ACTION.value,
                ["ALL_STRATEGIES_BLOCKED"],
                "All strategies blocked for shadow",
                ["strategy_eligibility_available"],
            )

        # Gate 3: Tradability
        if tradability is not None:
            if tradability.tradability == TradabilityStatus.UNTRADABLE.value:
                if has_position:
                    # Existing position: untradable stock should trigger exit
                    return (
                        ShadowAction.EXIT.value,
                        ["TRADABILITY_UNTRADABLE_EXIT"] + tradability.reason_codes,
                        f"Stock untradable; exiting existing position: {', '.join(tradability.reason_codes)}",
                        ["tradability_available"],
                    )
                return (
                    ShadowAction.NO_ACTION.value,
                    ["TRADABILITY_UNTRADABLE"] + tradability.reason_codes,
                    f"Stock untradable: {', '.join(tradability.reason_codes)}",
                    ["tradability_available"],
                )
            if tradability.tradability == TradabilityStatus.UNKNOWN.value:
                if not has_position:
                    return (
                        ShadowAction.NO_ACTION.value,
                        ["TRADABILITY_UNKNOWN_NO_ENTRY"] + tradability.reason_codes,
                        "Tradability unknown; default NO_ENTRY for new position",
                        ["tradability_available"],
                    )
                reason_codes.append("TRADABILITY_UNKNOWN_HOLD_EXISTING")
        else:
            if not has_position:
                return (
                    ShadowAction.NO_ACTION.value,
                    ["TRADABILITY_MISSING"],
                    "Tradability assessment missing; default NO_ENTRY",
                    ["tradability_available"],
                )
            reason_codes.append("TRADABILITY_MISSING_HOLD_EXISTING")

        # Gate 4: Trading Permission
        permission_status = (trading_permission or {}).get("permission_status", "")
        new_entry_allowed = (trading_permission or {}).get("new_entry", "DENY") == "ALLOW"
        no_new_entry = permission_status == "NO_NEW_ENTRY" or not new_entry_allowed

        if no_new_entry and not has_position:
            return (
                ShadowAction.NO_ACTION.value,
                ["PERMISSION_NO_NEW_ENTRY"],
                f"Trading Permission {permission_status} blocks new entry",
                ["trading_permission_available"],
            )

        # Gate 5: Portfolio Hard Constraints
        if portfolio_constraints is not None:
            if portfolio_constraints.position_size_status == "UNKNOWN":
                reason_codes.append("PORTFOLIO_SIZE_UNKNOWN")
            if portfolio_constraints.allowed_position_range is None:
                if not has_position:
                    return (
                        ShadowAction.NO_ACTION.value,
                        ["PORTFOLIO_CONSTRAINTS_BLOCK"],
                        "Portfolio constraints block new position",
                        ["portfolio_constraints_available"],
                    )
                reason_codes.append("PORTFOLIO_RANGE_UNKNOWN_HOLD_EXISTING")
        else:
            if not has_position:
                return (
                    ShadowAction.NO_ACTION.value,
                    ["PORTFOLIO_CONSTRAINTS_MISSING"],
                    "Portfolio constraints missing; default NO_ENTRY",
                    ["portfolio_constraints_available"],
                )
            reason_codes.append("PORTFOLIO_CONSTRAINTS_MISSING_HOLD_EXISTING")

        # Gate 6: Risk Hard Constraints
        if risk is not None:
            if risk.risk_state == RiskState.HIGH.value:
                if has_position:
                    reason_codes.append("RISK_STATE_HOLD_EXISTING")
                else:
                    return (
                        ShadowAction.NO_ACTION.value,
                        ["RISK_HIGH_BLOCK_NEW_ENTRY"] + risk.reason_codes,
                        f"Risk state HIGH blocks new entry: {', '.join(risk.reason_codes)}",
                        ["risk_available"],
                    )
            if risk.risk_state == RiskState.UNKNOWN.value:
                reason_codes.append("RISK_UNKNOWN")
        else:
            reason_codes.append("RISK_MISSING")

        # Gate 7: Opportunity Score (soft after hard gates)
        if opportunity is not None:
            eligibility = opportunity.get("eligibility", "")
            if eligibility == "REJECT":
                return (
                    ShadowAction.NO_ACTION.value,
                    ["OPPORTUNITY_REJECT"] + opportunity.get("reason_codes", []),
                    "Opportunity rejected by engine",
                    ["opportunity_available"],
                )
            if opportunity.get("opportunity_score") is None:
                reason_codes.append("OPPORTUNITY_SCORE_UNKNOWN")
        else:
            reason_codes.append("OPPORTUNITY_MISSING")

        # Gate 8: Entry Timing
        if entry_timing is not None:
            if entry_timing.entry_timing_state == EntryTimingState.NO_ENTRY.value:
                return (
                    ShadowAction.NO_ACTION.value,
                    ["ENTRY_TIMING_NO_ENTRY"] + entry_timing.reason_codes,
                    f"Entry timing says NO_ENTRY: {', '.join(entry_timing.reason_codes)}",
                    ["entry_timing_available"],
                )
            if entry_timing.entry_timing_state == EntryTimingState.UNKNOWN.value:
                reason_codes.append("ENTRY_TIMING_UNKNOWN")
        else:
            reason_codes.append("ENTRY_TIMING_MISSING")

        # Gate 9: Existing Position Handling
        if has_position:
            exit_signal = (current_position or {}).get("exit_signal")
            if exit_signal and exit_signal != "NONE":
                return (
                    ShadowAction.EXIT.value,
                    ["EXIT_TRIGGERED"] + (current_position or {}).get("exit_triggers", []),
                    f"Existing position exit triggered: {exit_signal}",
                    ["current_position_available"],
                )

            explanation = "Existing position held; no exit trigger and no new entry needed"
            return (
                ShadowAction.HOLD.value,
                reason_codes + ["EXISTING_POSITION_HOLD"],
                explanation,
                ["current_position_available"],
            )

        # Gate 10: New Entry Decision
        action = self._determine_new_entry_action(
            opportunity=opportunity,
            entry_timing=entry_timing,
            position_sizing=position_sizing,
            risk=risk,
        )
        reason_codes.extend(
            self._action_reason_codes(action, opportunity, entry_timing, position_sizing)
        )
        explanation = self._action_explanation(action, opportunity, entry_timing, position_sizing)
        invalidation_conditions = self._build_invalidation_conditions(
            opportunity, risk, tradability, entry_timing
        )
        return action, reason_codes, explanation, invalidation_conditions

    # ------------------------------------------------------------------
    # New Entry Action Selection
    # ------------------------------------------------------------------
    def _determine_new_entry_action(
        self,
        *,
        opportunity: Optional[Dict[str, Any]],
        entry_timing: Optional[EntryTimingAssessment],
        position_sizing: Optional[PositionSizingAssessment],
        risk: Optional[RiskAssessment],
    ) -> str:
        opp_score = opportunity.get("opportunity_score") if opportunity else None
        timing_state = entry_timing.entry_timing_state if entry_timing else EntryTimingState.UNKNOWN.value
        risk_state = risk.risk_state if risk else RiskState.UNKNOWN.value

        if (
            opp_score is not None
            and opp_score >= 0.7
            and timing_state == EntryTimingState.NOW.value
            and risk_state in (RiskState.LOW.value, RiskState.MEDIUM.value, RiskState.UNKNOWN.value)
        ):
            return ShadowAction.BUY.value

        if opp_score is not None and opp_score >= 0.5 and timing_state in (
            EntryTimingState.NOW.value,
            EntryTimingState.STAGED_ENTRY.value,
        ):
            return ShadowAction.BUY.value

        if opp_score is not None and opp_score < 0.5:
            return ShadowAction.NO_ACTION.value

        return ShadowAction.NO_ACTION.value

    def _action_reason_codes(
        self,
        action: str,
        opportunity: Optional[Dict[str, Any]],
        entry_timing: Optional[EntryTimingAssessment],
        position_sizing: Optional[PositionSizingAssessment],
    ) -> List[str]:
        codes: List[str] = []
        if action == ShadowAction.BUY.value:
            codes.append("NEW_ENTRY_APPROVED")
            if opportunity:
                codes.extend(opportunity.get("reason_codes", []))
            if entry_timing:
                codes.extend(entry_timing.reason_codes)
        elif action == ShadowAction.NO_ACTION.value:
            codes.append("NO_ACTION_GATES_PASSED_NO_ENTRY")
        return codes

    def _action_explanation(
        self,
        action: str,
        opportunity: Optional[Dict[str, Any]],
        entry_timing: Optional[EntryTimingAssessment],
        position_sizing: Optional[PositionSizingAssessment],
    ) -> str:
        opp_score = opportunity.get("opportunity_score") if opportunity else None
        timing_state = entry_timing.entry_timing_state if entry_timing else "UNKNOWN"
        timing_score = entry_timing.timing_score if entry_timing else None
        pos_range = position_sizing.allowed_position_range if position_sizing else None

        if action == ShadowAction.BUY.value:
            return (
                f"New entry approved: opportunity_score={opp_score}, "
                f"timing={timing_state}(score={timing_score}), "
                f"position_range={pos_range}"
            )
        if action == ShadowAction.NO_ACTION.value:
            return (
                f"No action: opportunity_score={opp_score}, timing={timing_state}, no gate override"
            )
        return f"Shadow action: {action}"

    def _build_invalidation_conditions(
        self,
        opportunity: Optional[Dict[str, Any]],
        risk: Optional[RiskAssessment],
        tradability: Optional[TradabilityAssessment],
        entry_timing: Optional[EntryTimingAssessment],
    ) -> List[str]:
        conditions: List[str] = []
        if risk:
            conditions.append(f"risk_escalation:{risk.risk_state}")
        if tradability:
            conditions.append(f"tradability_change:{tradability.tradability}")
        if entry_timing:
            conditions.append(f"timing_deterioration:{entry_timing.entry_timing_state}")
        if opportunity:
            conditions.append(f"opportunity_deterioration:{opportunity.get('eligibility')}")
        return conditions

    def _build_exit_assessment(
        self,
        *,
        stock_code: str,
        decision_time: str,
        action: str,
        opportunity: Optional[Dict[str, Any]],
        risk: Optional[RiskAssessment],
        portfolio_constraints: Optional[PortfolioConstraints],
        tradability: Optional[TradabilityAssessment],
        has_position: bool,
    ) -> Optional[Dict[str, Any]]:
        triggers: List[str] = []
        if risk and risk.risk_state == RiskState.HIGH.value:
            triggers.append("RISK_ESCALATION")
        if tradability and tradability.tradability == TradabilityStatus.UNTRADABLE.value:
            triggers.append("TRADING_STATUS_PROBLEM")
        if opportunity and opportunity.get("eligibility") == "REJECT":
            triggers.append("OPPORTUNITY_DETERIORATION")
        if portfolio_constraints and portfolio_constraints.drawdown_status == "CRITICAL":
            triggers.append("PORTFOLIO_CONSTRAINT")

        if not triggers:
            if has_position:
                triggers.append("NONE")
            else:
                return None

        exit_signal = "NONE"
        if triggers and triggers[0] != "NONE":
            exit_signal = triggers[0]

        return {
            "stock_code": stock_code,
            "decision_time": decision_time,
            "exit_signal": exit_signal,
            "exit_triggers": triggers,
            "exit_confidence": "LOW",
            "invalidation_conditions": [],
            "reason_codes": triggers,
            "provenance": {"source": "shadow_decision_engine_exit_v1"},
        }

    def _build_explanation(
        self,
        *,
        action: str,
        opportunity: Optional[Dict[str, Any]],
        entry_timing: Optional[EntryTimingAssessment],
        risk: Optional[RiskAssessment],
        portfolio_constraints: Optional[PortfolioConstraints],
        position_sizing: Optional[PositionSizingAssessment],
        reason_codes: List[str],
    ) -> Dict[str, str]:
        opp_score = opportunity.get("opportunity_score") if opportunity else None
        timing_state = entry_timing.entry_timing_state if entry_timing else "UNKNOWN"
        timing_score = entry_timing.timing_score if entry_timing else None
        risk_state = risk.risk_state if risk else "UNKNOWN"
        pos_range = position_sizing.allowed_position_range if position_sizing else None

        return {
            "WHY_STOCK": f"opportunity_score={opp_score}, eligibility={opportunity.get('eligibility') if opportunity else 'UNKNOWN'}",
            "WHY_NOW": f"timing={timing_state}(score={timing_score})",
            "WHY_SIZE": f"allowed_position_range={pos_range}",
            "WHY_NOT": f"hard_gate_failures={[c for c in reason_codes if 'BLOCK' in c or 'UNKNOWN' in c or 'MISSING' in c]}",
            "EXIT_CONDITIONS": f"risk_state={risk_state}, tradability_changes, opportunity_deterioration",
        }

    def _decision_confidence(
        self,
        opportunity: Optional[Dict[str, Any]],
        risk: Optional[RiskAssessment],
        entry_timing: Optional[EntryTimingAssessment],
        tradability: Optional[TradabilityAssessment],
    ) -> str:
        confidences = []
        if opportunity:
            confidences.append(opportunity.get("signal_confidence", "UNKNOWN"))
        if risk:
            confidences.append(risk.risk_state if risk.risk_state != "UNKNOWN" else "LOW")
        if entry_timing:
            confidences.append(entry_timing.confidence)
        if tradability:
            confidences.append(tradability.confidence)

        if not confidences:
            return "UNKNOWN"
        if any(c == "UNKNOWN" for c in confidences):
            return "LOW"
        if any(c == "LOW" for c in confidences):
            return "LOW"
        if all(c in ("HIGH", "MEDIUM") for c in confidences):
            return "MEDIUM"
        return "LOW"

    def _build_coverage(
        self,
        *,
        decision_time: str,
        stock_code: str,
        market_context_available: bool,
        strategy_signal_available: bool,
        opportunity_available: bool,
        tradability_available: bool,
        timing_available: bool,
        risk_available: bool,
        portfolio_truth_available: bool,
        position_sizing_available: bool,
    ) -> Dict[str, Any]:
        final_action_available = all(
            [
                market_context_available,
                strategy_signal_available,
                opportunity_available,
                tradability_available,
                timing_available,
                risk_available,
                portfolio_truth_available,
                position_sizing_available,
            ]
        )

        missing = []
        if not market_context_available:
            missing.append("market_context")
        if not strategy_signal_available:
            missing.append("strategy_signal")
        if not opportunity_available:
            missing.append("opportunity")
        if not tradability_available:
            missing.append("tradability")
        if not timing_available:
            missing.append("timing")
        if not risk_available:
            missing.append("risk")
        if not portfolio_truth_available:
            missing.append("portfolio_truth")
        if not position_sizing_available:
            missing.append("position_sizing")

        coverage = 1.0 if final_action_available else max(0.0, 1.0 - len(missing) / 8.0)

        return {
            "decision_time": decision_time,
            "stock_code": stock_code,
            "market_context_available": market_context_available,
            "strategy_signal_available": strategy_signal_available,
            "opportunity_available": opportunity_available,
            "tradability_available": tradability_available,
            "timing_available": timing_available,
            "risk_available": risk_available,
            "portfolio_truth_available": portfolio_truth_available,
            "position_sizing_available": position_sizing_available,
            "final_action_available": final_action_available,
            "coverage_pct": round(coverage, 2),
            "missing_components": missing,
        }

    def _build_provenance(
        self,
        *,
        decision_time: str,
        market_context: MarketContextSnapshot,
        opportunity: Optional[Dict[str, Any]],
        strategy_assessments: List[StrategyEligibilityAssessment],
    ) -> Dict[str, Any]:
        prov: Dict[str, Any] = {
            "decision_time": decision_time,
            "decision_policy_version": self.decision_policy_version,
            "context_id": market_context.context_id if market_context else "",
            "context_version": market_context.context_version if market_context else "",
            "strategy_count": len(strategy_assessments),
            "opportunity_id": opportunity.get("provenance", {}).get("run_id") if opportunity else "",
        }
        if opportunity and opportunity.get("provenance"):
            prov["opportunity_provenance"] = opportunity["provenance"]
        return prov
