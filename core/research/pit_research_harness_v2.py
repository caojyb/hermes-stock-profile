#!/usr/bin/env python3
"""
stock-work/core/research/pit_research_harness_v2.py

PIT Research Harness V2 — deterministic research run with full provenance.

Inputs:
  - decision_time
  - strategy_id / strategy_version
  - dataset_id / dataset_version

Outputs:
  - universe_version
  - dataset_version
  - eligible universe
  - applied cutoff
  - data sources
  - rejected datasets
  - PIT status
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'stock-work'))
from core.research.research_time_context import ResearchTimeContext, PITViolationError, PITStatus
from core.research.universe_pit import UniversePITEngine, UniverseSnapshotStore
from core.research.data_asof_metadata import DEFAULT_DATASETS


@dataclass
class PITResearchHarnessResult:
    run_id: str
    decision_time: str
    data_cutoff: str
    universe_snapshot_id: Optional[str]
    dataset_version: str
    universe_version: str
    pit_policy: str
    eligible_count: int
    excluded_count: int
    rejected_datasets: List[Dict]
    universe_gaps: List[Dict]
    allowed_datasets: List[str]
    blocked_datasets: List[str]


class PITResearchHarnessV2:
    """Deterministic research run with PIT enforcement."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._dataset_registry = {d.dataset_id: d for d in DEFAULT_DATASETS}

    def run(self, decision_time: str, dataset_version: str = "v1.0",
            universe_version: str = "v1.0", pit_policy: str = "PIT_SAFE_ONLY",
            exclude_kcb: bool = True, exclude_bse: bool = True) -> PITResearchHarnessResult:
        import uuid
        run_id = uuid.uuid4().hex[:12]
        data_cutoff = decision_time

        context = ResearchTimeContext(
            decision_time=decision_time,
            data_cutoff=data_cutoff,
            universe_snapshot_id=None,
            dataset_version=dataset_version,
            run_id=run_id,
        )

        universe_engine = UniversePITEngine(self.db_path)
        universe_rows = universe_engine.get_universe_at(decision_time, exclude_kcb, exclude_bse)
        snapshot_store = UniverseSnapshotStore(self.db_path)
        snapshot_id = snapshot_store.save_snapshot(decision_time, universe_rows, version=universe_version)

        context.universe_snapshot_id = snapshot_id

        rejected_datasets = []
        allowed_datasets = []
        blocked_datasets = []
        for dataset_id, meta in self._dataset_registry.items():
            if meta.pit_status in (PITStatus.PIT_UNSAFE, PITStatus.PIT_UNKNOWN):
                rejected_datasets.append({
                    "dataset_id": dataset_id,
                    "pit_status": meta.pit_status,
                    "reason": meta.notes,
                })
                blocked_datasets.append(dataset_id)
            else:
                allowed_datasets.append(dataset_id)

        return PITResearchHarnessResult(
            run_id=run_id,
            decision_time=decision_time,
            data_cutoff=data_cutoff,
            universe_snapshot_id=snapshot_id,
            dataset_version=dataset_version,
            universe_version=universe_version,
            pit_policy=pit_policy,
            eligible_count=len(universe_rows),
            excluded_count=0,
            rejected_datasets=rejected_datasets,
            universe_gaps=universe_engine.get_gaps(),
            allowed_datasets=allowed_datasets,
            blocked_datasets=blocked_datasets,
        )
