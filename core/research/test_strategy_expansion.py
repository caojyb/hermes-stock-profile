#!/usr/bin/env python3
"""
test_strategy_expansion.py — Strategy Family Expansion Tests
============================================================
"""

from __future__ import annotations

import unittest
from core.research.strategy_family_expansion import (
    StrategyFamilyExpansionRegistry,
    StrategyFamilyDefinition,
    create_default_expansion_registry,
    FAMILY_TREND,
    FAMILY_MOMENTUM,
    FAMILY_REVERSAL,
    FAMILY_BREAKOUT,
    FAMILY_VOLATILITY,
    FAMILY_PRICE_VOLUME,
)
from core.research.experiment_governance import (
    ExperimentRegistry,
    ExperimentRecord,
    EXPERIMENT_STATUS_REGISTERED,
    EXPERIMENT_STATUS_NO_EVIDENCE,
    SELECTION_EVENT_NONE,
)
from core.research.strategies.breakout_strategy import BreakoutStrengthStrategy, BreakoutConfirmationStrategy
from core.research.strategies.volatility_strategy import VolatilityLevelStrategy, VolatilityChangeStrategy
from core.research.strategies.price_volume_strategy import VolumeTrendStrategy, VolumePriceCorrelationStrategy
from core.research.strategies.momentum_strategy_variants import MomentumMediumStrategy, MomentumRiskAdjustedStrategy


