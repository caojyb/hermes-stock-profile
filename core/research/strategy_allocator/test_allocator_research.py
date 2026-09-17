#!/usr/bin/env python3
"""
stock-work/core/research/strategy_allocator/test_allocator_research.py

Phase C4: Validation for Strategy Allocation Intelligence.

Covers:
1. Regime isolation: different regimes do not mix statistics
2. Sample confidence: insufficient samples -> UNKNOWN
3. No future leakage
4. Allocator no action leakage
5. Deterministic replay
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
from core.research.strategy_allocator.allocator_research import AllocatorResearch
from core.research.strategy_allocator.regime_strategy_analysis import RegimeStrategyAnalyzer, StrategyRegimePerformance
from core.research.strategy_allocator.strategy_evidence_matrix import StrategyEvidenceMatrix
from core.research.strategy_registry.strategy_registry import build_default_registry


class TestRegimeIsolation(unittest.TestCase):
    def test_regimes_do_not_mix_in_analysis(self):
        analyzer = RegimeStrategyAnalyzer()
        analyzer.add_record("trend_v1", "BULL", 5, "fold_a", 0.1, 0.05, 0.6, -0.05)
        analyzer.add_record("trend_v1", "BEAR", 5, "fold_a", -0.2, 0.1, 0.3, -0.15)
        analyzer.add_record("trend_v1", "BULL", 5, "fold_b", 0.15, 0.04, 0.65, -0.03)

        results = analyzer.analyze()
        bull_results = [r for r in results if r.regime_state == "BULL"]
        bear_results = [r for r in results if r.regime_state == "BEAR"]

        self.assertEqual(len(bull_results), 2)
        self.assertEqual(len(bear_results), 1)
        for r in bull_results:
            self.assertEqual(r.regime_state, "BULL")
        for r in bear_results:
            self.assertEqual(r.regime_state, "BEAR")


class TestSampleConfidence(unittest.TestCase):
    def test_insufficient_samples_yield_unknown_confidence(self):
        analyzer = RegimeStrategyAnalyzer()
        analyzer.add_record("trend_v1", "BULL", 5, "fold_a", 0.1, 0.05, 0.6, -0.05)
        results = analyzer.analyze()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].confidence, "UNKNOWN")

    def test_moderate_samples_yield_low_confidence(self):
        analyzer = RegimeStrategyAnalyzer()
        for _ in range(10):
            analyzer.add_record("trend_v1", "BULL", 5, "fold_a", 0.1, 0.05, 0.6, -0.05)
        results = analyzer.analyze()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].confidence, "LOW")


class TestNoFutureLeakage(unittest.TestCase):
    def test_future_data_marker_recorded_in_audit_trace(self):
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        context.mark_future_data("test_source", "trend_state")
        self.assertIn("trend_state:future_data_source", context.audit_trace)
        self.assertFalse(context.action_safe())


class TestAllocatorNoActionLeakage(unittest.TestCase):
    def test_recommendation_contains_no_trade_actions(self):
        registry = build_default_registry()
        evidence_matrix = StrategyEvidenceMatrix([])
        allocator = AllocatorResearch(registry, evidence_matrix)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        recommendations = allocator.recommend(context)
        forbidden = {"BUY", "SELL", "WEIGHT", "ALLOCATION", "POSITION_SIZE"}
        for recommendation in recommendations:
            self.assertTrue(forbidden.isdisjoint(recommendation.rationale.split()))


class TestDeterministicReplay(unittest.TestCase):
    def test_same_inputs_same_recommendations(self):
        registry = build_default_registry()
        analyzer = RegimeStrategyAnalyzer()
        analyzer.add_record("trend_v1", "BULL", 5, "fold_a", 0.1, 0.05, 0.6, -0.05)
        performances = analyzer.analyze()
        evidence_matrix = StrategyEvidenceMatrix(performances)
        allocator = AllocatorResearch(registry, evidence_matrix)
        context = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()

        first = allocator.recommend(context)
        second = allocator.recommend(context)
        self.assertEqual(len(first), len(second))
        for a, b in zip(first, second):
            self.assertEqual(a.strategy_id, b.strategy_id)
            self.assertEqual(a.compatibility_score, b.compatibility_score)
            self.assertEqual(a.evidence_score, b.evidence_score)
            self.assertEqual(a.risk_score, b.risk_score)


if __name__ == "__main__":
    unittest.main()
