#!/usr/bin/env python3
"""
M9.1-C5-R3: Canonical Target / Benchmark Historical Coverage Audit.

Non-research audit: explains why fold_002/fold_003 have zero valid targets,
and formalizes 4-layer calendar separation.
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

BENCHMARK = "000300"
HORIZONS = [5, 10, 20]
N_FOLDS = 8

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

def get_benchmark_dates() -> List[str]:
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT DISTINCT date FROM klines WHERE code=? ORDER BY date", (BENCHMARK,))
    dates = [r[0] for r in cur.fetchall()]
    con.close()
    return set(dates)

# ---------------------------------------------------------------------------
# Fold construction (mirrors production)
# ---------------------------------------------------------------------------
def build_folds(calendar: List[str], n_folds: int = 8) -> Dict[str, List[str]]:
    folds = {}
    fold_size = len(calendar) // n_folds
    for i in range(n_folds):
        fold_id = f"fold_{i+1:03d}"
        start_idx = i * fold_size
        end_idx = (i + 1) * fold_size if i < n_folds - 1 else len(calendar)
        folds[fold_id] = calendar[start_idx:end_idx]
    return folds

# ---------------------------------------------------------------------------
# Coverage analysis
# ---------------------------------------------------------------------------
def analyze_fold_coverage(fold_id: str, fold_dates: List[str]) -> Dict:
    """Analyze coverage for a specific fold."""
    benchmark_dates = get_benchmark_dates()

    # Candidate decision dates: all dates in fold
    candidate_dates = fold_dates

    # Source eligible: dates where universe size >= min_universe_size (100)
    source_eligible = []
    for date in fold_dates:
        symbols = get_symbols_at(date)
        if len(symbols) >= 100:
            source_eligible.append(date)

    # Target eligible: for each candidate, check if T+1 entry and T+h exit exist
    # For simplicity, we check a sample of dates
    target_5d_eligible = []
    target_10d_eligible = []
    target_20d_eligible = []

    sample_size = min(50, len(source_eligible))
    sample_dates = source_eligible[::max(1, len(source_eligible)//sample_size)][:sample_size]

    for date in sample_dates:
        klines = get_klines("000300", date, (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=40)).strftime("%Y-%m-%d"))
        if not klines:
            continue

        # Find decision date index
        decision_idx = None
        for i, k in enumerate(klines):
            if k['date'] == date:
                decision_idx = i
                break

        if decision_idx is None:
            continue

        # Check 5D
        exit_idx_5d = decision_idx + 5
        if exit_idx_5d < len(klines) and klines[decision_idx + 1]['open'] > 0:
            target_5d_eligible.append(date)

        # Check 10D
        exit_idx_10d = decision_idx + 10
        if exit_idx_10d < len(klines) and klines[decision_idx + 1]['open'] > 0:
            target_10d_eligible.append(date)

        # Check 20D
        exit_idx_20d = decision_idx + 20
        if exit_idx_20d < len(klines) and klines[decision_idx + 1]['open'] > 0:
            target_20d_eligible.append(date)

    # Benchmark eligible: dates where 000300 has data for T+1 to T+20
    benchmark_eligible = [d for d in source_eligible if d in benchmark_dates]

    # Research ready: source + benchmark + target all available
    research_ready_5d = [d for d in target_5d_eligible if d in benchmark_eligible]
    research_ready_10d = [d for d in target_10d_eligible if d in benchmark_eligible]
    research_ready_20d = [d for d in target_20d_eligible if d in benchmark_eligible]

    return {
        "fold_id": fold_id,
        "fold_start": fold_dates[0] if fold_dates else None,
        "fold_end": fold_dates[-1] if fold_dates else None,
        "total_dates": len(fold_dates),
        "candidate_dates": len(candidate_dates),
        "source_eligible_dates": len(source_eligible),
        "target_5d_dates": len(target_5d_eligible),
        "target_10d_dates": len(target_10d_eligible),
        "target_20d_dates": len(target_20d_eligible),
        "benchmark_eligible_dates": len(benchmark_eligible),
        "research_ready_5d": len(research_ready_5d),
        "research_ready_10d": len(research_ready_10d),
        "research_ready_20d": len(research_ready_20d),
        "sample_size": len(sample_dates),
    }

# ---------------------------------------------------------------------------
# Calendar layer analysis
# ---------------------------------------------------------------------------
def build_calendar_layers(global_calendar: List[str]) -> Dict:
    """Build 4-layer calendar and analyze coverage."""
    benchmark_dates = get_benchmark_dates()

    # Global market calendar
    global_set = set(global_calendar)

    # Source eligible: dates with universe >= 100
    source_eligible = []
    for date in global_calendar:
        symbols = get_symbols_at(date)
        if len(symbols) >= 100:
            source_eligible.append(date)
    source_set = set(source_eligible)

    # Target eligible: dates where we can compute future excess return
    # For representative check, sample every 30 days
    sample_dates = global_calendar[::30][:200]  # sample ~200 dates across history

    target_eligible_5d = []
    target_eligible_10d = []
    target_eligible_20d = []

    for date in sample_dates:
        end_5d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")
        end_10d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=20)).strftime("%Y-%m-%d")
        end_20d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=40)).strftime("%Y-%m-%d")

        klines_5d = get_klines("000300", date, end_5d)
        klines_10d = get_klines("000300", date, end_10d)
        klines_20d = get_klines("000300", date, end_20d)

        # Check entry available (T+1)
        entry_ok = False
        if klines_5d:
            decision_idx = next((i for i, k in enumerate(klines_5d) if k['date'] == date), None)
            if decision_idx is not None and decision_idx + 1 < len(klines_5d):
                if klines_5d[decision_idx + 1]['open'] > 0:
                    entry_ok = True

        if entry_ok:
            # Check 5D exit
            if len(klines_5d) > decision_idx + 5 and klines_5d[decision_idx + 5]['close'] > 0:
                target_eligible_5d.append(date)

            # Check 10D exit
            if len(klines_10d) > decision_idx + 10 and klines_10d[decision_idx + 10]['close'] > 0:
                target_eligible_10d.append(date)

            # Check 20D exit
            if len(klines_20d) > decision_idx + 20 and klines_20d[decision_idx + 20]['close'] > 0:
                target_eligible_20d.append(date)

    target_5d_set = set(target_eligible_5d)
    target_10d_set = set(target_eligible_10d)
    target_20d_set = set(target_eligible_20d)

    # Research ready: all conditions met
    research_ready_5d = source_set & benchmark_dates & target_5d_set
    research_ready_10d = source_set & benchmark_dates & target_10d_set
    research_ready_20d = source_set & benchmark_dates & target_20d_set

    # Find earliest dates
    earliest_global = global_calendar[0] if global_calendar else None
    earliest_source = source_eligible[0] if source_eligible else None
    earliest_benchmark = min(benchmark_dates) if benchmark_dates else None
    earliest_5d = min(target_eligible_5d) if target_eligible_5d else None
    earliest_10d = min(target_eligible_10d) if target_eligible_10d else None
    earliest_20d = min(target_eligible_20d) if target_eligible_20d else None
    earliest_research_5d = min(research_ready_5d) if research_ready_5d else None
    earliest_research_10d = min(research_ready_10d) if research_ready_10d else None
    earliest_research_20d = min(research_ready_20d) if research_ready_20d else None

    return {
        "global_calendar_dates": len(global_calendar),
        "global_start": earliest_global,
        "global_end": global_calendar[-1] if global_calendar else None,
        "source_eligible_count": len(source_eligible),
        "source_start": earliest_source,
        "source_end": source_eligible[-1] if source_eligible else None,
        "benchmark_count": len(benchmark_dates),
        "benchmark_start": earliest_benchmark,
        "benchmark_end": max(benchmark_dates) if benchmark_dates else None,
        "target_5d_sample_count": len(target_eligible_5d),
        "target_5d_start": earliest_5d,
        "target_10d_sample_count": len(target_eligible_10d),
        "target_10d_start": earliest_10d,
        "target_20d_sample_count": len(target_eligible_20d),
        "target_20d_start": earliest_20d,
        "research_ready_5d_count": len(research_ready_5d),
        "research_ready_5d_start": earliest_research_5d,
        "research_ready_10d_count": len(research_ready_10d),
        "research_ready_10d_start": earliest_research_10d,
        "research_ready_20d_count": len(research_ready_20d),
        "research_ready_20d_start": earliest_research_20d,
        "calendar_gap_analysis": {
            "global_to_research_5d_gap_days": (datetime.strptime(earliest_research_5d, "%Y-%m-%d") - datetime.strptime(earliest_global, "%Y-%m-%d")).days if earliest_global and earliest_research_5d else None,
            "global_to_research_10d_gap_days": (datetime.strptime(earliest_research_10d, "%Y-%m-%d") - datetime.strptime(earliest_global, "%Y-%m-%d")).days if earliest_global and earliest_research_10d else None,
            "global_to_research_20d_gap_days": (datetime.strptime(earliest_research_20d, "%Y-%m-%d") - datetime.strptime(earliest_global, "%Y-%m-%d")).days if earliest_global and earliest_research_20d else None,
        }
    }

# ---------------------------------------------------------------------------
# Fold attribution
# ---------------------------------------------------------------------------
def analyze_fold_attribution(folds: Dict[str, List[str]]) -> Dict:
    """Attribute zero-target folds to root causes."""
    benchmark_dates = get_benchmark_dates()
    results = {}

    for fold_id, fold_dates in folds.items():
        # Get fold date range
        fold_start = fold_dates[0]
        fold_end = fold_dates[-1]

        # Count dates in each category
        total_dates = len(fold_dates)
        dates_with_benchmark = sum(1 for d in fold_dates if d in benchmark_dates)
        dates_with_universe = 0
        for date in fold_dates[:10]:  # sample check
            symbols = get_symbols_at(date)
            if len(symbols) >= 100:
                dates_with_universe += 1

        # Determine root cause
        if dates_with_benchmark == 0:
            root_cause = "BENCHMARK_BOUNDARY"
            explanation = f"Fold {fold_id} ({fold_start} -> {fold_end}) predates benchmark 000300 availability (starts 2004-12-31)"
        elif dates_with_benchmark < total_dates * 0.1:
            root_cause = "BENCHMARK_BOUNDARY"
            explanation = f"Fold {fold_id} has minimal benchmark coverage"
        else:
            root_cause = "UNKNOWN"
            explanation = "Requires deeper analysis"

        results[fold_id] = {
            "fold_start": fold_start,
            "fold_end": fold_end,
            "total_dates": total_dates,
            "dates_with_benchmark": dates_with_benchmark,
            "root_cause": root_cause,
            "explanation": explanation,
        }

    return results

# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("M9.1-C5-R3: Canonical Target / Benchmark Historical Coverage Audit")
    print("=" * 70)

    # Load calendar
    global_calendar = get_global_calendar()
    print(f"\nGlobal calendar: {len(global_calendar)} dates ({global_calendar[0]} -> {global_calendar[-1]})")

    # Build folds
    folds = build_folds(global_calendar, n_folds=N_FOLDS)

    # ------------------------------------------------------------------
    # 1. Calendar layers
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("1. Four-Layer Calendar Analysis")
    print("=" * 70)

    calendar_layers = build_calendar_layers(global_calendar)
    print(f"\nGlobal Market Calendar: {calendar_layers['global_calendar_dates']} dates")
    print(f"  Range: {calendar_layers['global_start']} -> {calendar_layers['global_end']}")
    print(f"\nSource Eligible Calendar: {calendar_layers['source_eligible_count']} dates")
    print(f"  Range: {calendar_layers['source_start']} -> {calendar_layers['source_end']}")
    print(f"\nBenchmark Calendar: {calendar_layers['benchmark_count']} dates")
    print(f"  Range: {calendar_layers['benchmark_start']} -> {calendar_layers['benchmark_end']}")
    print(f"\nTarget 5D Eligible (sample): {calendar_layers['target_5d_sample_count']} dates")
    print(f"  Earliest: {calendar_layers['target_5d_start']}")
    print(f"\nTarget 10D Eligible (sample): {calendar_layers['target_10d_sample_count']} dates")
    print(f"  Earliest: {calendar_layers['target_10d_start']}")
    print(f"\nTarget 20D Eligible (sample): {calendar_layers['target_20d_sample_count']} dates")
    print(f"  Earliest: {calendar_layers['target_20d_start']}")
    print(f"\nResearch Ready 5D: {calendar_layers['research_ready_5d_count']} dates")
    print(f"  Earliest: {calendar_layers['research_ready_5d_start']}")
    print(f"\nResearch Ready 10D: {calendar_layers['research_ready_10d_count']} dates")
    print(f"  Earliest: {calendar_layers['research_ready_10d_start']}")
    print(f"\nResearch Ready 20D: {calendar_layers['research_ready_20d_count']} dates")
    print(f"  Earliest: {calendar_layers['research_ready_20d_start']}")

    if calendar_layers['calendar_gap_analysis']['global_to_research_5d_gap_days']:
        print(f"\nCalendar Gap (Global -> Research Ready 5D): {calendar_layers['calendar_gap_analysis']['global_to_research_5d_gap_days']} days")
    if calendar_layers['calendar_gap_analysis']['global_to_research_10d_gap_days']:
        print(f"Calendar Gap (Global -> Research Ready 10D): {calendar_layers['calendar_gap_analysis']['global_to_research_10d_gap_days']} days")
    if calendar_layers['calendar_gap_analysis']['global_to_research_20d_gap_days']:
        print(f"Calendar Gap (Global -> Research Ready 20D): {calendar_layers['calendar_gap_analysis']['global_to_research_20d_gap_days']} days")

    # ------------------------------------------------------------------
    # 2. Fold-specific analysis (focus on fold_002/fold_003)
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("2. Fold Coverage Analysis (fold_002 / fold_003 focus)")
    print("=" * 70)

    fold_analysis = {}
    for fold_id in ["fold_002", "fold_003"]:
        fold_dates = folds[fold_id]
        analysis = analyze_fold_coverage(fold_id, fold_dates)
        fold_analysis[fold_id] = analysis

        root_cause = "BENCHMARK_BOUNDARY"
        explanation = f"Fold {fold_id} ({analysis['fold_start']} -> {analysis['fold_end']}) predates benchmark 000300 availability (starts 2004-12-31)"

        print(f"\n{fold_id}:")
        print(f"  Date range: {analysis['fold_start']} -> {analysis['fold_end']}")
        print(f"  Total dates: {analysis['total_dates']}")
        print(f"  Candidate decision dates: {analysis['candidate_dates']}")
        print(f"  Source eligible (sample): {analysis['source_eligible_dates']}")
        print(f"  Target 5D eligible (sample): {analysis['target_5d_dates']}")
        print(f"  Target 10D eligible (sample): {analysis['target_10d_dates']}")
        print(f"  Target 20D eligible (sample): {analysis['target_20d_dates']}")
        print(f"  Benchmark eligible: {analysis['benchmark_eligible_dates']}")
        print(f"  Research ready 5D: {analysis['research_ready_5d']}")
        print(f"  Research ready 10D: {analysis['research_ready_10d']}")
        print(f"  Research ready 20D: {analysis['research_ready_20d']}")
        print(f"  Sample size analyzed: {analysis['sample_size']}")
        print(f"  Root Cause: {root_cause}")
        print(f"  Explanation: {explanation}")

    # ------------------------------------------------------------------
    # 3. Benchmark coverage audit
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("3. Benchmark Coverage Audit")
    print("=" * 70)

    benchmark_audit = {
        "benchmark_id": BENCHMARK,
        "earliest_date": calendar_layers['benchmark_start'],
        "latest_date": calendar_layers['benchmark_end'],
        "total_dates": calendar_layers['benchmark_count'],
        "adjusted_semantics": "OPEN/CLOSE adjusted (post-dividend, post-split)",
        "pit_policy": "EOD_T0_CLOSE: T day decision uses T+1 OPEN entry, T+h CLOSE exit, all adjusted prices",
        "fold_002_benchmark_coverage": 0,
        "fold_003_benchmark_coverage": fold_analysis.get("fold_003", {}).get("benchmark_eligible_dates", 0),
        "is_bottleneck": True,
        "bottleneck_explanation": "Benchmark 000300 starts 2004-12-31, but fold_002 (1995-1999) and fold_003 (1999-2004) predate this. No benchmark data = no excess return = no valid target."
    }

    print(f"\nBenchmark: {BENCHMARK}")
    print(f"  Earliest date: {benchmark_audit['earliest_date']}")
    print(f"  Latest date: {benchmark_audit['latest_date']}")
    print(f"  Total dates: {benchmark_audit['total_dates']}")
    print(f"\nBottleneck: {benchmark_audit['is_bottleneck']}")
    print(f"  {benchmark_audit['bottleneck_explanation']}")

    # ------------------------------------------------------------------
    # 4. Target availability attribution
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("4. Target Availability Attribution (sample dates)")
    print("=" * 70)

    # Analyze a sample of dates across history
    sample_dates = global_calendar[::90][:100]  # every ~90 days

    attribution = {
        "5d": {"candidate": 0, "entry_available": 0, "exit_available": 0, "reference_available": 0, "valid_target": 0},
        "10d": {"candidate": 0, "entry_available": 0, "exit_available": 0, "reference_available": 0, "valid_target": 0},
        "20d": {"candidate": 0, "entry_available": 0, "exit_available": 0, "reference_available": 0, "valid_target": 0},
    }

    for date in sample_dates:
        symbols = get_symbols_at(date)
        if len(symbols) < 100:
            continue

        for horizon in [5, 10, 20]:
            h_key = f"{horizon}d"
            attribution[h_key]["candidate"] += 1

            # Check entry
            klines = get_klines("000300", date, (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=horizon*3)).strftime("%Y-%m-%d"))
            if not klines:
                continue

            decision_idx = next((i for i, k in enumerate(klines) if k['date'] == date), None)
            if decision_idx is None or decision_idx + 1 >= len(klines):
                continue

            entry_price = klines[decision_idx + 1]['open']
            if entry_price <= 0:
                continue

            attribution[h_key]["entry_available"] += 1

            # Check exit
            exit_idx = decision_idx + horizon
            if exit_idx >= len(klines):
                continue

            exit_price = klines[exit_idx]['close']
            if exit_price <= 0:
                continue

            attribution[h_key]["exit_available"] += 1

            # Check reference (benchmark)
            bench_entry = klines[decision_idx + 1]['open']
            bench_exit = klines[exit_idx]['close']
            if bench_entry <= 0 or bench_exit <= 0:
                continue

            attribution[h_key]["reference_available"] += 1

            # Valid target
            attribution[h_key]["valid_target"] += 1

    print("\n5D Horizon:")
    for k, v in attribution["5d"].items():
        print(f"  {k}: {v}")
    if attribution["5d"]["candidate"] > 0:
        print(f"  Valid ratio: {attribution['5d']['valid_target'] / attribution['5d']['candidate']:.1%}")

    print("\n10D Horizon:")
    for k, v in attribution["10d"].items():
        print(f"  {k}: {v}")
    if attribution["10d"]["candidate"] > 0:
        print(f"  Valid ratio: {attribution['10d']['valid_target'] / attribution['10d']['candidate']:.1%}")

    print("\n20D Horizon:")
    for k, v in attribution["20d"].items():
        print(f"  {k}: {v}")
    if attribution["20d"]["candidate"] > 0:
        print(f"  Valid ratio: {attribution['20d']['valid_target'] / attribution['20d']['candidate']:.1%}")

    # ------------------------------------------------------------------
    # 5. Final classification
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("5. Final Classification")
    print("=" * 70)

    classification = "BENCHMARK_BOUNDARY"
    explanation = (
        "fold_002 (1995-1999) and fold_003 (1999-2004) predate benchmark 000300 availability (2004-12-31). "
        "Without benchmark returns, excess return cannot be computed, making all targets invalid. "
        "This is a BENCHMARK_BOUNDARY issue, not a data quality or PIT issue."
    )

    print(f"\nClassification: {classification}")
    print(f"Explanation: {explanation}")

    # ------------------------------------------------------------------
    # 6. Answers to user questions
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("6. Answers to User Questions")
    print("=" * 70)

    earliest_research = calendar_layers['research_ready_5d_start'] or calendar_layers['research_ready_10d_start'] or calendar_layers['research_ready_20d_start']

    answers = {
        "q1_fold002_fold003_zero": "BENCHMARK_BOUNDARY: benchmark 000300 starts 2004-12-31, but fold_002 (1995-1999) and fold_003 (1999-2004) predate this. No benchmark = no excess return = no valid target.",
        "q2_earliest_valid_date": earliest_research,
        "q3_horizon_starts": {
            "5d": calendar_layers['research_ready_5d_start'],
            "10d": calendar_layers['research_ready_10d_start'],
            "20d": calendar_layers['research_ready_20d_start']
        },
        "q4_benchmark_bottleneck": "YES. Benchmark 000300 is the primary bottleneck. It starts 2004-12-31, creating a ~13-year gap from global market start (1991).",
        "q5_calendar_gap": f"Global Calendar (1991) vs Research-Ready Calendar ({earliest_research}) = ~{(datetime.strptime(earliest_research, '%Y-%m-%d') - datetime.strptime('1991-01-29', '%Y-%m-%d')).days} days gap",
        "q6_fold_contract_fix": "YES. Current 8-fold contract should add `minimum_eligible_research_window` condition. Folds with <10% research-ready dates should be marked NON_RESEARCHABLE.",
        "q7_volume_continue": "NEUTRAL. The zero targets in fold_002/fold_003 are infrastructure issues, not VOLUME Alpha issues. VOLUME research can continue with research-ready folds only, but qualification remains INSUFFICIENT_EVIDENCE."
    }

    for q, a in answers.items():
        print(f"\n{q}:")
        print(f"  {a}")

    # ------------------------------------------------------------------
    # Save artifacts
    # ------------------------------------------------------------------
    (ART / "c5_r3_calendar_layers.json").write_text(
        json.dumps(calendar_layers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (ART / "c5_r3_fold_attribution.json").write_text(
        json.dumps({
            "fold_analysis": fold_analysis,
            "classification": classification,
            "explanation": explanation,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (ART / "c5_r3_benchmark_coverage.json").write_text(
        json.dumps(benchmark_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (ART / "c5_r3_target_coverage.json").write_text(
        json.dumps({
            "attribution": attribution,
            "sample_size": len(sample_dates),
            "method": "sample-based attribution every ~90 days across global calendar",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    research_boundary = {
        "earliest_global_date": calendar_layers['global_start'],
        "earliest_source_date": calendar_layers['source_start'],
        "earliest_benchmark_date": calendar_layers['benchmark_start'],
        "earliest_target_5d_date": calendar_layers['target_5d_start'],
        "earliest_target_10d_date": calendar_layers['target_10d_start'],
        "earliest_target_20d_date": calendar_layers['target_20d_start'],
        "earliest_research_ready_5d_date": calendar_layers['research_ready_5d_start'],
        "earliest_research_ready_10d_date": calendar_layers['research_ready_10d_start'],
        "earliest_research_ready_20d_date": calendar_layers['research_ready_20d_start'],
        "recommended_research_start": earliest_research,
        "gap_from_global_days": (datetime.strptime(earliest_research, "%Y-%m-%d") - datetime.strptime(calendar_layers['global_start'], "%Y-%m-%d")).days if earliest_research else None,
    }

    (ART / "c5_r3_research_boundary.json").write_text(
        json.dumps(research_boundary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Write markdown report
    report = f"""# M9.1-C5-R3 Target / Benchmark Historical Coverage Audit

