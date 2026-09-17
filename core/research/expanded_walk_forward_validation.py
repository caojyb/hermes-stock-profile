#!/usr/bin/env python3
"""
expanded_walk_forward_validation.py — Expanded Strategy Walk-Forward Validation
==================================================================================
Validates all C4-B strategy variants using canonical walk-forward engine.
No parameter optimization. No winner selection. Research-plane only.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------- Variant Definition
@dataclass(frozen=True)
class StrategyVariantDefinition:
    strategy_id: str
    strategy_version: str
    family: str
    strategy_cls: Any
    parameters: Dict[str, Any]
    required_inputs: List[str]
    requires_eod_policy: bool
    experiment_id: str
    experiment_family_id: str
    status_override: Optional[str] = None


# ---------------------------------------------------------------- Registry Adapters
from core.research.experiment_governance import (
    ExperimentRegistry,
    ExperimentRecord,
    EXPERIMENT_STATUS_COMPLETED,
    EXPERIMENT_STATUS_NO_EVIDENCE,
    EXPERIMENT_STATUS_FAILED,
    EXPERIMENT_STATUS_BLOCKED,
    EXPERIMENT_STATUS_REGISTERED,
    SELECTION_EVENT_NONE,
)
from core.research.multiple_testing_registry import MultipleTestingRegistry


# ---------------------------------------------------------------- Expanded Validator
class ExpandedWalkForwardValidator:
    """
    Runs canonical walk-forward validation across a fixed set of strategy variants,
    aggregates family-level evidence, and updates governance registries.
    """

    def __init__(
        self,
        db_path: str,
        universe_fetcher: Callable[[str], List[dict]],
        kline_loader: Callable[[str, str, str], List[dict]],
        dataset_version: str = "v1",
        universe_version: str = "RESEARCH_UNIVERSE_V1",
        target_version: str = "v1",
        fold_policy: str = "anchored_expanding",
        min_folds: int = 5,
        max_folds: int = 8,
        train_window_days: int = 252,
        validation_window_days: int = 63,
        embargo_days: int = 5,
        horizons: Optional[List[int]] = None,
    ):
        self.db_path = db_path
        self.universe_fetcher = universe_fetcher
        self.kline_loader = kline_loader
        self.dataset_version = dataset_version
        self.universe_version = universe_version
        self.target_version = target_version
        self.fold_policy = fold_policy
        self.min_folds = min_folds
        self.max_folds = max_folds
        self.train_window_days = train_window_days
        self.validation_window_days = validation_window_days
        self.embargo_days = embargo_days
        self.horizons = horizons or [5, 10, 20]

        self.experiment_registry = ExperimentRegistry()
        self.multiple_testing_registry = MultipleTestingRegistry()
        self.fold_results: List[dict] = []
        self.family_summaries: Dict[str, dict] = {}
        self.variant_summaries: Dict[str, dict] = {}

    # ---------------------------------------------------------------- Variant Catalog
    def build_variant_catalog(self) -> List[StrategyVariantDefinition]:
        from core.research.strategies.breakout_strategy import (
            BreakoutStrengthStrategy,
            BreakoutConfirmationStrategy,
        )
        from core.research.strategies.volatility_strategy import (
            VolatilityLevelStrategy,
            VolatilityChangeStrategy,
        )
        from core.research.strategies.price_volume_strategy import (
            VolumeTrendStrategy,
            VolumePriceCorrelationStrategy,
        )
        from core.research.strategies.momentum_strategy_variants import (
            MomentumMediumStrategy,
            MomentumRiskAdjustedStrategy,
        )
        from core.research.strategies.trend_strategy import TrendStrategy
        from core.research.strategies.momentum_strategy import MomentumStrategy
        from core.research.strategies.reversal_strategy import ReversalStrategy
        from core.research.strategies.naive_baseline import NaiveBaselineStrategy

        variants = [
            # Legacy baselines
            StrategyVariantDefinition(
                strategy_id="trend_v1",
                strategy_version="v1",
                family="Trend",
                strategy_cls=TrendStrategy,
                parameters={"lookback": 60},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="legacy_trend_v1",
                experiment_family_id="TREND_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="momentum_v1",
                strategy_version="v1",
                family="Momentum",
                strategy_cls=MomentumStrategy,
                parameters={"lookback": 20},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="legacy_momentum_v1",
                experiment_family_id="MOMENTUM_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="reversal_v1",
                strategy_version="v1",
                family="Reversal",
                strategy_cls=ReversalStrategy,
                parameters={"lookback": 5},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="legacy_reversal_v1",
                experiment_family_id="REVERSAL_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="naive_baseline_v1",
                strategy_version="v1",
                family="Baseline",
                strategy_cls=NaiveBaselineStrategy,
                parameters={"seed": 42},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="legacy_baseline_v1",
                experiment_family_id="BASELINE_FAMILY_001",
            ),
            # New C4-B variants
            StrategyVariantDefinition(
                strategy_id="trend_short_v1",
                strategy_version="v1",
                family="Trend",
                strategy_cls=TrendStrategy,
                parameters={"lookback": 20},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="trend_short_v1_exp",
                experiment_family_id="TREND_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="trend_long_v1",
                strategy_version="v1",
                family="Trend",
                strategy_cls=TrendStrategy,
                parameters={"lookback": 120},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="trend_long_v1_exp",
                experiment_family_id="TREND_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="momentum_medium_v1",
                strategy_version="v1",
                family="Momentum",
                strategy_cls=MomentumMediumStrategy,
                parameters={"lookback": 60},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="momentum_medium_v1_exp",
                experiment_family_id="MOMENTUM_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="momentum_risk_adjusted_v1",
                strategy_version="v1",
                family="Momentum",
                strategy_cls=MomentumRiskAdjustedStrategy,
                parameters={"lookback": 60, "vol_lookback": 20},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="momentum_risk_adjusted_v1_exp",
                experiment_family_id="MOMENTUM_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="breakout_strength_v1",
                strategy_version="v1",
                family="Breakout",
                strategy_cls=BreakoutStrengthStrategy,
                parameters={"lookback": 20},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="breakout_strength_v1_exp",
                experiment_family_id="BREAKOUT_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="breakout_confirmation_v1",
                strategy_version="v1",
                family="Breakout",
                strategy_cls=BreakoutConfirmationStrategy,
                parameters={"lookback": 20},
                required_inputs=["daily_price", "daily_volume"],
                requires_eod_policy=True,
                experiment_id="breakout_confirmation_v1_exp",
                experiment_family_id="BREAKOUT_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="volatility_level_v1",
                strategy_version="v1",
                family="Volatility",
                strategy_cls=VolatilityLevelStrategy,
                parameters={"lookback": 20},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="volatility_level_v1_exp",
                experiment_family_id="VOLATILITY_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="volatility_change_v1",
                strategy_version="v1",
                family="Volatility",
                strategy_cls=VolatilityChangeStrategy,
                parameters={"lookback_short": 10, "lookback_long": 30},
                required_inputs=["daily_price"],
                requires_eod_policy=True,
                experiment_id="volatility_change_v1_exp",
                experiment_family_id="VOLATILITY_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="volume_trend_v1",
                strategy_version="v1",
                family="PriceVolume",
                strategy_cls=VolumeTrendStrategy,
                parameters={"lookback": 20},
                required_inputs=["daily_price", "daily_volume"],
                requires_eod_policy=True,
                experiment_id="volume_trend_v1_exp",
                experiment_family_id="PRICE_VOLUME_FAMILY_001",
            ),
            StrategyVariantDefinition(
                strategy_id="volume_price_correlation_v1",
                strategy_version="v1",
                family="PriceVolume",
                strategy_cls=VolumePriceCorrelationStrategy,
                parameters={"lookback": 20},
                required_inputs=["daily_price", "daily_volume"],
                requires_eod_policy=True,
                experiment_id="volume_price_correlation_v1_exp",
                experiment_family_id="PRICE_VOLUME_FAMILY_001",
            ),
        ]
        return variants

    # ---------------------------------------------------------------- Experiment Registration
    def _register_experiment(self, variant: StrategyVariantDefinition, fold_count: int = 8) -> None:
        record = ExperimentRecord(
            experiment_id=variant.experiment_id,
            parent_experiment_id=None,
            hypothesis="",
            strategy_family=variant.family,
            strategy_id=variant.strategy_id,
            strategy_version=variant.strategy_version,
            variant_id=variant.strategy_version,
            parameters=variant.parameters,
            parameter_space={k: [v] for k, v in variant.parameters.items()},
            required_datasets=variant.required_inputs,
            required_features=variant.required_inputs,
            required_pit_policies={inp: "CONDITIONAL" for inp in variant.required_inputs},
            target_id="future_excess_return",
            target_version=self.target_version,
            universe_version=self.universe_version,
            research_window={},
            fold_policy=self.fold_policy,
            evaluation_metrics=["IC", "RankIC", "MeanExcessReturn", "HitRate"],
            selection_rule="none",
            selection_event=SELECTION_EVENT_NONE,
            researcher="system",
            status=EXPERIMENT_STATUS_REGISTERED,
        )
        self.experiment_registry.register_experiment(record)

    # ---------------------------------------------------------------- Run Single Variant
    def run_variant(self, variant: StrategyVariantDefinition) -> Dict[str, Any]:
        from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition

        baseline_cls = None
        for v in self.build_variant_catalog():
            if v.strategy_id == "naive_baseline_v1":
                baseline_cls = v
                break
        if baseline_cls is None:
            raise RuntimeError("Baseline variant not found in catalog")

        strategy = variant.strategy_cls(**variant.parameters)
        baseline = baseline_cls.strategy_cls(**baseline_cls.parameters)

        engine = WalkForwardEngine(
            universe_fetcher=self.universe_fetcher,
            kline_loader=self.kline_loader,
            db_path=self.db_path,
            dataset_version=self.dataset_version,
            universe_version=self.universe_version,
            target_version=self.target_version,
            pit_policy="PIT_RESEARCH_V1",
            fold_policy=self.fold_policy,
        )

        folds = engine.define_folds_auto(
            train_window_days=self.train_window_days,
            validation_window_days=self.validation_window_days,
            embargo_days=self.embargo_days,
            min_folds=self.min_folds,
            max_folds=self.max_folds,
        )

        fold_outputs = []
        for fold in folds:
            fold_result = engine.run_fold(
                fold=fold,
                strategy=strategy,
                baseline_strategy=baseline,
                horizons=self.horizons,
                normalization_method="percentile",
            )
            fold_outputs.append(fold_result)
            self.fold_results.append({
                "strategy_id": variant.strategy_id,
                "strategy_version": variant.strategy_version,
                "family": variant.family,
                "experiment_id": variant.experiment_id,
                **self._fold_result_to_dict(fold_result),
            })

        summary = engine._aggregate_stability(
            [r for r in fold_outputs if r.fold_status == "VALID_FOLD"]
        )
        valid_count = sum(1 for r in fold_outputs if r.fold_status == "VALID_FOLD")
        low_sample_count = sum(1 for r in fold_outputs if r.fold_status == "LOW_SAMPLE")
        blocked_count = sum(1 for r in fold_outputs if r.fold_status in ("INVALID_FOLD", "DATA_QUALITY_WARNING"))

        if blocked_count > 0 and valid_count == 0:
            overall_status = EXPERIMENT_STATUS_BLOCKED
        elif valid_count == 0:
            overall_status = EXPERIMENT_STATUS_NO_EVIDENCE
        else:
            overall_status = EXPERIMENT_STATUS_COMPLETED

        variant_summary = {
            "strategy_id": variant.strategy_id,
            "strategy_version": variant.strategy_version,
            "family": variant.family,
            "experiment_id": variant.experiment_id,
            "status": overall_status,
            "fold_count": len(fold_outputs),
            "valid_fold_count": valid_count,
            "low_sample_fold_count": low_sample_count,
            "blocked_fold_count": blocked_count,
            "stability": summary,
            "parameters": variant.parameters,
        }
        self.variant_summaries[variant.strategy_id] = variant_summary
        return variant_summary

    # ---------------------------------------------------------------- Run All Variants
    def run_all(self) -> Dict[str, Any]:
        variants = self.build_variant_catalog()
        for variant in variants:
            self._register_experiment(variant)
        for variant in variants:
            self.run_variant(variant)
        self._aggregate_families()
        self._update_multiple_testing()
        return self.report()

    # ---------------------------------------------------------------- Family Aggregation
    def _aggregate_families(self) -> None:
        families = ["Trend", "Momentum", "Reversal", "Breakout", "Volatility", "PriceVolume", "Baseline"]
        for family in families:
            family_variants = [v for v in self.variant_summaries.values() if v["family"] == family]
            if not family_variants:
                continue
            valid_folds = []
            for v in family_variants:
                stability = v.get("stability", {})
                ic_stats = stability.get("ic", {})
                if ic_stats.get("mean") is not None:
                    valid_folds.append(v)
            self.family_summaries[family] = {
                "variant_count": len(family_variants),
                "valid_variant_count": len(valid_folds),
                "status": self._family_status(family_variants),
            }

    @staticmethod
    def _family_status(variants: List[dict]) -> str:
        statuses = [v.get("status", "UNKNOWN") for v in variants]
        if all(s == "COMPLETED" for s in statuses):
            return "COMPLETED"
        if all(s == "NO_EVIDENCE" for s in statuses):
            return "NO_EVIDENCE"
        if any(s == "BLOCKED" for s in statuses):
            return "PARTIALLY_BLOCKED"
        return "MIXED"

    # ---------------------------------------------------------------- Multiple Testing Update
    def _update_multiple_testing(self) -> None:
        from core.research.multiple_testing_registry import MultipleTestingRegistry, ExperimentRecord

        registry_summary = self.experiment_registry.summary()
        total_experiments = registry_summary["total_experiments"]
        total_families = registry_summary["total_families"]
        total_variants = len(self.variant_summaries)
        parameter_variants = sum(
            1 for v in self.variant_summaries.values()
            if len(v.get("parameters", {})) > 1
        )
        feature_variants = sum(
            1 for v in self.build_variant_catalog()
            if len(v.required_inputs) > 1
        )
        completed = sum(1 for v in self.variant_summaries.values() if v.get("status") == "COMPLETED")
        no_evidence = sum(1 for v in self.variant_summaries.values() if v.get("status") == "NO_EVIDENCE")
        failed = sum(1 for v in self.variant_summaries.values() if v.get("status") == "FAILED")
        blocked = sum(1 for v in self.variant_summaries.values() if v.get("status") == "BLOCKED")

        # Register each variant as an individual experiment record
        for variant in self.build_variant_catalog():
            summary = self.variant_summaries.get(variant.strategy_id, {})
            record = ExperimentRecord(
                experiment_id=variant.experiment_id,
                strategy_id=variant.strategy_id,
                strategy_version=variant.strategy_version,
                strategy_family=variant.family,
                parameter_space=variant.parameters,
                features=variant.required_inputs,
                target="future_excess_return",
                target_version="v1",
                research_window={},
                result_selection=summary.get("status", "UNKNOWN"),
                status=summary.get("status", "UNKNOWN"),
            )
            self.multiple_testing_registry.register(record)

    # ---------------------------------------------------------------- PBO / DSR Applicability
    def pbo_dsr_applicability(self) -> Dict[str, Any]:
        from core.research.experiment_governance import MultipleTestingApplicability
        pbo = MultipleTestingApplicability.assess_pbo(self.experiment_registry)
        dsr = MultipleTestingApplicability.assess_dsr(self.experiment_registry)
        return {
            "pbo_applicable": pbo.get("pbo_applicable", False),
            "pbo_reason": pbo.get("pbo_reason", ""),
            "dsr_applicable": dsr.get("dsr_applicable", False),
            "dsr_reason": dsr.get("dsr_reason", ""),
        }

    # ---------------------------------------------------------------- Report
    def report(self) -> Dict[str, Any]:
        registry_summary = self.experiment_registry.summary()
        return {
            "total_families": len(self.family_summaries),
            "total_variants": len(self.variant_summaries),
            "total_experiments": registry_summary["total_experiments"],
            "family_summaries": self.family_summaries,
            "variant_summaries": self.variant_summaries,
            "fold_results": self.fold_results,
            "multiple_testing_snapshot": self.multiple_testing_registry.latest_snapshot(),
            "pbo_dsr": self.pbo_dsr_applicability(),
        }

    # ---------------------------------------------------------------- Helpers
    @staticmethod
    def _fold_result_to_dict(r) -> Dict[str, Any]:
        return {
            "fold_id": r.fold_id,
            "strategy_id": r.strategy_id,
            "strategy_version": r.strategy_version,
            "horizon": r.horizon,
            "train_start": r.train_start,
            "train_end": r.train_end,
            "validation_start": r.validation_start,
            "validation_end": r.validation_end,
            "fold_policy": r.fold_policy,
            "universe_size": r.universe_size,
            "signal_count": r.signal_count,
            "eligible_count": r.eligible_count,
            "valid_target_count": r.valid_target_count,
            "missing_target_count": r.missing_target_count,
            "excluded_anomaly_count": r.excluded_anomaly_count,
            "excluded_anomaly_ratio": r.excluded_anomaly_ratio,
            "baseline_ic": r.baseline_ic,
            "baseline_rank_ic": r.baseline_rank_ic,
            "baseline_mean_excess": r.baseline_mean_excess,
            "strategy_ic": r.strategy_ic,
            "strategy_rank_ic": r.strategy_rank_ic,
            "strategy_mean_excess": r.strategy_mean_excess,
            "strategy_hit_rate": r.strategy_hit_rate,
            "ic_delta": r.ic_delta,
            "rank_ic_delta": r.rank_ic_delta,
            "mean_excess_delta": r.mean_excess_delta,
            "market_period": r.market_period,
            "fold_status": r.fold_status,
            "evidence_strength": r.evidence_strength,
            "result_summary": r.result_summary,
            "created_at": r.created_at,
        }
