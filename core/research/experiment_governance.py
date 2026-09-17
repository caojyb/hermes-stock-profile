#!/usr/bin/env python3
"""
experiment_governance.py — Strategy Research Experiment Governance
====================================================================
Formal experiment tracking for strategy research.

Provides:
- Hypothesis-first experiment registration
- Parameter/feature/target/universe/window binding
- Experiment family grouping
- Parent-child lineage
- Decision log
- PBO/DSR applicability assessment
- Negative result retention
- Deterministic append-only registry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


# ---------------------------------------------------------------- Status & Enums
EXPERIMENT_STATUS_REGISTERED = "REGISTERED"
EXPERIMENT_STATUS_RUNNING = "RUNNING"
EXPERIMENT_STATUS_COMPLETED = "COMPLETED"
EXPERIMENT_STATUS_FAILED = "FAILED"
EXPERIMENT_STATUS_BLOCKED = "BLOCKED"
EXPERIMENT_STATUS_NO_EVIDENCE = "NO_EVIDENCE"
EXPERIMENT_STATUS_SELECTED_FOR_FURTHER_RESEARCH = "SELECTED_FOR_FURTHER_RESEARCH"
EXPERIMENT_STATUS_RETIRED = "RETIRED"

SELECTION_EVENT_BEST_VARIANT = "best_variant_selected"
SELECTION_EVENT_MEDIAN_VARIANT = "median_variant_selected"
SELECTION_EVENT_FAMILY_SELECTED = "family_selected"
SELECTION_EVENT_NONE = "none"


# ---------------------------------------------------------------- Core Records
@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    parent_experiment_id: Optional[str]
    hypothesis: str
    strategy_family: str
    strategy_id: str
    strategy_version: str
    variant_id: str
    parameters: Dict[str, Any]
    parameter_space: Dict[str, Any]
    required_datasets: List[str]
    required_features: List[str]
    required_pit_policies: Dict[str, str]
    target_id: str
    target_version: str
    universe_version: str
    research_window: Dict[str, str]
    fold_policy: str
    evaluation_metrics: List[str]
    selection_rule: str
    selection_event: str
    researcher: str
    status: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    notes: str = ""


@dataclass(frozen=True)
class ExperimentFamily:
    experiment_family_id: str
    family_name: str
    hypothesis: str
    strategy_family: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    notes: str = ""


@dataclass(frozen=True)
class DecisionLogEntry:
    decision_id: str
    experiment_id: str
    decision: str
    reason: str
    evidence: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    actor: str = "system"


# ---------------------------------------------------------------- Registry
class ExperimentRegistry:
    """
    Append-only research experiment governance registry.
    """

    def __init__(self):
        self._experiments: Dict[str, ExperimentRecord] = {}
        self._families: Dict[str, ExperimentFamily] = {}
        self._lineage: Dict[str, List[str]] = {}
        self._decisions: List[DecisionLogEntry] = []

    def register_experiment(self, record: ExperimentRecord) -> None:
        if record.experiment_id in self._experiments:
            raise ValueError(f"Experiment {record.experiment_id} already registered")
        self._experiments[record.experiment_id] = record
        if record.parent_experiment_id:
            self._lineage.setdefault(record.parent_experiment_id, []).append(record.experiment_id)

    def register_family(self, family: ExperimentFamily) -> None:
        self._families[family.experiment_family_id] = family

    def log_decision(self, entry: DecisionLogEntry) -> None:
        self._decisions.append(entry)

    def get_experiment(self, experiment_id: str) -> Optional[ExperimentRecord]:
        return self._experiments.get(experiment_id)

    def get_children(self, parent_id: str) -> List[str]:
        return list(self._lineage.get(parent_id, []))

    def get_lineage(self, experiment_id: str) -> List[str]:
        lineage = []
        current = experiment_id
        while current:
            lineage.append(current)
            exp = self._experiments.get(current)
            current = exp.parent_experiment_id if exp else None
        return lineage

    def count_by_family(self, strategy_family: str) -> int:
        return sum(1 for e in self._experiments.values() if e.strategy_family == strategy_family)

    def count_total(self) -> int:
        return len(self._experiments)

    def count_by_status(self, status: str) -> int:
        return sum(1 for e in self._experiments.values() if e.status == status)

    def get_negative_results(self) -> List[ExperimentRecord]:
        return [
            e for e in self._experiments.values()
            if e.status in (EXPERIMENT_STATUS_FAILED, EXPERIMENT_STATUS_NO_EVIDENCE, EXPERIMENT_STATUS_BLOCKED)
        ]

    def summary(self) -> Dict[str, Any]:
        by_family = {}
        for e in self._experiments.values():
            by_family[e.strategy_family] = by_family.get(e.strategy_family, 0) + 1
        by_status = {}
        for e in self._experiments.values():
            by_status[e.status] = by_status.get(e.status, 0) + 1
        return {
            "total_experiments": len(self._experiments),
            "total_families": len(self._families),
            "total_decisions": len(self._decisions),
            "by_family": by_family,
            "by_status": by_status,
            "negative_result_count": len(self.get_negative_results()),
        }


# ---------------------------------------------------------------- PBO / DSR Applicability
class MultipleTestingApplicability:
    """
    Dynamic PBO/DSR applicability assessment.
    Does NOT use hardcoded trial count thresholds alone.
    """

    @staticmethod
    def assess_pbo(registry: ExperimentRegistry) -> Dict[str, Any]:
        total = registry.count_total()
        by_family = registry.summary()["by_family"]
        independent_trials = sum(1 for e in registry._experiments.values() if e.selection_event == SELECTION_EVENT_NONE)
        families = len(by_family)

        reasons = []
        applicable = False

        if total < 5:
            reasons.append(f"total_experiments={total} < 5")
        if families < 2:
            reasons.append(f"strategy_families={families} < 2")
        if independent_trials < 5:
            reasons.append(f"independent_trials={independent_trials} < 5")

        if not reasons:
            applicable = True
            reasons.append("sufficient experiments and families for PBO")

        return {
            "pbo_applicable": applicable,
            "pbo_reason": "; ".join(reasons),
            "total_experiments": total,
            "independent_trials": independent_trials,
            "strategy_families": families,
        }

    @staticmethod
    def assess_dsr(registry: ExperimentRegistry) -> Dict[str, Any]:
        total = registry.count_total()
        by_family = registry.summary()["by_family"]
        families = len(by_family)

        reasons = []
        applicable = False

        if total < 5:
            reasons.append(f"total_experiments={total} < 5")
        if families < 2:
            reasons.append(f"strategy_families={families} < 2")

        if not reasons:
            applicable = True
            reasons.append("sufficient experiments and families for DSR")

        return {
            "dsr_applicable": applicable,
            "dsr_reason": "; ".join(reasons),
            "total_experiments": total,
            "strategy_families": families,
        }
