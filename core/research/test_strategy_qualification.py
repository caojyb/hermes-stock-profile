#!/usr/bin/env python3
"""
test_strategy_qualification.py — Strategy Qualification Framework Tests
=======================================================================
"""

from __future__ import annotations

import unittest

from core.research.experiment_governance import EXPERIMENT_STATUS_REGISTERED
from core.research.strategy_qualification import (
    StrategyQualificationEngine,
    StrategyQualificationInput,
    FoldMetrics,
    LayerStatus,
    QualificationStatus,
    EvidenceStrength,
)


class TestStrategyQualification(unittest.TestCase):
    """Test suite for Strategy Qualification Engine."""

    def _make_fold(self, fold_id="fold_1", valid=True, low_sample=False, dq_warning=False,
                   ic_5d=0.02, rank_ic_5d=0.02, baseline_ic_5d=0.0,
                   horizon=5):
        suffix = f"_{horizon}d"
        return FoldMetrics(
            fold_id=fold_id,
            train_start="2020-01-01",
            train_end="2024-06-30",
            validation_start="2024-07-01",
            validation_end="2024-09-30",
            dataset_version="v1",
            universe_version="RESEARCH_UNIVERSE_V1",
            target_version="v1",
            strategy_version="v1",
            normalization_version="v1",
            signal_count=100,
            eligible_count=90,
            valid_target_count=80,
            excluded_count=10,
            low_sample=low_sample,
            data_quality_warning=dq_warning,
            **{f"ic{suffix}": ic_5d, f"rank_ic{suffix}": rank_ic_5d,
               f"baseline_ic{suffix}": baseline_ic_5d,
               f"mean_excess_return{suffix}": 0.001, f"median_excess_return{suffix}": 0.001,
               f"hit_rate{suffix}": 0.52, f"baseline_rank_ic{suffix}": 0.0,
               f"baseline_mean_excess_return{suffix}": 0.0}
        )

    def test_01_qualification_engine_initializes(self):
        """Test 1: Engine initializes with default parameters."""
        engine = StrategyQualificationEngine()
        self.assertIsNotNone(engine)
        self.assertEqual(engine.min_valid_folds, 3)
        self.assertEqual(engine.min_valid_observations, 50)

    def test_02_pit_gate_blocks_illegal_datasets(self):
        """Test 2: PIT gate blocks forbidden datasets."""
        engine = StrategyQualificationEngine()
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=[self._make_fold()],
            requires_eod_policy=True,
            required_datasets=["daily_price", "financial_data"],
            required_pit_policies={"daily_price": "CONDITIONAL", "financial_data": "PIT_UNSAFE"},
        )
        result = engine.evaluate(inp)
        pit_layer = result.layers["L2_PIT_LEAKAGE"]
        self.assertEqual(pit_layer.status, LayerStatus.FAIL.value)
        self.assertIsNotNone(pit_layer.blocker_reason)

    def test_03_data_integrity_gate_passes_clean(self):
        """Test 3: Data integrity passes with complete provenance."""
        engine = StrategyQualificationEngine()
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=[self._make_fold()],
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
        )
        result = engine.evaluate(inp)
        integrity_layer = result.layers["L1_DATA_INTEGRITY"]
        self.assertEqual(integrity_layer.status, LayerStatus.PASS.value)

    def test_04_predictive_metrics_computed(self):
        """Test 4: Predictive evidence metrics are computed correctly."""
        engine = StrategyQualificationEngine()
        folds = [self._make_fold(f"fold_{i}", ic_5d=0.02 + i * 0.005) for i in range(1, 6)]
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=folds,
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
        )
        result = engine.evaluate(inp)
        pred = result.layers["L3_PREDICTIVE_EVIDENCE"]
        self.assertIn("ic_mean", pred.details)
        self.assertIn("rank_ic_mean", pred.details)
        self.assertIn("ic_positive_ratio", pred.details)

    def test_05_low_sample_gate_marks_folds(self):
        """Test 5: Low sample folds are marked and counted."""
        engine = StrategyQualificationEngine()
        folds = [
            self._make_fold("fold_1", low_sample=False),
            self._make_fold("fold_2", low_sample=True),
            self._make_fold("fold_3", low_sample=False),
        ]
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=folds,
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
        )
        result = engine.evaluate(inp)
        self.assertEqual(result.fold_count, 3)
        self.assertEqual(result.valid_fold_count, 2)
        self.assertEqual(result.low_sample_fold_count, 1)

    def test_06_baseline_consistency(self):
        """Test 6: Baseline comparison is computed."""
        engine = StrategyQualificationEngine()
        strat_folds = [self._make_fold(f"fold_{i}", ic_5d=0.02) for i in range(1, 4)]
        base_folds = [self._make_fold(f"fold_{i}", baseline_ic_5d=0.0) for i in range(1, 4)]
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=strat_folds,
            baseline_folds=base_folds,
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
        )
        result = engine.evaluate(inp)
        comp = result.baseline_comparison
        self.assertEqual(comp["status"], "COMPUTED")
        self.assertIn("ic_delta_mean", comp)

    def test_07_pbo_prerequisite_tracked(self):
        """Test 7: PBO prerequisite is tracked."""
        engine = StrategyQualificationEngine()
        folds = [self._make_fold() for _ in range(5)]
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=folds,
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
            variant_count=4,
        )
        result = engine.evaluate(inp)
        self.assertEqual(result.pbo_status, "NOT_APPLICABLE_YET")
        self.assertEqual(result.dsr_status, "NOT_APPLICABLE_YET")
        pbo_layer = result.layers["L8_MULTIPLE_TESTING"]
        self.assertEqual(pbo_layer.status, LayerStatus.NOT_APPLICABLE_YET.value)
        self.assertIn("note", pbo_layer.details)

    def test_08_not_applicable_handling(self):
        """Test 8: NOT_APPLICABLE_YET does not become PASS."""
        engine = StrategyQualificationEngine()
        folds = [self._make_fold(f"fold_{i}") for i in range(1, 6)]
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=folds,
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
            variant_count=4,
        )
        result = engine.evaluate(inp)
        cap_layer = result.layers["L7_CAPACITY_IMPLEMENTABILITY"]
        self.assertEqual(cap_layer.status, LayerStatus.NOT_APPLICABLE_YET.value)
        rob_layer = result.layers["L9_ROBUSTNESS"]
        self.assertEqual(rob_layer.status, LayerStatus.NOT_APPLICABLE_YET.value)
        self.assertNotEqual(result.qualification_status, QualificationStatus.QUALIFIED.value)

    def test_09_baseline_excluded_from_qualification(self):
        """Test 9: Baseline strategy is not qualified (reference only)."""
        engine = StrategyQualificationEngine()
        folds = [self._make_fold() for _ in range(5)]
        inp = StrategyQualificationInput(
            strategy_id="naive_baseline_v1",
            strategy_version="v1",
            strategy_family="Baseline",
            horizon=5,
            folds=folds,
            requires_eod_policy=False,
            required_datasets=[],
            required_pit_policies={},
        )
        result = engine.evaluate(inp)
        self.assertNotEqual(result.qualification_status, QualificationStatus.QUALIFIED.value)

    def test_10_provenance_completeness(self):
        """Test 10: Provenance fields are required."""
        engine = StrategyQualificationEngine()
        base_fold = self._make_fold()
        fold = FoldMetrics(
            fold_id=base_fold.fold_id,
            train_start=base_fold.train_start,
            train_end=base_fold.train_end,
            validation_start=base_fold.validation_start,
            validation_end=base_fold.validation_end,
            dataset_version="",
            universe_version=base_fold.universe_version,
            target_version=base_fold.target_version,
            strategy_version=base_fold.strategy_version,
            normalization_version=base_fold.normalization_version,
            signal_count=base_fold.signal_count,
            eligible_count=base_fold.eligible_count,
            valid_target_count=base_fold.valid_target_count,
            excluded_count=base_fold.excluded_count,
            low_sample=base_fold.low_sample,
            data_quality_warning=base_fold.data_quality_warning,
            ic_5d=base_fold.ic_5d,
            rank_ic_5d=base_fold.rank_ic_5d,
            baseline_ic_5d=base_fold.baseline_ic_5d,
            mean_excess_return_5d=base_fold.mean_excess_return_5d,
            median_excess_return_5d=base_fold.median_excess_return_5d,
            hit_rate_5d=base_fold.hit_rate_5d,
            baseline_rank_ic_5d=base_fold.baseline_rank_ic_5d,
            baseline_mean_excess_return_5d=base_fold.baseline_mean_excess_return_5d,
        )
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=[fold],
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
        )
        result = engine.evaluate(inp)
        integrity = result.layers["L1_DATA_INTEGRITY"]
        self.assertEqual(integrity.status, LayerStatus.FAIL.value)
        self.assertIn("Provenance", integrity.blocker_reason)

    def test_11_deterministic_result(self):
        """Test 11: Same inputs produce same qualification result."""
        engine = StrategyQualificationEngine()
        folds = [self._make_fold("fold_1"), self._make_fold("fold_2")]
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=folds,
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
        )
        r1 = engine.evaluate(inp)
        r2 = engine.evaluate(inp)
        self.assertEqual(r1.qualification_status, r2.qualification_status)
        self.assertEqual(r1.evidence_strength, r2.evidence_strength)

    def test_12_failed_gate_blocks_qualification(self):
        """Test 12: Failed PIT gate blocks qualification."""
        engine = StrategyQualificationEngine()
        folds = [self._make_fold() for _ in range(5)]
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=folds,
            requires_eod_policy=True,
            required_datasets=["daily_price", "news"],
            required_pit_policies={"daily_price": "CONDITIONAL", "news": "PIT_UNSAFE"},
        )
        result = engine.evaluate(inp)
        self.assertEqual(result.qualification_status, QualificationStatus.BLOCKED.value)
        pit_layer = result.layers["L2_PIT_LEAKAGE"]
        self.assertEqual(pit_layer.status, LayerStatus.FAIL.value)

    def test_13_cross_fold_metrics_ready(self):
        """Test 13: Cross-fold metrics are computed."""
        engine = StrategyQualificationEngine()
        folds = [self._make_fold(f"fold_{i}", ic_5d=0.01 * i) for i in range(1, 6)]
        inp = StrategyQualificationInput(
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            horizon=5,
            folds=folds,
            requires_eod_policy=True,
            required_datasets=["daily_price"],
            required_pit_policies={"daily_price": "CONDITIONAL"},
        )
        result = engine.evaluate(inp)
        cfm = result.cross_fold_metrics
        self.assertIn("horizon_5", cfm)
        self.assertIn("ic", cfm["horizon_5"])
        self.assertIn("mean", cfm["horizon_5"]["ic"])


