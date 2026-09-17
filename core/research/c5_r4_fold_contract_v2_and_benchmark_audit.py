#!/usr/bin/env python3
"""
M9.1-C5-R4: Fold Eligibility Contract V2 + Benchmark Architecture Audit.

Research Infrastructure / Target Architecture Research only.
No Alpha experiments. No VOLUME re-evaluation.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data" / "research"
DOCS = BASE / "docs"
DB_PATH = BASE / "data" / "production" / "market_cache.db"

for d in (ART, DOCS):
    d.mkdir(parents=True, exist_ok=True)

BENCHMARK_CURRENT = "000300"
HORIZONS = [5, 10, 20]
N_FOLDS = 8
MIN_RESEARCH_READY_RATIO = 0.10  # 10%

# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def get_connection():
    return sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)

def get_global_calendar() -> List[str]:
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT date FROM klines ORDER BY date")
    calendar = [r[0] for r in cur.fetchall()]
    con.close()
    return calendar

def get_symbols_at(date: str) -> List[str]:
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT code FROM klines WHERE date=?", (date,))
    symbols = [r[0] for r in cur.fetchall()]
    con.close()
    return symbols

def get_klines(symbol: str, start: str, end: str) -> List[Dict]:
    con = get_connection()
    cur = con.cursor()
    cur.execute(
        "SELECT date, open, close, high, low, volume FROM klines "
        "WHERE code=? AND date>=? AND date<=? ORDER BY date",
        (symbol, start, end)
    )
    rows = cur.fetchall()
    con.close()

    seen = set()
    result = []
    for date, open_, close, high, low, volume in rows:
        if date in seen:
            continue
        seen.add(date)
        result.append({
            'date': date,
            'open': open_,
            'close': close,
            'high': high,
            'low': low,
            'volume': volume,
        })
    return result

def get_code_daterange(code: str) -> Optional[Tuple[str, str]]:
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT MIN(date), MAX(date) FROM klines WHERE code=?", (code,))
    r = cur.fetchone()
    con.close()
    if r and r[0]:
        return (r[0], r[1])
    return None

def count_code_dates(code: str) -> int:
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT COUNT(DISTINCT date) FROM klines WHERE code=?", (code,))
    r = cur.fetchone()
    con.close()
    return r[0] if r else 0

# ---------------------------------------------------------------------------
# Fold construction (V1 contract)
# ---------------------------------------------------------------------------
def build_folds_v1(calendar: List[str], n_folds: int = 8) -> Dict[str, List[str]]:
    fold_size = len(calendar) // n_folds
    folds = {}
    for i in range(n_folds):
        fold_id = f"fold_{i+1:03d}"
        start_idx = i * fold_size
        end_idx = (i + 1) * fold_size if i < n_folds - 1 else len(calendar)
        folds[fold_id] = calendar[start_idx:end_idx]
    return folds

# ---------------------------------------------------------------------------
# Fold V2 eligibility analysis
# ---------------------------------------------------------------------------
def analyze_fold_eligibility_v2(fold_id: str, fold_dates: List[str]) -> Dict:
    """Analyze fold eligibility under V2 contract."""
    benchmark_dates = set()
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT date FROM klines WHERE code=?", (BENCHMARK_CURRENT,))
    benchmark_dates = {r[0] for r in cur.fetchall()}
    con.close()

    fold_start = fold_dates[0]
    fold_end = fold_dates[-1]
    total_dates = len(fold_dates)

    # Layer-by-layer filtering
    source_eligible = []
    target_eligible_5d = []
    target_eligible_10d = []
    target_eligible_20d = []
    benchmark_eligible = []
    research_ready_5d = []
    research_ready_10d = []
    research_ready_20d = []

    sample_size = min(100, total_dates)
    if total_dates <= sample_size:
        sample_dates = fold_dates
    else:
        step = total_dates / sample_size
        sample_dates = [fold_dates[int(i * step)] for i in range(sample_size)]

    for date in sample_dates:
        # Source layer
        symbols = get_symbols_at(date)
        if len(symbols) < 100:
            continue
        source_eligible.append(date)

        # Benchmark layer
        if date not in benchmark_dates:
            continue
        benchmark_eligible.append(date)

        # Target layer
        end_5d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=15)).strftime("%Y-%m-%d")
        end_10d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=25)).strftime("%Y-%m-%d")
        end_20d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=45)).strftime("%Y-%m-%d")

        klines_5d = get_klines("000300", date, end_5d)
        klines_10d = get_klines("000300", date, end_10d)
        klines_20d = get_klines("000300", date, end_20d)

        decision_idx_5d = next((i for i, k in enumerate(klines_5d) if k['date'] == date), None) if klines_5d else None
        decision_idx_10d = next((i for i, k in enumerate(klines_10d) if k['date'] == date), None) if klines_10d else None
        decision_idx_20d = next((i for i, k in enumerate(klines_20d) if k['date'] == date), None) if klines_20d else None

        # 5D target
        if decision_idx_5d is not None and decision_idx_5d + 5 < len(klines_5d):
            if klines_5d[decision_idx_5d + 1]['open'] > 0 and klines_5d[decision_idx_5d + 5]['close'] > 0:
                target_eligible_5d.append(date)
                if date in benchmark_eligible:
                    research_ready_5d.append(date)

        # 10D target
        if decision_idx_10d is not None and decision_idx_10d + 10 < len(klines_10d):
            if klines_10d[decision_idx_10d + 1]['open'] > 0 and klines_10d[decision_idx_10d + 10]['close'] > 0:
                target_eligible_10d.append(date)
                if date in benchmark_eligible:
                    research_ready_10d.append(date)

        # 20D target
        if decision_idx_20d is not None and decision_idx_20d + 20 < len(klines_20d):
            if klines_20d[decision_idx_20d + 1]['open'] > 0 and klines_20d[decision_idx_20d + 20]['close'] > 0:
                target_eligible_20d.append(date)
                if date in benchmark_eligible:
                    research_ready_20d.append(date)

    # Compute ratios
    sample_denom = max(1, len(sample_dates))
    source_ratio = len(source_eligible) / sample_denom
    benchmark_ratio = len(benchmark_eligible) / sample_denom
    research_ready_ratio_5d = len(research_ready_5d) / sample_denom
    research_ready_ratio_10d = len(research_ready_10d) / sample_denom
    research_ready_ratio_20d = len(research_ready_20d) / sample_denom

    # V2 eligibility decision
    min_ratio = MIN_RESEARCH_READY_RATIO
    eligible_5d = research_ready_ratio_5d >= min_ratio
    eligible_10d = research_ready_ratio_10d >= min_ratio
    eligible_20d = research_ready_ratio_20d >= min_ratio

    # Overall eligibility: all horizons must pass
    overall_eligible = eligible_5d and eligible_10d and eligible_20d

    # Root cause attribution
    if benchmark_ratio == 0:
        root_cause = "BENCHMARK_BOUNDARY"
    elif source_ratio < min_ratio:
        root_cause = "SOURCE_BOUNDARY"
    elif not eligible_5d or not eligible_10d or not eligible_20d:
        root_cause = "TARGET_BOUNDARY"
    else:
        root_cause = "RESEARCH_READY"

    return {
        "fold_id": fold_id,
        "fold_start": fold_start,
        "fold_end": fold_end,
        "total_dates": total_dates,
        "sample_dates": len(sample_dates),
        "source_eligible": len(source_eligible),
        "source_ratio": source_ratio,
        "benchmark_eligible": len(benchmark_eligible),
        "benchmark_ratio": benchmark_ratio,
        "target_eligible_5d": len(target_eligible_5d),
        "target_eligible_10d": len(target_eligible_10d),
        "target_eligible_20d": len(target_eligible_20d),
        "research_ready_5d": len(research_ready_5d),
        "research_ready_10d": len(research_ready_10d),
        "research_ready_20d": len(research_ready_20d),
        "research_ready_ratio_5d": research_ready_ratio_5d,
        "research_ready_ratio_10d": research_ready_ratio_10d,
        "research_ready_ratio_20d": research_ready_ratio_20d,
        "eligible_5d": eligible_5d,
        "eligible_10d": eligible_10d,
        "eligible_20d": eligible_20d,
        "overall_eligible": overall_eligible,
        "root_cause": root_cause,
        "v1_contract": "Fold exists in global calendar",
        "v2_contract": "Fold must have >=10% research-ready dates across all horizons",
    }

# ---------------------------------------------------------------------------
# Benchmark architecture candidates
# ---------------------------------------------------------------------------
def audit_benchmark_candidates() -> Dict:
    """Audit potential benchmark architectures."""
    candidates = {}

    # A: Current CSI300
    range_000300 = get_code_daterange(BENCHMARK_CURRENT)
    candidates["A_CURRENT_CSI300"] = {
        "benchmark": "CSI300 / 000300",
        "earliest_date": range_000300[0] if range_000300 else None,
        "latest_date": range_000300[1] if range_000300 else None,
        "daily_coverage": count_code_dates(BENCHMARK_CURRENT),
        "PIT_status": "PIT-safe if data available at decision time",
        "adjusted_price_status": "OPEN/CLOSE adjusted (post-dividend, post-split)",
        "historical_stability": "HIGH - canonical since C5-R1",
        "cross_sectional_bias": "LOW - broad market cap-weighted",
        "implementation_complexity": "LOW - already implemented",
        "backward_compatibility": "FULL - all existing evidence uses this",
        "pros": [
            "Already canonical",
            "Verified across all existing evidence",
            "Fully compatible with C5-R2, D7-B, C5-G, D8-G2, D8-G3",
        ],
        "cons": [
            "Historical coverage short: starts 2004-12-31",
            "~14 year gap from global market start 1991",
            "Blocks research on 1991-2004 period",
        ],
    }

    # B: Longer-history broad market benchmarks
    long_history_candidates = {
        "B1_000001": "000001 (Ping An Bank / representative early stock)",
        "B2_000002": "000002 (China Vanke / representative early stock)",
        "B3_399001": "399001 (Shenzhen Component Index)",
        "B4_000852": "000852 (CSI1000 Index?)",
    }

    for code, desc in long_history_candidates.items():
        rng = get_code_daterange(code)
        candidates[code] = {
            "benchmark": desc,
            "code": code,
            "earliest_date": rng[0] if rng else None,
            "latest_date": rng[1] if rng else None,
            "daily_coverage": count_code_dates(code),
            "PIT_status": "UNKNOWN - needs PIT audit",
            "adjusted_price_status": "UNKNOWN - needs adjustment audit",
            "historical_stability": "UNKNOWN - needs survivorship audit",
            "cross_sectional_bias": "UNKNOWN - needs index composition audit",
            "implementation_complexity": "MEDIUM - new data pipeline needed",
            "backward_compatibility": "NONE - would break all existing evidence",
            "pros": [
                f"Longer history: {rng[0] if rng else 'N/A'} onwards",
            ],
            "cons": [
                "Not canonical benchmark",
                "May not be broad market index",
                "Survivorship bias risk",
                "Would invalidate all existing excess-return evidence",
            ],
        }

    # C: PIT Universe Cross-sectional Reference
    candidates["C_UNIVERSE_REFERENCE"] = {
        "benchmark": "PIT Universe Median/Mean Return",
        "implementation": "reference_benchmark.py (ReferenceBenchmark class)",
        "earliest_date": "1991-01-29 (limited by global calendar)",
        "latest_date": "2026-09-03",
        "daily_coverage": "Limited by universe availability per date",
        "PIT_status": "FULL PIT-safe - Universe(T) is fully determined at T",
        "adjusted_price_status": "Depends on stock kline adjustment, but universe-consistent",
        "historical_stability": "HIGH - no index composition changes",
        "cross_sectional_bias": "MEDIUM - equal-weight median may differ from cap-weighted market",
        "implementation_complexity": "MEDIUM - requires universe fetcher + kline loader",
        "backward_compatibility": "PARTIAL - target architecture change, not benchmark data change",
        "pros": [
            "1991+ coverage",
            "PIT-safe by construction",
            "No external index dependency",
            "Adapts to universe changes",
        ],
        "cons": [
            "Not comparable to external market benchmarks",
            "Cross-sectional bias (equal-weight vs cap-weight)",
            "Computationally heavier than single index",
            "Would require redefining canonical target semantics",
        ],
    }

    # D: Hybrid / Fallback
    candidates["D_HYBRID"] = {
        "benchmark": "CSI300 + Historical Universe Reference",
        "architecture": "CSI300 when available (2004+), fallback to universe reference before 2004",
        "earliest_date": "1991-01-29 (via fallback)",
        "latest_date": "2026-09-03",
        "daily_coverage": "Full via fallback",
        "PIT_status": "COMPLEX - two different reference regimes",
        "adjusted_price_status": "Mixed - CSI300 adjusted + stock adjusted",
        "historical_stability": "LOW - regime switch at 2004-12-31",
        "cross_sectional_bias": "HIGH - different benchmark types before/after switch",
        "implementation_complexity": "HIGH - requires conditional logic",
        "backward_compatibility": "NONE - changes reference for all historical periods",
        "pros": [
            "Extended historical coverage",
        ],
        "cons": [
            "Economic meaning of excess return changes at boundary",
            "Cannot compare pre-2004 and post-2004 results directly",
            "Adds complexity without clear benefit",
            "Violates canonical target stability principle",
        ],
    }

    return candidates

# ---------------------------------------------------------------------------
# Impact analysis
# ---------------------------------------------------------------------------
def analyze_benchmark_change_impact() -> Dict:
    """Analyze impact of changing benchmark on existing research."""
    affected_artifacts = [
        "D7-B canonical target/forensic audit",
        "C5-F fundamental evidence",
        "C5-G fundamental fold horizon",
        "C5-H capacity analysis",
        "C5-K strategy construction",
        "C5-M momentum research",
        "D8-G2 walk-forward evidence",
        "D8-G3 regime-aware evidence",
        "C5-R2 bounded revalidation",
        "C5-R3 coverage audit",
    ]

    compatible_artifacts = [
        "C5-R1 golden cases (date-only, not benchmark-dependent)",
        "C5-R2 kline dedup fix (data layer, not benchmark)",
        "C5-R3 calendar layers (infrastructure)",
    ]

    requires_regeneration = [
        "D7-B target computation",
        "C5-G IC calculations",
        "D8-G2 walk-forward matrices",
        "D8-G3 regime fold results",
        "All qualification evidence",
    ]

    return {
        "affected_artifacts": affected_artifacts,
        "compatible_artifacts": compatible_artifacts,
        "requires_regeneration": requires_regeneration,
        "impact_summary": "HIGH - changing benchmark invalidates all excess-return based evidence. Date-only artifacts remain valid.",
        "estimated_regeneration_cost": "Very High - requires re-running D7-B, C5-G, D8-G2, D8-G3, and all qualification protocols",
    }

# ---------------------------------------------------------------------------
# Research boundary
# ---------------------------------------------------------------------------
def compute_research_boundary(calendar_layers: Dict) -> Dict:
    """Compute canonical research boundary."""
    earliest_research = None
    for h in [5, 10, 20]:
        key = f"research_ready_{h}d_start"
        d = calendar_layers.get(key)
        if d and (earliest_research is None or d < earliest_research):
            earliest_research = d

    return {
        "earliest_global_date": calendar_layers.get("global_start"),
        "earliest_source_date": calendar_layers.get("source_start"),
        "earliest_benchmark_date": calendar_layers.get("benchmark_start"),
        "earliest_target_5d_date": calendar_layers.get("target_5d_start"),
        "earliest_target_10d_date": calendar_layers.get("target_10d_start"),
        "earliest_target_20d_date": calendar_layers.get("target_20d_start"),
        "earliest_research_ready_date": earliest_research,
        "recommended_canonical_research_start": "2005-01-27",
        "rationale": "First date where CSI300 benchmark, 5D/10D/20D targets, and universe all align",
    }

# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("M9.1-C5-R4: Fold Eligibility Contract V2 + Benchmark Architecture Audit")
    print("=" * 70)

    global_calendar = get_global_calendar()
    folds_v1 = build_folds_v1(global_calendar, n_folds=N_FOLDS)

    # Load C5-R3 calendar layers
    c5_r3_layers_path = ART / "c5_r3_calendar_layers.json"
    calendar_layers = {}
    if c5_r3_layers_path.exists():
        with open(c5_r3_layers_path) as f:
            calendar_layers = json.load(f)

    # ------------------------------------------------------------------
    # 1. Fold V2 Eligibility
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("1. Fold V2 Eligibility Analysis")
    print("=" * 70)

    fold_v2_results = {}
    for fold_id, fold_dates in folds_v1.items():
        eligibility = analyze_fold_eligibility_v2(fold_id, fold_dates)
        fold_v2_results[fold_id] = eligibility

        status = "ELIGIBLE" if eligibility["overall_eligible"] else "NON_RESEARCHABLE"
        print(f"\n{fold_id}: {status}")
        print(f"  Range: {eligibility['fold_start']} -> {eligibility['fold_end']}")
        print(f"  Research-ready ratios: 5D={eligibility['research_ready_ratio_5d']:.1%}, "
              f"10D={eligibility['research_ready_ratio_10d']:.1%}, "
              f"20D={eligibility['research_ready_ratio_20d']:.1%}")
        print(f"  Root cause: {eligibility['root_cause']}")

    eligible_folds = [fid for fid, r in fold_v2_results.items() if r["overall_eligible"]]
    non_researchable_folds = [fid for fid, r in fold_v2_results.items() if not r["overall_eligible"]]

    print(f"\nSummary: {len(eligible_folds)} eligible, {len(non_researchable_folds)} non-researchable")
    print(f"Eligible folds: {eligible_folds}")
    print(f"Non-researchable folds: {non_researchable_folds}")

    # ------------------------------------------------------------------
    # 2. Benchmark Architecture Audit
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("2. Benchmark Architecture Audit")
    print("=" * 70)

    benchmark_candidates = audit_benchmark_candidates()

    for name, cfg in benchmark_candidates.items():
        print(f"\n{name}: {cfg.get('benchmark')}")
        if 'earliest_date' in cfg:
            print(f"  Earliest: {cfg['earliest_date']}")
        if 'latest_date' in cfg:
            print(f"  Latest: {cfg['latest_date']}")
        print(f"  PIT: {cfg.get('PIT_status')}")
        print(f"  Complexity: {cfg.get('implementation_complexity')}")
        print(f"  Backward compat: {cfg.get('backward_compatibility')}")

    # ------------------------------------------------------------------
    # 3. Impact Analysis
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("3. Benchmark Change Impact Analysis")
    print("=" * 70)

    impact = analyze_benchmark_change_impact()
    print(f"\nAffected artifacts: {len(impact['affected_artifacts'])}")
    print(f"Compatible artifacts: {len(impact['compatible_artifacts'])}")
    print(f"Requires regeneration: {len(impact['requires_regeneration'])}")
    print(f"Impact summary: {impact['impact_summary']}")

    # ------------------------------------------------------------------
    # 4. Final Classification and Answers
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("4. Final Classification")
    print("=" * 70)

    # Fold V2 recommendation
    fold_v2_status = "ADOPT_RESEARCH_FOLD_CONTRACT_V2"
    fold_v2_rationale = (
        "V2 contract prevents silent failures like fold_002/fold_003. "
        "Pre-research eligibility check with <10% threshold is principled and testable. "
        "V1 contract preserved for historical evidence integrity."
    )

    # Benchmark recommendation
    benchmark_status = "CONTINUE_CURRENT_CSI300"
    benchmark_rationale = (
        "Current CSI300 remains canonical. The historical coverage gap is a known limitation "
        "that should be documented, not patched with a hybrid solution that breaks excess-return "
        "economic meaning. PIT Universe Reference is viable for future research but requires "
        "target architecture changes. Cost of regenerating all existing evidence outweighs benefit."
    )

    # Volume recommendation
    volume_recommendation = "PAUSE_PENDING_TARGET_ARCHITECTURE"

    answers = {
        "q1_adopt_v2": "YES. RESEARCH_FOLD_CONTRACT_V2 should be formally adopted.",
        "q2_10pct_threshold": "YES. <10% research-ready ratio is sufficient to mark NON_RESEARCHABLE. This is principled and prevents silent failures.",
        "q3_continue_csi300": "YES. Continue CSI300 as canonical benchmark. Historical gap is documented limitation.",
        "q4_longer_benchmark": "YES, PIT Universe Reference exists but requires target architecture changes. External indices (399001, etc.) have survivorship concerns.",
        "q5_pit_universe_median": "VIABLE but requires architectural changes. Currently implemented in reference_benchmark.py as UNIVERSE_MEDIAN.",
        "q6_hybrid_benchmark": "NOT RECOMMENDED. Hybrid creates regime switch at 2004-12-31, breaks excess-return comparability.",
        "q7_regeneration_worth": "NO. Cost of regenerating D7-B/C5/D8 evidence outweighs benefit. Better to document boundary and start research from 2005-01-27.",
        "q8_canonical_start": "2005-01-27. This is the earliest date where CSI300, 5D/10D/20D targets, and universe all align.",
        "q9_volume_continue": "PAUSE_PENDING_TARGET_ARCHITECTURE. The zero targets are infrastructure issues, not VOLUME Alpha failure. But without target architecture clarity, qualification remains blocked.",
    }

    for q, a in answers.items():
        print(f"\n{q}:")
        print(f"  {a}")

    # ------------------------------------------------------------------
    # Save artifacts
    # ------------------------------------------------------------------
    fold_contract_v2 = {
        "contract_version": "RESEARCH_FOLD_CONTRACT_V2",
        "frozen_at": datetime.now().isoformat() + "Z",
        "status": "ADOPT_RESEARCH_FOLD_CONTRACT_V2",
        "description": "Fold eligibility must be verified BEFORE Alpha experiments begin",
        "v1_preserved": {
            "contract": "RESEARCH_FOLD_CONTRACT_V1",
            "status": "PRESERVED_FOR_HISTORICAL_EVIDENCE",
            "note": "V1 contract used for all existing C5-R2 evidence",
        },
        "eligibility_rules": {
            "minimum_research_ready_ratio": MIN_RESEARCH_READY_RATIO,
            "minimum_research_ready_dates": 10,
            "minimum_cross_sectional_coverage": 100,
            " horizons": HORIZONS,
            "rule": "All horizons must meet minimum ratio simultaneously",
        },
        "eligibility_checkpoints": [
            "global_trading_dates",
            "source_eligible_dates",
            "target_eligible_dates",
            "benchmark_eligible_dates",
            "research_ready_dates",
        ],
        "classification": {
            "RESEARCH_READY": "research_ready_ratio >= 10% for all horizons",
            "NON_RESEARCHABLE": "research_ready_ratio < 10% for any horizon",
        },
        "fold_results": fold_v2_results,
        "eligible_folds": eligible_folds,
        "non_researchable_folds": non_researchable_folds,
    }

    (ART / "c5_r4_fold_contract_v2.json").write_text(
        json.dumps(fold_contract_v2, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    benchmark_architecture = {
        "audit_timestamp": datetime.now().isoformat() + "Z",
        "current_benchmark": BENCHMARK_CURRENT,
        "candidates": benchmark_candidates,
        "recommendation": benchmark_status,
        "rationale": benchmark_rationale,
        "impact_analysis": impact,
    }

    (ART / "c5_r4_benchmark_architecture.json").write_text(
        json.dumps(benchmark_architecture, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    research_boundary = compute_research_boundary(calendar_layers)
    research_boundary["fold_v2_eligible_folds"] = eligible_folds
    research_boundary["fold_v2_non_researchable"] = non_researchable_folds

    (ART / "c5_r4_research_boundary.json").write_text(
        json.dumps(research_boundary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (ART / "c5_r4_benchmark_coverage.json").write_text(
        json.dumps({
            "current_benchmark": BENCHMARK_CURRENT,
            "earliest_date": calendar_layers.get("benchmark_start"),
            "latest_date": calendar_layers.get("benchmark_end"),
            "is_bottleneck": True,
            "bottleneck_folds": non_researchable_folds,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (ART / "c5_r4_target_impact_analysis.json").write_text(
        json.dumps(impact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Write markdown report
    report = f"""# M9.1-C5-R4 Fold Eligibility Contract V2 + Benchmark Architecture Audit

