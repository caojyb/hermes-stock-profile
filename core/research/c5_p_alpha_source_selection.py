#!/usr/bin/env python3
"""
c5_p_alpha_source_selection.py — M9.1-C5-P Independent Alpha Source Selection / Triage.

Evaluates candidate alpha sources for next independent research phase.
Does NOT modify any production logic, thresholds, or strategies.

Outputs:
- data/research/c5_p_alpha_source_selection.json
- docs/M9_1-C5-P_INDEPENDENT_ALPHA_SOURCE_SELECTION.md
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Paths / safety
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data" / "research"
DOCS = BASE / "docs"

for d in (ART, DOCS):
    d.mkdir(parents=True, exist_ok=True)

SAFETY = {
    "READ_ONLY": True,
    "NO_MIGRATION": True,
    "NO_DB_WRITE": True,
    "NO_CRON_MODIFIED": True,
    "NO_SYSTEMD_MODIFIED": True,
    "NO_GATEWAY_RESTART": True,
    "AUTO_TRADING": "OFF",
    "RESEARCH_ONLY": True,
    "NO_PRODUCTION_CUTOVER": True,
    "NO_STRATEGY_MODIFICATION": True,
    "NO_THRESHOLD_CHANGE": True,
}

# ---------------------------------------------------------------------------
# Frozen gates (must not be changed by C5-P)
# ---------------------------------------------------------------------------
FROZEN_GATES = {
    "QUALIFICATION_STATUS": "INSUFFICIENT_EVIDENCE",
    "D8_H_ALLOWED": False,
    "PRODUCTION_PROMOTION": False,
    "FUNDAMENTAL_ROLE": "OPTIONAL_EVIDENCE",
    "OPPORTUNITY_VALIDATION_STATUS": "UNSTABLE",
    "REGIME_AWARE_OPPORTUNITY_STATUS": "NO_IMPROVEMENT",
}

# ---------------------------------------------------------------------------
# Minimum researchability thresholds
# ---------------------------------------------------------------------------
MIN_UNIQUE_CODES = 100
MIN_DAYS_COVERAGE = 250  # ~1 year of daily data
MIN_DECISION_DATES = 12  # minimum for 1 fold × 3 horizons
MIN_OVERLAP_DAYS = 50  # days overlapping with existing decision times

# ---------------------------------------------------------------------------
# Candidate evaluation
# ---------------------------------------------------------------------------
def evaluate_candidate(source_id: str, metadata: dict, db_coverage: dict | None = None) -> dict:
    """Evaluate a single alpha source against researchability criteria."""
    result = {
        "source_id": source_id,
        "status": metadata.get("status", "UNKNOWN"),
        "pit_status": metadata.get("pit_status", "UNKNOWN"),
        "priority": metadata.get("priority", "UNKNOWN"),
        "research_ready": metadata.get("research_ready", False),
        "evaluation": {},
        "classification": None,
        "blockers": [],
        "notes": metadata.get("note", ""),
    }

    # 1. Data coverage check
    coverage = metadata.get("historical_coverage", {})
    if isinstance(coverage, dict):
        date_range = coverage.get("main_fund_flow", coverage.get("financial_data", {}))
        if isinstance(date_range, dict):
            min_date = date_range.get("start")
            max_date = date_range.get("end")
            day_count = date_range.get("days", 0)
        else:
            min_date = max_date = None
            day_count = 0
    else:
        min_date = max_date = None
        day_count = 0

    unique_codes = metadata.get("symbol_coverage", "unknown")
    if db_coverage:
        unique_codes = db_coverage.get("unique_codes", unique_codes)
        day_count = max(day_count, db_coverage.get("day_count", 0))
        overlap = db_coverage.get("overlap_with_decision_times", 0)
    else:
        overlap = 0

    result["evaluation"]["data_coverage"] = {
        "min_date": str(min_date) if min_date else None,
        "max_date": str(max_date) if max_date else None,
        "day_count": day_count,
        "unique_codes": unique_codes,
        "overlap_with_existing_decision_times": overlap,
    }

    # 2. PIT check
    pit_status = metadata.get("pit_status", "UNKNOWN")
    available_time = metadata.get("available_time", "unknown")
    result["evaluation"]["pit"] = {
        "pit_status": pit_status,
        "available_time": available_time,
        "future_injection_test": "NOT_AVAILABLE",
        "look_ahead_risk": "UNKNOWN",
    }

    # 3. Sample sufficiency check
    sample_ok = True
    if isinstance(unique_codes, (int, float)) and unique_codes < MIN_UNIQUE_CODES:
        sample_ok = False
        result["blockers"].append(f"unique_codes={unique_codes} < {MIN_UNIQUE_CODES}")
    if day_count < MIN_DAYS_COVERAGE:
        sample_ok = False
        result["blockers"].append(f"day_count={day_count} < {MIN_DAYS_COVERAGE}")
    if overlap < MIN_OVERLAP_DAYS:
        sample_ok = False
        result["blockers"].append(f"overlap={overlap} < {MIN_OVERLAP_DAYS}")

    result["evaluation"]["sample_sufficiency"] = {
        "meets_minimum": sample_ok,
        "min_unique_codes": MIN_UNIQUE_CODES,
        "min_days_coverage": MIN_DAYS_COVERAGE,
        "min_overlap_days": MIN_OVERLAP_DAYS,
    }

    # 4. Independence potential
    depends_on = metadata.get("depends_on", [])
    orthogonal_to = metadata.get("potentially_orthogonal_to", [])
    result["evaluation"]["independence"] = {
        "depends_on": depends_on,
        "potentially_orthogonal_to": orthogonal_to,
        "independence_score": len(orthogonal_to) / max(1, len(orthogonal_to) + len(depends_on)),
    }

    # 5. Classification
    if pit_status in ("UNSAFE", "NOT_READY"):
        result["classification"] = "BLOCKED_BY_PIT"
    elif not sample_ok:
        result["classification"] = "BLOCKED_BY_SAMPLE"
    elif metadata.get("status") == "PARTIAL" and pit_status == "CONDITIONAL":
        result["classification"] = "PARTIAL_NEEDS_DATA_REPAIR"
    elif result["evaluation"]["independence"]["independence_score"] < 0.5:
        result["classification"] = "NOT_RESEARCHABLE"
    else:
        result["classification"] = "READY_FOR_INDEPENDENT_RESEARCH"

    return result


# ---------------------------------------------------------------------------
# Load existing metadata
# ---------------------------------------------------------------------------
alpha_dir = ART / "alpha_source"
readiness = json.loads((alpha_dir / "alpha_source_readiness.json").read_text())
priority = json.loads((alpha_dir / "alpha_source_priority.json").read_text())
independence = json.loads((alpha_dir / "alpha_source_independence_matrix.json").read_text())

# Build lookup by source_id
readiness_map = {s["source_id"]: s for s in readiness["sources"]}
priority_map = {s["source_id"]: s for s in priority["sources"]}
independence_map = independence.get("by_source", {})

# ---------------------------------------------------------------------------
# DB coverage check
# ---------------------------------------------------------------------------
import sqlite3
from pathlib import Path

db_path = BASE / "data" / "production" / "market_cache.db"
db_coverage_map = {}

if db_path.exists():
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    
    # Check capital flow tables
    for table in ["main_fund_flow", "holder_change", "margin_data"]:
        try:
            cnt = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if cnt > 0:
                if table == "holder_change":
                    date_col = "change_date"
                elif table == "margin_data":
                    date_col = "trade_date"
                else:
                    date_col = "date"
                min_d, max_d = cur.execute(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table}").fetchone()
                unique_codes = cur.execute(f"SELECT COUNT(DISTINCT code) FROM {table}").fetchone()[0]
                overlap = cur.execute(f"""
                    SELECT COUNT(*) FROM {table} 
                    WHERE {date_col} BETWEEN '2025-03-13' AND '2026-07-02'
                """).fetchone()[0]
                db_coverage_map[table] = {
                    "rows": cnt,
                    "min_date": min_d,
                    "max_date": max_d,
                    "unique_codes": unique_codes,
                    "overlap_with_decision_times": overlap,
                }
        except Exception as e:
            db_coverage_map[table] = {"error": str(e)}
    
    con.close()

print("DB coverage:", db_coverage_map)

# ---------------------------------------------------------------------------
# Evaluate candidates
# ---------------------------------------------------------------------------
candidates = []

# 1. CAPITAL_FLOW
cf_meta = readiness_map.get("CAPITAL_FLOW", {})
cf_db = db_coverage_map.get("main_fund_flow", {})
cf_meta["historical_coverage"] = {
    "main_fund_flow": {
        "start": cf_db.get("min_date"),
        "end": cf_db.get("max_date"),
        "days": (datetime.strptime(cf_db["max_date"], "%Y-%m-%d") - datetime.strptime(cf_db["min_date"], "%Y-%m-%d")).days + 1 if cf_db.get("min_date") and cf_db.get("max_date") else 0,
    }
}
cf_eval = evaluate_candidate("CAPITAL_FLOW", cf_meta, {
    "unique_codes": cf_db.get("unique_codes", 0),
    "day_count": cf_meta.get("historical_coverage", {}).get("main_fund_flow", {}).get("days", 0),
    "overlap_with_decision_times": cf_db.get("overlap_with_decision_times", 0),
})
candidates.append(cf_eval)

# 2. HOLDER_CHANGE
hc_meta = readiness_map.get("HOLDER_CHANGE", {})
hc_db = db_coverage_map.get("holder_change", {})
hc_meta["historical_coverage"] = {
    "holder_change": {
        "start": hc_db.get("min_date"),
        "end": hc_db.get("max_date"),
        "days": (datetime.strptime(hc_db["max_date"], "%Y-%m-%d") - datetime.strptime(hc_db["min_date"], "%Y-%m-%d")).days + 1 if hc_db.get("min_date") and hc_db.get("max_date") else 0,
    }
}
hc_eval = evaluate_candidate("HOLDER_CHANGE", hc_meta, {
    "unique_codes": hc_db.get("unique_codes", 0),
    "day_count": hc_meta.get("historical_coverage", {}).get("holder_change", {}).get("days", 0),
    "overlap_with_decision_times": hc_db.get("overlap_with_decision_times", 0),
})
candidates.append(hc_eval)

# 3. INDUSTRY_SECTOR
ind_meta = readiness_map.get("INDUSTRY_SECTOR", {})
ind_eval = evaluate_candidate("INDUSTRY_SECTOR", ind_meta, {
    "unique_codes": 0,
    "day_count": 0,
    "overlap_with_decision_times": 0,
})
candidates.append(ind_eval)

# 4. FUNDAMENTAL (already in C5 series, but check independence)
fund_meta = readiness_map.get("FUNDAMENTAL", {})
fund_eval = evaluate_candidate("FUNDAMENTAL", fund_meta, {
    "unique_codes": 5187,
    "day_count": 15000,  # ~40 years quarterly
    "overlap_with_decision_times": 8,
})
candidates.append(fund_eval)

# 5. VOLUME
vol_meta = readiness_map.get("VOLUME", {})
vol_eval = evaluate_candidate("VOLUME", vol_meta, {
    "unique_codes": 6128,
    "day_count": 9000,
    "overlap_with_decision_times": 8,
})
candidates.append(vol_eval)

# 6. CORPORATE_ACTION
ca_meta = readiness_map.get("CORPORATE_ACTION", {})
ca_eval = evaluate_candidate("CORPORATE_ACTION", ca_meta, {
    "unique_codes": 0,
    "day_count": 0,
    "overlap_with_decision_times": 0,
})
candidates.append(ca_eval)

# ---------------------------------------------------------------------------
# Select next alpha source
# ---------------------------------------------------------------------------
ready_candidates = [c for c in candidates if c["classification"] == "READY_FOR_INDEPENDENT_RESEARCH"]
partial_candidates = [c for c in candidates if c["classification"] == "PARTIAL_NEEDS_DATA_REPAIR"]

if ready_candidates:
    # Select highest priority ready candidate
    next_source = ready_candidates[0]["source_id"]
    selection_reason = f"{next_source} meets all researchability criteria"
    no_next_source = False
elif partial_candidates:
    # Select highest potential partial candidate
    next_source = partial_candidates[0]["source_id"]
    selection_reason = f"{next_source} has potential but needs data repair before independent research"
    no_next_source = False
else:
    next_source = None
    selection_reason = "No candidate meets minimum researchability criteria"
    no_next_source = True

# ---------------------------------------------------------------------------
# Build output
# ---------------------------------------------------------------------------
output = {
    "frozen_gates": FROZEN_GATES,
    "evaluation_timestamp": datetime.utcnow().isoformat() + "Z",
    "minimum_thresholds": {
        "min_unique_codes": MIN_UNIQUE_CODES,
        "min_days_coverage": MIN_DAYS_COVERAGE,
        "min_decision_dates": MIN_DECISION_DATES,
        "min_overlap_days": MIN_OVERLAP_DAYS,
    },
    "candidates": candidates,
    "ready_count": len(ready_candidates),
    "partial_count": len(partial_candidates),
    "next_alpha_source": next_source,
    "no_next_alpha_source_ready": no_next_source,
    "selection_reason": selection_reason,
    "db_coverage": db_coverage_map,
}

(ART / "c5_p_alpha_source_selection.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

# ---------------------------------------------------------------------------
# Generate report
# ---------------------------------------------------------------------------
report_lines = [
    "# M9.1-C5-P Independent Alpha Source Selection",
    "",
    f"- Evaluation timestamp: {output['evaluation_timestamp']}",
    f"- Candidates evaluated: {len(candidates)}",
    f"- READY_FOR_INDEPENDENT_RESEARCH: {len(ready_candidates)}",
    f"- PARTIAL_NEEDS_DATA_REPAIR: {len(partial_candidates)}",
    f"- Next alpha source: {next_source if next_source else 'NONE'}",
    f"- NO_NEXT_ALPHA_SOURCE_READY: {no_next_source}",
    "",
    "## Frozen Gates (must not be changed)",
    f"- QUALIFICATION_STATUS = {FROZEN_GATES['QUALIFICATION_STATUS']}",
    f"- D8_H_ALLOWED = {FROZEN_GATES['D8_H_ALLOWED']}",
    f"- PRODUCTION_PROMOTION = {FROZEN_GATES['PRODUCTION_PROMOTION']}",
    f"- FUNDAMENTAL_ROLE = {FROZEN_GATES['FUNDAMENTAL_ROLE']}",
    f"- OPPORTUNITY_VALIDATION_STATUS = {FROZEN_GATES['OPPORTUNITY_VALIDATION_STATUS']}",
    f"- REGIME_AWARE_OPPORTUNITY_STATUS = {FROZEN_GATES['REGIME_AWARE_OPPORTUNITY_STATUS']}",
    "",
    "## Minimum Researchability Thresholds",
    f"- MIN_UNIQUE_CODES = {MIN_UNIQUE_CODES}",
    f"- MIN_DAYS_COVERAGE = {MIN_DAYS_COVERAGE}",
    f"- MIN_DECISION_DATES = {MIN_DECISION_DATES}",
    f"- MIN_OVERLAP_DAYS = {MIN_OVERLAP_DAYS}",
    "",
    "## Candidate Evaluation",
]

for c in candidates:
    report_lines.append(f"### {c['source_id']}")
    report_lines.append(f"- Status: {c['status']}")
    report_lines.append(f"- PIT Status: {c['pit_status']}")
    report_lines.append(f"- Priority: {c['priority']}")
    report_lines.append(f"- Classification: **{c['classification']}**")
    if c["blockers"]:
        report_lines.append("- Blockers:")
        for b in c["blockers"]:
            report_lines.append(f"  - {b}")
    report_lines.append(f"- Notes: {c['notes']}")
    report_lines.append("")

report_lines.extend([
    "## Next Alpha Source Decision",
    f"- Selected: {next_source if next_source else 'NONE'}",
    f"- Reason: {selection_reason}",
    "",
    "## Recommendation",
])

if no_next_source:
    report_lines.append("- **NO_NEXT_ALPHA_SOURCE_READY**")
    report_lines.append("- No current candidate meets minimum researchability criteria.")
    report_lines.append("- Do not force-create C5-Q.")
    report_lines.append("- Options:")
    report_lines.append("  1. Improve data coverage for existing PARTIAL sources (CAPITAL_FLOW, HOLDER_CHANGE)")
    report_lines.append("  2. Acquire new independent alpha data (e.g., news/events, macro)")
    report_lines.append("  3. Revisit Fundamental research path with improved PIT handling")
else:
    report_lines.append(f"- Proceed with **{next_source}** independent alpha research.")
    report_lines.append("- This does not change any frozen gates.")
    report_lines.append("- Next step would be M9.1-C5-Q (or equivalent) for this source.")

report_lines.extend([
    "",
    "## Gates (unchanged)",
    "- QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE",
    "- D8_H_ALLOWED = NO",
    "- PRODUCTION_PROMOTION = NO",
    "- FUNDAMENTAL_ROLE = OPTIONAL_EVIDENCE",
    "- OPPORTUNITY_VALIDATION_STATUS = UNSTABLE",
    "- REGIME_AWARE_OPPORTUNITY_STATUS = NO_IMPROVEMENT",
    "",
    "## Artifacts",
    "- `data/research/c5_p_alpha_source_selection.json`",
])

(DOCS / "M9_1-C5-P_INDEPENDENT_ALPHA_SOURCE_SELECTION.md").write_text(
    "\n".join(report_lines),
    encoding="utf-8",
)

print(f"C5-P complete.")
print(f"Next alpha source: {next_source if next_source else 'NONE'}")
print(f"NO_NEXT_ALPHA_SOURCE_READY: {no_next_source}")
print(f"Artifacts: {ART}/c5_p_alpha_source_selection.json, {DOCS}/M9_1-C5-P_INDEPENDENT_ALPHA_SOURCE_SELECTION.md")
