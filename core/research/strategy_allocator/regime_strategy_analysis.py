#!/usr/bin/env python3
"""
stock-work/core/research/strategy_allocator/regime_strategy_analysis.py

Phase C1: Regime Conditional Analysis.

Analyzes historical strategy performance conditioned on market regimes.
Outputs per-strategy, per-regime performance metrics.

Important:
- This is research-only.
- No production trading decisions.
- No automatic strategy switching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.research.market_context.context_schema import (
    IntermediateState,
    RiskState,
    StructuralState,
    TacticalState,
)


@dataclass(frozen=True)
class StrategyRegimePerformance:
    strategy_id: str
    regime_state: str
    horizon: int
    fold: str
    ic_mean: Optional[float]
    ic_std: Optional[float]
    win_rate: Optional[float]
    drawdown: Optional[float]
    sample_count: int
    confidence: str
    notes: str = ""


class RegimeStrategyAnalyzer:
    """
    Computes strategy performance metrics grouped by regime state.

    Inputs are expected to be pre-aligned historical records:
    - each record represents one strategy evaluation at one decision_time
    - regime_state is the market context at that decision_time
    - outcome metrics are forward-looking returns / IC / drawdown within horizon
    """

    def __init__(self) -> None:
        self._records: List[Dict] = []

    def add_record(
        self,
        strategy_id: str,
        regime_state: str,
        horizon: int,
        fold: str,
        ic_mean: Optional[float],
        ic_std: Optional[float],
        win_rate: Optional[float],
        drawdown: Optional[float],
        notes: str = "",
    ) -> None:
        self._records.append(
            {
                "strategy_id": strategy_id,
                "regime_state": regime_state,
                "horizon": horizon,
                "fold": fold,
                "ic_mean": ic_mean,
                "ic_std": ic_std,
                "win_rate": win_rate,
                "drawdown": drawdown,
                "sample_count": 1,
                "notes": notes,
            }
        )

    def analyze(self) -> List[StrategyRegimePerformance]:
        grouped: Dict[str, List[Dict]] = {}
        for record in self._records:
            key = (record["strategy_id"], record["regime_state"], record["horizon"], record["fold"])
            grouped.setdefault(key, []).append(record)

        results: List[StrategyRegimePerformance] = []
        for (strategy_id, regime_state, horizon, fold), records in grouped.items():
            sample_count = len(records)
            ic_means = [r["ic_mean"] for r in records if r["ic_mean"] is not None]
            ic_stds = [r["ic_std"] for r in records if r["ic_std"] is not None]
            win_rates = [r["win_rate"] for r in records if r["win_rate"] is not None]
            drawdowns = [r["drawdown"] for r in records if r["drawdown"] is not None]

            ic_mean = sum(ic_means) / len(ic_means) if ic_means else None
            ic_std = sum(ic_stds) / len(ic_stds) if ic_stds else None
            win_rate = sum(win_rates) / len(win_rates) if win_rates else None
            drawdown = sum(drawdowns) / len(drawdowns) if drawdowns else None

            confidence = self._derive_confidence(sample_count, ic_means, win_rates)

            results.append(
                StrategyRegimePerformance(
                    strategy_id=strategy_id,
                    regime_state=regime_state,
                    horizon=horizon,
                    fold=fold,
                    ic_mean=ic_mean,
                    ic_std=ic_std,
                    win_rate=win_rate,
                    drawdown=drawdown,
                    sample_count=sample_count,
                    confidence=confidence,
                    notes=records[0].get("notes", ""),
                )
            )
        return results

    def _derive_confidence(self, sample_count: int, ic_means: List[float], win_rates: List[float]) -> str:
        if sample_count < 5:
            return "UNKNOWN"
        if sample_count < 20:
            return "LOW"
        if len(ic_means) < 3 or len(win_rates) < 3:
            return "LOW"
        return "MEDIUM"