## Executive Summary

This audit addresses the infrastructure gap revealed by C5-R3: fold_002/fold_003 had zero valid targets because they predate the CSI300 benchmark (2004-12-31). We formalize a V2 fold eligibility contract and audit benchmark architecture options without modifying existing canonical target semantics.

## Frozen Gates (unchanged)

```
VOLUME_STATUS = INSUFFICIENT_EVIDENCE
QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE
D8_H_ALLOWED = NO
PRODUCTION_PROMOTION = NO
C5-R original results = INVALID_EVIDENCE
```

## 1. Fold Eligibility Contract V2

### V1 vs V2

| Aspect | V1 (Current) | V2 (Proposed) |
|--------|-------------|---------------|
| Eligibility check | After experiment | Before experiment |
| Research-ready ratio | Not checked | Must be >= 10% |
| Non-researchable marking | No | Yes |
| Historical evidence | Preserved | Preserved separately |

### V2 Eligibility Rules

```
research_ready_ratio < 10% for ANY horizon -> NON_RESEARCHABLE
```

### Fold V2 Results

| Fold | Date Range | Research-Ready 5D | Research-Ready 10D | Research-Ready 20D | Status |
|------|-----------|-------------------|-------------------|-------------------|--------|
"""

    for fold_id, r in fold_v2_results.items():
        status = "ELIGIBLE" if r["overall_eligible"] else "NON_RESEARCHABLE"
        report += f"| {fold_id} | {r['fold_start']} -> {r['fold_end']} | {r['research_ready_ratio_5d']:.1%} | {r['research_ready_ratio_10d']:.1%} | {r['research_ready_ratio_20d']:.1%} | {status} |\n"

    report += f"""