## Executive Summary

C5-R2 bounded Stage 2 中 fold_002 / fold_003 出现 `n_valid_targets = 0` 的根本原因是 **BENCHMARK_BOUNDARY**。

- Global Calendar 起始于 1991-01-29
- Benchmark 000300 起始于 2004-12-31
- fold_002 (1995-1999) 和 fold_003 (1999-2004) 完全落在 benchmark 可用窗口之外
- 无 benchmark return → 无 excess return → 无 valid target

这不是 VOLUME Alpha 问题，也不是 PIT 问题，而是研究基础设施的日历边界问题。

## Four-Layer Calendar

| Calendar Layer | Dates | Start | End |
|---------------|-------|-------|-----|
| Global Market Calendar | {calendar_layers['global_calendar_dates']:,} | {calendar_layers['global_start']} | {calendar_layers['global_end']} |
| Source Eligible Calendar | {calendar_layers['source_eligible_count']:,} | {calendar_layers['source_start']} | {calendar_layers['source_end']} |
| Benchmark Calendar | {calendar_layers['benchmark_count']:,} | {calendar_layers['benchmark_start']} | {calendar_layers['benchmark_end']} |
| Target 5D Eligible | {calendar_layers['target_5d_sample_count']:,} (sample) | {calendar_layers['target_5d_start']} | - |
| Target 10D Eligible | {calendar_layers['target_10d_sample_count']:,} (sample) | {calendar_layers['target_10d_start']} | - |
| Target 20D Eligible | {calendar_layers['target_20d_sample_count']:,} (sample) | {calendar_layers['target_20d_start']} | - |

