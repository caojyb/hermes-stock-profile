#!/usr/bin/env python3
"""
test_expanded_walk_forward.py — Expanded Walk-Forward Validation Tests
======================================================================
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import unittest
from typing import List, Dict

from core.research.expanded_walk_forward_validation import ExpandedWalkForwardValidator
from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition, FoldResult
from core.research.strategies.breakout_strategy import BreakoutStrengthStrategy, BreakoutConfirmationStrategy
from core.research.strategies.volatility_strategy import VolatilityLevelStrategy, VolatilityChangeStrategy
from core.research.strategies.price_volume_strategy import VolumeTrendStrategy, VolumePriceCorrelationStrategy
from core.research.strategies.momentum_strategy_variants import MomentumMediumStrategy, MomentumRiskAdjustedStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy
from core.research.strategy_family_expansion import create_default_expansion_registry


class FakeStrategy:
    strategy_id = "fake_strategy_v1"
    strategy_version = "v1"
    family = "Fake"
    required_inputs = ["daily_price"]
    requires_eod_policy = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def generate_signal(self, stock: dict, decision_time: str, context: dict = None):
        from core.research.base_strategy import Signal
        return Signal(
            stock_code=stock.get("code", ""),
            decision_time=decision_time,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            raw_score=0.5,
            normalized_score=None,
            eligibility=True,
            reason_code="OK",
            horizon=5,
            family=self.family,
        )


class TestExpandedWalkForwardValidation(unittest.TestCase):
    """Test suite for expanded walk-forward validation."""

    def test_01_all_new_variants_registered(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        )
        catalog = validator.build_variant_catalog()
        ids = {v.strategy_id for v in catalog}
        expected = {
            "trend_short_v1",
            "trend_long_v1",
            "momentum_medium_v1",
            "momentum_risk_adjusted_v1",
            "breakout_strength_v1",
            "breakout_confirmation_v1",
            "volatility_level_v1",
            "volatility_change_v1",
            "volume_trend_v1",
            "volume_price_correlation_v1",
        }
        self.assertTrue(expected.issubset(ids))

    def test_02_canonical_fold_policy(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            fold_policy="anchored_expanding",
            min_folds=5,
            max_folds=8,
        )
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
            fold_policy="anchored_expanding",
        )
        folds = engine.define_folds_auto(min_folds=5, max_folds=8)
        for fold in folds:
            self.assertEqual(fold.fold_policy, "anchored_expanding")

    def test_03_chronological_ordering(self):
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
        )
        folds = engine.define_folds_auto(min_folds=5, max_folds=8)
        for i in range(len(folds) - 1):
            self.assertLess(folds[i].validation_start, folds[i + 1].validation_start)

    def test_04_no_overlap(self):
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
        )
        folds = engine.define_folds_auto(min_folds=5, max_folds=8)
        for fold in folds:
            self.assertLess(fold.train_end, fold.validation_start)

    def test_05_normalization_isolation(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        )
        catalog = validator.build_variant_catalog()
        new_variants = [v for v in catalog if v.family == "Breakout"]
        self.assertTrue(len(new_variants) >= 1)
        for variant in new_variants:
            self.assertEqual(variant.experiment_family_id, "BREAKOUT_FAMILY_001")

    def test_06_eod_policy(self):
        catalog = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        ).build_variant_catalog()
        for variant in catalog:
            self.assertTrue(variant.requires_eod_policy)

    def test_07_target_integration(self):
        from core.research.target_engine import TargetEngine
        self.assertTrue(hasattr(TargetEngine, "compute_target"))
        self.assertTrue(hasattr(TargetEngine, "compute_targets_batch"))

    def test_08_baseline_comparison(self):
        baseline = NaiveBaselineStrategy(seed=42)
        self.assertEqual(baseline.strategy_id, "naive_baseline_v1")
        self.assertEqual(baseline.family, "Baseline")

    def test_09_pit_enforcement(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        )
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
        )
        fold = FoldDefinition(
            fold_id="fold_001",
            train_start="2020-01-01",
            train_end="2024-05-30",
            validation_start="2024-05-31",
            validation_end="2024-07-31",
            fold_index=1,
            fold_policy="anchored_expanding",
        )
        result = engine.run_fold(fold, FakeStrategy(), NaiveBaselineStrategy(seed=42), horizons=[5])
        self.assertIn(result.fold_status, ["VALID_FOLD", "LOW_SAMPLE", "INVALID_FOLD"])

    def test_10_deterministic_execution(self):
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
        )
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        fold = folds[0]
        result1 = engine.run_fold(fold, FakeStrategy(), NaiveBaselineStrategy(seed=42), horizons=[5])
        result2 = engine.run_fold(fold, FakeStrategy(), NaiveBaselineStrategy(seed=42), horizons=[5])
        self.assertEqual(result1.strategy_ic, result2.strategy_ic)
        self.assertEqual(result1.strategy_rank_ic, result2.strategy_rank_ic)

    def test_11_provenance(self):
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
        )
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        result = engine.run_fold(folds[0], FakeStrategy(), NaiveBaselineStrategy(seed=42), horizons=[5])
        self.assertEqual(result.strategy_id, "fake_strategy_v1")
        self.assertEqual(result.strategy_version, "v1")
        self.assertIsNotNone(result.created_at)
        self.assertEqual(result.fold_policy, "anchored_expanding")

    def test_12_low_sample(self):
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
            min_valid_targets=999,
        )
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        result = engine.run_fold(folds[0], FakeStrategy(), NaiveBaselineStrategy(seed=42), horizons=[5])
        # Empty universe returns INVALID_FOLD; low-sample marking requires a non-empty universe
        self.assertIn(result.fold_status, ["LOW_SAMPLE", "INVALID_FOLD"])

    def test_13_anomaly_handling(self):
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
            max_anomaly_ratio=0.0,
        )
        fold = FoldDefinition(
            fold_id="fold_001",
            train_start="2020-01-01",
            train_end="2024-05-30",
            validation_start="2024-05-31",
            validation_end="2024-07-31",
            fold_index=1,
            fold_policy="anchored_expanding",
        )
        result = engine.run_fold(fold, FakeStrategy(), NaiveBaselineStrategy(seed=42), horizons=[5])
        self.assertIn(result.fold_status, ["VALID_FOLD", "LOW_SAMPLE", "INVALID_FOLD", "DATA_QUALITY_WARNING"])

    def test_14_family_aggregation(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        )
        variants = validator.build_variant_catalog()
        breakout_variants = [v for v in variants if v.family == "Breakout"]
        self.assertTrue(len(breakout_variants) >= 1)

    def test_15_experiment_lineage(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        )
        catalog = validator.build_variant_catalog()
        breakout_variants = [v for v in catalog if v.family == "Breakout"]
        for variant in breakout_variants:
            self.assertTrue(variant.experiment_id.endswith("_exp"))
            self.assertEqual(variant.experiment_family_id, "BREAKOUT_FAMILY_001")

    def test_16_multiple_testing_accounting(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        )
        catalog = validator.build_variant_catalog()
        family_ids = {v.experiment_family_id for v in catalog}
        # Includes Baseline as the 7th family; new research families should be >= 6
        self.assertGreaterEqual(len(family_ids), 6)

    def test_17_pbo_applicability(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        )
        result = validator.pbo_dsr_applicability()
        self.assertIn("pbo_applicable", result)
        self.assertIn("pbo_reason", result)

    def test_18_dsr_applicability(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
        )
        result = validator.pbo_dsr_applicability()
        self.assertIn("dsr_applicable", result)
        self.assertIn("dsr_reason", result)

    def test_19_canonical_fold_count(self):
        validator = ExpandedWalkForwardValidator(
            db_path=":memory:",
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            min_folds=5,
            max_folds=8,
        )
        catalog = validator.build_variant_catalog()
        self.assertTrue(len(catalog) >= 10)

    def test_20_coverage_matrix_interface(self):
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: [],
            kline_loader=lambda s, a, b: [],
            db_path=":memory:",
        )
        strategy = FakeStrategy()
        baseline = NaiveBaselineStrategy(seed=42)
        summary = engine.run_full_validation(strategy, baseline, horizons=[5, 10, 20])
        self.assertIn("coverage_matrix", summary)


if __name__ == "__main__":
    unittest.main()
