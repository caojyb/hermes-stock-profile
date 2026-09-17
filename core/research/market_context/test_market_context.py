#!/usr/bin/env python3
"""
stock-work/core/research/market_context/test_market_context.py

Validation for Market Context Builder + Regime Engine V1.

Uses unittest so it can run without pytest.
"""

from __future__ import annotations

import unittest

from core.research.market_context.context_builder import (
    BreadthInputs,
    IndexTrendInputs,
    LiquidityInputs,
    MarketContextBuilder,
    VolatilityInputs,
)
from core.research.market_context.context_schema import (
    ConfidenceLevel,
    RiskState,
    StructuralState,
    TacticalState,
    TrendState,
    VolatilityState,
    LiquidityState,
    BreadthState,
)
from core.research.market_context.market_context import MarketContext
from core.research.market_context.strategy_context_analysis import StrategyContextAnalyzer
from core.research.strategy_registry.strategy_registry import build_default_registry


class TestPITSafety(unittest.TestCase):
    def test_decision_time_after_data_cutoff_rejected(self):
        with self.assertRaises(ValueError):
            MarketContextBuilder(decision_time="2026-08-22", data_cutoff="2026-08-21").build()

    def test_missing_trend_inputs_do_not_infer_bull_or_bear(self):
        builder = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21")
        ctx = builder.build()
        self.assertEqual(ctx.model.structural_state, StructuralState.UNKNOWN)
        self.assertEqual(ctx.model.trend_state, TrendState.UNKNOWN)

    def test_context_action_safe_always_false(self):
        builder = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21")
        ctx = builder.build()
        self.assertFalse(ctx.action_safe())
        self.assertTrue(ctx.is_research_only())


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_context_states(self):
        builder = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21")
        trend = IndexTrendInputs(close=10.0, ma20=9.8, ma60=9.5, ma120=9.2)
        breadth = BreadthInputs(up_ratio=0.7, new_high_ratio=0.1, new_low_ratio=0.05)
        volatility = VolatilityInputs(index_return=0.01, realized_vol_20d=0.25)
        liquidity = LiquidityInputs(amount_trend="RISING", volume_change=0.2)

        first = builder.build(trend, breadth, volatility, liquidity)
        second = builder.build(trend, breadth, volatility, liquidity)
        self.assertEqual(first.model.to_dict(), second.model.to_dict())
        self.assertEqual(first.provenance_fingerprint(), second.provenance_fingerprint())

    def test_replay_historical_date(self):
        trend = IndexTrendInputs(close=10.0, ma20=9.8, ma60=9.5, ma120=9.2)
        first = MarketContextBuilder(decision_time="2024-01-02", data_cutoff="2024-01-02").build(index_trend_inputs=trend)
        replay = MarketContextBuilder(decision_time="2024-01-02", data_cutoff="2024-01-02").build(index_trend_inputs=trend)
        self.assertEqual(first.model.to_dict(), replay.model.to_dict())


class TestRegimeEngineV1(unittest.TestCase):
    def test_structural_bull_requires_known_inputs(self):
        builder = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21")
        trend = IndexTrendInputs(close=10.0, ma20=9.8, ma60=9.5, ma120=9.2)
        volatility = VolatilityInputs(index_return=0.01, realized_vol_20d=0.18)
        liquidity = LiquidityInputs(amount_trend="RISING", volume_change=0.1)
        ctx = builder.build(trend, None, volatility, liquidity)
        self.assertEqual(ctx.model.structural_state, StructuralState.BULL)

    def test_tactical_mean_reversion_when_high_vol_tight_liquidity(self):
        builder = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21")
        volatility = VolatilityInputs(index_return=0.01, realized_vol_20d=0.4)
        liquidity = LiquidityInputs(amount_trend="DECLINING", volume_change=-0.2)
        ctx = builder.build(None, None, volatility, liquidity)
        self.assertEqual(ctx.model.tactical_state, TacticalState.MEAN_REVERSION)

    def test_risk_state_high_when_multiple_stresses(self):
        builder = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21")
        trend = IndexTrendInputs(close=10.0, ma20=10.1, ma60=10.2, ma120=10.3)
        volatility = VolatilityInputs(index_return=0.01, realized_vol_20d=0.4)
        liquidity = LiquidityInputs(amount_trend="DECLINING", volume_change=-0.2)
        ctx = builder.build(trend, None, volatility, liquidity)
        self.assertEqual(ctx.model.risk_state, RiskState.HIGH)


class TestActionLeakageGuard(unittest.TestCase):
    def test_no_trade_action_in_context_output(self):
        builder = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21")
        ctx = builder.build()
        data = ctx.to_dict()
        forbidden_keys = {"action", "decision", "trade", "order", "signal"}
        self.assertTrue(forbidden_keys.isdisjoint(data.keys()))

    def test_no_buy_sell_in_compatibility_assessment(self):
        registry = build_default_registry()
        analyzer = StrategyContextAnalyzer(registry)
        ctx = MarketContextBuilder(decision_time="2026-08-21", data_cutoff="2026-08-21").build()
        assessments = analyzer.assess_all(ctx)
        forbidden = {"BUY", "SELL", "WEIGHT", "ALLOCATION"}
        for assessment in assessments:
            self.assertTrue(forbidden.isdisjoint(assessment.reason.split()), f"forbidden token in reason: {assessment.reason}")


if __name__ == "__main__":
    unittest.main()
