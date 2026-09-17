#!/usr/bin/env python3
"""
strategy_qualification.py — Strategy Qualification Framework & Eligibility Gate
==============================================================================
Evaluates whether a strategy variant has sufficient evidence to qualify for
next-stage research or production consideration.

Qualification Engine computes metrics across evidence layers.
Eligibility Gate judges whether those metrics meet minimum standards.

This module does NOT:
- optimize parameters
- modify strategies
- select winners
- promote to production
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


# ---------------------------------------------------------------- Status Enums
class LayerStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_APPLICABLE_YET = "NOT_APPLICABLE_YET"
    DATA_BLOCKED = "DATA_BLOCKED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class EvidenceStrength(Enum):
    ADEQUATE = "ADEQUATE"
    PRELIMINARY = "PRELIMINARY"
    INSUFFICIENT = "INSUFFICIENT"
    DATA_BLOCKED = "DATA_BLOCKED"


class QualificationStatus(Enum):
    BLOCKED = "BLOCKED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    FAILED = "FAILED"
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    QUALIFIED = "QUALIFIED"


# ---------------------------------------------------------------- Evidence Layer Result
@dataclass(frozen=True)
class LayerResult:
    layer_id: str
    layer_name: str
    status: str  # LayerStatus value
    score: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    blocker_reason: Optional[str] = None


# ---------------------------------------------------------------- Fold Metrics
@dataclass(frozen=True)
class FoldMetrics:
    fold_id: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    dataset_version: str
    universe_version: str
    target_version: str
    strategy_version: str
    normalization_version: str
    signal_count: int
    eligible_count: int
    valid_target_count: int
    excluded_count: int
    low_sample: bool
    data_quality_warning: bool
    ic_5d: Optional[float] = None
    rank_ic_5d: Optional[float] = None
    mean_excess_return_5d: Optional[float] = None
    median_excess_return_5d: Optional[float] = None
    hit_rate_5d: Optional[float] = None
    baseline_ic_5d: Optional[float] = None
    baseline_rank_ic_5d: Optional[float] = None
    baseline_mean_excess_return_5d: Optional[float] = None
    ic_10d: Optional[float] = None
    rank_ic_10d: Optional[float] = None
    mean_excess_return_10d: Optional[float] = None
    median_excess_return_10d: Optional[float] = None
    hit_rate_10d: Optional[float] = None
    baseline_ic_10d: Optional[float] = None
    baseline_rank_ic_10d: Optional[float] = None
    baseline_mean_excess_return_10d: Optional[float] = None
    ic_20d: Optional[float] = None
    rank_ic_20d: Optional[float] = None
    mean_excess_return_20d: Optional[float] = None
    median_excess_return_20d: Optional[float] = None
    hit_rate_20d: Optional[float] = None
    baseline_ic_20d: Optional[float] = None
    baseline_rank_ic_20d: Optional[float] = None
    baseline_mean_excess_return_20d: Optional[float] = None
    market_period: str = "unknown"
    turnover_proxy: Optional[float] = None


# ---------------------------------------------------------------- Strategy Qualification Input
@dataclass(frozen=True)
class StrategyQualificationInput:
    strategy_id: str
    strategy_version: str
    strategy_family: str
    horizon: int
    folds: List[FoldMetrics]
    baseline_folds: Optional[List[FoldMetrics]] = None
    requires_eod_policy: bool = False
    required_datasets: List[str] = field(default_factory=list)
    required_pit_policies: Dict[str, str] = field(default_factory=dict)
    variant_count: int = 1
    experiment_id: str = ""
    notes: str = ""


# ---------------------------------------------------------------- Qualification Result
@dataclass(frozen=True)
class QualificationResult:
    strategy_id: str
    strategy_version: str
    strategy_family: str
    horizon: int
    qualification_status: str  # QualificationStatus value
    evidence_strength: str  # EvidenceStrength value
    fold_count: int
    valid_fold_count: int
    low_sample_fold_count: int
    data_quality_warning_count: int
    variant_count: int
    layers: Dict[str, LayerResult] = field(default_factory=dict)
    cross_fold_metrics: Dict[str, Any] = field(default_factory=dict)
    baseline_comparison: Dict[str, Any] = field(default_factory=dict)
    why_not_qualified: Optional[str] = None
    pbo_status: str = "NOT_APPLICABLE_YET"
    dsr_status: str = "NOT_APPLICABLE_YET"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


# ---------------------------------------------------------------- Qualification Engine
class StrategyQualificationEngine:
    """
    Computes evidence layers for a strategy variant.
    Does NOT make final qualification decisions — that is the Eligibility Gate's job.
    """

    def __init__(
        self,
        *,
        min_valid_folds: int = 3,
        min_valid_observations: int = 50,
        low_sample_threshold: int = 20,
        pit_violation_tolerance: float = 0.0,
        max_data_quality_warning_ratio: float = 0.2,
        ic_positive_threshold: float = 0.0,
        rank_ic_positive_threshold: float = 0.0,
        baseline_ic_min_delta: float = 0.01,
        max_worst_fold_ic: float = -0.25,
    ):
        self.min_valid_folds = min_valid_folds
        self.min_valid_observations = min_valid_observations
        self.low_sample_threshold = low_sample_threshold
        self.pit_violation_tolerance = pit_violation_tolerance
        self.max_data_quality_warning_ratio = max_data_quality_warning_ratio
        self.ic_positive_threshold = ic_positive_threshold
        self.rank_ic_positive_threshold = rank_ic_positive_threshold
        self.baseline_ic_min_delta = baseline_ic_min_delta
        self.max_worst_fold_ic = max_worst_fold_ic

    def evaluate(self, inp: StrategyQualificationInput) -> QualificationResult:
        folds = inp.folds or []
        total = len(folds)
        valid = [f for f in folds if not f.low_sample and not f.data_quality_warning]
        low_sample = [f for f in folds if f.low_sample]
        dq_warnings = [f for f in folds if f.data_quality_warning]
        valid_folds = len(valid)
        low_sample_count = len(low_sample)
        dq_warning_count = len(dq_warnings)

        layers = {
            "L1_DATA_INTEGRITY": self._layer_data_integrity(inp, folds, total, dq_warning_count),
            "L2_PIT_LEAKAGE": self._layer_pit_leakage(inp),
            "L3_PREDICTIVE_EVIDENCE": self._layer_predictive_evidence(inp, valid, valid_folds),
            "L4_ECONOMIC_PERFORMANCE": self._layer_economic_performance(inp, valid),
            "L5_RISK": self._layer_risk(inp, valid),
            "L6_STABILITY": self._layer_stability(inp, valid),
            "L7_CAPACITY_IMPLEMENTABILITY": self._layer_capacity(inp, valid),
            "L8_MULTIPLE_TESTING": self._layer_multiple_testing(inp),
            "L9_ROBUSTNESS": self._layer_robustness(inp, valid),
        }

        gate_order = [
            "L1_DATA_INTEGRITY",
            "L2_PIT_LEAKAGE",
            "L3_PREDICTIVE_EVIDENCE",
            "L4_ECONOMIC_PERFORMANCE",
            "L5_RISK",
            "L6_STABILITY",
            "L7_CAPACITY_IMPLEMENTABILITY",
            "L8_MULTIPLE_TESTING",
            "L9_ROBUSTNESS",
        ]

        overall_status = QualificationStatus.QUALIFIED.value
        blockers = []

        for lid in gate_order:
            layer = layers[lid]
            if layer.status == LayerStatus.FAIL.value:
                overall_status = QualificationStatus.BLOCKED.value
                blockers.append(f"{lid}: {layer.blocker_reason or layer.status}")
                break
            if layer.status == LayerStatus.INSUFFICIENT_EVIDENCE.value:
                if overall_status not in (
                    QualificationStatus.BLOCKED.value,
                    QualificationStatus.FAILED.value,
                ):
                    overall_status = QualificationStatus.INSUFFICIENT_EVIDENCE.value
                    blockers.append(f"{lid}: insufficient evidence")
            if layer.status == LayerStatus.DATA_BLOCKED.value:
                overall_status = QualificationStatus.BLOCKED.value
                blockers.append(f"{lid}: data blocked")
                break
            if layer.status == LayerStatus.NOT_APPLICABLE_YET.value:
                if overall_status == QualificationStatus.QUALIFIED.value:
                    overall_status = QualificationStatus.INSUFFICIENT_EVIDENCE.value
                    blockers.append(f"{lid}: not applicable yet")

        if overall_status == QualificationStatus.QUALIFIED.value and valid_folds < self.min_valid_folds:
            overall_status = QualificationStatus.INSUFFICIENT_EVIDENCE.value
            blockers.append(f"valid_fold_count {valid_folds} < {self.min_valid_folds}")

        cross = self._cross_fold_metrics(valid)
        baseline_comp = self._baseline_comparison(inp, valid)
        evidence_strength = self._evidence_strength(valid_folds, cross)

        why = "; ".join(blockers) if blockers else None
        if overall_status == QualificationStatus.QUALIFIED.value and why is None:
            why = "All gates passed"

        return QualificationResult(
            strategy_id=inp.strategy_id,
            strategy_version=inp.strategy_version,
            strategy_family=inp.strategy_family,
            horizon=inp.horizon,
            qualification_status=overall_status,
            evidence_strength=evidence_strength,
            fold_count=total,
            valid_fold_count=valid_folds,
            low_sample_fold_count=low_sample_count,
            data_quality_warning_count=dq_warning_count,
            variant_count=inp.variant_count,
            layers=layers,
            cross_fold_metrics=cross,
            baseline_comparison=baseline_comp,
            why_not_qualified=why,
            pbo_status="NOT_APPLICABLE_YET" if inp.variant_count < 10 else "PENDING",
            dsr_status="NOT_APPLICABLE_YET" if inp.variant_count < 10 else "PENDING",
        )

    # ---------------------------------------------------------------- Layers
    def _layer_data_integrity(
        self, inp: StrategyQualificationInput, folds: List[FoldMetrics], total: int, dq_warning_count: int
    ) -> LayerResult:
        details: Dict[str, Any] = {"total_folds": total}
        if total == 0:
            return LayerResult(
                "L1_DATA_INTEGRITY", "Data Integrity",
                LayerStatus.DATA_BLOCKED.value, score=0.0,
                details=details, blocker_reason="No folds provided"
            )

        missing_provenance = 0
        for f in folds:
            for field_name in (
                "dataset_version", "universe_version", "target_version",
                "strategy_version", "normalization_version",
            ):
                val = getattr(f, field_name, None)
                if not val:
                    missing_provenance += 1
        details["missing_provenance_count"] = missing_provenance
        details["dq_warning_count"] = dq_warning_count
        dq_ratio = dq_warning_count / total
        details["dq_warning_ratio"] = round(dq_ratio, 4)

        if missing_provenance > 0:
            return LayerResult(
                "L1_DATA_INTEGRITY", "Data Integrity",
                LayerStatus.FAIL.value, score=0.0,
                details=details, blocker_reason="Provenance fields missing"
            )
        if dq_ratio > self.max_data_quality_warning_ratio:
            return LayerResult(
                "L1_DATA_INTEGRITY", "Data Integrity",
                LayerStatus.FAIL.value, score=1.0 - dq_ratio,
                details=details, blocker_reason="Data quality warning ratio too high"
            )
        score = 1.0
        if dq_warning_count:
            score -= 0.2 * dq_ratio
        return LayerResult(
            "L1_DATA_INTEGRITY", "Data Integrity",
            LayerStatus.PASS.value, score=score, details=details
        )

    def _layer_pit_leakage(self, inp: StrategyQualificationInput) -> LayerResult:
        details: Dict[str, Any] = {
            "requires_eod_policy": inp.requires_eod_policy,
            "required_datasets": inp.required_datasets,
        }
        if inp.requires_eod_policy:
            details["eod_policy_status"] = "DECLARED"
        else:
            details["eod_policy_status"] = "NOT_REQUIRED"

        blocked = {"financial", "news", "fund_flow", "macro", "event", "regime"}
        implicit = [ds for ds in inp.required_datasets if ds in blocked]
        if implicit:
            return LayerResult(
                "L2_PIT_LEAKAGE", "PIT / Leakage",
                LayerStatus.FAIL.value, score=0.0,
                details=details,
                blocker_reason=f"Blocked datasets declared: {implicit}"
            )

        pit_ok = all(
            policy in ("PIT_SAFE", "CONDITIONAL")
            for policy in inp.required_pit_policies.values()
        )
        if not pit_ok:
            return LayerResult(
                "L2_PIT_LEAKAGE", "PIT / Leakage",
                LayerStatus.FAIL.value, score=0.0,
                details=details, blocker_reason="Non-compliant PIT policy detected"
            )

        return LayerResult(
            "L2_PIT_LEAKAGE", "PIT / Leakage",
            LayerStatus.PASS.value, score=1.0, details=details
        )

    def _layer_predictive_evidence(
        self, inp: StrategyQualificationInput, valid: List[FoldMetrics], valid_folds: int
    ) -> LayerResult:
        details: Dict[str, Any] = {"valid_folds": valid_folds}
        if valid_folds < self.min_valid_folds:
            details["min_valid_folds"] = self.min_valid_folds
            return LayerResult(
                "L3_PREDICTIVE_EVIDENCE", "Predictive Evidence",
                LayerStatus.INSUFFICIENT_EVIDENCE.value, score=0.0,
                details=details,
                blocker_reason=f"valid_folds {valid_folds} < {self.min_valid_folds}"
            )

        suffix = f"_{inp.horizon}d"
        ics = [getattr(f, f"ic{suffix}") for f in valid]
        rank_ics = [getattr(f, f"rank_ic{suffix}") for f in valid]
        ics = [x for x in ics if x is not None]
        rank_ics = [x for x in rank_ics if x is not None]
        if not ics:
            return LayerResult(
                "L3_PREDICTIVE_EVIDENCE", "Predictive Evidence",
                LayerStatus.INSUFFICIENT_EVIDENCE.value, score=0.0,
                details=details, blocker_reason="No valid IC observations"
            )

        ic_mean = sum(ics) / len(ics)
        rank_ic_mean = sum(rank_ics) / len(rank_ics) if rank_ics else 0.0
        ic_pos_ratio = sum(1 for x in ics if x > self.ic_positive_threshold) / len(ics)
        rank_ic_pos_ratio = sum(1 for x in rank_ics if x > self.rank_ic_positive_threshold) / len(rank_ics) if rank_ics else 0.0

        details["ic_mean"] = round(ic_mean, 6)
        details["rank_ic_mean"] = round(rank_ic_mean, 6)
        details["ic_positive_ratio"] = round(ic_pos_ratio, 4)
        details["rank_ic_positive_ratio"] = round(rank_ic_pos_ratio, 4)
        details["ic_count"] = len(ics)

        score = max(0.0, min(1.0, 0.5 * (ic_pos_ratio + rank_ic_pos_ratio)))
        if ic_pos_ratio >= 0.6 and rank_ic_pos_ratio >= 0.6:
            status = LayerStatus.PASS.value
        elif ic_pos_ratio >= 0.4 or rank_ic_pos_ratio >= 0.4:
            status = LayerStatus.PASS.value
            details["note"] = "borderline predictive evidence"
        else:
            status = LayerStatus.INSUFFICIENT_EVIDENCE.value
            details["note"] = "insufficient predictive evidence"

        return LayerResult(
            "L3_PREDICTIVE_EVIDENCE", "Predictive Evidence",
            status, score=round(score, 4), details=details
        )

    def _layer_economic_performance(self, inp: StrategyQualificationInput, valid: List[FoldMetrics]) -> LayerResult:
        details: Dict[str, Any] = {}
        suffix = f"_{inp.horizon}d"
        means = [getattr(f, f"mean_excess_return{suffix}") for f in valid]
        means = [x for x in means if x is not None]
        if not means:
            return LayerResult(
                "L4_ECONOMIC_PERFORMANCE", "Economic Performance",
                LayerStatus.INSUFFICIENT_EVIDENCE.value, score=0.0,
                details=details, blocker_reason="No economic observations"
            )
        mean_return = sum(means) / len(means)
        details["mean_excess_return"] = round(mean_return, 6)
        details["observation_count"] = len(means)
        score = max(0.0, min(1.0, 0.5 + mean_return * 100))
        return LayerResult(
            "L4_ECONOMIC_PERFORMANCE", "Economic Performance",
            LayerStatus.PASS.value, score=round(score, 4), details=details
        )

    def _layer_risk(self, inp: StrategyQualificationInput, valid: List[FoldMetrics]) -> LayerResult:
        details: Dict[str, Any] = {}
        suffix = f"_{inp.horizon}d"
        ics = [getattr(f, f"ic{suffix}") for f in valid]
        ics = [x for x in ics if x is not None]
        if not ics:
            return LayerResult(
                "L5_RISK", "Risk",
                LayerStatus.INSUFFICIENT_EVIDENCE.value, score=0.0,
                details=details, blocker_reason="No risk observations"
            )
        worst = min(ics)
        details["worst_fold_ic"] = round(worst, 6)
        details["ic_count"] = len(ics)
        if worst < self.max_worst_fold_ic:
            return LayerResult(
                "L5_RISK", "Risk",
                LayerStatus.INSUFFICIENT_EVIDENCE.value, score=0.0,
                details=details, blocker_reason=f"Worst fold IC {worst:.4f} below threshold {self.max_worst_fold_ic}"
            )
        score = max(0.0, min(1.0, 0.5 + (worst - self.max_worst_fold_ic) / 0.1))
        return LayerResult(
            "L5_RISK", "Risk",
            LayerStatus.PASS.value, score=round(score, 4), details=details
        )

    def _layer_stability(self, inp: StrategyQualificationInput, valid: List[FoldMetrics]) -> LayerResult:
        details: Dict[str, Any] = {}
        suffix = f"_{inp.horizon}d"
        ics = [getattr(f, f"ic{suffix}") for f in valid]
        ics = [x for x in ics if x is not None]
        if not ics:
            return LayerResult(
                "L6_STABILITY", "Stability",
                LayerStatus.INSUFFICIENT_EVIDENCE.value, score=0.0,
                details=details, blocker_reason="No stability observations"
            )
        mean_ic = sum(ics) / len(ics)
        variance = sum((x - mean_ic) ** 2 for x in ics) / len(ics)
        std_ic = variance ** 0.5
        cv = abs(std_ic / (mean_ic + 1e-12))
        pos_ratio = sum(1 for x in ics if x > 0) / len(ics)
        details["ic_mean"] = round(mean_ic, 6)
        details["ic_std"] = round(std_ic, 6)
        details["ic_cv"] = round(cv, 4)
        details["ic_positive_ratio"] = round(pos_ratio, 4)
        details["fold_count"] = len(ics)

        score = max(0.0, min(1.0, pos_ratio))
        if pos_ratio < 0.4:
            status = LayerStatus.INSUFFICIENT_EVIDENCE.value
            details["note"] = "insufficient cross-fold consistency"
        else:
            status = LayerStatus.PASS.value
        return LayerResult(
            "L6_STABILITY", "Stability",
            status, score=round(score, 4), details=details
        )

    def _layer_capacity(self, inp: StrategyQualificationInput, valid: List[FoldMetrics]) -> LayerResult:
        details: Dict[str, Any] = {"capacity_model_status": "NOT_IMPLEMENTED"}
        return LayerResult(
            "L7_CAPACITY_IMPLEMENTABILITY", "Capacity / Implementability",
            LayerStatus.NOT_APPLICABLE_YET.value, score=0.0, details=details
        )

    def _layer_multiple_testing(self, inp: StrategyQualificationInput) -> LayerResult:
        details: Dict[str, Any] = {
            "variant_count": inp.variant_count,
            "experiment_id": inp.experiment_id,
        }
        if inp.variant_count < 10:
            details["pbo_status"] = "NOT_APPLICABLE_YET"
            details["dsr_status"] = "NOT_APPLICABLE_YET"
            details["note"] = (
                f"{inp.variant_count} variants is insufficient for PBO/DSR; "
                "minimum recommended: 10+ variants or parameter combinations"
            )
            return LayerResult(
                "L8_MULTIPLE_TESTING", "Multiple Testing",
                LayerStatus.NOT_APPLICABLE_YET.value, score=0.0, details=details
            )
        details["pbo_status"] = "PENDING"
        details["dsr_status"] = "PENDING"
        return LayerResult(
            "L8_MULTIPLE_TESTING", "Multiple Testing",
            LayerStatus.PASS.value, score=1.0, details=details
        )

    def _layer_robustness(self, inp: StrategyQualificationInput, valid: List[FoldMetrics]) -> LayerResult:
        details: Dict[str, Any] = {"status": "FRAMEWORK_READY"}
        details["available_methods"] = [
            "bootstrap",
            "block_bootstrap",
            "signal_perturbation",
            "missing_data_stress",
            "transaction_cost_stress",
        ]
        return LayerResult(
            "L9_ROBUSTNESS", "Robustness",
            LayerStatus.NOT_APPLICABLE_YET.value, score=0.0, details=details
        )

    # ---------------------------------------------------------------- Cross-Fold Metrics
    def _cross_fold_metrics(self, valid: List[FoldMetrics]) -> Dict[str, Any]:
        if not valid:
            return {"ic": {}, "rank_ic": {}, "mean_excess_return": {}}

        def summarize(vals: List[Optional[float]]) -> Dict[str, Optional[float]]:
            clean = [x for x in vals if x is not None]
            if not clean:
                return {"mean": None, "median": None, "std": None, "positive_ratio": None}
            mean = sum(clean) / len(clean)
            median = sorted(clean)[len(clean) // 2]
            variance = sum((x - mean) ** 2 for x in clean) / len(clean)
            std = variance ** 0.5
            pos_ratio = sum(1 for x in clean if x > 0) / len(clean)
            return {
                "mean": round(mean, 8),
                "median": round(median, 8),
                "std": round(std, 8),
                "positive_ratio": round(pos_ratio, 4),
            }

        result: Dict[str, Any] = {}
        for horizon in (5, 10, 20):
            suffix = f"_{horizon}d"
            result[f"horizon_{horizon}"] = {
                "ic": summarize([getattr(f, f"ic{suffix}") for f in valid]),
                "rank_ic": summarize([getattr(f, f"rank_ic{suffix}") for f in valid]),
                "mean_excess_return": summarize([getattr(f, f"mean_excess_return{suffix}") for f in valid]),
            }
        return result

    def _baseline_comparison(self, inp: StrategyQualificationInput, valid: List[FoldMetrics]) -> Dict[str, Any]:
        if not inp.baseline_folds:
            return {"status": "NO_BASELINE"}
        suffix = f"_{inp.horizon}d"
        deltas = []
        for f, b in zip(valid, inp.baseline_folds):
            s_ic = getattr(f, f"ic{suffix}")
            b_ic = getattr(b, f"ic{suffix}")
            if s_ic is not None and b_ic is not None:
                deltas.append(s_ic - b_ic)
        if not deltas:
            return {"status": "NO_COMPARABLE_PAIRS"}
        avg_delta = sum(deltas) / len(deltas)
        return {
            "status": "COMPUTED",
            "ic_delta_mean": round(avg_delta, 6),
            "comparison_count": len(deltas),
            "outperforms_baseline_ratio": round(
                sum(1 for d in deltas if d > self.baseline_ic_min_delta) / len(deltas), 4
            ),
        }

    def _evidence_strength(self, valid_folds: int, cross: Dict[str, Any]) -> str:
        total_obs = 0
        for h_key, h_data in cross.items():
            ic = h_data.get("ic", {})
            total_obs += len([v for v in ic.values() if v is not None]) if ic else 0

        if valid_folds < 3 or total_obs < 50:
            return EvidenceStrength.INSUFFICIENT.value
        if total_obs < 100:
            return EvidenceStrength.PRELIMINARY.value
        return EvidenceStrength.ADEQUATE.value