class TestMultipleTestingRegistry(unittest.TestCase):
    """Test suite for Multiple Testing Registry."""

    def test_01_registry_initializes_empty(self):
        """Test 1: Registry initializes empty."""
        from core.research.multiple_testing_registry import MultipleTestingRegistry
        reg = MultipleTestingRegistry()
        self.assertEqual(reg.count_total(), 0)

    def test_02_register_experiment(self):
        """Test 2: Register experiment and count."""
        from core.research.multiple_testing_registry import MultipleTestingRegistry, ExperimentRecord
        reg = MultipleTestingRegistry()
        rec = ExperimentRecord(
            experiment_id="exp_001",
            strategy_id="trend_v1",
            strategy_version="v1",
            strategy_family="Trend",
            parameter_space={"lookback": 60},
            features=["daily_price"],
            target="future_excess_return_5d",
            target_version="v1",
            research_window={"start": "2020-01-01", "end": "2025-01-01"},
            result_selection="first_valid",
            status=EXPERIMENT_STATUS_REGISTERED,
        )
        reg.register(rec)
        self.assertEqual(reg.count_total(), 1)
        self.assertEqual(reg.count_by_strategy("trend_v1"), 1)

    def test_03_summary_tracks_counts(self):
        """Test 3: Summary reflects registered experiments."""
        from core.research.multiple_testing_registry import MultipleTestingRegistry, ExperimentRecord
        reg = MultipleTestingRegistry()
        for sid in ("trend_v1", "momentum_v1", "reversal_v1"):
            reg.register(ExperimentRecord(
                experiment_id=f"exp_{sid}",
                strategy_id=sid,
                strategy_version="v1",
                strategy_family="Trend",
                parameter_space={},
                features=[],
                target="future_excess_return_5d",
                target_version="v1",
                research_window={"start": "2020-01-01", "end": "2025-01-01"},
                result_selection="first_valid",
                status=EXPERIMENT_STATUS_REGISTERED,
            ))
        summary = reg.summary()
        self.assertEqual(summary["total_experiments"], 3)
        self.assertEqual(summary["by_strategy"]["trend_v1"], 1)
        self.assertFalse(summary["pbo_eligible"])

    def test_04_pbo_dsr_eligibility(self):
        """Test 4: PBO/DSR eligibility requires >=10 experiments."""
        from core.research.multiple_testing_registry import MultipleTestingRegistry, ExperimentRecord
        reg = MultipleTestingRegistry()
        for i in range(10):
            reg.register(ExperimentRecord(
                experiment_id=f"exp_{i:03d}",
                strategy_id="trend_v1",
                strategy_version="v1",
                strategy_family="Trend",
                parameter_space={},
                features=[],
                target="future_excess_return_5d",
                target_version="v1",
                research_window={"start": "2020-01-01", "end": "2025-01-01"},
                result_selection="first_valid",
                status=EXPERIMENT_STATUS_REGISTERED,
            ))
        summary = reg.summary()
        self.assertTrue(summary["pbo_eligible"])
        self.assertTrue(summary["dsr_eligible"])


if __name__ == "__main__":
    unittest.main()