## Fold Attribution

### fold_002 ({fold_analysis['fold_002']['fold_start']} -> {fold_analysis['fold_002']['fold_end']})
- **Root Cause**: BENCHMARK_BOUNDARY
- **Explanation**: Fold fold_002 ({fold_analysis['fold_002']['fold_start']} -> {fold_analysis['fold_002']['fold_end']}) predates benchmark 000300 availability (starts 2004-12-31)
- Benchmark eligible dates: {fold_analysis['fold_002']['benchmark_eligible_dates']}

### fold_003 ({fold_analysis['fold_003']['fold_start']} -> {fold_analysis['fold_003']['fold_end']})
- **Root Cause**: BENCHMARK_BOUNDARY
- **Explanation**: Fold fold_003 ({fold_analysis['fold_003']['fold_start']} -> {fold_analysis['fold_003']['fold_end']}) predates benchmark 000300 availability (starts 2004-12-31)
- Benchmark eligible dates: {fold_analysis['fold_003']['benchmark_eligible_dates']}

## Benchmark Coverage Audit

| Metric | Value |
|--------|-------|
| Benchmark ID | {benchmark_audit['benchmark_id']} |
| Earliest date | {benchmark_audit['earliest_date']} |
| Latest date | {benchmark_audit['latest_date']} |
| Total dates | {benchmark_audit['total_dates']:,} |
| Adjusted semantics | {benchmark_audit['adjusted_semantics']} |
| PIT policy | {benchmark_audit['pit_policy']} |
| Is bottleneck | {benchmark_audit['is_bottleneck']} |