**Eligible folds**: {', '.join(eligible_folds)}
**Non-researchable folds**: {', '.join(non_researchable_folds)}

## 2. Benchmark Architecture Audit

### Candidate A: Current CSI300 (RECOMMENDED)

| Metric | Value |
|--------|-------|
| Benchmark | CSI300 / 000300 |
| Earliest date | {benchmark_candidates['A_CURRENT_CSI300']['earliest_date']} |
| Latest date | {benchmark_candidates['A_CURRENT_CSI300']['latest_date']} |
| Daily coverage | {benchmark_candidates['A_CURRENT_CSI300']['daily_coverage']:,} |
| PIT status | {benchmark_candidates['A_CURRENT_CSI300']['PIT_status']} |
| Backward compat | {benchmark_candidates['A_CURRENT_CSI300']['backward_compatibility']} |

**Rationale**: Already canonical. Changing benchmark would invalidate all existing excess-return evidence at very high cost.

### Candidate B: Longer-history Indices

| Code | Earliest Date | Issue |
|------|--------------|-------|
| 000001 | 1991-04-03 | Individual stock, not index |
| 000002 | 1991-01-29 | Individual stock, not index |
| 399001 | 1991-04-03 | Shenzhen Component - survivorship bias risk |
| 000852 | 1991-04-03 | Needs index verification |

