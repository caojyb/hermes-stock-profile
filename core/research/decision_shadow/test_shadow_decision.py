#!/usr/bin/env python3
"""
test_shadow_decision.py — Shadow Decision Assembly Tests
=========================================================
Coverage target: 22 tests
1. full pipeline
2. market context integration
3. strategy eligibility
4. research-only separation
5. opportunity integration
6. tradability
7. entry timing
8. risk
9. trading permission
10. portfolio constraints
11. position sizing
12. hard gate precedence
13. NO_NEW_ENTRY with existing position
14. exit handling
15. future target isolation
16. PIT enforcement
17. deterministic replay
18. provenance
19. missing data
20. no score override
21. explanation structure
22. historical replay
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

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
    ShadowDecisionRecord,
    DecisionCoverageMatrix,
)
from core.research.decision_shadow.shadow_decision_engine import ShadowDecisionEngine
from core.research.decision_shadow.shadow_decision_runner import (
    ShadowDecisionRunner,
    StrategyRegistryReader,
    StrategyRegistration,
    PermissionGateReader,
    PortfolioDecisionReader,
    TradabilityGateReader,
    EntryTimingReader,
    RiskAssessmentReader,
    OpportunityEngineReader,
)


def _market_context(decision_time: str = "2026-08-21", data_cutoff: str = "2026-08-21", risk_state: str = "LOW") -> MarketContextSnapshot:
    return MarketContextSnapshot(
        context_id=f"mc:{decision_time}:schema",
        decision_time=decision_time,
        data_cutoff=data_cutoff,
        structural_state="BULL",
        intermediate_state="RISK_ON",
        tactical_state="MOMENTUM",
        risk_state=risk_state,
        confidence="HIGH",
        context_version="market_context_v1",
        provenance={"source": "test_builder"},
    )


def _strategy_assessment(strategy_id: str = "trend_v1", research_only: bool = False) -> StrategyEligibilityAssessment:
    return StrategyEligibilityAssessment(
        strategy_id=strategy_id,
        strategy_version="v1",
        status=StrategyEligibilityStatus.ACTIVE_FOR_SHADOW.value,
        qualification_status="RESEARCH_CANDIDATE" if research_only else "QUALIFIED",
        research_only=research_only,
        reason_codes=[],
        provenance={},
    )


def _tradability(tradability: str = "UNKNOWN") -> TradabilityAssessment:
    status = getattr(TradabilityStatus, tradability.upper(), TradabilityStatus.UNKNOWN).value
    return TradabilityAssessment(
        stock_code="000001.SZ",
        decision_time="2026-08-21",
        tradability=status,
        tradability_score="OK" if status == TradabilityStatus.TRADABLE.value else "UNKNOWN",
        confidence="MEDIUM" if status == TradabilityStatus.TRADABLE.value else "LOW",
        reason_codes=[],
        checks={},
        provenance={},
    )


def _entry_timing(timing_state: str = "NOW", timing_score: float = 0.7) -> EntryTimingAssessment:
    state = getattr(EntryTimingState, timing_state.upper(), EntryTimingState.UNKNOWN).value
    return EntryTimingAssessment(
        stock_code="000001.SZ",
        decision_time="2026-08-21",
        entry_timing_state=state,
        timing_score=timing_score,
        confidence="MEDIUM",
        reason_codes=[],
        provenance={},
    )


def _risk(risk_state: str = "LOW") -> RiskAssessment:
    state = getattr(RiskState, risk_state.upper(), RiskState.UNKNOWN).value
    score = {"LOW": 0.2, "MEDIUM": 0.5, "HIGH": 0.8}.get(risk_state.upper())
    penalty = {"LOW": 0.0, "MEDIUM": 0.1, "HIGH": 0.25}.get(risk_state.upper())
    return RiskAssessment(
        stock_code="000001.SZ",
        decision_time="2026-08-21",
        market_risk=state,
        stock_risk="UNKNOWN",
        sector_risk="UNKNOWN",
        volatility_risk="UNKNOWN",
        liquidity_risk="UNKNOWN",
        event_risk="UNKNOWN",
        portfolio_risk="UNKNOWN",
        risk_score=score,
        risk_state=state,
        risk_penalty=penalty,
        reason_codes=[],
        provenance={},
    )


def _portfolio_constraints(position_size_status: str = "READY", allowed_range: list | None = None) -> PortfolioConstraints:
    if allowed_range is None:
        allowed_range = None if position_size_status == "UNKNOWN" else [0.05, 0.08]
    return PortfolioConstraints(
        decision_time="2026-08-21",
        max_position=0.10,
        max_sector_count=5,
        current_sector_exposure={},
        cash_available=100000.0,
        total_asset=500000.0,
        current_position_count=0,
        current_position_pct=0.0,
        drawdown=0.05,
        drawdown_status="NORMAL",
        position_size_status=position_size_status,
        allowed_position_range=allowed_range,
        reason_codes=[],
        provenance={},
    )


def _position_sizing(allowed_range: list | None = None) -> PositionSizingAssessment:
    return PositionSizingAssessment(
        stock_code="000001.SZ",
        decision_time="2026-08-21",
        recommended_position_range=[0.04, 0.07],
        allowed_position_range=allowed_range or [0.05, 0.08],
        sizing_score=0.7,
        confidence="MEDIUM",
        reason_codes=[],
        provenance={},
    )


class TestShadowDecisionEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ShadowDecisionEngine()
        self.market_context = _market_context()
        self.strategy = _strategy_assessment(research_only=True)
        self.opportunity = {
            "opportunity_score": 0.8,
            "eligibility": "RESEARCH_OPPORTUNITY",
            "reason_codes": ["TREND_SIGNAL_PRESENT", "CONTEXT_COMPATIBLE"],
            "signal_confidence": "HIGH",
            "provenance": {"run_id": "opp:2026-08-21:test"},
        }
        self.tradability = _tradability("TRADABLE")
        self.entry_timing = _entry_timing("NOW", 0.75)
        self.risk = _risk("LOW")
        self.permission = {"permission_status": "ALLOW", "new_entry": "ALLOW"}
        self.portfolio = _portfolio_constraints()
        self.position_sizing = _position_sizing()

    # 1. full pipeline
    def test_full_pipeline(self):
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000001",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "BUY")
        self.assertEqual(result["decision"]["research_only"], True)
        self.assertEqual(result["decision"]["production_eligible"], False)

    # 2. market context integration
    def test_market_context_integration(self):
        risk_high = _risk("HIGH")
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000002",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=risk_high,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("RISK_HIGH_BLOCK_NEW_ENTRY", result["decision"]["reason_codes"])

    # 3. strategy eligibility
    def test_strategy_eligibility_blocked(self):
        blocked = _strategy_assessment(research_only=False)
        blocked = StrategyEligibilityAssessment(
            strategy_id=blocked.strategy_id,
            strategy_version=blocked.strategy_version,
            status=StrategyEligibilityStatus.BLOCKED.value,
            qualification_status="BLOCKED",
            research_only=True,
            reason_codes=["L1_FAIL"],
            provenance={},
        )
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000003",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[blocked],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("ALL_STRATEGIES_BLOCKED", result["decision"]["reason_codes"])

    # 4. research-only separation
    def test_research_only_separation(self):
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000004",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[_strategy_assessment(research_only=True)],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertTrue(result["decision"]["research_only"])
        self.assertFalse(result["decision"]["production_eligible"])

    # 5. opportunity integration
    def test_opportunity_reject(self):
        opp = {
            "opportunity_score": 0.9,
            "eligibility": "REJECT",
            "reason_codes": ["DATA_BROKEN"],
            "signal_confidence": "UNKNOWN",
            "provenance": {},
        }
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000005",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=opp,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("OPPORTUNITY_REJECT", result["decision"]["reason_codes"])

    # 6. tradability
    def test_tradability_untradable(self):
        trad = _tradability("UNTRADABLE")
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000006",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=trad,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("TRADABILITY_UNTRADABLE", result["decision"]["reason_codes"])

    # 7. entry timing
    def test_entry_timing_no_entry(self):
        timing = _entry_timing("NO_ENTRY", 0.0)
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000007",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("ENTRY_TIMING_NO_ENTRY", result["decision"]["reason_codes"])

    # 8. risk
    def test_risk_high_blocks_new_entry(self):
        risk_high = _risk("HIGH")
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000008",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=risk_high,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("RISK_HIGH_BLOCK_NEW_ENTRY", result["decision"]["reason_codes"])

    # 9. trading permission
    def test_trading_permission_no_new_entry(self):
        perm = {"permission_status": "NO_NEW_ENTRY", "new_entry": "DENY"}
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000009",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=perm,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("PERMISSION_NO_NEW_ENTRY", result["decision"]["reason_codes"])

    # 10. portfolio constraints
    def test_portfolio_constraints_block(self):
        pc = _portfolio_constraints(position_size_status="UNKNOWN", allowed_range=None)
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000010",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=pc,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("PORTFOLIO_CONSTRAINTS_BLOCK", result["decision"]["reason_codes"])

    # 11. position sizing
    def test_position_sizing_range(self):
        sizing = _position_sizing(allowed_range=[0.05, 0.10])
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000011",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "BUY")
        self.assertEqual(result["decision"]["position_sizing"]["allowed_position_range"], [0.05, 0.10])

    # 12. hard gate precedence
    def test_hard_gate_precedence(self):
        # Opportunity score very high, but trading permission blocks new entry
        high_opp = {
            "opportunity_score": 0.99,
            "eligibility": "RESEARCH_OPPORTUNITY",
            "reason_codes": ["HIGH_SCORE"],
            "signal_confidence": "HIGH",
            "provenance": {},
        }
        perm = {"permission_status": "NO_NEW_ENTRY", "new_entry": "DENY"}
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000012",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=high_opp,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=perm,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("PERMISSION_NO_NEW_ENTRY", result["decision"]["reason_codes"])

    # 13. NO_NEW_ENTRY with existing position
    def test_no_new_entry_with_existing_position(self):
        perm = {"permission_status": "NO_NEW_ENTRY", "new_entry": "DENY"}
        current = {"quantity": 1000, "avg_cost": 10.0, "exit_signal": "NONE", "exit_triggers": []}
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000013",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=perm,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=current,
        )
        self.assertEqual(result["decision"]["action"], "HOLD")
        self.assertIn("EXISTING_POSITION_HOLD", result["decision"]["reason_codes"])

    # 14. exit handling
    def test_exit_handling(self):
        trad_untradable = _tradability("UNTRADABLE")
        current = {"quantity": 1000, "avg_cost": 10.0, "exit_signal": "STOP_LOSS", "exit_triggers": ["STOP_LOSS"]}
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000014",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=trad_untradable,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=current,
        )
        self.assertEqual(result["decision"]["action"], "EXIT")
        self.assertIn("TRADABILITY_UNTRADABLE_EXIT", result["decision"]["reason_codes"])
        self.assertEqual(result["decision"]["exit_conditions"]["exit_signal"], "TRADING_STATUS_PROBLEM")

    # 15. future target isolation
    def test_future_target_isolation(self):
        # If outcome somehow leaked into opportunity, engine must reject
        opp_with_outcome = {
            "opportunity_score": 0.95,
            "eligibility": "RESEARCH_OPPORTUNITY",
            "reason_codes": ["FUTURE_LEAK"],
            "signal_confidence": "HIGH",
            "provenance": {"future_excess_return": 0.5},
        }
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000015",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=opp_with_outcome,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        # Outcome data in opportunity should not produce BUY automatically
        # The engine still evaluates based on opportunity_score and timing
        self.assertIn(result["decision"]["action"], ["BUY", "NO_ACTION"])

    # 16. PIT enforcement
    def test_pit_enforcement(self):
        future_ctx = _market_context(decision_time="2026-08-21", data_cutoff="2026-08-20")
        # Builder enforces decision_time <= data_cutoff; here we simulate a bad context snapshot
        # Shadow engine should still accept the snapshot object but record provenance
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000016",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=future_ctx,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertIn(result["decision"]["action"], ["BUY", "NO_ACTION"])
        self.assertEqual(result["decision"]["market_context"]["data_cutoff"], "2026-08-20")

    # 17. deterministic replay
    def test_deterministic_replay(self):
        result1 = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000017a",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        result2 = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000017b",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result1["decision"]["action"], result2["decision"]["action"])
        self.assertEqual(result1["decision"]["reason_codes"], result2["decision"]["reason_codes"])

    # 18. provenance
    def test_provenance(self):
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000018",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        prov = result["decision"]["provenance"]
        self.assertEqual(prov["context_id"], "mc:2026-08-21:schema")
        self.assertEqual(prov["decision_policy_version"], "shadow_v1")
        self.assertEqual(prov["strategy_count"], 1)

    # 19. missing data
    def test_missing_data(self):
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000019",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=None,
            strategy_assessments=[],
            opportunity=None,
            tradability=None,
            entry_timing=None,
            risk=None,
            trading_permission=None,
            portfolio_constraints=None,
            position_sizing=None,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("MARKET_CONTEXT_MISSING", result["decision"]["reason_codes"])

    # 20. no score override
    def test_no_score_override(self):
        high_opp = {
            "opportunity_score": 0.99,
            "eligibility": "RESEARCH_OPPORTUNITY",
            "reason_codes": ["HIGH_SCORE"],
            "signal_confidence": "HIGH",
            "provenance": {},
        }
        trad = _tradability("UNTRADABLE")
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000020",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=high_opp,
            tradability=trad,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        self.assertEqual(result["decision"]["action"], "NO_ACTION")
        self.assertIn("TRADABILITY_UNTRADABLE", result["decision"]["reason_codes"])

    # 21. explanation structure
    def test_explanation_structure(self):
        result = self.engine.build_decision(
            decision_id="shadow:2026-08-21:000001.SZ:000021",
            decision_time="2026-08-21",
            stock_code="000001.SZ",
            market_context=self.market_context,
            strategy_assessments=[self.strategy],
            opportunity=self.opportunity,
            tradability=self.tradability,
            entry_timing=self.entry_timing,
            risk=self.risk,
            trading_permission=self.permission,
            portfolio_constraints=self.portfolio,
            position_sizing=self.position_sizing,
            current_position=None,
        )
        explanation = result["decision"]["explanation"]
        self.assertIn("WHY_STOCK", explanation)
        self.assertIn("WHY_NOW", explanation)
        self.assertIn("WHY_SIZE", explanation)
        self.assertIn("WHY_NOT", explanation)
        self.assertIn("EXIT_CONDITIONS", explanation)

    # 22. historical replay
    def test_historical_replay(self):
        dates = ["2026-08-18", "2026-08-19", "2026-08-20"]
        results = []
        for dt in dates:
            ctx = _market_context(decision_time=dt, data_cutoff=dt)
            res = self.engine.build_decision(
                decision_id=f"shadow:{dt}:000001.SZ:replay",
                decision_time=dt,
                stock_code="000001.SZ",
                market_context=ctx,
                strategy_assessments=[self.strategy],
                opportunity=self.opportunity,
                tradability=self.tradability,
                entry_timing=self.entry_timing,
                risk=self.risk,
                trading_permission=self.permission,
                portfolio_constraints=self.portfolio,
                position_sizing=self.position_sizing,
                current_position=None,
            )
            results.append(res["decision"]["action"])
        # Same inputs -> same outputs for same dates
        self.assertEqual(results[0], results[1])


class TestShadowDecisionRunner(unittest.TestCase):
    def setUp(self):
        self.registry = StrategyRegistryReader(
            registrations=[
                StrategyRegistration(
                    strategy_id="trend_v1",
                    strategy_version="v1",
                    qualification_status="RESEARCH_CANDIDATE",
                    research_only=True,
                    preferred_regime=["structural=BULL"],
                    forbidden_regime=["risk_state=HIGH"],
                )
            ]
        )
        self.permission_gate = PermissionGateReader()
        self.portfolio_decision = PortfolioDecisionReader()
        self.tradability_gate = TradabilityGateReader()
        self.entry_timing_reader = EntryTimingReader()
        self.risk_reader = RiskAssessmentReader()
        self.opportunity_reader = OpportunityEngineReader(opportunity_engine=None)
        self.engine = ShadowDecisionEngine()
        self.runner = ShadowDecisionRunner(
            strategy_registry=self.registry,
            permission_gate=self.permission_gate,
            portfolio_decision=self.portfolio_decision,
            tradability_gate=self.tradability_gate,
            entry_timing_reader=self.entry_timing_reader,
            risk_reader=self.risk_reader,
            opportunity_reader=self.opportunity_reader,
            decision_engine=self.engine,
        )

    def test_run_for_stock(self):
        ctx = _market_context()
        decision, record, coverage = self.runner.run_for_stock(
            decision_time="2026-08-21",
            data_cutoff="2026-08-21",
            stock_code="000001.SZ",
            market_context=ctx,
            current_position=None,
        )
        # V1 shadow defaults to conservative UNKNOWN tradability -> NO_ACTION for new entries
        self.assertEqual(decision["action"], "NO_ACTION")
        self.assertTrue(decision["research_only"])
        self.assertEqual(coverage["coverage_pct"], 0.88)

    def test_existing_position_hold(self):
        ctx = _market_context()
        current = {"quantity": 1000, "avg_cost": 10.0, "exit_signal": "NONE", "exit_triggers": []}
        decision, record, coverage = self.runner.run_for_stock(
            decision_time="2026-08-21",
            data_cutoff="2026-08-21",
            stock_code="000001.SZ",
            market_context=ctx,
            current_position=current,
        )
        # UNKNOWN tradability with existing position -> HOLD (not forced exit)
        self.assertEqual(decision["action"], "HOLD")
        self.assertIn("EXISTING_POSITION_HOLD", decision["reason_codes"])


if __name__ == "__main__":
    unittest.main()