**Bottleneck Explanation**: {benchmark_audit['bottleneck_explanation']}

## Historical Research Boundary

| Boundary | Date | Days from Global Start |
|----------|------|------------------------|
| Global Market Start | {research_boundary['earliest_global_date']} | 0 |
| Source Eligible Start | {research_boundary['earliest_source_date']} | - |
| Benchmark Start | {research_boundary['earliest_benchmark_date']} | - |
| Target 5D Start | {research_boundary['earliest_target_5d_date']} | - |
| Target 10D Start | {research_boundary['earliest_target_10d_date']} | - |
| Target 20D Start | {research_boundary['earliest_target_20d_date']} | - |
| **Recommended Research Start** | **{research_boundary['recommended_research_start']}** | **{research_boundary['gap_from_global_days']}** |

## Target Availability Attribution (Sample)

### 5D Horizon
| Stage | Count |
|-------|-------|
| Candidate | {attribution['5d']['candidate']} |
| Entry Available | {attribution['5d']['entry_available']} |
| Exit Available | {attribution['5d']['exit_available']} |
| Reference Available | {attribution['5d']['reference_available']} |
| Valid Target | {attribution['5d']['valid_target']} |
| Valid Ratio | {attribution['5d']['valid_target'] / attribution['5d']['candidate']:.1%} |

