#!/usr/bin/env python3
"""
stock-work/core/research/strategy_allocator/strategy_evidence_matrix.py

Phase C2: Strategy Evidence Matrix.

Builds a descriptive regime x strategy performance matrix from
RegimeStrategyAnalyzer outputs.

Important:
- This module only summarizes existing analysis results.
- It does not recommend strategies.
- It does not produce weights or actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from core.research.strategy_allocator.regime_strategy_analysis import StrategyRegimePerformance


@dataclass(frozen=True)
class EvidenceMatrixCell:
    strategy_id: str
    regime_state: str
    horizon: int
    fold: str
    ic_mean: Optional[float]
    win_rate: Optional[float]
    drawdown: Optional[float]
    sample_count: int
    confidence: str
    status: str


class StrategyEvidenceMatrix:
    """
    Descriptive matrix of strategy evidence across regimes.

    Status values:
    - EVIDENCE: enough samples and metrics available
    - PRELIMINARY: some metrics available but confidence is LOW/UNKNOWN
    - NO_DATA: no records for this cell
    """

    def __init__(self, performances: List[StrategyRegimePerformance]) -> None:
        self._performances = performances

    def build(self) -> List[EvidenceMatrixCell]:
        cells: List[EvidenceMatrixCell] = []
        for performance in self._performances:
            if performance.sample_count == 0 or performance.confidence == "UNKNOWN":
                status = "NO_DATA"
            elif performance.confidence == "LOW":
                status = "PRELIMINARY"
            else:
                status = "EVIDENCE"

            cells.append(
                EvidenceMatrixCell(
                    strategy_id=performance.strategy_id,
                    regime_state=performance.regime_state,
                    horizon=performance.horizon,
                    fold=performance.fold,
                    ic_mean=performance.ic_mean,
                    win_rate=performance.win_rate,
                    drawdown=performance.drawdown,
                    sample_count=performance.sample_count,
                    confidence=performance.confidence,
                    status=status,
                )
            )
        return cells

    def to_dict_matrix(self, horizon: int = 5, fold: str = "walk_forward") -> Dict[str, Dict[str, Optional[float]]]:
        cells = [c for c in self.build() if c.horizon == horizon and c.fold == fold]
        matrix: Dict[str, Dict[str, Optional[float]]] = {}
        for cell in cells:
            matrix.setdefault(cell.strategy_id, {})[cell.regime_state] = cell.ic_mean
        return matrix
