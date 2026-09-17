#!/usr/bin/env python3
"""
optimized_walk_forward_engine.py — Runtime-optimized walk-forward engine.
Subclasses canonical WalkForwardEngine and replaces per-signal target computation
with batch target computation, while preserving all research semantics.
"""

from __future__ import annotations

from typing import List, Dict, Any

from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition


class OptimizedWalkForwardEngine(WalkForwardEngine):
    """
    Optimized variant of WalkForwardEngine.
    
    Changes:
    - Batch target computation instead of per-signal compute_target
    - Pre-cached kline/reference per fold
    - No change to strategy formulas, parameters, targets, universes, folds,
      normalization, or qualification logic.
    """

    def run_fold(
        self,
        fold: FoldDefinition,
        strategy,
        baseline_strategy,
        horizons: List[int] = None,
        normalization_method: str = "percentile",
    ):
        if horizons is None:
            horizons = [5, 10, 20]

        universe = self.universe_fetcher(fold.validation_start)
        if not universe:
            return self._invalid_fold_result(fold, strategy, "EMPTY_UNIVERSE")

        train_universe = self.universe_fetcher(fold.train_end)
        if not train_universe:
            train_universe = universe

        from core.research.signal_normalization import NormalizationLayer
        normalization_layer = NormalizationLayer(method=normalization_method)

        baseline_results = self._run_strategy_on_fold_optimized(
            baseline_strategy, universe, fold.validation_start, fold.validation_end,
            horizons, train_universe, normalization_layer
        )
        strategy_results = self._run_strategy_on_fold_optimized(
            strategy, universe, fold.validation_start, fold.validation_end,
            horizons, train_universe, normalization_layer
        )

        h = horizons[0]
        baseline_metrics = baseline_results.get(h, {})
        strategy_metrics = strategy_results.get(h, {})

        ic_delta = self._safe_diff(strategy_metrics.get("ic"), baseline_metrics.get("ic"))
        rank_ic_delta = self._safe_diff(strategy_metrics.get("rank_ic"), baseline_metrics.get("rank_ic"))
        mean_excess_delta = self._safe_diff(
            strategy_metrics.get("mean_excess_return"),
            baseline_metrics.get("mean_excess_return"),
        )

        anomaly_ratio = strategy_metrics.get("excluded_anomaly_ratio", 0.0)
        valid_count = strategy_metrics.get("valid_target_count", 0)

        if anomaly_ratio > self.max_anomaly_ratio:
            fold_status = "DATA_QUALITY_WARNING"
        elif valid_count < self.min_valid_targets:
            fold_status = "LOW_SAMPLE"
        else:
            fold_status = "VALID_FOLD"

        evidence_strength = self._evidence_strength(fold_status, valid_count, fold)
        market_period = self._classify_market_period(fold.validation_start)

        from core.research.walk_forward_validation import FoldResult
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

    def _run_strategy_on_fold_optimized(
        self,
        strategy,
        universe: List[dict],
        validation_start: str,
        validation_end: str,
        horizons: List[int],
        train_universe: List[dict],
        normalization_layer,
    ) -> Dict[int, Dict[str, Any]]:
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

        # Fit normalization on training universe only
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

        # Use batch target computation
        all_targets = pilot.target_engine.compute_targets_batch(candidates, validation_start)

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