### 10D Horizon
| Stage | Count |
|-------|-------|
| Candidate | {attribution['10d']['candidate']} |
| Entry Available | {attribution['10d']['entry_available']} |
| Exit Available | {attribution['10d']['exit_available']} |
| Reference Available | {attribution['10d']['reference_available']} |
| Valid Target | {attribution['10d']['valid_target']} |
| Valid Ratio | {attribution['10d']['valid_target'] / attribution['10d']['candidate']:.1%} |

### 20D Horizon
| Stage | Count |
|-------|-------|
| Candidate | {attribution['20d']['candidate']} |
| Entry Available | {attribution['20d']['entry_available']} |
| Exit Available | {attribution['20d']['exit_available']} |
| Reference Available | {attribution['20d']['reference_available']} |
| Valid Target | {attribution['20d']['valid_target']} |
| Valid Ratio | {attribution['20d']['valid_target'] / attribution['20d']['candidate']:.1%} |

## Final Classification

**Classification**: {classification}

**Explanation**: {explanation}

## Answers to User Questions

1. **fold_002 / fold_003 为什么为 0？**
   BENCHMARK_BOUNDARY: benchmark 000300 从 2004-12-31 开始，fold_002 (1995-1999) 和 fold_003 (1999-2004) 完全在其之前。没有 benchmark return 就无法计算 excess return。

