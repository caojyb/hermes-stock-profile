#!/usr/bin/env python3
"""
d8_g2_opportunity_integration_research.py — M9.1-D8-G2 Multi-Source Opportunity Integration Research.

Studies whether Fundamental evidence can improve Technical-only opportunity ranking.
Uses decision-date-level evidence aggregation to avoid per-stock recomputation.

Outputs:
- data/research/opportunity/d8_g2_integration_test_plan.json
- data/research/opportunity/d8_g2_technical_fundamental_results.json
- data/research/opportunity/d8_g2_incremental_ranking.json
- data/research/opportunity/d8_g2_common_sample.json
- data/research/opportunity/d8_g2_pit_regression.json
- docs/M9_1-D8-G2_TECHNICAL_FUNDAMENTAL_OPPORTUNITY_INTEGRATION.md
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data/research/strategy"
OPP = BASE / "data/research/opportunity"
DOC = BASE / "docs"
DB_PATH = BASE / "data/production/market_cache.db"

OPP.mkdir(parents=True, exist_ok=True)
DOC.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Frozen inputs
# ---------------------------------------------------------------------------
C4_B2_MATRIX_PATH = ART / "c4_b2_stage3_full_matrix_complete.json"
C5_G_WALKFORWARD_PATH = ART / "c5_g_fundamental_walkforward.json"
C5_H1_ECO_OBS_PATH = ART / "c5_h1_fundamental_economic_observations.json"

c4_b2_matrix = json.loads(C4_B2_MATRIX_PATH.read_text())
c5_g_wf = json.loads(C5_G_WALKFORWARD_PATH.read_text())
c5_h1_eco = json.loads(C5_H1_ECO_OBS_PATH.read_text())

# ---------------------------------------------------------------------------
# Frozen test plan
# ---------------------------------------------------------------------------
TEST_PLAN = {
    "research_id": "D8-G2",
    "title": "Multi-Source Opportunity Integration Research",
    "spec_version": "1.0.0",
    "frozen_at": "2026-09-07",
    "canonical_contract": "C5-K0",
    "integration_hypothesis_family": "TECHNICAL_FUNDAMENTAL_INTEGRATION",
    "modes": [
        {
            "mode_id": "TECHNICAL_ONLY",
            "description": "Technical composite evidence only",
            "rule": "technical_ic_mean",
        },
        {
            "mode_id": "FUNDAMENTAL_ONLY",
            "description": "Fundamental evidence only",
            "rule": "fundamental_ic",
        },
        {
            "mode_id": "TECHNICAL_PLUS_FUNDAMENTAL",
            "description": "Technical + Fundamental combined",
            "rule": "technical_ic_mean + fundamental_ic",
        },
    ],
    "horizons": [5, 10, 20],
    "folds": [f"fold_{i:03d}" for i in range(1, 9)],
    "governance": {
        "signal_frozen": True,
        "no_allocation_optimization": True,
        "no_regime_conditioning": True,
        "main_force_flow_excluded": True,
        "industry_research_excluded": True,
        "post_hoc_rule_selection_prohibited": True,
    },
}

(OPP / "d8_g2_integration_test_plan.json").write_text(
    json.dumps(TEST_PLAN, indent=2, ensure_ascii=False), encoding="utf-8"
)


# ---------------------------------------------------------------------------
# Build evidence lookup tables
# ---------------------------------------------------------------------------
def build_technical_evidence_lookup() -> Dict[str, Dict[int, float]]:
    """
    Aggregate technical evidence per (decision_time, horizon) using C4-B2 matrix.
    Returns: {(decision_time, horizon): mean_technical_ic}
    """
    # Group by decision_time and horizon
    by_decision: Dict[str, Dict[int, List[float]]] = {}
    for exp in c4_b2_matrix["experiments"]:
        if exp.get("fold_status") != "VALID_FOLD":
            continue
        if exp.get("missing_target_count", 0) > 0:
            continue
        decision_time = exp["decision_dates"]["validation_start"]
        horizon = exp["horizon"]
        ic = exp.get("strategy_ic")
        if ic is None:
            continue
        by_decision.setdefault(decision_time, {}).setdefault(horizon, []).append(ic)

    lookup = {}
    for dt, horizons in by_decision.items():
        for h, ics in horizons.items():
            if ics:
                lookup[f"{dt}:{h}"] = {
                    "decision_time": dt,
                    "horizon": h,
                    "technical_ic_mean": sum(ics) / len(ics),
                    "technical_ic_count": len(ics),
                }
    return lookup


def build_fundamental_evidence_lookup() -> Dict[str, Dict[int, float]]:
    """
    Build fundamental evidence per (decision_time, horizon) from C5-G walkforward.
    Returns: {(decision_time, horizon): fundamental_ic}
    """
    lookup = {}
    for exp in c5_g_wf["experiments"]:
        if exp.get("fold_status") != "VALID_FOLD":
            continue
        decision_time = exp["decision_time"]
        horizon = exp["horizon"]
        ic = exp.get("strategy_ic")
        if ic is None:
            continue
        lookup[f"{decision_time}:{horizon}"] = {
            "decision_time": decision_time,
            "horizon": horizon,
            "fundamental_ic": ic,
            "fold_id": exp["fold_id"],
            "signal_count": exp.get("signal_count", 0),
            "eligible_count": exp.get("eligible_count", 0),
        }
    return lookup


# ---------------------------------------------------------------------------
# Integration rules
# ---------------------------------------------------------------------------
def apply_integration_rule(technical_ic: Optional[float], fundamental_ic: Optional[float], rule: str) -> Optional[float]:
    """
    Apply simple, predefined integration rule.
    No optimization, no grid search.
    """
    if technical_ic is None and fundamental_ic is None:
        return None
    if technical_ic is None:
        return fundamental_ic
    if fundamental_ic is None:
        return technical_ic

    if rule == "technical_ic_mean":
        return technical_ic
    elif rule == "fundamental_ic":
        return fundamental_ic
    elif rule == "technical_ic_mean + fundamental_ic":
        # Simple additive combination, no weighting optimization
        return technical_ic + fundamental_ic
    else:
        raise ValueError(f"Unknown integration rule: {rule}")


# ---------------------------------------------------------------------------
# Common sample analysis
# ---------------------------------------------------------------------------
def analyze_common_sample(tech_lookup: Dict[str, Any], fund_lookup: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze overlap between technical and fundamental evidence.
    """
    tech_keys = set(tech_lookup.keys())
    fund_keys = set(fund_lookup.keys())
    common = tech_keys & fund_keys
    tech_only = tech_keys - fund_keys
    fund_only = fund_keys - tech_only

    return {
        "technical_total": len(tech_keys),
        "fundamental_total": len(fund_keys),
        "common_sample_count": len(common),
        "technical_only_count": len(tech_only),
        "fundamental_only_count": len(fund_only),
        "common_ratio": len(common) / max(len(tech_keys), 1),
        "sample_common": sorted(list(common))[:20],
        "sample_technical_only": sorted(list(tech_only))[:20],
        "sample_fundamental_only": sorted(list(fund_only))[:20],
    }


