#!/usr/bin/env python3
"""
strategy_research_pilot.py — Strategy Research Pilot Runner
=============================================================
Runs a bounded sample of strategies against the canonical target engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from .target_engine import TargetEngine, HORIZONS
from .reference_benchmark import ReferenceBenchmark
from .signal_normalization import NormalizationLayer
from .research_artifact_store import ResearchArtifactStore, StrategyResearchRun
from .strategies.trend_strategy import TrendStrategy
from .strategies.momentum_strategy import MomentumStrategy
from .strategies.reversal_strategy import ReversalStrategy
from .strategies.naive_baseline import NaiveBaselineStrategy


class StrategyResearchPilot:
    """Runs strategy research pilot on bounded sample."""

    def __init__(
        self,
        universe_fetcher,
        kline_loader,
        db_path: str,
        dataset_version: str = "v1",
        universe_version: str = "RESEARCH_UNIVERSE_V1",
        target_version: str = "v1",
        pit_policy: str = "PIT_RESEARCH_V1",
    ):
        self.universe_fetcher = universe_fetcher
        self.kline_loader = kline_loader
        self.db_path = db_path
        self.dataset_version = dataset_version
        self.universe_version = universe_version
        self.target_version = target_version
        self.pit_policy = pit_policy

        self.target_engine = TargetEngine(
            universe_fetcher=universe_fetcher,
            kline_loader=kline_loader,
            db_path=db_path,
            reference_method="UNIVERSE_MEDIAN",
        )
        self.reference_benchmark = ReferenceBenchmark(
            universe_fetcher=universe_fetcher,
            kline_loader=kline_loader,
        )
        self.normalization_layer = NormalizationLayer(method="percentile")
        self.artifact_store = ResearchArtifactStore(db_path)

    def run_strategy(
        self,
        strategy,
        decision_time: str,
        horizon: int = 5,
    ) -> Dict[str, Any]:
        """Run a single strategy at decision_time for given horizon."""
        universe = self.universe_fetcher(decision_time)
        if not universe:
            return {
                "strategy_id": strategy.strategy_id,
                "strategy_version": strategy.strategy_version,
                "decision_time": decision_time,
                "horizon": horizon,
                "status": "BLOCKED",
                "reason": "EMPTY_UNIVERSE",
            }

        # Set strategy horizon
        strategy.horizon = horizon
        strategy.normalization_layer = self.normalization_layer

        # Generate signals
        signals = strategy.run(universe, decision_time)
        eligible_signals = [s for s in signals if s.eligibility]
        rejected_signals = [s for s in signals if not s.eligibility]

        # Compute targets for eligible signals
        targets = []
        for signal in eligible_signals:
            target = self.target_engine.compute_target(
                {
                    "symbol": signal.stock_code,
                    "candidate_date": decision_time,
                    "entry_price": None,
                    "entry_date": None,
                },
                decision_time=decision_time,
            )
            targets.append(target)

        # Evaluation metrics
        valid_targets = [t for t in targets if t.target_status == "VALID" and t.excess_return is not None]
        missing_targets = [t for t in targets if t.target_status != "VALID"]

        evaluation = self._compute_evaluation(eligible_signals, valid_targets)

        # Store artifact
        run_id = f"{strategy.strategy_id}_{strategy.strategy_version}_{decision_time}_{horizon}_{uuid.uuid4().hex[:8]}"
        created_at = datetime.utcnow().isoformat() + "Z"

        run = StrategyResearchRun(
            run_id=run_id,
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.strategy_version,
            decision_time=decision_time,
            universe_version=self.universe_version,
            dataset_version=self.dataset_version,
            target_version=self.target_version,
            pit_policy=self.pit_policy,
            input_datasets=",".join(strategy.required_inputs),
            rejected_datasets=",".join([s.reason_code for s in rejected_signals]),
            signal_count=len(signals),
            eligible_count=len(eligible_signals),
            mean_signal=evaluation.get("mean_signal"),
            mean_excess_return=evaluation.get("mean_excess_return"),
            median_excess_return=evaluation.get("median_excess_return"),
            ic=evaluation.get("ic"),
            rank_ic=evaluation.get("rank_ic"),
            hit_rate=evaluation.get("hit_rate"),
            turnover_proxy=None,
            missing_target_rate=len(missing_targets) / len(targets) if targets else 0.0,
            result_summary=f"valid={len(valid_targets)} missing={len(missing_targets)}",
            created_at=created_at,
        )
        self.artifact_store.store_run(run)

        return {
            "run_id": run_id,
            "strategy_id": strategy.strategy_id,
            "strategy_version": strategy.strategy_version,
            "decision_time": decision_time,
            "horizon": horizon,
            "status": "COMPLETE",
            "signal_count": len(signals),
            "eligible_count": len(eligible_signals),
            "valid_target_count": len(valid_targets),
            "missing_target_count": len(missing_targets),
            "evaluation": evaluation,
        }

    def _compute_evaluation(self, signals, valid_targets) -> Dict[str, Any]:
        """Compute evaluation metrics for a set of signals and targets."""
        if not signals or not valid_targets:
            return {
                "mean_signal": None,
                "mean_excess_return": None,
                "median_excess_return": None,
                "ic": None,
                "rank_ic": None,
                "hit_rate": None,
            }

        # Build signal -> target mapping
        signal_map = {s.stock_code: s for s in signals}
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

        # IC = correlation(raw_score, excess_return)
        ic = self._pearson_correlation(raw_scores, excess_returns)

        # Rank IC = correlation(rank(raw_score), rank(excess_return))
        rank_ic = self._pearson_correlation(
            [self._rank(raw_scores)],
            [self._rank(excess_returns)],
        )

        # Hit rate = fraction where signal direction matches excess return direction
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

    @staticmethod
    def _pearson_correlation(x: List[float], y: List[float]) -> Optional[float]:
        """Compute Pearson correlation."""
        n = len(x)
        if n < 2:
            return None
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        var_x = sum((xi - mean_x) ** 2 for xi in x)
        var_y = sum((yi - mean_y) ** 2 for yi in y)
        if var_x == 0 or var_y == 0:
            return 0.0
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        return cov / (var_x ** 0.5 * var_y ** 0.5)

    @staticmethod
    def _rank(values: List[float]) -> List[float]:
        """Convert values to ranks [1, n]."""
        sorted_vals = sorted(values)
        return [sorted_vals.index(v) + 1 for v in values]