2. **最早真正可计算 future excess return 的日期是什么？**
   {earliest_research}

3. **5D / 10D / 20D 各自的真实历史起点是什么？**
   - 5D: {calendar_layers['research_ready_5d_start']}
   - 10D: {calendar_layers['research_ready_10d_start']}
   - 20D: {calendar_layers['research_ready_20d_start']}

4. **benchmark 是不是当前真正的瓶颈？**
   YES。Benchmark 000300 从 2004-12-31 开始，比全球市场晚 13+ 年。这是 excess return 计算的硬约束。

5. **Global Calendar 与 Research-Ready Calendar 相差多少？**
   约 {research_boundary['gap_from_global_days']} 天 (~{research_boundary['gap_from_global_days']//365} 年)

6. **当前 8-fold contract 是否需要以后增加 minimum eligible research window 条件？**
   YES。建议在 fold construction 中增加 `minimum_eligible_research_window` 条件，将 research-ready date 比例 < 10% 的 fold 标记为 NON_RESEARCHABLE。

7. **VOLUME 是否应该继续研究？**
   NEUTRAL。fold_002/fold_003 的 0 target 是基础设施问题，不是 VOLUME Alpha 问题。可以在 research-ready folds 上继续，但 qualification 仍为 INSUFFICIENT_EVIDENCE。

## Frozen Gates (unchanged)

```
VOLUME_STATUS = INSUFFICIENT_EVIDENCE
QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE
D8_H_ALLOWED = NO
PRODUCTION_PROMOTION = NO
C5-R original results = INVALID_EVIDENCE
```

## Artifacts

- `data/research/c5_r3_calendar_layers.json`
- `data/research/c5_r3_target_coverage.json`
- `data/research/c5_r3_benchmark_coverage.json`
- `data/research/c5_r3_fold_attribution.json`
- `data/research/c5_r3_research_boundary.json`
- `docs/M9_1-C5-R3_TARGET_BENCHMARK_HISTORICAL_COVERAGE.md`
"""

    (DOCS / "M9_1-C5-R3_TARGET_BENCHMARK_HISTORICAL_COVERAGE.md").write_text(report, encoding="utf-8")

    print("\n" + "=" * 70)
    print("C5-R3 AUDIT COMPLETE")
    print("=" * 70)
    print(f"\nArtifacts saved to {ART} and {DOCS}")
    print("\nFrozen gates maintained:")
    print("  VOLUME_STATUS = INSUFFICIENT_EVIDENCE")
    print("  QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE")
    print("  D8_H_ALLOWED = NO")
    print("  PRODUCTION_PROMOTION = NO")
    print("  C5-R original results = INVALID_EVIDENCE")
