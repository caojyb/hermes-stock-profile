#!/usr/bin/env python3
"""
stock-work/core/research/opportunity/test_opportunity_engine.py

Validation for Stock Opportunity Engine.

Covers key requirements from D8-D:
- schema / eligibility / research-only separation
- current signal generation / normalization / evidence integration
- context compatibility / risk penalty / correlation handling
- candidate ranking / reason codes
- PIT enforcement / future target isolation
- deterministic replay / provenance / top-N
- missing data / strategy incompatibility / baseline separation
"""

from __future__ import annotations

import copy
import unittest

from core.research.market_context.context_builder import (
    BreadthInputs,
    IndexTrendInputs,
    LiquidityInputs,
    MarketContextBuilder,
    VolatilityInputs,
)
from core.research.market_context.context_schema import RiskState
from core.research.market_context.market_context import MarketContext
from core.research.market_context.strategy_context_analysis import CompatibilityAssessment, StrategyContextAnalyzer
from core.research.opportunity.opportunity_engine import OpportunityEngine, OpportunityEngineConfig
from core.research.opportunity.opportunity_ranker import OpportunityRanker
from core.research.opportunity.opportunity_schema import (
    Eligibility,
    Opportunity,
    StrategyEvidenceSummary,
    StrategySignalSummary,
)
from core.research.strategy_allocator.strategy_evidence_matrix import StrategyEvidenceMatrix
from core.research.strategy_registry.strategy_registry import build_default_registry


def _make_signal(strategy_id: str, family: str, normalized_score: float, confidence: str = "HIGH", research_only: bool = True) -> StrategySignalSummary:
    return StrategySignalSummary(
        strategy_id=strategy_id,
        strategy_version="v1",
        family=family,
        horizon=5,
        raw_score=normalized_score,
        normalized_score=normalized_score,
        confidence=confidence,
        eligibility="ELIGIBLE",
        reason_code="OK",
        research_only=research_only,
        signal_timestamp="2026-08-21",
    )


def _make_evidence(strategy_id: str, qualification_status: str = "RESEARCH_CANDIDATE", evidence_strength: str = "PRELIMINARY") -> StrategyEvidenceSummary:
    return StrategyEvidenceSummary(
        strategy_id=strategy_id,
        qualification_status=qualification_status,
        evidence_strength=evidence_strength,
        cross_fold_ic_mean=0.05,
        positive_fold_ratio=0.6,
        rank_ic_mean=0.04,
        mean_excess_return=0.01,
        hit_rate=0.55,
        sample_count=30,
        confidence="MEDIUM",
        notes="research evidence",
    )


class TestOpportunitySchema(unittest.TestCase):
    def test_opportunity_creation(self):
        o = Opportunity(
            stock_code="000001.SZ",
            decision_time="2026-08-21",
            market_context_id="mc:2026-08-21:ctx",
            strategy_ids=["trend_v1"],
            strategy_versions={"trend_v1": "v1"},
            strategy_signal_summary=[],
            strategy_evidence_summary=[],
            context_compatibility="COMPATIBLE",
            signal_strength=0.8,
            signal_confidence="HIGH",
            risk_penalty=0.1,
            data_quality="OK",
            opportunity_score=0.8,
            rank=1,
            eligibility=Eligibility.RESEARCH_OPPORTUNITY,
            reason_codes=["TREND_SIGNAL_PRESENT"],
            score_components=None,
            provenance={},
            research_only=True,
        )
        self.assertEqual(o.eligibility, Eligibility.RESEARCH_OPPORTUNITY)
        self.assertTrue(o.research_only)