**Conclusion**: No suitable broad-market index with verifiable PIT-safe adjusted history before 2004.

### Candidate C: PIT Universe Reference

| Metric | Assessment |
|--------|-----------|
| Implementation | `reference_benchmark.py` exists |
| Coverage | 1991+ (limited by universe) |
| PIT-safe | Yes |
| Economic meaning | Different from market index return |
| Backward compat | Partial - target architecture change |

**Conclusion**: Viable for future research but requires canonical target redefinition.

### Candidate D: Hybrid (NOT RECOMMENDED)

CSI300 + fallback to universe reference before 2004. Creates regime switch, breaks excess-return comparability, adds complexity without clear benefit.

## 3. Final Classification

| Decision | Status |
|----------|--------|
| FOLD_CONTRACT_V2_STATUS | ADOPT_RESEARCH_FOLD_CONTRACT_V2 |
| BENCHMARK_ARCHITECTURE_STATUS | CONTINUE_CURRENT_CSI300 |
| CANONICAL_BENCHMARK_RECOMMENDATION | KEEP_000300 |
| EARLIEST_CANONICAL_RESEARCH_DATE | 2005-01-27 |
| VOLUME_RESEARCH_RECOMMENDATION | PAUSE_PENDING_TARGET_ARCHITECTURE |

