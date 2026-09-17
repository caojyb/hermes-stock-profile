#!/usr/bin/env python3
"""
c5_r1_canonical_target_forensic_audit.py — M9.1-C5-R1 Canonical Target / Economic Pipeline Forensic Audit.

Compares C5-R target computation with canonical target engine to identify root cause
of economic anomalies.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# ---------------------------------------------------------------------------
# Paths / safety
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data" / "research"
DOCS = BASE / "docs"
DB_PATH = BASE / "data" / "production" / "market_cache.db"

for d in (ART, DOCS):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Frozen gates
# ---------------------------------------------------------------------------
FROZEN_GATES = {
    "QUALIFICATION_STATUS": "INSUFFICIENT_EVIDENCE",
    "D8_H_ALLOWED": False,
    "PRODUCTION_PROMOTION": False,
    "FUNDAMENTAL_ROLE": "OPTIONAL_EVIDENCE",
    "OPPORTUNITY_VALIDATION_STATUS": "UNSTABLE",
    "REGIME_AWARE_OPPORTUNITY_STATUS": "NO_IMPROVEMENT",
    "NO_NEXT_ALPHA_SOURCE_READY": True,
    "C5_R_EVIDENCE_STATUS": "INVALID_PENDING_PIPELINE_AUDIT",
}

# ---------------------------------------------------------------------------
# Golden cases
# ---------------------------------------------------------------------------
GOLDEN_CASES = [
    # Early dates
    {"decision_time": "2005-01-04", "horizon": 5, "symbol": "000001"},
    {"decision_time": "2005-01-04", "horizon": 10, "symbol": "000001"},
    {"decision_time": "2005-01-04", "horizon": 20, "symbol": "000001"},
    {"decision_time": "2006-01-04", "horizon": 5, "symbol": "600000"},
    {"decision_time": "2006-01-04", "horizon": 10, "symbol": "600000"},
    {"decision_time": "2006-01-04", "horizon": 20, "symbol": "600000"},
    # Middle dates
    {"decision_time": "2015-01-05", "horizon": 5, "symbol": "000002"},
    {"decision_time": "2015-01-05", "horizon": 10, "symbol": "000002"},
    {"decision_time": "2015-01-05", "horizon": 20, "symbol": "000002"},
    # Late dates
    {"decision_time": "2024-01-02", "horizon": 5, "symbol": "600036"},
    {"decision_time": "2024-01-02", "horizon": 10, "symbol": "600036"},
    {"decision_time": "2024-01-02", "horizon": 20, "symbol": "600036"},
    # Edge cases
    {"decision_time": "2025-03-13", "horizon": 5, "symbol": "000001"},
    {"decision_time": "2025-03-13", "horizon": 10, "symbol": "000001"},
    {"decision_time": "2025-03-13", "horizon": 20, "symbol": "000001"},
]

# ---------------------------------------------------------------------------
# Canonical target computation (from target_engine.py)
# ---------------------------------------------------------------------------
HORIZONS = [5, 10, 20]

def get_klines(symbol: str, start: str, end: str):
    con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT date, open, close, high, low, volume FROM klines "
        "WHERE code=? AND date>=? AND date<=? ORDER BY date",
        (symbol, start, end),
    )
    rows = [dict(zip(['date','open','close','high','low','volume'], r)) for r in cur.fetchall()]
    con.close()
    return rows


def compute_canonical_target(symbol: str, decision_time: str, horizon: int):
    """Canonical target computation matching target_engine.py semantics."""
    start = (datetime.strptime(decision_time, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    end = (datetime.strptime(decision_time, "%Y-%m-%d") + timedelta(days=horizon*2)).strftime("%Y-%m-%d")
    klines = get_klines(symbol, start, end)
    
    if not klines:
        return None
    
    # Find decision_time index
    decision_idx = None
    for i, k in enumerate(klines):
        if k['date'] == decision_time:
            decision_idx = i
            break
    
    if decision_idx is None or decision_idx + 1 >= len(klines):
        return None
    
    # Entry: T+1 open
    entry_idx = decision_idx + 1
    entry_price = klines[entry_idx]['open']
    entry_date = klines[entry_idx]['date']
    
    # Exit: T+horizon close
    exit_idx = decision_idx + horizon
    if exit_idx >= len(klines):
        return None
    
    exit_price = klines[exit_idx]['close']
    exit_date = klines[exit_idx]['date']
    
    if entry_price <= 0 or exit_price <= 0:
        return None
    
    stock_return = exit_price / entry_price - 1.0
    
    # Benchmark: 000300
    bench_klines = get_klines("000300", start, end)
    if not bench_klines:
        return None
    
    bench_decision_idx = None
    for i, k in enumerate(bench_klines):
        if k['date'] == decision_time:
            bench_decision_idx = i
            break
    
    if bench_decision_idx is None or bench_decision_idx + 1 >= len(bench_klines):
        return None
    
    bench_entry_idx = bench_decision_idx + 1
    bench_exit_idx = bench_decision_idx + horizon
    
    if bench_exit_idx >= len(bench_klines):
        return None
    
    bench_entry = bench_klines[bench_entry_idx]['open']
    bench_exit = bench_klines[bench_exit_idx]['close']
    
    if bench_entry <= 0 or bench_exit <= 0:
        return None
    
    benchmark_return = bench_exit / bench_entry - 1.0
    excess_return = stock_return - benchmark_return
    
    return {
        "decision_date": decision_time,
        "code": symbol,
        "horizon": horizon,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "stock_return": stock_return,
        "benchmark_id": "000300",
        "benchmark_date": decision_time,
        "benchmark_entry_date": bench_klines[bench_entry_idx]['date'],
        "benchmark_exit_date": bench_klines[bench_exit_idx]['date'],
        "benchmark_entry_price": bench_entry,
        "benchmark_exit_price": bench_exit,
        "benchmark_return": benchmark_return,
        "excess_return": excess_return,
    }


# ---------------------------------------------------------------------------
# C5-R target computation (as implemented in c5_r_volume_independent_alpha.py)
# ---------------------------------------------------------------------------
def compute_c5r_target(symbol: str, decision_time: str, horizon: int):
    """C5-R target computation (potentially buggy)."""
    start = (datetime.strptime(decision_time, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    end = (datetime.strptime(decision_time, "%Y-%m-%d") + timedelta(days=horizon*2)).strftime("%Y-%m-%d")
    
    symbol_klines = get_klines(symbol, start, end)
    bench_klines = get_klines("000300", start, end)
    
    if not symbol_klines or not bench_klines:
        return None
    
    # Find entry/exit indices
    entry_idx = None
    for i, k in enumerate(symbol_klines):
        if k['date'] == decision_time:
            entry_idx = i + 1
            break
    
    if entry_idx is None or entry_idx >= len(symbol_klines):
        return None
    
    exit_idx = entry_idx + horizon - 1
    if exit_idx >= len(symbol_klines):
        return None
    
    entry_price = symbol_klines[entry_idx]['open']
    exit_price = symbol_klines[exit_idx]['close']
    stock_return = (exit_price - entry_price) / max(1e-9, entry_price)
    
    # Benchmark
    bench_entry_idx = None
    for i, k in enumerate(bench_klines):
        if k['date'] == decision_time:
            bench_entry_idx = i + 1
            break
    
    if bench_entry_idx is None or bench_entry_idx >= len(bench_klines):
        return None
    
    bench_exit_idx = bench_entry_idx + horizon - 1
    if bench_exit_idx >= len(bench_klines):
        return None
    
    bench_entry = bench_klines[bench_entry_idx]['open']
    bench_exit = bench_klines[bench_exit_idx]['close']
    bench_return = (bench_exit - bench_entry) / max(1e-9, bench_entry)
    
    excess_return = stock_return - bench_return
    
    return {
        "decision_date": decision_time,
        "code": symbol,
        "horizon": horizon,
        "entry_date": symbol_klines[entry_idx]['date'],
        "entry_price": entry_price,
        "exit_date": symbol_klines[exit_idx]['date'],
        "exit_price": exit_price,
        "stock_return": stock_return,
        "benchmark_id": "000300",
        "benchmark_date": decision_time,
        "benchmark_entry_date": bench_klines[bench_entry_idx]['date'],
        "benchmark_exit_date": bench_klines[bench_exit_idx]['date'],
        "benchmark_entry_price": bench_entry,
        "benchmark_exit_price": bench_exit,
        "benchmark_return": bench_return,
        "excess_return": excess_return,
    }


# ---------------------------------------------------------------------------
# Run golden cases
# ---------------------------------------------------------------------------
print("Running golden case comparison...")
golden_results = []

for case in GOLDEN_CASES:
    canonical = compute_canonical_target(case["symbol"], case["decision_time"], case["horizon"])
    c5r = compute_c5r_target(case["symbol"], case["decision_time"], case["horizon"])
    
    result = {
        "case": case,
        "canonical": canonical,
        "c5r": c5r,
        "diff": {},
        "root_cause": None,
    }
    
    if canonical and c5r:
        # Compare fields
        result["diff"] = {
            "entry_price_diff_pct": (canonical["entry_price"] - c5r["entry_price"]) / max(1e-9, canonical["entry_price"]) * 100,
            "exit_price_diff_pct": (canonical["exit_price"] - c5r["exit_price"]) / max(1e-9, canonical["exit_price"]) * 100,
            "stock_return_diff": canonical["stock_return"] - c5r["stock_return"],
            "benchmark_return_diff": canonical["benchmark_return"] - c5r["benchmark_return"],
            "excess_return_diff": canonical["excess_return"] - c5r["excess_return"],
            "entry_date_match": canonical["entry_date"] == c5r["entry_date"],
            "exit_date_match": canonical["exit_date"] == c5r["exit_date"],
        }
        
        # Root cause analysis
        if abs(result["diff"]["stock_return_diff"]) > 0.01:
            result["root_cause"] = "STOCK_RETURN_MISMATCH"
        elif abs(result["diff"]["benchmark_return_diff"]) > 0.01:
            result["root_cause"] = "BENCHMARK_RETURN_MISMATCH"
        elif abs(result["diff"]["excess_return_diff"]) > 0.01:
            result["root_cause"] = "EXCESS_RETURN_MISMATCH"
        else:
            result["root_cause"] = "MATCH"
    elif canonical and not c5r:
        result["root_cause"] = "C5R_TARGET_MISSING"
    elif not canonical and c5r:
        result["root_cause"] = "CANONICAL_TARGET_MISSING"
    else:
        result["root_cause"] = "BOTH_MISSING"
    
    golden_results.append(result)

# ---------------------------------------------------------------------------
# Analyze C5-R full matrix for anomalies
# ---------------------------------------------------------------------------
full_matrix = json.loads((ART / "c5_r_volume_full_matrix.json").read_text())

# Find experiments with extreme excess returns
extreme_cases = [r for r in full_matrix if abs(r["mean_excess_return"]) > 1.0]
print(f"Extreme cases (|excess| > 1.0): {len(extreme_cases)}")

# Sample a few
sample_extreme = extreme_cases[:5]
for r in sample_extreme:
    print(f"  {r['decision_time']} {r['variant']} h={r['horizon']}: excess={r['mean_excess_return']:.4f}, n={r['n_valid_targets']}")

# Check if extreme values correlate with specific dates/horizons
from collections import Counter
extreme_by_date = Counter(r["decision_time"] for r in extreme_cases)
extreme_by_horizon = Counter(r["horizon"] for r in extreme_cases)
print(f"Extreme by horizon: {dict(extreme_by_horizon)}")

# ---------------------------------------------------------------------------
# Experiment protocol audit
# ---------------------------------------------------------------------------
print("\nExperiment protocol audit...")

# Load VOLUME_SPEC from artifact if available
vol_spec_path = ART / "c5_r_volume_research_spec.json"
if vol_spec_path.exists():
    vol_spec = json.loads(vol_spec_path.read_text())
    registered_variants = set()
    for family in vol_spec.get("families", {}).values():
        for vid in family.keys():
            registered_variants.add(vid)
else:
    registered_variants = set()

actual_variants = set(r["variant"] for r in full_matrix)
actual_horizons = set(r["horizon"] for r in full_matrix)
actual_folds = set(r["fold_id"] for r in full_matrix)

print(f"Registered variants: {sorted(registered_variants)}")
print(f"Actual variants: {sorted(actual_variants)}")
print(f"Actual horizons: {sorted(actual_horizons)}")
print(f"Actual folds: {sorted(actual_folds)}")
print(f"Registered experiments: 192")
print(f"Actual experiments: {len(full_matrix)}")
print(f"Unregistered variants: {sorted(actual_variants - registered_variants)}")
print(f"Duplicate experiments: {len(full_matrix) - 192}")

# Check for duplicate fold/date/horizon/variant combinations
from collections import Counter
combo_counts = Counter((r["fold_id"], r["decision_time"], r["horizon"], r["variant"]) for r in full_matrix)
duplicates = {k: v for k, v in combo_counts.items() if v > 1}
print(f"Duplicate combinations: {len(duplicates)}")

# ---------------------------------------------------------------------------
# Save artifacts
# ---------------------------------------------------------------------------
(ART / "c5_r1_golden_cases.json").write_text(
    json.dumps(golden_results, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

(ART / "c5_r1_economic_sanity.json").write_text(
    json.dumps({
        "total_experiments": len(full_matrix),
        "extreme_cases_count": len(extreme_cases),
        "extreme_threshold": 1.0,
        "sample_extreme": sample_extreme,
        "extreme_by_horizon": dict(extreme_by_horizon),
        "extreme_by_date": dict(extreme_by_date),
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

protocol_audit = {
    "registered_variants": sorted(registered_variants),
    "actual_variants": sorted(actual_variants),
    "registered_experiment_count": 192,
    "actual_experiment_count": len(full_matrix),
    "unregistered_variants": sorted(actual_variants - registered_variants),
    "duplicate_experiment_count": len(full_matrix) - 192,
    "audit_pass": len(full_matrix) == 192,
}

(ART / "c5_r1_experiment_protocol_audit.json").write_text(
    json.dumps(protocol_audit, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

# ---------------------------------------------------------------------------
# Generate report
# ---------------------------------------------------------------------------
report_lines = [
    "# M9.1-C5-R1 Canonical Target / Economic Pipeline Forensic Audit",
    "",
    f"- Evaluation timestamp: {datetime.utcnow().isoformat()}Z",
    f"- Golden cases tested: {len(golden_results)}",
    f"- Total experiments audited: {len(full_matrix)}",
    "",
    "## Frozen Gates",
    f"- QUALIFICATION_STATUS = {FROZEN_GATES['QUALIFICATION_STATUS']}",
    f"- D8_H_ALLOWED = {FROZEN_GATES['D8_H_ALLOWED']}",
    f"- PRODUCTION_PROMOTION = {FROZEN_GATES['PRODUCTION_PROMOTION']}",
    f"- C5_R_EVIDENCE_STATUS = {FROZEN_GATES['C5_R_EVIDENCE_STATUS']}",
    "",
    "## Golden Case Results",
]

match_count = 0
mismatch_count = 0
for g in golden_results:
    status = "✓ MATCH" if g["root_cause"] == "MATCH" else f"✗ {g['root_cause']}"
    report_lines.append(f"- {g['case']['decision_time']} {g['case']['symbol']} h={g['case']['horizon']}: {status}")
    if g["root_cause"] == "MATCH":
        match_count += 1
    else:
        mismatch_count += 1

report_lines.extend([
    "",
    "## Economic Sanity",
    f"- Total experiments: {len(full_matrix)}",
    f"- Extreme cases (|excess| > 1.0): {len(extreme_cases)}",
    f"- Sample extreme: {sample_extreme[0]['mean_excess_return']:.4f}" if sample_extreme else "None",
    "",
    "## Experiment Protocol Audit",
    f"- Registered variants: {sorted(registered_variants)}",
    f"- Actual variants: {sorted(actual_variants)}",
    f"- Registered count: 192",
    f"- Actual count: {len(full_matrix)}",
    f"- Audit pass: {len(full_matrix) == 192}",
    "",
    "## Root Cause Hypothesis",
])

if extreme_cases:
    # Check if extreme values are due to missing benchmark
    report_lines.append("- Extreme excess returns detected.")
    report_lines.append("- Likely causes:")
    report_lines.append("  1. Benchmark 000300 missing for early dates")
    report_lines.append("  2. Target computation using wrong horizon indexing")
    report_lines.append("  3. Signal normalization contaminating economic outcome")
    report_lines.append("  4. Price alignment or unit conversion error")
else:
    report_lines.append("- No extreme cases found.")

report_lines.extend([
    "",
    "## Next Steps",
    "- Fix identified bugs in C5-R target adapter",
    "- Re-run Stage 1 with fixed pipeline",
    "- Validate economic sanity before Stage 2",
    "",
    "## Gates (unchanged)",
    "- D8_H_ALLOWED = NO",
    "- PRODUCTION_PROMOTION = NO",
    "",
    "## Artifacts",
    "- `data/research/c5_r1_golden_cases.json`",
    "- `data/research/c5_r1_economic_sanity.json`",
    "- `data/research/c5_r1_experiment_protocol_audit.json`",
    "- `docs/M9_1-C5-R1_CANONICAL_TARGET_FORENSIC_AUDIT.md`",
])

(DOCS / "M9_1-C5-R1_CANONICAL_TARGET_FORENSIC_AUDIT.md").write_text(
    "\n".join(report_lines),
    encoding="utf-8",
)

print(f"\nC5-R1 complete.")
print(f"Golden cases: {match_count} match, {mismatch_count} mismatch")
print(f"Extreme cases: {len(extreme_cases)}")
print(f"Artifacts in {ART} and {DOCS}")
