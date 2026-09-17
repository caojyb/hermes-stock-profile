#!/usr/bin/env python3
"""
multiple_testing_registry.py — Multiple Testing Registry
========================================================
Records every research experiment to enable honest multiple-testing
adjustment later (PBO, DSR, etc.).

Even failed experiments must be recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


# ---------------------------------------------------------------- Registry Entry
@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    strategy_id: str
    strategy_version: str
    strategy_family: str
    parameter_space: Dict[str, Any]
    features: List[str]
    target: str
    target_version: str
    research_window: Dict[str, str]
    result_selection: str
    status: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    notes: str = ""


# ---------------------------------------------------------------- Registry
class MultipleTestingRegistry:
    """
    Append-only registry for research experiments.
    """

    def __init__(self, store: Optional[Any] = None):
        self._records: List[ExperimentRecord] = []
        self._store = store

    def register(self, record: ExperimentRecord) -> None:
        self._records.append(record)
        if self._store is not None:
            self._store.save(record)

    def count_by_strategy(self, strategy_id: str) -> int:
        return sum(1 for r in self._records if r.strategy_id == strategy_id)

    def count_total(self) -> int:
        return len(self._records)

    def get_records(self) -> List[ExperimentRecord]:
        return list(self._records)

    def summary(self) -> Dict[str, Any]:
        by_strategy: Dict[str, int] = {}
        by_family: Dict[str, int] = {}
        for r in self._records:
            by_strategy[r.strategy_id] = by_strategy.get(r.strategy_id, 0) + 1
            by_family[r.strategy_family] = by_family.get(r.strategy_family, 0) + 1
        return {
            "total_experiments": len(self._records),
            "total_strategy_variants": len(by_strategy),
            "total_parameter_variants": sum(1 for r in self._records if r.parameter_space),
            "total_feature_variants": sum(1 for r in self._records if r.features),
            "total_target_variants": len({r.target for r in self._records}),
            "by_strategy": by_strategy,
            "by_family": by_family,
            "pbo_eligible": len(self._records) >= 10,
            "dsr_eligible": len(self._records) >= 10,
        }