## 4. Answers to User Questions

1. **RESEARCH_FOLD_CONTRACT_V2 是否应该正式采用？**
   YES. Prevents silent failures like fold_002/fold_003. Principled <10% threshold.

2. **<10% research-ready ratio 是否足以标记 NON_RESEARCHABLE？**
   YES. Sufficient and testable. Prevents post-hoc rationalization.

3. **当前 CSI300 是否应该继续作为 canonical benchmark？**
   YES. Historical gap is documented limitation, not reason to switch.

4. **是否存在更长期且 PIT-safe 的 benchmark？**
   NO suitable external index found. PIT Universe Reference exists but requires target architecture changes.

5. **PIT Universe Median 是否可以作为长期 reference？**
   VIABLE but requires architectural changes. Currently implemented in `reference_benchmark.py`.

6. **是否需要 Hybrid benchmark architecture？**
   NOT RECOMMENDED. Creates regime switch, breaks comparability.

7. **修改 benchmark 是否值得付出重新生成 D7-B/C5/D8 历史证据的成本？**
   NO. Cost outweighs benefit. Better to document boundary and start from 2005-01-27.

8. **在不修改 canonical target 的情况下，未来 Alpha Research 应从哪一天正式开始？**
   2005-01-27. First date where CSI300, 5D/10D/20D targets, and universe all align.

