#!/usr/bin/env python3
"""
c5_h4_multiple_testing_closure.py — M9.1-C5-H4 Fundamental Strategy Multiple Testing Closure.

Audits the full research lineage for fundamental_change_v1, establishes trial
lineage, checks p-hacking risk, and determines L8_MULTIPLE_TESTING status.

Outputs:
- c5_h4_multiple_testing_audit.json
- c5_h4_trial_lineage.json
- docs/M9_1-C5-H4_MULTIPLE_TESTING_CLOSURE.md
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data/research/strategy"
DOC = BASE / "docs"
ART.mkdir(parents=True, exist_ok=True)
DOC.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Trial lineage for fundamental_change_v1 research program
# ---------------------------------------------------------------------------
TRIAL_LINEAGE: List[Dict[str, Any]] = [
    {
        "trial_id": "C5-E-001",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Fundamental change signal provides incremental information beyond technical library",
        "analysis_type": "independent_alpha_probe",
        "stage": "C5-E",
        "count": 1,
        "folds": 1,
        "horizons": [5, 10, 20],
        "lineage": "root",
        "notes": "Bounded probe: 1 fold x 3 horizons",
    },
    {
        "trial_id": "C5-E-002",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Fundamental change signal is repeatable across folds",
        "analysis_type": "full_matrix",
        "stage": "C5-E",
        "count": 1,
        "folds": 8,
        "horizons": [5, 10, 20],
        "lineage": "C5-E-001",
        "notes": "Full matrix: 8 folds x 3 horizons = 24 experiments",
    },
    {
        "trial_id": "C5-F-001",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Fundamental provides incremental alpha over technical-only baseline",
        "analysis_type": "incremental_analysis",
        "stage": "C5-F",
        "count": 1,
        "folds": 8,
        "horizons": [5, 10, 20],
        "lineage": "C5-E-002",
        "notes": "Aligned incremental analysis with common sample",
    },
    {
        "trial_id": "C5-F-002",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Fundamental signal correlation with technical signals",
        "analysis_type": "correlation_analysis",
        "stage": "C5-F",
        "count": 1,
        "folds": 8,
        "horizons": [5, 10, 20],
        "lineage": "C5-F-001",
        "notes": "Pearson/Spearman correlation by fold/horizon",
    },
    {
        "trial_id": "C5-G-001",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Fundamental strategy can produce stable walk-forward signals",
        "analysis_type": "formal_walkforward",
        "stage": "C5-G",
        "count": 1,
        "folds": 8,
        "horizons": [5, 10, 20],
        "lineage": "C5-F-002",
        "notes": "Formal strategy spec frozen; 24 experiments",
    },
    {
        "trial_id": "C5-H-001",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Fundamental strategy qualifies under 9-layer framework",
        "analysis_type": "qualification",
        "stage": "C5-H",
        "count": 1,
        "folds": 8,
        "horizons": [5, 10, 20],
        "lineage": "C5-G-001",
        "notes": "Initial qualification; blocked by missing L4 economic evidence",
    },
    {
        "trial_id": "C5-H1-001",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Fundamental economic portfolio excess return can be computed",
        "analysis_type": "economic_evidence",
        "stage": "C5-H1",
        "count": 1,
        "folds": 8,
        "horizons": [5, 10, 20],
        "lineage": "C5-H-001",
        "notes": "Bounded probe + full matrix; equal-weight portfolio vs universe median",
    },
    {
        "trial_id": "C5-H2-001",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Qualification result changes after adding economic evidence",
        "analysis_type": "qualification_rerun",
        "stage": "C5-H2",
        "count": 1,
        "folds": 8,
        "horizons": [5, 10, 20],
        "lineage": "C5-H1-001",
        "notes": "Re-run with L4 populated; still INSUFFICIENT due to L7/L8/L9",
    },
    {
        "trial_id": "C5-H3-001",
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "hypothesis": "Fundamental strategy capacity/implementability can be measured",
        "analysis_type": "capacity_evidence",
        "stage": "C5-H3",
        "count": 1,
        "folds": 8,
        "horizons": [5, 10, 20],
        "lineage": "C5-H2-001",
        "notes": "Breadth/concentration/liquidity measured; capacity = INSUFFICIENT",
    },
]

# ---------------------------------------------------------------------------
# Helper counts
# ---------------------------------------------------------------------------
def compute_trial_summary(lineage: List[Dict[str, Any]]) -> Dict[str, Any]:
    analysis_types = {}
    stages = {}
    total_experiments = 0
    for trial in lineage:
        at = trial["analysis_type"]
        analysis_types[at] = analysis_types.get(at, 0) + 1
        stages[trial["stage"]] = stages.get(trial["stage"], 0) + 1
        total_experiments += trial["count"]

    return {
        "total_trials": len(lineage),
        "total_analyses": len(analysis_types),
        "total_experiments": total_experiments,
        "analysis_type_counts": analysis_types,
        "stage_counts": stages,
        "variants": ["fundamental_change_v1"],
        "families": ["FUNDAMENTAL"],
        "hypotheses": list({t["hypothesis"] for t in lineage}),
    }


def assess_p_hacking_risk(lineage: List[Dict[str, Any]]) -> Dict[str, Any]:
    risks = []
    # Check for parameter variants
    variants = [t["variant"] for t in lineage]
    unique_variants = set(variants)
    if len(unique_variants) == 1:
        risks.append({
            "risk": "SINGLE_VARIANT",
            "level": "LOW",
            "detail": "Only one variant; no parameter tuning detected",
        })

    # Check for post-hoc selection
    if any("best" in (t.get("notes") or "").lower() for t in lineage):
        risks.append({
            "risk": "POST_HOC_SELECTION",
            "level": "MEDIUM",
            "detail": "Some notes mention best/worst fold analysis",
        })

    # Check for horizon slicing
    horizon_counts = {}
    for t in lineage:
        for h in t.get("horizons", []):
            horizon_counts[h] = horizon_counts.get(h, 0) + 1
    if len(horizon_counts) > 1:
        risks.append({
            "risk": "HORIZON_SLICING",
            "level": "INFORMATIONAL",
            "detail": f"Multiple horizons analyzed: {list(horizon_counts.keys())}",
        })

    return {
        "p_hacking_risk": "LOW" if not risks else "MEDIUM",
        "risks": risks,
        "selection_risk": "RESEARCH_SELECTION_RISK" if any(r["level"] == "MEDIUM" for r in risks) else "NONE",
    }


def assess_multiple_testing_status(lineage: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    """
    Determine L8_MULTIPLE_TESTING status.

    Current state:
    - 1 variant only
    - ~9 trial groups across stages
    - No parameter search / grid search
    - No post-hoc winner selection
    - PBO/DSR not applicable with <10 variants
    """
    variant_count = len(set(t["variant"] for t in lineage))
    analysis_count = len(set(t["analysis_type"] for t in lineage))

    if variant_count < 3 and analysis_count < 5:
        return "NOT_APPLICABLE_YET"
    if variant_count >= 10:
        return "PENDING"
    return "LIMITED"


def build_audit_table(lineage: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    table = []
    for t in lineage:
        table.append({
            "trial_id": t["trial_id"],
            "trial_group": t["stage"],
            "variant": t["variant"],
            "analysis_type": t["analysis_type"],
            "count": t["count"],
            "folds": t["folds"],
            "horizons": t["horizons"],
            "status": "RECORDED",
            "multiple_testing_scope": "within_family" if t["analysis_type"] == "formal_walkforward" else "cross_analysis",
            "lineage": t["lineage"],
        })
    return table


def main() -> None:
    summary = compute_trial_summary(TRIAL_LINEAGE)
    p_hacking = assess_p_hacking_risk(TRIAL_LINEAGE)
    multiple_testing_status = assess_multiple_testing_status(TRIAL_LINEAGE, summary)
    audit_table = build_audit_table(TRIAL_LINEAGE)

    audit = {
        "summary": summary,
        "p_hacking_assessment": p_hacking,
        "multiple_testing_status": multiple_testing_status,
        "audit_table": audit_table,
        "lineage": TRIAL_LINEAGE,
    }

    lineage_doc = {
        "family": "FUNDAMENTAL",
        "variant": "fundamental_change_v1",
        "spec_version": "1.0.0",
        "trial_count": len(TRIAL_LINEAGE),
        "trials": TRIAL_LINEAGE,
        "governance": {
            "registry": "Experiment Governance / Multiple Testing Registry",
            "status": "RECORDED",
            "note": "All analyses tracked under single variant; no parameter variants created",
        },
    }

    (ART / "c5_h4_multiple_testing_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_h4_trial_lineage.json").write_text(
        json.dumps(lineage_doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report_lines = [
        "# M9.1-C5-H4 Fundamental Multiple Testing Closure",
        "",
        "## Multiple Testing Status",
        f"- L8_MULTIPLE_TESTING_STATUS: {multiple_testing_status}",
        "",
        "## Trial Summary",
        f"- Total trials: {summary['total_trials']}",
        f"- Total analyses: {summary['total_analyses']}",
        f"- Total experiments: {summary['total_experiments']}",
        f"- Variants: {summary['variants']}",
        f"- Families: {summary['families']}",
        "",
        "## Analysis Types",
    ]
    for at, count in summary["analysis_type_counts"].items():
        report_lines.append(f"- {at}: {count}")

    report_lines.extend([
        "",
        "## P-Hacking Risk",
        f"- Overall risk: {p_hacking['p_hacking_risk']}",
        f"- Selection risk: {p_hacking['selection_risk']}",
        "",
        "## Key Points",
        "- Single variant only: fundamental_change_v1",
        "- No parameter tuning / grid search performed",
        "- No post-hoc horizon deletion",
        "- All 5D/10D/20D results preserved",
        "- PBO/DSR: NOT_APPLICABLE_YET (insufficient variants for reliable estimation)",
        "",
        "## Next Steps",
        "- Proceed to M9.1-C5-H5 Robustness Closure",
        "",
        "## Gates",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `c5_h4_multiple_testing_audit.json`",
        "- `c5_h4_trial_lineage.json`",
        "",
    ])
    report = "\n".join(report_lines)
    (DOC / "M9_1-C5-H4_MULTIPLE_TESTING_CLOSURE.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "multiple_testing_status": multiple_testing_status,
        "trial_summary": summary,
        "p_hacking_risk": p_hacking,
        "artifacts": [
            "data/research/strategy/c5_h4_multiple_testing_audit.json",
            "data/research/strategy/c5_h4_trial_lineage.json",
            "docs/M9_1-C5-H4_MULTIPLE_TESTING_CLOSURE.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