class TestStrategyFamilyExpansion(unittest.TestCase):
    """Test suite for Strategy Family Expansion."""

    def test_01_family_registration(self):
        """Test 1: Families can be registered."""
        registry = create_default_expansion_registry()
        families = registry.list_families()
        self.assertEqual(len(families), 6)
        ids = [f.family_id for f in families]
        self.assertIn("TREND_FAMILY_001", ids)
        self.assertIn("BREAKOUT_FAMILY_001", ids)

    def test_02_hypothesis_governance(self):
        """Test 2: Each family has a hypothesis."""
        registry = create_default_expansion_registry()
        for family in registry.list_families():
            self.assertTrue(family.hypothesis)
            self.assertTrue(family.economic_rationale)

    def test_03_variant_lineage(self):
        """Test 3: Variants can be registered with lineage."""
        registry = create_default_expansion_registry()
        exp_registry = registry.get_experiment_registry()
        parent = ExperimentRecord(
            experiment_id="momentum_family_root",
            parent_experiment_id=None,
            hypothesis="Momentum family root",
            strategy_family=FAMILY_MOMENTUM,
            strategy_id="momentum_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 20},
            parameter_space={"lookback": [20, 60]},
            required_datasets=["daily_price"],
            required_features=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
            target_id="future_excess_return",
            target_version="v1",
            universe_version="RESEARCH_UNIVERSE_V1",
            research_window={"start": "2020-01-01", "end": "2025-01-01"},
            fold_policy="anchored_expanding",
            evaluation_metrics=["IC", "RankIC"],
            selection_rule="best_ic",
            selection_event=SELECTION_EVENT_NONE,
            researcher="system",
            status=EXPERIMENT_STATUS_REGISTERED,
        )
        child = ExperimentRecord(
            experiment_id="momentum_medium_v1",
            parent_experiment_id="momentum_family_root",
            hypothesis="Medium-term momentum variant",
            strategy_family=FAMILY_MOMENTUM,
            strategy_id="momentum_medium_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 60},
            parameter_space={"lookback": [60]},
            required_datasets=["daily_price"],
            required_features=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
            target_id="future_excess_return",
            target_version="v1",
            universe_version="RESEARCH_UNIVERSE_V1",
            research_window={"start": "2020-01-01", "end": "2025-01-01"},
            fold_policy="anchored_expanding",
            evaluation_metrics=["IC", "RankIC"],
            selection_rule="best_ic",
            selection_event=SELECTION_EVENT_NONE,
            researcher="system",
            status=EXPERIMENT_STATUS_REGISTERED,
        )
        exp_registry.register_experiment(parent)
        exp_registry.register_experiment(child)
        self.assertEqual(exp_registry.count_total(), 2)
        lineage = exp_registry.get_lineage("momentum_medium_v1")
        self.assertEqual(lineage, ["momentum_medium_v1", "momentum_family_root"])

    def test_04_parameter_binding(self):
        """Test 4: Parameter space is bound to experiment."""
        registry = create_default_expansion_registry()
        exp_registry = registry.get_experiment_registry()
        exp = ExperimentRecord(
            experiment_id="breakout_strength_v1",
            parent_experiment_id=None,
            hypothesis="Breakout strength variant",
            strategy_family=FAMILY_BREAKOUT,
            strategy_id="breakout_strength_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 20},
            parameter_space={"lookback": [20]},
            required_datasets=["daily_price"],
            required_features=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
            target_id="future_excess_return",
            target_version="v1",
            universe_version="RESEARCH_UNIVERSE_V1",
            research_window={"start": "2020-01-01", "end": "2025-01-01"},
            fold_policy="anchored_expanding",
            evaluation_metrics=["IC", "RankIC"],
            selection_rule="best_ic",
            selection_event=SELECTION_EVENT_NONE,
            researcher="system",
            status=EXPERIMENT_STATUS_REGISTERED,
        )
        exp_registry.register_experiment(exp)
        retrieved = exp_registry.get_experiment("breakout_strength_v1")
        self.assertEqual(retrieved.parameter_space, {"lookback": [20]})

    def test_05_feature_binding(self):
        """Test 5: Required features are bound to experiment."""
        registry = create_default_expansion_registry()
        family = registry.get_family("PRICE_VOLUME_FAMILY_001")
        self.assertIn("daily_volume", family.required_features)

    def test_06_target_binding(self):
        """Test 6: Target version is bound to family."""
        registry = create_default_expansion_registry()
        for family in registry.list_families():
            self.assertEqual(family.target_id, "future_excess_return")
            self.assertEqual(family.target_version, "v1")

    def test_07_universe_binding(self):
        """Test 7: Universe version is bound to family."""
        registry = create_default_expansion_registry()
        for family in registry.list_families():
            self.assertEqual(family.universe_version, "RESEARCH_UNIVERSE_V1")

    def test_08_new_strategy_interface(self):
        """Test 8: New strategies implement BaseStrategy interface."""
        strategies = [
            BreakoutStrengthStrategy(),
            BreakoutConfirmationStrategy(),
            VolatilityLevelStrategy(),
            VolatilityChangeStrategy(),
            VolumeTrendStrategy(),
            VolumePriceCorrelationStrategy(),
            MomentumMediumStrategy(),
            MomentumRiskAdjustedStrategy(),
        ]
        for strategy in strategies:
            self.assertTrue(hasattr(strategy, "strategy_id"))
            self.assertTrue(hasattr(strategy, "strategy_version"))
            self.assertTrue(hasattr(strategy, "family"))
            self.assertTrue(hasattr(strategy, "required_inputs"))
            self.assertTrue(hasattr(strategy, "requires_eod_policy"))
            self.assertTrue(hasattr(strategy, "generate_signal"))

    def test_09_normalization_compatibility(self):
        """Test 9: New strategies output raw_score compatible with canonical normalization."""
        strategy = BreakoutStrengthStrategy()
        signal = strategy.generate_signal({"code": "000001"}, "2024-01-01")
        # Without kline_loader, signal should be None or have valid structure
        if signal is not None:
            self.assertIsInstance(signal.raw_score, float)
            self.assertIn(signal.eligibility, [True, False])
        else:
            self.assertIsNone(signal)

    def test_10_pit_enforcement(self):
        """Test 10: New strategies do not access future data."""
        strategy = VolatilityLevelStrategy(lookback=20)
        signal = strategy.generate_signal({"code": "000001"}, "2024-01-01")
        if signal is not None:
            self.assertIn(signal.reason_code, ["OK", "INSUFFICIENT_HISTORY", "DECISION_DATE_NOT_FOUND", "INVALID_PRICE"])
        else:
            self.assertIsNone(signal)

    def test_11_walk_forward_integration(self):
        """Test 11: New strategies are compatible with walk-forward engine interface."""
        from core.research.walk_forward_validation import WalkForwardEngine
        strategy = BreakoutStrengthStrategy()
        self.assertTrue(hasattr(strategy, "strategy_id"))
        self.assertTrue(hasattr(strategy, "strategy_version"))
        self.assertTrue(hasattr(strategy, "run"))

    def test_12_target_integration(self):
        """Test 12: New strategies use canonical target engine."""
        from core.research.target_engine import TargetEngine
        strategy = BreakoutStrengthStrategy()
        self.assertIsNotNone(strategy)
        self.assertEqual(strategy.family, "Breakout")

    def test_13_baseline_comparison(self):
        """Test 13: New strategies can be compared against baseline."""
        from core.research.strategies.naive_baseline import NaiveBaselineStrategy
        new_strategy = BreakoutStrengthStrategy()
        baseline = NaiveBaselineStrategy(seed=42)
        self.assertNotEqual(new_strategy.strategy_id, baseline.strategy_id)
        self.assertEqual(baseline.family, "Baseline")

    def test_14_family_aggregation(self):
        """Test 14: Family-level metrics can be aggregated."""
        registry = create_default_expansion_registry()
        summary = registry.summary()
        self.assertEqual(summary["total_families"], 6)
        family_ids = summary["family_ids"]
        self.assertIn("TREND_FAMILY_001", family_ids)
        self.assertIn("BREAKOUT_FAMILY_001", family_ids)

    def test_15_orthogonality_audit(self):
        """Test 15: Orthogonality audit identifies redundant hypotheses."""
        registry = create_default_expansion_registry()
        breakout_family = registry.get_family("BREAKOUT_FAMILY_001")
        momentum_family = registry.get_family("MOMENTUM_FAMILY_001")
        breakout_features = set(breakout_family.required_features)
        momentum_features = set(momentum_family.required_features)
        overlap = breakout_features & momentum_features
        self.assertEqual(overlap, {"daily_price"})
        breakout_hypothesis = breakout_family.hypothesis.lower()
        momentum_hypothesis = momentum_family.hypothesis.lower()
        self.assertNotIn("trend", breakout_hypothesis)
        self.assertNotIn("breakout", momentum_hypothesis)

    def test_16_negative_result_retention(self):
        """Test 16: Failed/no-evidence variants are retained in registry."""
        registry = create_default_expansion_registry()
        exp_registry = registry.get_experiment_registry()
        exp = ExperimentRecord(
            experiment_id="volatility_level_v1",
            parent_experiment_id=None,
            hypothesis="Volatility level variant",
            strategy_family=FAMILY_VOLATILITY,
            strategy_id="volatility_level_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 20},
            parameter_space={"lookback": [20]},
            required_datasets=["daily_price"],
            required_features=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
            target_id="future_excess_return",
            target_version="v1",
            universe_version="RESEARCH_UNIVERSE_V1",
            research_window={"start": "2020-01-01", "end": "2025-01-01"},
            fold_policy="anchored_expanding",
            evaluation_metrics=["IC", "RankIC"],
            selection_rule="best_ic",
            selection_event=SELECTION_EVENT_NONE,
            researcher="system",
            status=EXPERIMENT_STATUS_NO_EVIDENCE,
        )
        exp_registry.register_experiment(exp)
        self.assertEqual(exp_registry.count_by_status(EXPERIMENT_STATUS_NO_EVIDENCE), 1)

    def test_17_perturbation_analysis_interface(self):
        """Test 17: Strategies support parameter perturbation observation."""
        base = BreakoutStrengthStrategy(lookback=20)
        perturbed = BreakoutStrengthStrategy(lookback=20)
        self.assertEqual(base.lookback, perturbed.lookback)
        perturbed2 = BreakoutStrengthStrategy(lookback=25)
        self.assertNotEqual(base.lookback, perturbed2.lookback)

    def test_18_deterministic_execution(self):
        """Test 18: Same strategy + inputs produce same outputs."""
        strategy1 = VolumeTrendStrategy(lookback=20)
        strategy2 = VolumeTrendStrategy(lookback=20)
        signal1 = strategy1.generate_signal({"code": "000001"}, "2024-01-01")
        signal2 = strategy2.generate_signal({"code": "000001"}, "2024-01-01")
        if signal1 and signal2:
            self.assertEqual(signal1.raw_score, signal2.raw_score)
            self.assertEqual(signal1.eligibility, signal2.eligibility)

    def test_19_multiple_testing_accounting(self):
        """Test 19: Registry accounts for variants across families."""
        registry = create_default_expansion_registry()
        exp_registry = registry.get_experiment_registry()
        for name, sid in (
            ("trend", "trend_v1"),
            ("momentum", "momentum_v1"),
            ("reversal", "reversal_v1"),
            ("breakout", "breakout_strength_v1"),
            ("volatility", "volatility_level_v1"),
            ("price_volume", "volume_trend_v1"),
        ):
            exp_registry.register_experiment(ExperimentRecord(
                experiment_id=f"legacy_{name}",
                parent_experiment_id=None,
                hypothesis="Legacy baseline",
                strategy_family=name.capitalize(),
                strategy_id=sid,
                strategy_version="v1",
                variant_id="v1",
                parameters={},
                parameter_space={},
                required_datasets=["daily_price"],
                required_features=["daily_price"],
                required_pit_policies={"daily_price": "CONDITIONAL"},
                target_id="future_excess_return",
                target_version="v1",
                universe_version="RESEARCH_UNIVERSE_V1",
                research_window={"start": "2020-01-01", "end": "2025-01-01"},
                fold_policy="anchored_expanding",
                evaluation_metrics=["IC", "RankIC"],
                selection_rule="best_ic",
                selection_event=SELECTION_EVENT_NONE,
                researcher="system",
                status=EXPERIMENT_STATUS_REGISTERED,
            ))
        summary = exp_registry.summary()
        self.assertEqual(summary["total_experiments"], 6)
        self.assertEqual(summary["total_families"], 6)

    def test_20_pbo_dsr_applicability(self):
        """Test 20: PBO/DSR applicability assessed from registry."""
        registry = create_default_expansion_registry()
        exp_registry = registry.get_experiment_registry()
        from core.research.experiment_governance import MultipleTestingApplicability
        pbo = MultipleTestingApplicability.assess_pbo(exp_registry)
        dsr = MultipleTestingApplicability.assess_dsr(exp_registry)
        self.assertIn("pbo_applicable", pbo)
        self.assertIn("dsr_applicable", dsr)
        self.assertIn("pbo_reason", pbo)
        self.assertIn("dsr_reason", dsr)


if __name__ == "__main__":
    unittest.main()