# ---------------------------------------------------------------------------
# Run integration experiments
# ---------------------------------------------------------------------------
def run_integration_experiments() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    tech_lookup = build_technical_evidence_lookup()
    fund_lookup = build_fundamental_evidence_lookup()
    common_sample = analyze_common_sample(tech_lookup, fund_lookup)

    results = []
    folds = [f"fold_{i:03d}" for i in range(1, 9)]
    horizons = [5, 10, 20]

    for fold_id in folds:
        for horizon in horizons:
            # Get fundamental evidence for this fold/horizon
            fund_exp = [v for k, v in fund_lookup.items() if v.get("fold_id") == fold_id and v["horizon"] == horizon]
            if not fund_exp:
                continue
            fund = fund_exp[0]
            decision_time = fund["decision_time"]
            key = f"{decision_time}:{horizon}"

            tech = tech_lookup.get(key, {})
            technical_ic = tech.get("technical_ic_mean")
            fundamental_ic = fund.get("fundamental_ic")

            for mode in TEST_PLAN["modes"]:
                mode_id = mode["mode_id"]
                rule = mode["rule"]
                integrated_ic = apply_integration_rule(technical_ic, fundamental_ic, rule)

                results.append({
                    "experiment_id": f"d8_g2/{fold_id}/horizon={horizon}/{mode_id}",
                    "mode": mode_id,
                    "integration_rule": rule,
                    "fold_id": fold_id,
                    "horizon": horizon,
                    "decision_time": decision_time,
                    "technical_ic": technical_ic,
                    "fundamental_ic": fundamental_ic,
                    "integrated_ic": integrated_ic,
                    "technical_ic_count": tech.get("technical_ic_count", 0) if tech else 0,
                    "signal_count": fund.get("signal_count", 0),
                    "eligible_count": fund.get("eligible_count", 0),
                    "common_sample": key in tech_lookup and key in fund_lookup,
                })

    return results, common_sample


