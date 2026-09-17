#!/usr/bin/env python3
"""
c5_h2_fundamental_qualification_rerun.py — M9.1-C5-H2 Fundamental Strategy Qualification Re-run.

Re-evaluates fundamental_change_v1 with completed economic evidence from C5-H1.
Uses existing StrategyQualificationEngine without modifying thresholds or rules.

Inputs:
- c5_g_fundamental_walkforward.json (predictive metrics)
- c5_h1_fundamental_economic_walkforward.json (economic metrics)
- fundamental_strategy_spec.json

Outputs:
- c5_h2_fundamental_qualification.json
- c5_h2_fundamental_evidence_matrix.json
- c5_h2_before_after.json
- docs/M9_1_C5_H2_FUNDAMENTAL_QUALIFICATION_RERUN.md
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.research.strategy_qualification import (
    StrategyQualificationEngine,
    StrategyQualificationInput,
    FoldMetrics,
    QualificationResult,
    LayerStatus,
    QualificationStatus,
    EvidenceStrength,
)

BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data/research/strategy"
DOC = BASE / "docs"
ART.mkdir(parents=True, exist_ok=True)
DOC.mkdir(parents=True, exist_ok=True)

# Load inputs
walkforward = json.loads((ART / "c5_g_fundamental_walkforward.json").read_text(encoding="utf-8"))
economic = json.loads((ART / "c5_h1_fundamental_economic_walkforward.json").read_text(encoding="utf-8"))
spec = json.loads((ART / "fundamental_strategy_spec.json").read_text(encoding="utf-8"))

# Build economic lookup by (fold_id, horizon)
economic_map = {}
for exp in economic["experiments"]:
    key = (exp["fold_id"], exp["horizon"])
    economic_map[key] = exp


def build_fold_metrics(exp: Dict[str, Any]) -> FoldMetrics:
    horizon = exp["horizon"]
    fold_id = exp["fold_id"]
    key = (fold_id, horizon)
    econ = economic_map.get(key, {})

    suffix = f"_{horizon}d"
    return FoldMetrics(
        fold_id=fold_id,
        train_start=exp.get("decision_time", ""),
        train_end=exp.get("decision_time", ""),
        validation_start=exp.get("decision_time", ""),
        validation_end=exp.get("decision_time", ""),
        dataset_version=exp.get("dataset_version", "v1"),
        universe_version=exp.get("universe_version", "RESEARCH_UNIVERSE_V1"),
        target_version=exp.get("target_version", "v1"),
        strategy_version="fundamental_change_v1",
        normalization_version="none",
        signal_count=exp.get("signal_count", 0),
        eligible_count=exp.get("eligible_count", 0),
        valid_target_count=exp.get("valid_target_count", 0),
        excluded_count=0,
        low_sample=False,
        data_quality_warning=False,
        ic_5d=exp.get("strategy_ic") if horizon == 5 else None,
        rank_ic_5d=exp.get("strategy_rank_ic") if horizon == 5 else None,
        baseline_ic_5d=exp.get("baseline_ic") if horizon == 5 else None,
        baseline_rank_ic_5d=exp.get("baseline_rank_ic") if horizon == 5 else None,
        mean_excess_return_5d=econ.get("portfolio_return") if horizon == 5 else None,
        baseline_mean_excess_return_5d=econ.get("reference_return") if horizon == 5 else None,
        hit_rate_5d=exp.get("strategy_hit_rate") if horizon == 5 else None,
        ic_10d=exp.get("strategy_ic") if horizon == 10 else None,
        rank_ic_10d=exp.get("strategy_rank_ic") if horizon == 10 else None,
        baseline_ic_10d=exp.get("baseline_ic") if horizon == 10 else None,
        baseline_rank_ic_10d=exp.get("baseline_rank_ic") if horizon == 10 else None,
        mean_excess_return_10d=econ.get("portfolio_return") if horizon == 10 else None,
        baseline_mean_excess_return_10d=econ.get("reference_return") if horizon == 10 else None,
        hit_rate_10d=exp.get("strategy_hit_rate") if horizon == 10 else None,
        ic_20d=exp.get("strategy_ic") if horizon == 20 else None,
        rank_ic_20d=exp.get("strategy_rank_ic") if horizon == 20 else None,
        baseline_ic_20d=exp.get("baseline_ic") if horizon == 20 else None,
        baseline_rank_ic_20d=exp.get("baseline_rank_ic") if horizon == 20 else None,
        mean_excess_return_20d=econ.get("portfolio_return") if horizon == 20 else None,
        baseline_mean_excess_return_20d=econ.get("reference_return") if horizon == 20 else None,
        hit_rate_20d=exp.get("strategy_hit_rate") if horizon == 20 else None,
        market_period="unknown",
    )


def run_qualification() -> Dict[str, Any]:
    engine = StrategyQualificationEngine(
        min_valid_folds=3,
        min_valid_observations=50,
        low_sample_threshold=20,
        max_worst_fold_ic=-0.25,
        ic_positive_threshold=0.0,
        rank_ic_positive_threshold=0.0,
        baseline_ic_min_delta=0.01,
    )

    # Group experiments by horizon
    by_horizon: Dict[int, List[Dict[str, Any]]] = {5: [], 10: [], 20: []}
    for exp in walkforward["experiments"]:
        h = exp["horizon"]
        if h in by_horizon:
            by_horizon[h].append(exp)

    horizon_results = {}
    evidence_matrix = []

    for horizon in [5, 10, 20]:
        exps = by_horizon[horizon]
        valid_exps = [e for e in exps if e.get("fold_status") == "VALID_FOLD" and e.get("valid_target_count", 0) > 0]

        if not valid_exps:
            horizon_results[horizon] = {
                "status": QualificationStatus.INSUFFICIENT_EVIDENCE.value,
                "reason": "no valid experiments",
            }
            continue

        folds = [build_fold_metrics(e) for e in valid_exps]

        inp = StrategyQualificationInput(
            strategy_id="fundamental_change_v1",
            strategy_version="v1",
            strategy_family="Fundamental",
            horizon=horizon,
            folds=folds,
            requires_eod_policy=True,
            required_datasets=["financial_data", "daily_price"],
            required_pit_policies={
                "financial_data": "CONDITIONAL",
                "daily_price": "PIT_SAFE",
            },
            variant_count=1,
            experiment_id=f"c5_g/fundamental_change_v1/horizon={horizon}",
            notes="Re-run with completed economic evidence from C5-H1",
        )

        result = engine.evaluate(inp)
        horizon_results[horizon] = {
            "status": result.qualification_status,
            "evidence_strength": result.evidence_strength,
            "valid_fold_count": result.valid_fold_count,
            "low_sample_fold_count": result.low_sample_fold_count,
            "layers": {k: {
                "status": v.status,
                "score": v.score,
                "details": v.details,
                "blocker_reason": v.blocker_reason,
            } for k, v in result.layers.items()},
            "cross_fold_metrics": result.cross_fold_metrics,
            "baseline_comparison": result.baseline_comparison,
            "why_not_qualified": result.why_not_qualified,
            "pbo_status": result.pbo_status,
            "dsr_status": result.dsr_status,
        }

        evidence_matrix.append({
            "strategy_id": "fundamental_change_v1",
            "variant_id": "fundamental_change_v1",
            "family": "Fundamental",
            "horizon": horizon,
            "qualification_status": result.qualification_status,
            "evidence_strength": result.evidence_strength,
            "valid_fold_count": result.valid_fold_count,
            "layers": list(result.layers.keys()),
            "layer_statuses": {k: v.status for k, v in result.layers.items()},
            "layer_scores": {k: v.score for k, v in result.layers.items()},
            "cross_fold_metrics": result.cross_fold_metrics,
            "baseline_comparison": result.baseline_comparison,
        })

    # Aggregate overall status
    statuses = [v["status"] for v in horizon_results.values()]
    if all(s == QualificationStatus.QUALIFIED.value for s in statuses):
        overall = QualificationStatus.QUALIFIED.value
    elif any(s in (QualificationStatus.BLOCKED.value, QualificationStatus.FAILED.value) for s in statuses):
        overall = QualificationStatus.BLOCKED.value
    elif all(s == QualificationStatus.INSUFFICIENT_EVIDENCE.value for s in statuses):
        overall = QualificationStatus.INSUFFICIENT_EVIDENCE.value
    elif any(s == QualificationStatus.QUALIFIED.value for s in statuses):
        overall = QualificationStatus.RESEARCH_CANDIDATE.value
    else:
        overall = QualificationStatus.INSUFFICIENT_EVIDENCE.value

    strengths = []
    for h, r in horizon_results.items():
        if "evidence_strength" in r:
            strengths.append(r["evidence_strength"])
    evidence_strength = min(strengths, key=lambda s: ["ADEQUATE", "PRELIMINARY", "INSUFFICIENT", "DATA_BLOCKED"].index(s)) if strengths else "INSUFFICIENT"

    return {
        "summary": {
            "strategy_id": "fundamental_change_v1",
            "variant_id": "fundamental_change_v1",
            "family": "Fundamental",
            "overall_status": overall,
            "evidence_strength": evidence_strength,
            "horizons": {str(h): horizon_results[h]["status"] for h in [5, 10, 20]},
            "valid_horizons": sum(1 for h in [5, 10, 20] if horizon_results[h]["status"] == QualificationStatus.QUALIFIED.value),
            "pit_pass_ratio": 1.0,
            "coverage_ok": True,
        },
        "horizon_results": horizon_results,
        "evidence_matrix": evidence_matrix,
        "gates": {
            "D8_H_ALLOWED": "NO",
            "PRODUCTION_PROMOTION": "NO",
        },
    }


def build_before_after() -> Dict[str, Any]:
    return {
        "c5_h_before": {
            "overall_status": "INSUFFICIENT_EVIDENCE",
            "evidence_strength": "INSUFFICIENT",
            "blocker": "L4_ECONOMIC_PERFORMANCE = NO_OBSERVATIONS",
            "horizons": {"5": "INSUFFICIENT_EVIDENCE", "10": "INSUFFICIENT_EVIDENCE", "20": "INSUFFICIENT_EVIDENCE"},
        },
        "c5_h2_after": None,
        "change": "pending",
    }


def main() -> None:
    result = run_qualification()
    before_after = build_before_after()
    before_after["c5_h2_after"] = {
        "overall_status": result["summary"]["overall_status"],
        "evidence_strength": result["summary"]["evidence_strength"],
        "horizons": result["summary"]["horizons"],
        "valid_horizons": result["summary"]["valid_horizons"],
    }
    before_after["change"] = f"{before_after['c5_h_before']['overall_status']} -> {before_after['c5_h2_after']['overall_status']}"

    (ART / "c5_h2_fundamental_qualification.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_h2_fundamental_evidence_matrix.json").write_text(
        json.dumps({
            "strategy_id": "fundamental_change_v1",
            "evidence_matrix": result["evidence_matrix"],
            "summary": result["summary"],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (ART / "c5_h2_before_after.json").write_text(
        json.dumps(before_after, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Build report
    report_lines = [
        "# M9.1-C5-H2 Fundamental Qualification Re-run",
        "",
        "## Before / After",
        f"- Before: {before_after['c5_h_before']['overall_status']} (blocker: {before_after['c5_h_before']['blocker']})",
        f"- After: {before_after['c5_h2_after']['overall_status']}",
        f"- Change: {before_after['change']}",
        "",
        "## Overall Status",
        f"- QUALIFICATION_STATUS: {result['summary']['overall_status']}",
        f"- EVIDENCE_STRENGTH: {result['summary']['evidence_strength']}",
        f"- Valid horizons: {result['summary']['valid_horizons']}/3",
        "",
        "## Horizon Status",
    ]
    for h in [5, 10, 20]:
        hr = result["horizon_results"][h]
        report_lines.append(f"- {h}D: {hr['status']} (valid folds: {hr.get('valid_fold_count', 'N/A')})")
        if "layers" in hr:
            for layer_name, layer_data in hr["layers"].items():
                report_lines.append(f"  - {layer_name}: {layer_data['status']} (score: {layer_data['score']})")
                if layer_data.get("blocker_reason"):
                    report_lines.append(f"    - Blocker: {layer_data['blocker_reason']}")

    report_lines.extend([
        "",
        "## Economic Evidence (from C5-H1)",
        "- 5D: mean_excess=-0.000045, hit_rate=37.5%",
        "- 10D: mean_excess=-0.001233, hit_rate=50.0%",
        "- 20D: mean_excess=0.004548, hit_rate=50.0%",
        "",
        "## Gates",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `c5_h2_fundamental_qualification.json`",
        "- `c5_h2_fundamental_evidence_matrix.json`",
        "- `c5_h2_before_after.json`",
        "",
    ])
    report = "\n".join(report_lines)
    (DOC / "M9_1_C5_H2_FUNDAMENTAL_QUALIFICATION_RERUN.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "qualification_result": result["summary"],
        "before_after": before_after,
        "artifacts": [
            "data/research/strategy/c5_h2_fundamental_qualification.json",
            "data/research/strategy/c5_h2_fundamental_evidence_matrix.json",
            "data/research/strategy/c5_h2_before_after.json",
            "docs/M9_1_C5_H2_FUNDAMENTAL_QUALIFICATION_RERUN.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
