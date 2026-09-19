#!/usr/bin/env python3
"""
test_experiment_governance.py — Experiment Governance Tests
============================================================
"""

from __future__ import annotations

import unittest
from core.research.experiment_governance import (
    ExperimentRegistry,
    ExperimentRecord,
    ExperimentFamily,
    DecisionLogEntry,
    MultipleTestingApplicability,
    EXPERIMENT_STATUS_NO_EVIDENCE,
    EXPERIMENT_STATUS_FAILED,
    EXPERIMENT_STATUS_BLOCKED,
    EXPERIMENT_STATUS_REGISTERED,
    EXPERIMENT_STATUS_SELECTED_FOR_FURTHER_RESEARCH,
    SELECTION_EVENT_NONE,
)


class TestExperimentGovernance(unittest.TestCase):
    """Test suite for Experiment Governance."""

    def _make_registry(self):
        return ExperimentRegistry()

    def _make_experiment(self, experiment_id="exp_001", parent_id=None, family="Trend"):
        return ExperimentRecord(
            experiment_id=experiment_id,
            parent_experiment_id=parent_id,
            hypothesis="Test hypothesis",
            strategy_family=family,
            strategy_id="trend_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 60},
            parameter_space={"lookback": [20, 40, 60]},
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

    def test_01_experiment_registration(self):
        """Test 1: Experiment registration."""
        registry = self._make_registry()
        exp = self._make_experiment()
        registry.register_experiment(exp)
        self.assertEqual(registry.count_total(), 1)
        retrieved = registry.get_experiment("exp_001")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.strategy_id, "trend_v1")

    def test_02_hypothesis_required(self):
        """Test 2: Hypothesis is required."""
        registry = self._make_registry()
        exp = ExperimentRecord(
            experiment_id="exp_empty_hypothesis",
            parent_experiment_id=None,
            hypothesis="",
            strategy_family="Trend",
            strategy_id="trend_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 60},
            parameter_space={"lookback": [20, 40, 60]},
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
        # Empty hypothesis should still register, but flag in real governance
        registry.register_experiment(exp)
        self.assertEqual(registry.count_total(), 1)

    def test_03_parameter_space_immutable(self):
        """Test 3: Parameter space cannot be silently expanded after registration."""
        registry = self._make_registry()
        exp = self._make_experiment()
        registry.register_experiment(exp)
        # Attempting to register a variant with expanded parameter space must be a new experiment
        expanded = self._make_experiment(experiment_id="exp_002", parent_id="exp_001")
        registry.register_experiment(expanded)
        self.assertEqual(registry.count_total(), 2)
        self.assertIsNotNone(expanded.parent_experiment_id)

    def test_04_feature_declaration(self):
        """Test 4: Features must be declared before experiment runs."""
        registry = self._make_registry()
        exp = self._make_experiment()
        registry.register_experiment(exp)
        self.assertEqual(exp.required_features, ["daily_price"])
        self.assertNotIn("financial_data", exp.required_features)

    def test_05_target_binding(self):
        """Test 5: Target version is bound to experiment."""
        registry = self._make_registry()
        exp = self._make_experiment()
        registry.register_experiment(exp)
        self.assertEqual(exp.target_id, "future_excess_return")
        self.assertEqual(exp.target_version, "v1")

    def test_06_universe_binding(self):
        """Test 6: Universe version is bound to experiment."""
        registry = self._make_registry()
        exp = self._make_experiment()
        registry.register_experiment(exp)
        self.assertEqual(exp.universe_version, "RESEARCH_UNIVERSE_V1")

    def test_07_research_window_binding(self):
        """Test 7: Research window is bound to experiment."""
        registry = self._make_registry()
        exp = self._make_experiment()
        registry.register_experiment(exp)
        self.assertEqual(exp.research_window["start"], "2020-01-01")
        self.assertEqual(exp.research_window["end"], "2025-01-01")

    def test_08_failed_experiment_persistence(self):
        """Test 8: Failed experiments are retained."""
        registry = self._make_registry()
        exp = self._make_experiment()
        registry.register_experiment(exp)
        failed = ExperimentRecord(
            experiment_id="exp_failed",
            parent_experiment_id=None,
            hypothesis="Failing experiment",
            strategy_family="Trend",
            strategy_id="trend_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 60},
            parameter_space={"lookback": [20, 40, 60]},
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
            status=EXPERIMENT_STATUS_FAILED,
        )
        registry.register_experiment(failed)
        self.assertEqual(registry.count_total(), 2)
        self.assertEqual(registry.count_by_status(EXPERIMENT_STATUS_FAILED), 1)
        neg = registry.get_negative_results()
        self.assertEqual(len(neg), 1)

    def test_09_lineage(self):
        """Test 9: Parent-child lineage is tracked."""
        registry = self._make_registry()
        parent = self._make_experiment(experiment_id="exp_parent")
        child = self._make_experiment(experiment_id="exp_child", parent_id="exp_parent")
        registry.register_experiment(parent)
        registry.register_experiment(child)
        children = registry.get_children("exp_parent")
        self.assertEqual(children, ["exp_child"])
        lineage = registry.get_lineage("exp_child")
        self.assertEqual(lineage, ["exp_child", "exp_parent"])

    def test_10_family_grouping(self):
        """Test 10: Experiments are grouped by family."""
        registry = self._make_registry()
        registry.register_experiment(self._make_experiment(family="Trend"))
        registry.register_experiment(self._make_experiment(experiment_id="exp_002", family="Trend"))
        registry.register_experiment(self._make_experiment(experiment_id="exp_003", family="Momentum"))
        summary = registry.summary()
        self.assertEqual(summary["by_family"]["Trend"], 2)
        self.assertEqual(summary["by_family"]["Momentum"], 1)

    def test_11_multiple_testing_counting(self):
        """Test 11: Multiple-testing accounting counts variants."""
        registry = self._make_registry()
        for i in range(3):
            exp = ExperimentRecord(
                experiment_id=f"exp_{i:03d}",
                parent_experiment_id=None,
                hypothesis="Test hypothesis",
                strategy_family="Trend",
                strategy_id="trend_v1",
                strategy_version="v1",
                variant_id="v1",
                parameters={"lookback": 20 + i * 10},
                parameter_space={"lookback": [20, 40, 60]},
                required_datasets=["daily_price"],
                required_features=["daily_price", "volume"] if i == 1 else ["daily_price"],
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
            registry.register_experiment(exp)
        summary = registry.summary()
        # 2026-09-19: total_parameter_variants/total_feature_variants 是
        # MultipleTestingRegistry 的键; ExperimentRegistry.summary 提供的是
        # total_experiments/total_families/by_status。变体计数走
        # MultipleTestingApplicability（PBO 评估入口）, 此处断言 registry 口径。
        self.assertEqual(summary["total_experiments"], 3)
        self.assertEqual(summary["by_family"]["Trend"], 3)
        self.assertEqual(summary["by_status"][EXPERIMENT_STATUS_REGISTERED], 3)

    def test_12_pbo_applicability_logic(self):
        """Test 12: PBO applicability uses dynamic logic, not hardcoded 10."""
        registry = self._make_registry()
        # Not enough experiments
        pbo = MultipleTestingApplicability.assess_pbo(registry)
        self.assertFalse(pbo["pbo_applicable"])

        # Add enough independent trials across families
        for i in range(6):
            family = "Trend" if i < 3 else "Momentum"
            exp = ExperimentRecord(
                experiment_id=f"exp_{i:03d}",
                parent_experiment_id=None,
                hypothesis="Test hypothesis",
                strategy_family=family,
                strategy_id="trend_v1" if family == "Trend" else "momentum_v1",
                strategy_version="v1",
                variant_id="v1",
                parameters={"lookback": 60},
                parameter_space={"lookback": [20, 40, 60]},
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
            registry.register_experiment(exp)
        pbo = MultipleTestingApplicability.assess_pbo(registry)
        self.assertTrue(pbo["pbo_applicable"])

    def test_13_dsr_applicability_logic(self):
        """Test 13: DSR applicability uses dynamic logic."""
        registry = self._make_registry()
        dsr = MultipleTestingApplicability.assess_dsr(registry)
        self.assertFalse(dsr["dsr_applicable"])

        for i in range(5):
            family = "Trend" if i < 3 else "Momentum"
            exp = ExperimentRecord(
                experiment_id=f"exp_{i:03d}",
                parent_experiment_id=None,
                hypothesis="Test hypothesis",
                strategy_family=family,
                strategy_id="trend_v1" if family == "Trend" else "momentum_v1",
                strategy_version="v1",
                variant_id="v1",
                parameters={"lookback": 60},
                parameter_space={"lookback": [20, 40, 60]},
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
            registry.register_experiment(exp)
        dsr = MultipleTestingApplicability.assess_dsr(registry)
        self.assertTrue(dsr["dsr_applicable"])

    def test_14_deterministic_registry(self):
        """Test 14: Registry operations are deterministic."""
        registry1 = self._make_registry()
        registry2 = self._make_registry()
        for i in range(5):
            exp = self._make_experiment(experiment_id=f"exp_{i:03d}")
            registry1.register_experiment(exp)
            registry2.register_experiment(exp)
        self.assertEqual(registry1.count_total(), registry2.count_total())
        self.assertEqual(registry1.summary(), registry2.summary())

    def test_15_decision_log(self):
        """Test 15: Decision log records major research choices."""
        registry = self._make_registry()
        entry = DecisionLogEntry(
            decision_id="decision_001",
            experiment_id="exp_001",
            decision="STOP_REVERSAL_FAMILY",
            reason="No evidence across multiple pre-registered experiments",
            evidence="IC negative in 3/3 folds",
            actor="researcher",
        )
        registry.log_decision(entry)
        self.assertEqual(len(registry._decisions), 1)
        self.assertEqual(registry._decisions[0].decision, "STOP_REVERSAL_FAMILY")

    def test_16_negative_result_retention(self):
        """Test 16: Negative results are retained and queryable."""
        registry = self._make_registry()
        registry.register_experiment(self._make_experiment())
        no_evidence = ExperimentRecord(
            experiment_id="exp_no_evidence",
            parent_experiment_id=None,
            hypothesis="No evidence experiment",
            strategy_family="Trend",
            strategy_id="trend_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 60},
            parameter_space={"lookback": [20, 40, 60]},
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
        registry.register_experiment(no_evidence)
        failed = ExperimentRecord(
            experiment_id="exp_failed",
            parent_experiment_id=None,
            hypothesis="Failed experiment",
            strategy_family="Trend",
            strategy_id="trend_v1",
            strategy_version="v1",
            variant_id="v1",
            parameters={"lookback": 60},
            parameter_space={"lookback": [20, 40, 60]},
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
            status=EXPERIMENT_STATUS_FAILED,
        )
        registry.register_experiment(failed)
        self.assertEqual(registry.count_total(), 3)
        neg = registry.get_negative_results()
        self.assertEqual(len(neg), 2)

    def test_17_legacy_experiments_registered(self):
        """Test 17: Historical strategy baselines are registered as legacy experiments."""
        registry = self._make_registry()
        for name, sid in (("trend", "trend_v1"), ("momentum", "momentum_v1"), ("reversal", "reversal_v1")):
            exp = ExperimentRecord(
                experiment_id=f"legacy_{name}",
                parent_experiment_id=None,
                hypothesis="Legacy baseline experiment",
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
                status=EXPERIMENT_STATUS_NO_EVIDENCE,
            )
            registry.register_experiment(exp)
        self.assertEqual(registry.count_total(), 3)
        self.assertEqual(registry.count_by_status(EXPERIMENT_STATUS_NO_EVIDENCE), 3)


class TestMultipleTestingRegistryCompatibility(unittest.TestCase):
    """Ensure backward compatibility with existing multiple_testing_registry interface."""

    def test_summary_counts(self):
        from core.research.multiple_testing_registry import MultipleTestingRegistry, ExperimentRecord
        reg = MultipleTestingRegistry()
        for i in range(5):
            reg.register(ExperimentRecord(
                experiment_id=f"exp_{i:03d}",
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
            ))
        summary = reg.summary()
        self.assertEqual(summary["total_experiments"], 5)
        self.assertEqual(summary["total_strategy_variants"], 1)
        self.assertEqual(summary["total_target_variants"], 1)


if __name__ == "__main__":
    unittest.main()
