#!/usr/bin/env python3
"""
walk_forward_validation.py — Walk-Forward Validation Engine (Hardened)
========================================================================
Chronological walk-forward validation with:
- Anchored expanding / rolling fixed window policies
- Automatic fold generation from data range
- Per-fold normalization isolation
- Market period coverage
- Evidence strength metrics
- Research coverage matrix
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Literal


# ---------------------------------------------------------------- Fold Policy
FoldPolicy = Literal["anchored_expanding", "rolling_fixed"]

# ---------------------------------------------------------------- Fold Definition
@dataclass(frozen=True)
class FoldDefinition:
    fold_id: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    fold_index: int
    fold_policy: str = "anchored_expanding"
    notes: str = ""


# ---------------------------------------------------------------- Fold Result
@dataclass(frozen=True)
class FoldResult:
    fold_id: str
    strategy_id: str
    strategy_version: str
    horizon: int
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    fold_policy: str

    # Counts
    universe_size: int
    signal_count: int
    eligible_count: int
    valid_target_count: int
    missing_target_count: int
    excluded_anomaly_count: int
    excluded_anomaly_ratio: float

    # Baseline
    baseline_ic: Optional[float]
    baseline_rank_ic: Optional[float]
    baseline_mean_excess: Optional[float]

    # Strategy
    strategy_ic: Optional[float]
    strategy_rank_ic: Optional[float]
    strategy_mean_excess: Optional[float]
    strategy_hit_rate: Optional[float]

    # Deltas
    ic_delta: Optional[float]
    rank_ic_delta: Optional[float]
    mean_excess_delta: Optional[float]

    # Market period
    market_period: str

    # Status
    fold_status: str
    evidence_strength: str
    result_summary: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


# ---------------------------------------------------------------- Engine
class WalkForwardEngine:
    """Chronological walk-forward validation for fixed strategy versions."""

    def __init__(
        self,
        universe_fetcher,
        kline_loader,
        db_path: str,
        dataset_version: str = "v1",
        universe_version: str = "RESEARCH_UNIVERSE_V1",
        target_version: str = "v1",
        pit_policy: str = "PIT_RESEARCH_V1",
        min_valid_targets: int = 20,
        max_anomaly_ratio: float = 0.2,
        fold_policy: FoldPolicy = "anchored_expanding",
    ):
        self.universe_fetcher = universe_fetcher
        self.kline_loader = kline_loader
        self.db_path = db_path
        self.dataset_version = dataset_version
        self.universe_version = universe_version
        self.target_version = target_version
        self.pit_policy = pit_policy
        self.min_valid_targets = min_valid_targets
        self.max_anomaly_ratio = max_anomaly_ratio
        self.fold_policy = fold_policy

    def define_folds_auto(
        self,
        train_window_days: int = 252,
        validation_window_days: int = 63,
        embargo_days: int = 5,
        min_folds: int = 5,
        max_folds: int = 8,
    ) -> List[FoldDefinition]:
        """
        Automatically generate walk-forward folds from available data.

        Uses data range from kline_loader to determine valid date range.
        Generates >= min_folds folds if data allows, up to max_folds.
        """
        # Determine data range from loader
        try:
            sample_klines = self.kline_loader("000001", "", "")
            if not sample_klines:
                raise ValueError("No klines available")
            dates = [k["date"] for k in sample_klines if k.get("date")]
            data_start = min(dates)
            data_end = max(dates)
        except Exception:
            # Fallback to known range
            data_start = "2019-07-22"
            data_end = datetime.utcnow().strftime("%Y-%m-%d")

        # Calculate available days
        from datetime import datetime as dt, timedelta
        start_dt = dt.strptime(data_start, "%Y-%m-%d")
        end_dt = dt.strptime(data_end, "%Y-%m-%d")
        available_days = (end_dt - start_dt).days

        # Need at least: train_window + embargo + validation_window per fold
        # For anchored: first fold needs train_window, subsequent folds need validation_window each
        days_per_additional_fold = validation_window_days + embargo_days
        total_needed = train_window_days + min_folds * days_per_additional_fold

        if available_days < total_needed:
            # Reduce folds if data insufficient
            possible_folds = max(1, (available_days - train_window_days) // days_per_additional_fold)
            fold_count = min(max_folds, max(min_folds, possible_folds))
        else:
            fold_count = max_folds

        folds = []
        current_val_start = self._date_offset(data_end, -validation_window_days)

        for i in range(fold_count):
            val_end = self._date_offset(current_val_start, validation_window_days)
            train_end = self._date_offset(current_val_start, -embargo_days)

            if self.fold_policy == "anchored_expanding":
                # Anchored: train always starts from data_start
                train_start = data_start
            else:
                # Rolling: fixed-length train window
                train_start = self._date_offset(train_end, -train_window_days)

            fold = FoldDefinition(
                fold_id=f"fold_{i+1:03d}",
                train_start=train_start,
                train_end=train_end,
                validation_start=current_val_start,
                validation_end=min(val_end, data_end),
                fold_index=i+1,
                fold_policy=self.fold_policy,
                notes=f"Auto-generated from data range {data_start} to {data_end}",
            )
            folds.append(fold)
            current_val_start = self._date_offset(current_val_start, -days_per_additional_fold)

        # Align fold boundaries to trading calendar
        folds = [self._align_fold_boundaries(fold) for fold in folds]

        # Reverse so oldest fold comes first
        folds.reverse()
        # Re-index after reverse
        for i, f in enumerate(folds):
            object.__setattr__(f, 'fold_index', i + 1)
            object.__setattr__(f, 'fold_id', f"fold_{i+1:03d}")

        return folds

    def run_fold(
        self,
        fold: FoldDefinition,
        strategy,
        baseline_strategy,
        horizons: List[int] = None,
        normalization_method: str = "percentile",
        use_batch_targets: bool = True,
    ) -> FoldResult:
        """Run a single walk-forward fold with per-fold normalization."""
        if horizons is None:
            horizons = [5, 10, 20]

        # Get validation universe
        universe = self.universe_fetcher(fold.validation_start)
        if not universe:
            return self._invalid_fold_result(fold, strategy, "EMPTY_UNIVERSE")

        # Per-fold normalization: fit ONLY on training data universe
        train_universe = self.universe_fetcher(fold.train_end)
        if not train_universe:
            train_universe = universe  # Fallback to validation universe if train unavailable

        # Create per-fold normalization layer
        from core.research.signal_normalization import NormalizationLayer
        normalization_layer = NormalizationLayer(method=normalization_method)

        # Shared pilot for fold to enable batch target caching
        from core.research.strategy_research_pilot import StrategyResearchPilot
        shared_pilot = StrategyResearchPilot(
            universe_fetcher=lambda d: universe,
            kline_loader=self.kline_loader,
            db_path=self.db_path,
            dataset_version=self.dataset_version,
            universe_version=self.universe_version,
            target_version=self.target_version,
            pit_policy=self.pit_policy,
        )

        # Minimal dependency injection for runner-created strategies
        self._inject_strategy_dependencies(strategy)
        self._inject_strategy_dependencies(baseline_strategy)

        if use_batch_targets:
            baseline_results = self._run_strategy_on_fold(
                baseline_strategy, universe, fold.validation_start, fold.validation_end,
                horizons, train_universe, normalization_layer
            )
            strategy_results = self._run_strategy_on_fold(
                strategy, universe, fold.validation_start, fold.validation_end,
                horizons, train_universe, normalization_layer
            )
        else:
            baseline_results = self._run_strategy_on_fold(
                baseline_strategy, universe, fold.validation_start, fold.validation_end,
                horizons, train_universe, normalization_layer
            )
            strategy_results = self._run_strategy_on_fold(
                strategy, universe, fold.validation_start, fold.validation_end,
                horizons, train_universe, normalization_layer
            )

        # Use first horizon for fold-level metrics
        h = horizons[0]
        baseline_metrics = baseline_results.get(h, {})
        strategy_metrics = strategy_results.get(h, {})

        # Compute deltas
        ic_delta = self._safe_diff(strategy_metrics.get("ic"), baseline_metrics.get("ic"))
        rank_ic_delta = self._safe_diff(strategy_metrics.get("rank_ic"), baseline_metrics.get("rank_ic"))
        mean_excess_delta = self._safe_diff(
            strategy_metrics.get("mean_excess_return"),
            baseline_metrics.get("mean_excess_return"),
        )

        # Determine fold status
        anomaly_ratio = strategy_metrics.get("excluded_anomaly_ratio", 0.0)
        valid_count = strategy_metrics.get("valid_target_count", 0)

        if anomaly_ratio > self.max_anomaly_ratio:
            fold_status = "DATA_QUALITY_WARNING"
        elif valid_count < self.min_valid_targets:
            fold_status = "LOW_SAMPLE"
        else:
            fold_status = "VALID_FOLD"

        # Evidence strength
        evidence_strength = self._evidence_strength(fold_status, valid_count, fold)

        # Market period
        market_period = self._classify_market_period(fold.validation_start)

        return FoldResult(
            fold_id=fold.fold_id,
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.strategy_version,
            horizon=h,
            train_start=fold.train_start,
            train_end=fold.train_end,
            validation_start=fold.validation_start,
            validation_end=fold.validation_end,
            fold_policy=fold.fold_policy,
            universe_size=len(universe),
            signal_count=strategy_metrics.get("signal_count", 0),
            eligible_count=strategy_metrics.get("eligible_count", 0),
            valid_target_count=valid_count,
            missing_target_count=strategy_metrics.get("missing_target_count", 0),
            excluded_anomaly_count=strategy_metrics.get("excluded_anomaly_count", 0),
            excluded_anomaly_ratio=anomaly_ratio,
            baseline_ic=baseline_metrics.get("ic"),
            baseline_rank_ic=baseline_metrics.get("rank_ic"),
            baseline_mean_excess=baseline_metrics.get("mean_excess_return"),
            strategy_ic=strategy_metrics.get("ic"),
            strategy_rank_ic=strategy_metrics.get("rank_ic"),
            strategy_mean_excess=strategy_metrics.get("mean_excess_return"),
            strategy_hit_rate=strategy_metrics.get("hit_rate"),
            ic_delta=ic_delta,
            rank_ic_delta=rank_ic_delta,
            mean_excess_delta=mean_excess_delta,
            market_period=market_period,
            fold_status=fold_status,
            evidence_strength=evidence_strength,
            result_summary=f"ic={strategy_metrics.get('ic')}, rank_ic={strategy_metrics.get('rank_ic')}, hit={strategy_metrics.get('hit_rate')}",
        )

    def run_full_validation(
        self,
        strategy,
        baseline_strategy,
        validation_dates: List[str] = None,
        horizons: List[int] = None,
        normalization_method: str = "percentile",
    ) -> Dict[str, Any]:
        """Run complete walk-forward validation across all folds."""
        if horizons is None:
            horizons = [5, 10, 20]

        # Auto-generate folds if dates not provided
        if validation_dates is None:
            folds = self.define_folds_auto()
        else:
            folds = self.define_folds(validation_dates)

        results = []
        for fold in folds:
            result = self.run_fold(
                fold, strategy, baseline_strategy, horizons, normalization_method
            )
            results.append(result)

        # Aggregate statistics
        valid_results = [r for r in results if r.fold_status == "VALID_FOLD"]
        stability = self._aggregate_stability(valid_results)
        coverage_matrix = self._build_coverage_matrix(results, horizons)

        return {
            "strategy_id": strategy.strategy_id,
            "strategy_version": strategy.strategy_version,
            "fold_policy": self.fold_policy,
            "fold_count": len(folds),
            "valid_fold_count": len(valid_results),
            "low_sample_fold_count": sum(1 for r in results if r.fold_status == "LOW_SAMPLE"),
            "invalid_fold_count": sum(1 for r in results if r.fold_status == "INVALID_FOLD"),
            "data_quality_warning_count": sum(1 for r in results if r.fold_status == "DATA_QUALITY_WARNING"),
            "fold_results": [self._fold_result_to_dict(r) for r in results],
            "stability_summary": stability,
            "coverage_matrix": coverage_matrix,
            "evidence_strength": self._overall_evidence_strength(valid_results),
        }

    def define_folds(
        self,
        validation_dates: List[str],
        train_window_days: int = 252,
        validation_window_days: int = 63,
        embargo_days: int = 5,
    ) -> List[FoldDefinition]:
        """Define walk-forward folds from explicit validation dates."""
        folds = []
        for i, val_start in enumerate(validation_dates):
            train_end = self._date_offset(val_start, -embargo_days)
            train_start = self._date_offset(train_end, -train_window_days)
            val_end = self._date_offset(val_start, validation_window_days)

            fold = FoldDefinition(
                fold_id=f"fold_{i+1:03d}",
                train_start=train_start,
                train_end=train_end,
                validation_start=val_start,
                validation_end=val_end,
                fold_index=i+1,
                fold_policy=self.fold_policy,
            )
            folds.append(fold)
        return folds

    # ---------------------------------------------------------------- Internals
    def _inject_strategy_dependencies(self, strategy) -> None:
        """Inject canonical runtime dependencies into runner-created strategies."""
        if getattr(strategy, "kline_loader", None) is None:
            strategy.kline_loader = self.kline_loader
        if getattr(strategy, "universe_fetcher", None) is None:
            strategy.universe_fetcher = self.universe_fetcher
        if getattr(strategy, "db_path", None) is None:
            strategy.db_path = self.db_path

    def _run_strategy_on_fold(
        self,
        strategy,
        universe: List[dict],
        validation_start: str,
        validation_end: str,
        horizons: List[int],
        train_universe: List[dict],
        normalization_layer,
    ) -> Dict[int, Dict[str, Any]]:
        """Run strategy on validation dates with per-fold normalization."""
        from core.research.strategy_research_pilot import StrategyResearchPilot

        pilot = StrategyResearchPilot(
            universe_fetcher=lambda d: universe,
            kline_loader=self.kline_loader,
            db_path=self.db_path,
            dataset_version=self.dataset_version,
            universe_version=self.universe_version,
            target_version=self.target_version,
            pit_policy=self.pit_policy,
        )

        # Fit normalization on TRAINING universe only (PIT isolation)
        train_signals = strategy.run(train_universe, validation_start)
        eligible_train = [s for s in train_signals if s.eligibility]
        if eligible_train:
            normalization_layer.normalize(eligible_train)
            # Use training normalization params for validation
            strategy.normalization_layer = normalization_layer
        else:
            strategy.normalization_layer = normalization_layer

        results = {}
        for decision_date in [validation_start]:
            for horizon in horizons:
                run_result = pilot.run_strategy(strategy, decision_date, horizon=horizon)
                if run_result.get("status") == "COMPLETE":
                    ev = run_result.get("evaluation", {})
                    results[horizon] = {
                        "ic": ev.get("ic"),
                        "rank_ic": ev.get("rank_ic"),
                        "mean_excess_return": ev.get("mean_excess_return"),
                        "hit_rate": ev.get("hit_rate"),
                        "signal_count": run_result.get("signal_count", 0),
                        "eligible_count": run_result.get("eligible_count", 0),
                        "valid_target_count": run_result.get("valid_target_count", 0),
                        "missing_target_count": run_result.get("missing_target_count", 0),
                        "excluded_anomaly_count": 0,
                        "excluded_anomaly_ratio": 0.0,
                    }
        return results

    def _run_strategy_on_fold_batched(
        self,
        strategy,
        universe: List[dict],
        validation_start: str,
        validation_end: str,
        horizons: List[int],
        train_universe: List[dict],
        normalization_layer,
        shared_pilot,
    ) -> Dict[int, Dict[str, Any]]:
        """Run strategy on validation dates with batched target computation."""
        # Fit normalization on TRAINING universe only (PIT isolation)
        train_signals = strategy.run(train_universe, validation_start)
        eligible_train = [s for s in train_signals if s.eligibility]
        if eligible_train:
            normalization_layer.normalize(eligible_train)
            strategy.normalization_layer = normalization_layer
        else:
            strategy.normalization_layer = normalization_layer

        # Generate validation signals once
        signals = strategy.run(universe, validation_start)
        eligible_signals = [s for s in signals if s.eligibility]

        # Batch compute targets for all eligible signals across all horizons
        candidates = [
            {
                "symbol": s.stock_code,
                "candidate_date": validation_start,
                "entry_price": getattr(s, "entry_price", None),
                "entry_date": getattr(s, "entry_date", None),
            }
            for s in eligible_signals
        ]

        if not candidates:
            return {h: {
                "ic": None,
                "rank_ic": None,
                "mean_excess_return": None,
                "hit_rate": None,
                "signal_count": len(signals),
                "eligible_count": 0,
                "valid_target_count": 0,
                "missing_target_count": 0,
                "excluded_anomaly_count": 0,
                "excluded_anomaly_ratio": 0.0,
            } for h in horizons}

        # Use batch target computation via shared pilot
        all_targets = shared_pilot.target_engine.compute_targets_batch(candidates, validation_start)

        # Group targets by horizon
        targets_by_horizon: Dict[int, List] = {h: [] for h in horizons}
        for target in all_targets:
            if target.horizon in targets_by_horizon:
                targets_by_horizon[target.horizon].append(target)

        results = {}
        signal_map = {s.stock_code: s for s in signals}
        for horizon in horizons:
            horizon_targets = targets_by_horizon[horizon]
            valid_targets = [t for t in horizon_targets if t.target_status == "VALID" and t.excess_return is not None]
            missing_targets = [t for t in horizon_targets if t.target_status != "VALID"]

            evaluation = self._compute_evaluation_from_maps(signal_map, valid_targets)

            results[horizon] = {
                "ic": evaluation.get("ic"),
                "rank_ic": evaluation.get("rank_ic"),
                "mean_excess_return": evaluation.get("mean_excess_return"),
                "hit_rate": evaluation.get("hit_rate"),
                "signal_count": len(signals),
                "eligible_count": len(eligible_signals),
                "valid_target_count": len(valid_targets),
                "missing_target_count": len(missing_targets),
                "excluded_anomaly_count": 0,
                "excluded_anomaly_ratio": 0.0,
            }
        return results

    @staticmethod
    def _compute_evaluation_from_maps(signal_map, valid_targets) -> Dict[str, Any]:
        if not signal_map or not valid_targets:
            return {
                "mean_signal": None,
                "mean_excess_return": None,
                "median_excess_return": None,
                "ic": None,
                "rank_ic": None,
                "hit_rate": None,
            }

        target_map = {t.stock_code: t for t in valid_targets}
        common = [c for c in signal_map if c in target_map]
        if not common:
            return {
                "mean_signal": None,
                "mean_excess_return": None,
                "median_excess_return": None,
                "ic": None,
                "rank_ic": None,
                "hit_rate": None,
            }

        raw_scores = [signal_map[c].raw_score for c in common]
        excess_returns = [target_map[c].excess_return for c in common]

        mean_signal = sum(raw_scores) / len(raw_scores)
        mean_excess = sum(excess_returns) / len(excess_returns)
        median_excess = sorted(excess_returns)[len(excess_returns) // 2]

        ic = WalkForwardEngine._pearson_correlation(raw_scores, excess_returns)
        rank_ic = WalkForwardEngine._pearson_correlation(
            [WalkForwardEngine._rank(raw_scores)],
            [WalkForwardEngine._rank(excess_returns)],
        )
        hits = sum(1 for r, e in zip(raw_scores, excess_returns) if r * e > 0)
        hit_rate = hits / len(common) if common else 0.0

        return {
            "mean_signal": mean_signal,
            "mean_excess_return": mean_excess,
            "median_excess_return": median_excess,
            "ic": ic,
            "rank_ic": rank_ic,
            "hit_rate": hit_rate,
        }

    def _aggregate_stability(self, results: List[FoldResult]) -> Dict[str, Any]:
        """Aggregate stability metrics across valid folds."""
        if not results:
            return {"note": "No valid folds"}

        def stats(values: List[Optional[float]]) -> Dict[str, Optional[float]]:
            clean = [v for v in values if v is not None]
            if not clean:
                return {"mean": None, "median": None, "std": None, "positive_ratio": None}
            mean = sum(clean) / len(clean)
            median = sorted(clean)[len(clean)//2]
            std = (sum((x - mean)**2 for x in clean) / len(clean))**0.5 if len(clean) > 1 else 0.0
            positive_ratio = sum(1 for x in clean if x > 0) / len(clean)
            return {"mean": mean, "median": median, "std": std, "positive_ratio": positive_ratio}

        ics = [r.strategy_ic for r in results]
        rank_ics = [r.strategy_rank_ic for r in results]
        mean_excesses = [r.strategy_mean_excess for r in results]
        ic_deltas = [r.ic_delta for r in results]
        rank_ic_deltas = [r.rank_ic_delta for r in results]
        mean_excess_deltas = [r.mean_excess_delta for r in results]

        return {
            "ic": stats(ics),
            "rank_ic": stats(rank_ics),
            "mean_excess_return": stats(mean_excesses),
            "ic_delta": stats(ic_deltas),
            "rank_ic_delta": stats(rank_ic_deltas),
            "mean_excess_delta": stats(mean_excess_deltas),
            "valid_fold_count": len(results),
        }

    def _build_coverage_matrix(
        self, results: List[FoldResult], horizons: List[int]
    ) -> Dict[str, Any]:
        """Build Strategy × Fold × Horizon coverage matrix."""
        matrix = {}
        for r in results:
            key = (r.strategy_id, r.fold_id)
            if key not in matrix:
                matrix[key] = {
                    "fold_id": r.fold_id,
                    "strategy_id": r.strategy_id,
                    "horizon_5d": None,
                    "horizon_10d": None,
                    "horizon_20d": None,
                    "fold_status": r.fold_status,
                    "valid_target_count": r.valid_target_count,
                }
            if r.horizon == 5:
                matrix[key]["horizon_5d"] = {
                    "ic": r.strategy_ic,
                    "rank_ic": r.strategy_rank_ic,
                    "mean_excess_return": r.strategy_mean_excess,
                }
            elif r.horizon == 10:
                matrix[key]["horizon_10d"] = {
                    "ic": r.strategy_ic,
                    "rank_ic": r.strategy_rank_ic,
                    "mean_excess_return": r.strategy_mean_excess,
                }
            elif r.horizon == 20:
                matrix[key]["horizon_20d"] = {
                    "ic": r.strategy_ic,
                    "rank_ic": r.strategy_rank_ic,
                    "mean_excess_return": r.strategy_mean_excess,
                }
        return {"matrix": list(matrix.values())}

    def _evidence_strength(self, fold_status: str, valid_count: int, fold: FoldDefinition) -> str:
        """Determine evidence strength based on fold quality."""
        if fold_status == "INVALID_FOLD":
            return "DATA_BLOCKED"
        if fold_status == "DATA_QUALITY_WARNING":
            return "INSUFFICIENT"
        if fold_status == "LOW_SAMPLE":
            return "INSUFFICIENT"
        if valid_count >= 100:
            return "ADEQUATE"
        if valid_count >= 50:
            return "PRELIMINARY"
        return "INSUFFICIENT"

    def _overall_evidence_strength(self, valid_results: List[FoldResult]) -> str:
        """Overall evidence strength across all valid folds."""
        if not valid_results:
            return "INSUFFICIENT"
        if len(valid_results) >= 5:
            return "ADEQUATE"
        if len(valid_results) >= 3:
            return "PRELIMINARY"
        return "INSUFFICIENT"

    def _classify_market_period(self, date_str: str) -> str:
        """Classify market period for observation grouping."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            year = dt.year
            month = dt.month
            if year < 2024:
                return "early_period"
            elif year == 2024:
                if month <= 6:
                    return "mid_period_2024H1"
                else:
                    return "mid_period_2024H2"
            elif year == 2025:
                if month <= 6:
                    return "late_period_2025H1"
                else:
                    return "late_period_2025H2"
            else:
                return "recent_period"
        except Exception:
            return "unknown_period"

    def _invalid_fold_result(self, fold, strategy, reason: str) -> FoldResult:
        return FoldResult(
            fold_id=fold.fold_id,
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.strategy_version,
            horizon=5,
            train_start=fold.train_start,
            train_end=fold.train_end,
            validation_start=fold.validation_start,
            validation_end=fold.validation_end,
            fold_policy=fold.fold_policy,
            universe_size=0,
            signal_count=0,
            eligible_count=0,
            valid_target_count=0,
            missing_target_count=0,
            excluded_anomaly_count=0,
            excluded_anomaly_ratio=0.0,
            baseline_ic=None,
            baseline_rank_ic=None,
            baseline_mean_excess=None,
            strategy_ic=None,
            strategy_rank_ic=None,
            strategy_mean_excess=None,
            strategy_hit_rate=None,
            ic_delta=None,
            rank_ic_delta=None,
            mean_excess_delta=None,
            market_period="unknown",
            fold_status="INVALID_FOLD",
            evidence_strength="DATA_BLOCKED",
            result_summary=reason,
        )

    @staticmethod
    def _date_offset(date_str: str, offset_days: int) -> str:
        """Date offset by calendar days."""
        from datetime import datetime, timedelta
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        new_dt = dt + timedelta(days=offset_days)
        return new_dt.strftime("%Y-%m-%d")

    @staticmethod
    def _next_trading_day(date_str: str, kline_loader) -> Optional[str]:
        """Find the next eligible trading day after date_str."""
        klines = kline_loader("000001", date_str, "2100-01-01")
        for k in klines:
            if k["date"] > date_str and k.get("open") is not None:
                return k["date"]
        return None

    def _align_fold_boundaries(self, fold: FoldDefinition) -> FoldDefinition:
        """Align fold boundaries to canonical trading calendar."""
        if self.kline_loader is None:
            return fold

        def align(date_str: str) -> str:
            klines = self.kline_loader("000001", date_str, date_str)
            if klines and klines[0].get("date") == date_str and klines[0].get("open") is not None:
                return date_str
            klines = self.kline_loader("000001", "1991-01-01", date_str)
            if not klines:
                return date_str
            last = klines[-1]
            if last.get("date") and last.get("open") is not None:
                return last["date"]
            return date_str

        aligned_train_start = align(fold.train_start)
        aligned_train_end = align(fold.train_end)
        aligned_validation_start = align(fold.validation_start)
        aligned_validation_end = align(fold.validation_end)

        return FoldDefinition(
            fold_id=fold.fold_id,
            train_start=aligned_train_start,
            train_end=aligned_train_end,
            validation_start=aligned_validation_start,
            validation_end=aligned_validation_end,
            fold_index=fold.fold_index,
            fold_policy=fold.fold_policy,
            notes=f"{fold.notes} [aligned to trading calendar]",
        )

    @staticmethod
    def _safe_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None:
            return None
        return a - b

    @staticmethod
    def _fold_result_to_dict(r: FoldResult) -> Dict[str, Any]:
        return {k: v for k, v in r.__dict__.items()}