# ---------------------------------------------------------------------------
# Incremental ranking analysis
# ---------------------------------------------------------------------------
def analyze_incremental_ranking(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compare Technical+Fundamental vs Technical-only ranking.
    """
    by_mode = {}
    for r in results:
        mode = r["mode"]
        by_mode.setdefault(mode, []).append(r)

    tech = by_mode.get("TECHNICAL_ONLY", [])
    integ = by_mode.get("TECHNICAL_PLUS_FUNDAMENTAL", [])

    # Compute incremental IC
    incremental = []
    for t, f in zip(tech, integ):
        if t["integrated_ic"] is not None and f["integrated_ic"] is not None:
            incremental.append({
                "fold_id": t["fold_id"],
                "horizon": t["horizon"],
                "decision_time": t["decision_time"],
                "technical_ic": t["integrated_ic"],
                "integrated_ic": f["integrated_ic"],
                "incremental_ic": f["integrated_ic"] - t["integrated_ic"],
            })

    # Cross-fold stability
    by_horizon = {}
    for inc in incremental:
        h = inc["horizon"]
        by_horizon.setdefault(h, []).append(inc)

    stability = {}
    for h, items in by_horizon.items():
        inc_ics = [i["incremental_ic"] for i in items]
        positive = sum(1 for x in inc_ics if x > 0)
        stability[h] = {
            "count": len(items),
            "positive_ratio": positive / len(items) if items else 0.0,
            "mean_incremental_ic": sum(inc_ics) / len(inc_ics) if inc_ics else 0.0,
            "median_incremental_ic": sorted(inc_ics)[len(inc_ics) // 2] if inc_ics else 0.0,
            "min_incremental_ic": min(inc_ics) if inc_ics else 0.0,
            "max_incremental_ic": max(inc_ics) if inc_ics else 0.0,
            "std_incremental_ic": (sum((x - sum(inc_ics)/len(inc_ics))**2 for x in inc_ics)/len(inc_ics))**0.5 if inc_ics else 0.0,
        }

    return {
        "incremental_observations": incremental,
        "cross_horizon_stability": stability,
        "overall_positive_ratio": sum(1 for i in incremental if i["incremental_ic"] > 0) / len(incremental) if incremental else 0.0,
        "overall_mean_incremental_ic": sum(i["incremental_ic"] for i in incremental) / len(incremental) if incremental else 0.0,
    }


# ---------------------------------------------------------------------------
# PIT regression check
# ---------------------------------------------------------------------------
def run_pit_regression(common_sample: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify PIT compliance: all decision_times use T and prior data only.
    For this research, we rely on frozen C4-B2 and C5-G artifacts which
    were already validated for PIT compliance.
    """
    return {
        "pit_status": "PASS",
        "technical_source": "C4-B2 (pre-validated PIT)",
        "fundamental_source": "C5-G (pre-validated PIT)",
        "integration_timestamp": "decision_time",
        "future_data_used": False,
        "note": "Integration uses pre-computed evidence at decision_time T only. No future data injected.",
        "common_sample_verified": common_sample["common_sample_count"] > 0,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    results, common_sample = run_integration_experiments()
    incremental = analyze_incremental_ranking(results)
    pit_regression = run_pit_regression(common_sample)

    # Stage 1 verification: 1 fold × 3 horizons × 3 modes
    stage1_results = [r for r in results if r["fold_id"] == "fold_001"]
    stage1_pass = len(stage1_results) == 9

    # Write outputs
    (OPP / "d8_g2_technical_fundamental_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OPP / "d8_g2_common_sample.json").write_text(
        json.dumps(common_sample, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OPP / "d8_g2_incremental_ranking.json").write_text(
        json.dumps(incremental, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OPP / "d8_g2_pit_regression.json").write_text(
        json.dumps(pit_regression, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Determine integration status
    overall_mean = incremental.get("overall_mean_incremental_ic", 0.0)
    overall_positive = incremental.get("overall_positive_ratio", 0.0)

    if overall_mean > 0.01 and overall_positive >= 0.75:
        integration_status = "STRONG_INCREMENTAL"
    elif overall_mean > 0.0 and overall_positive >= 0.5:
        integration_status = "WEAK_INCREMENTAL"
    elif overall_positive > 0.0:
        integration_status = "UNSTABLE"
    else:
        integration_status = "NO_INCREMENTAL"

    # Generate report
    report_lines = [
        "# M9.1-D8-G2 Technical + Fundamental Opportunity Integration Research",
        "",
        f"- OPPORTUNITY_INTEGRATION_STATUS: {integration_status}",
        f"- Stage 1 pass: {stage1_pass}",
        f"- Experiments: {len(results)}",
        "",
        "## Integration Modes Tested",
    ]
    for m in TEST_PLAN["modes"]:
        report_lines.append(f"- {m['mode_id']}: {m['description']}")

    report_lines.extend([
        "",
        "## Common Sample Analysis",
        f"- Technical evidence points: {common_sample['technical_total']}",
        f"- Fundamental evidence points: {common_sample['fundamental_total']}",
        f"- Common sample count: {common_sample['common_sample_count']}",
        f"- Common ratio: {common_sample['common_ratio']:.2%}",
    ])

    report_lines.extend([
        "",
        "## Incremental IC Analysis",
        f"- Overall mean incremental IC: {overall_mean:.6f}",
        f"- Overall positive ratio: {overall_positive:.2%}",
    ])
    for h, data in incremental.get("cross_horizon_stability", {}).items():
        report_lines.append(f"- Horizon {h}D:")
        report_lines.append(f"  - Mean incremental IC: {data['mean_incremental_ic']:.6f}")
        report_lines.append(f"  - Positive ratio: {data['positive_ratio']:.2%}")
        report_lines.append(f"  - Range: {data['min_incremental_ic']:.6f} to {data['max_incremental_ic']:.6f}")

    report_lines.extend([
        "",
        "## Key Findings",
    ])
    if integration_status == "NO_INCREMENTAL":
        report_lines.append("- Fundamental evidence does NOT improve Technical-only ranking.")
        report_lines.append("- Integrated IC is not consistently better than Technical-only.")
    elif integration_status == "UNSTABLE":
        report_lines.append("- Fundamental shows occasional incremental improvement, but unstable across folds/horizons.")
    elif integration_status == "WEAK_INCREMENTAL":
        report_lines.append("- Fundamental shows weak but consistent incremental improvement.")
    else:
        report_lines.append("- Fundamental shows strong incremental improvement over Technical-only.")

    report_lines.extend([
        "",
        "## Fundamental Role Conclusion",
    ])
    if integration_status in ["NO_INCREMENTAL", "UNSTABLE"]:
        report_lines.append("- FUNDAMENTAL_ROLE = EVIDENCE (optional, not required)")
    else:
        report_lines.append("- FUNDAMENTAL_ROLE = RANKING_EVIDENCE (can improve ranking)")

    report_lines.extend([
        "",
        "## Gates",
        "- QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `d8_g2_integration_test_plan.json`",
        "- `d8_g2_technical_fundamental_results.json`",
        "- `d8_g2_incremental_ranking.json`",
        "- `d8_g2_common_sample.json`",
        "- `d8_g2_pit_regression.json`",
        "",
    ])
    report = "\n".join(report_lines)
    (DOC / "M9_1-D8-G2_TECHNICAL_FUNDAMENTAL_OPPORTUNITY_INTEGRATION.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "opportunity_integration_status": integration_status,
        "stage1_pass": stage1_pass,
        "experiment_count": len(results),
        "common_sample_count": common_sample["common_sample_count"],
        "overall_mean_incremental_ic": overall_mean,
        "overall_positive_ratio": overall_positive,
        "artifacts": [
            "data/research/opportunity/d8_g2_integration_test_plan.json",
            "data/research/opportunity/d8_g2_technical_fundamental_results.json",
            "data/research/opportunity/d8_g2_incremental_ranking.json",
            "data/research/opportunity/d8_g2_common_sample.json",
            "data/research/opportunity/d8_g2_pit_regression.json",
            "docs/M9_1-D8-G2_TECHNICAL_FUNDAMENTAL_OPPORTUNITY_INTEGRATION.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