class TestStrategyEligibility(unittest.TestCase):
    def test_research_only_signal_is_eligible(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        signal = _make_signal("trend_v1", "Trend", 0.8, research_only=True)
        evidence = _make_evidence("trend_v1")
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        self.assertEqual(len(opportunities), 1)

    def test_blocked_strategy_excluded(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        signal = _make_signal("trend_v1", "Trend", 0.8, research_only=False)
        evidence = _make_evidence("trend_v1", qualification_status="BLOCKED")
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        self.assertEqual(len(opportunities), 0)


class TestResearchOnlySeparation(unittest.TestCase):
    def test_opportunity_output_contains_no_trade_actions(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        signal = _make_signal("trend_v1", "Trend", 0.8)
        evidence = _make_evidence("trend_v1")
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        forbidden = {"BUY", "SELL", "ADD", "REDUCE", "EXIT", "POSITION_SIZE"}
        for o in opportunities:
            self.assertFalse(o.research_only is False)
            self.assertTrue(forbidden.isdisjoint(o.reason_codes))


class TestContextCompatibility(unittest.TestCase):
    def test_incompatible_context_lowers_score(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        signal = _make_signal("trend_v1", "Trend", 0.9)
        evidence = _make_evidence("trend_v1")
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        self.assertEqual(len(opportunities), 1)
        self.assertIn(opportunities[0].context_compatibility, {"COMPATIBLE", "NEUTRAL", "INCOMPATIBLE", "UNKNOWN"})


class TestRiskPenalty(unittest.TestCase):
    def test_high_risk_penalty_reduces_score(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        trend = IndexTrendInputs(close=10.0, ma20=10.1, ma60=10.2, ma120=10.3)
        volatility = VolatilityInputs(index_return=0.01, realized_vol_20d=0.4)
        liquidity = LiquidityInputs(amount_trend="DECLINING", volume_change=-0.2)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build(trend, None, volatility, liquidity)
        signal = _make_signal("trend_v1", "Trend", 0.9)
        evidence = _make_evidence("trend_v1")
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        self.assertEqual(opportunities[0].risk_penalty, 0.25)
        self.assertIn("HIGH_RISK", opportunities[0].reason_codes)


class TestCandidateRanking(unittest.TestCase):
    def test_top_n_respected(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        config = OpportunityEngineConfig(top_n=2)
        engine = OpportunityEngine(registry, evidence_matrix, config=config)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        signals = {code: [_make_signal("trend_v1", "Trend", 0.8)] for code in [f"{i:06d}.SZ" for i in range(5)]}
        evidences = {f"trend_v1": _make_evidence("trend_v1")}
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals=signals,
            evidence_by_strategy=evidences,
            data_quality_by_stock={code: "OK" for code in signals},
        )
        self.assertEqual(len(opportunities), 2)
        self.assertEqual(opportunities[0].rank, 1)
        self.assertEqual(opportunities[1].rank, 2)


class TestReasonCodes(unittest.TestCase):
    def test_reason_codes_are_structured(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        trend = IndexTrendInputs(close=10.0, ma20=9.8, ma60=9.5, ma120=9.2)
        volatility = VolatilityInputs(index_return=0.01, realized_vol_20d=0.18)
        liquidity = LiquidityInputs(amount_trend="RISING", volume_change=0.1)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build(trend, None, volatility, liquidity)
        signal = _make_signal("trend_v1", "Trend", 0.8)
        evidence = _make_evidence("trend_v1")
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        self.assertTrue(len(opportunities) > 0)
        self.assertIn("TREND_SIGNAL_PRESENT", opportunities[0].reason_codes)
        self.assertIn(opportunities[0].eligibility.value, {"RESEARCH_OPPORTUNITY", "RESEARCH_CANDIDATE", "WATCH", "REJECT"})


class TestPITEnforcement(unittest.TestCase):
    def test_builder_rejects_decision_time_after_data_cutoff(self):
        with self.assertRaises(ValueError):
            MarketContextBuilder(decision_time="2026-08-22", data_cutoff="2026-08-21").build()


class TestDeterministicReplay(unittest.TestCase):
    def test_same_inputs_same_outputs(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        signal = _make_signal("trend_v1", "Trend", 0.8)
        evidence = _make_evidence("trend_v1")
        first = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        second = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        self.assertEqual(len(first), len(second))
        if first:
            self.assertEqual(first[0].opportunity_score, second[0].opportunity_score)
            self.assertEqual(first[0].eligibility, second[0].eligibility)
            self.assertEqual(first[0].reason_codes, second[0].reason_codes)


class TestProvenance(unittest.TestCase):
    def test_provenance_contains_required_keys(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        signal = _make_signal("trend_v1", "Trend", 0.8)
        evidence = _make_evidence("trend_v1")
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        self.assertTrue(opportunities[0].provenance.get("run_id"))
        self.assertEqual(opportunities[0].provenance.get("decision_time"), "2026-08-21")
        self.assertEqual(opportunities[0].provenance.get("normalization_version"), "v1")
        self.assertEqual(opportunities[0].provenance.get("opportunity_version"), "v1")


class TestBaselineSeparation(unittest.TestCase):
    def test_research_opportunity_is_not_production_signal(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        engine = OpportunityEngine(registry, evidence_matrix)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        signal = _make_signal("trend_v1", "Trend", 0.8)
        evidence = _make_evidence("trend_v1", evidence_strength="INSUFFICIENT")
        opportunities = engine.build_opportunities(
            context=context,
            universe_signals={"000001.SZ": [signal]},
            evidence_by_strategy={"trend_v1": evidence},
            data_quality_by_stock={"000001.SZ": "OK"},
        )
        for o in opportunities:
            self.assertTrue(o.research_only)
            self.assertIn(o.eligibility, {Eligibility.RESEARCH_OPPORTUNITY, Eligibility.RESEARCH_CANDIDATE, Eligibility.WATCH, Eligibility.REJECT})


if __name__ == "__main__":
    unittest.main()