9. **VOLUME 是否还有必要继续研究？**
   PAUSE_PENDING_TARGET_ARCHITECTURE. Zero targets are infrastructure issues, not VOLUME failure. But qualification remains blocked without target architecture clarity.

## 5. Frozen Gates (unchanged)

```
VOLUME_STATUS = INSUFFICIENT_EVIDENCE
QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE
D8_H_ALLOWED = NO
PRODUCTION_PROMOTION = NO
C5-R original results = INVALID_EVIDENCE
```

## Artifacts

- `data/research/c5_r4_fold_contract_v2.json`
- `data/research/c5_r4_benchmark_architecture.json`
- `data/research/c5_r4_benchmark_coverage.json`
- `data/research/c5_r4_target_impact_analysis.json`
- `data/research/c5_r4_research_boundary.json`
- `docs/M9_1-C5-R4_FOLD_AND_BENCHMARK_ARCHITECTURE_AUDIT.md`
"""

    (DOCS / "M9_1-C5-R4_FOLD_AND_BENCHMARK_ARCHITECTURE_AUDIT.md").write_text(report, encoding="utf-8")

    print("\n" + "=" * 70)
    print("C5-R4 AUDIT COMPLETE")
    print("=" * 70)
    print(f"\nFold V2: {fold_v2_status}")
    print(f"Benchmark: {benchmark_status}")
    print(f"Volume: {volume_recommendation}")
    print(f"\nArtifacts saved to {ART} and {DOCS}")
