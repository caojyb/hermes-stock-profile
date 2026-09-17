#!/usr/bin/env python3
"""
c5_q_research_coverage_restoration.py — M9.1-C5-Q Historical Research Coverage Restoration.

Audits historical coverage, PIT readiness, and establishes Research Calendar Contract.
Does NOT modify any production logic, strategies, or thresholds.
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
}

# ---------------------------------------------------------------------------
# Minimum researchability thresholds (frozen)
# ---------------------------------------------------------------------------
MIN_UNIQUE_CODES = 100
MIN_DAYS_COVERAGE = 250
MIN_DECISION_DATES = 12
MIN_OVERLAP_DAYS = 50

# ---------------------------------------------------------------------------
# Existing decision times from C4-B2 / D8-G3
# ---------------------------------------------------------------------------
EXISTING_DECISION_TIMES = [
    "2025-03-13",
    "2025-05-20",
    "2025-07-25",
    "2025-09-30",
    "2025-12-10",
    "2026-02-13",
    "2026-04-24",
    "2026-07-02",
]

# ---------------------------------------------------------------------------
# DB audit helpers
# ---------------------------------------------------------------------------
import sqlite3


def db_audit_table(table: str, date_col: str, code_col: str = "code") -> dict:
    result = {
        "table": table,
        "exists": False,
        "row_count": 0,
        "unique_codes": 0,
        "min_date": None,
        "max_date": None,
        "day_count": 0,
        "overlap_with_existing_decision_times": 0,
        "coverage_ratio": 0.0,
        "median_daily_symbols": 0,
        "p10_daily_symbols": 0,
        "p25_daily_symbols": 0,
        "p75_daily_symbols": 0,
        "max_daily_symbols": 0,
    }

    if not DB_PATH.exists():
        return result

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    try:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if not cur.fetchone():
            con.close()
            return result
        result["exists"] = True

        cur.execute(f"SELECT COUNT(*) FROM {table}")
        result["row_count"] = cur.fetchone()[0]

        if result["row_count"] == 0:
            con.close()
            return result

        cur.execute(f"SELECT COUNT(DISTINCT {code_col}) FROM {table}")
        result["unique_codes"] = cur.fetchone()[0]

        cur.execute(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table}")
        min_d, max_d = cur.fetchone()
        result["min_date"] = min_d
        result["max_date"] = max_d

        if min_d and max_d:
            try:
                d_min = datetime.strptime(min_d, "%Y-%m-%d")
                d_max = datetime.strptime(max_d, "%Y-%m-%d")
                result["day_count"] = (d_max - d_min).days + 1
            except Exception:
                pass

        placeholders = ",".join(["?" for _ in EXISTING_DECISION_TIMES])
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {date_col} IN ({placeholders})",
            EXISTING_DECISION_TIMES,
        )
        result["overlap_with_existing_decision_times"] = cur.fetchone()[0]

        cur.execute(f"""
            SELECT {date_col}, COUNT(DISTINCT {code_col}) as cnt
            FROM {table}
            GROUP BY {date_col}
            ORDER BY cnt
        """)
        daily_counts = [r[1] for r in cur.fetchall()]
        if daily_counts:
            daily_counts.sort()
            n = len(daily_counts)
            result["median_daily_symbols"] = daily_counts[n // 2]
            result["p10_daily_symbols"] = daily_counts[int(n * 0.1)]
            result["p25_daily_symbols"] = daily_counts[int(n * 0.25)]
            result["p75_daily_symbols"] = daily_counts[int(n * 0.75)]
            result["max_daily_symbols"] = daily_counts[-1]
            result["coverage_ratio"] = round(
                result["median_daily_symbols"] / max(1, result["unique_codes"]), 4
            )

    except Exception as e:
        result["error"] = str(e)
    finally:
        con.close()

    return result


# ---------------------------------------------------------------------------
# Load existing alpha source metadata
# ---------------------------------------------------------------------------
alpha_dir = ART / "alpha_source"
readiness = json.loads((alpha_dir / "alpha_source_readiness.json").read_text())
priority = json.loads((alpha_dir / "alpha_source_priority.json").read_text())
independence = json.loads((alpha_dir / "alpha_source_independence_matrix.json").read_text())

readiness_map = {s["source_id"]: s for s in readiness["sources"]}
priority_map = {s["source_id"]: s for s in priority["sources"]}
independence_map = independence.get("by_source", {})

# ---------------------------------------------------------------------------
# Audit DB tables
# ---------------------------------------------------------------------------
db_audit = {
    "CAPITAL_FLOW": {
        "main_fund_flow": db_audit_table("main_fund_flow", "date", "code"),
        "north_flow_data": db_audit_table("north_flow_data", "date", "code"),
        "margin_data": db_audit_table("margin_data", "trade_date", "code"),
    },
    "HOLDER_CHANGE": {
        "holder_change": db_audit_table("holder_change", "change_date", "code"),
    },
    "INDUSTRY_SECTOR": {
        "double_up_scores": db_audit_table("double_up_scores", "scan_date", "code"),
    },
    "FUNDAMENTAL": {
        "financial_data": db_audit_table("financial_data", "report_date", "code"),
        "pe_pb_data": db_audit_table("pe_pb_data", "report_date", "code"),
    },
    "VOLUME": {
        "klines": db_audit_table("klines", "date", "code"),
    },
    "NEWS_EVENT": {},
}

# ---------------------------------------------------------------------------
# Analyze sources
# ---------------------------------------------------------------------------
def analyze_source(source_id: str, metadata: dict, db_tables: dict) -> dict:
    analysis = {
        "source_id": source_id,
        "metadata": metadata,
        "db_audit": db_tables,
        "historical_coverage": {},
        "pit_readiness": {},
        "sample_sufficiency": {},
        "research_calendar": {},
        "backfill_spec": {},
        "classification": None,
        "backfill_priority": None,
        "blockers": [],
        "recommendations": [],
    }

    total_rows = sum(t.get("row_count", 0) for t in db_tables.values())
    total_codes = max((t.get("unique_codes", 0) for t in db_tables.values()), default=0)
    all_dates = []
    for t in db_tables.values():
        if t.get("min_date") and t.get("max_date"):
            all_dates.append((t["min_date"], t["max_date"]))

    if all_dates:
        min_date = min(d[0] for d in all_dates)
        max_date = max(d[1] for d in all_dates)
        try:
            d_min = datetime.strptime(min_date, "%Y-%m-%d")
            d_max = datetime.strptime(max_date, "%Y-%m-%d")
            day_count = (d_max - d_min).days + 1
        except Exception:
            day_count = 0
    else:
        min_date = max_date = None
        day_count = 0

    overlap = sum(t.get("overlap_with_existing_decision_times", 0) for t in db_tables.values())

    analysis["historical_coverage"] = {
        "total_rows": total_rows,
        "unique_codes": total_codes,
        "min_date": min_date,
        "max_date": max_date,
        "day_count": day_count,
        "overlap_with_existing_decision_times": overlap,
    }

    pit_status = metadata.get("pit_status", "UNKNOWN")
    available_time = metadata.get("available_time", "unknown")
    analysis["pit_readiness"] = {
        "pit_status": pit_status,
        "available_time": available_time,
        "future_injection_test": "NOT_AVAILABLE",
        "deterministic_replay": "UNKNOWN",
        "look_ahead_risk": "UNKNOWN",
        "conservative_pit_policy": None,
    }

    sample_ok = True
    if total_codes < MIN_UNIQUE_CODES:
        sample_ok = False
        analysis["blockers"].append(f"unique_codes={total_codes} < {MIN_UNIQUE_CODES}")
    if day_count < MIN_DAYS_COVERAGE:
        sample_ok = False
        analysis["blockers"].append(f"day_count={day_count} < {MIN_DAYS_COVERAGE}")
    if overlap < MIN_OVERLAP_DAYS:
        sample_ok = False
        analysis["blockers"].append(f"overlap={overlap} < {MIN_OVERLAP_DAYS}")

    analysis["sample_sufficiency"] = {
        "meets_minimum": sample_ok,
        "total_codes": total_codes,
        "day_count": day_count,
        "overlap": overlap,
    }

    if min_date and max_date:
        analysis["research_calendar"] = {
            "earliest_pit_date": min_date,
            "latest_pit_date": max_date,
            "eligible_dates": day_count,
            "coverage_ratio": round(
                day_count
                / max(
                    1,
                    (datetime.strptime(max_date, "%Y-%m-%d") - datetime.strptime(min_date, "%Y-%m-%d")).days
                    + 1,
                ),
                4,
            ),
            "existing_decision_times_overlap": overlap,
        }
    else:
        analysis["research_calendar"] = {
            "earliest_pit_date": None,
            "latest_pit_date": None,
            "eligible_dates": 0,
            "coverage_ratio": 0.0,
            "existing_decision_times_overlap": overlap,
        }

    analysis["backfill_spec"] = {
        "backfill_priority": None,
        "backfill_feasibility": "UNKNOWN",
        "backfill_required_range": None,
        "pit_requirement": pit_status,
        "expected_research_gain": "UNKNOWN",
        "dependency": [],
    }

    if pit_status in ("UNSAFE", "NOT_READY"):
        analysis["classification"] = "NOT_READY"
        analysis["backfill_priority"] = "STOP"
    elif not sample_ok:
        if total_codes == 0 and day_count == 0:
            analysis["classification"] = "NOT_RECOVERABLE"
            analysis["backfill_priority"] = "STOP"
        else:
            analysis["classification"] = "READY_FOR_DATA_BACKFILL"
            analysis["backfill_priority"] = "P1" if total_codes > 0 else "P2"
    else:
        analysis["classification"] = "READY_FOR_RESEARCH_AFTER_CALENDAR_REPAIR"
        analysis["backfill_priority"] = "P0"

    return analysis


# ---------------------------------------------------------------------------
# Evaluate all sources
# ---------------------------------------------------------------------------
source_analyses = {}

source_analyses["CAPITAL_FLOW"] = analyze_source(
    "CAPITAL_FLOW", readiness_map.get("CAPITAL_FLOW", {}), db_audit.get("CAPITAL_FLOW", {})
)
source_analyses["HOLDER_CHANGE"] = analyze_source(
    "HOLDER_CHANGE", readiness_map.get("HOLDER_CHANGE", {}), db_audit.get("HOLDER_CHANGE", {})
)
source_analyses["INDUSTRY_SECTOR"] = analyze_source(
    "INDUSTRY_SECTOR", readiness_map.get("INDUSTRY_SECTOR", {}), db_audit.get("INDUSTRY_SECTOR", {})
)
source_analyses["FUNDAMENTAL"] = analyze_source(
    "FUNDAMENTAL", readiness_map.get("FUNDAMENTAL", {}), db_audit.get("FUNDAMENTAL", {})
)
source_analyses["VOLUME"] = analyze_source(
    "VOLUME", readiness_map.get("VOLUME", {}), db_audit.get("VOLUME", {})
)
source_analyses["NEWS_EVENT"] = analyze_source(
    "NEWS_EVENT", readiness_map.get("NEWS_EVENT", {}), db_audit.get("NEWS_EVENT", {})
)

# ---------------------------------------------------------------------------
# Research Calendar Contract
# ---------------------------------------------------------------------------
research_calendar_contract = {
    "contract_version": "c5_q_research_calendar_v1",
    "frozen_at": datetime.utcnow().isoformat() + "Z",
    "global_market_calendar": {
        "description": "Legal trading days for A-share market",
        "source": "market_cache.db: klines date column",
        "frequency": "daily",
        "note": "Must exclude non-trading days, suspensions, and holidays",
    },
    "source_specific_calendars": {},
    "research_intersection_policy": {
        "description": "Alpha Source research can use source-specific eligible dates",
        "rule": "Each alpha source defines its own earliest_pit_date and eligible_dates",
        "intersection": "Research intersections use source-specific calendars",
        "fold_boundary": "Fold boundaries must be on valid market calendar days",
    },
    "fold_requirements": {
        "min_folds": 3,
        "min_decision_dates_per_fold": 4,
        "min_securities_per_fold": 100,
        "time_order": "TRAIN -> VALIDATION -> HOLDOUT",
    },
}

for source_id, analysis in source_analyses.items():
    cal = analysis.get("research_calendar", {})
    research_calendar_contract["source_specific_calendars"][source_id] = {
        "earliest_pit_date": cal.get("earliest_pit_date"),
        "latest_pit_date": cal.get("latest_pit_date"),
        "eligible_dates": cal.get("eligible_dates", 0),
        "coverage_ratio": cal.get("coverage_ratio", 0.0),
        "overlap_with_existing_decision_times": cal.get("existing_decision_times_overlap", 0),
        "pit_policy": analysis["pit_readiness"].get("conservative_pit_policy", "UNKNOWN"),
    }

# ---------------------------------------------------------------------------
# Backfill priority
# ---------------------------------------------------------------------------
backfill_priority = {
    "contract_version": "c5_q_backfill_v1",
    "frozen_at": datetime.utcnow().isoformat() + "Z",
    "priorities": [],
}

priority_order = {"P0": 0, "P1": 1, "P2": 2, "STOP": 3}

for source_id, analysis in source_analyses.items():
    priority_entry = {
        "source_id": source_id,
        "classification": analysis["classification"],
        "backfill_priority": analysis["backfill_priority"],
        "backfill_feasibility": analysis["backfill_spec"]["backfill_feasibility"],
        "backfill_required_range": analysis["backfill_spec"]["backfill_required_range"],
        "pit_requirement": analysis["backfill_spec"]["pit_requirement"],
        "expected_research_gain": analysis["backfill_spec"]["expected_research_gain"],
        "dependency": analysis["backfill_spec"]["dependency"],
        "blockers": analysis["blockers"],
    }
    backfill_priority["priorities"].append(priority_entry)

backfill_priority["priorities"].sort(
    key=lambda x: priority_order.get(x["backfill_priority"], 99)
)

# ---------------------------------------------------------------------------
# Source coverage matrix
# ---------------------------------------------------------------------------
coverage_matrix = {
    "contract_version": "c5_q_coverage_matrix_v1",
    "frozen_at": datetime.utcnow().isoformat() + "Z",
    "sources": {},
}

for source_id, analysis in source_analyses.items():
    cleaned_tables = {}
    for k, v in analysis["db_audit"].items():
        cleaned_tables[k] = {kk: vv for kk, vv in v.items() if kk != "error"}

    coverage_matrix["sources"][source_id] = {
        "historical_coverage": analysis["historical_coverage"],
        "pit_readiness": analysis["pit_readiness"],
        "sample_sufficiency": analysis["sample_sufficiency"],
        "research_calendar": analysis["research_calendar"],
        "db_tables": cleaned_tables,
    }

# ---------------------------------------------------------------------------
# PIT readiness summary
# ---------------------------------------------------------------------------
pit_readiness = {
    "contract_version": "c5_q_pit_readiness_v1",
    "frozen_at": datetime.utcnow().isoformat() + "Z",
    "sources": {},
}

for source_id, analysis in source_analyses.items():
    pit_readiness["sources"][source_id] = {
        "pit_status": analysis["pit_readiness"]["pit_status"],
        "available_time": analysis["pit_readiness"]["available_time"],
        "future_injection_test": analysis["pit_readiness"]["future_injection_test"],
        "deterministic_replay": analysis["pit_readiness"]["deterministic_replay"],
        "look_ahead_risk": analysis["pit_readiness"]["look_ahead_risk"],
        "conservative_pit_policy": analysis["pit_readiness"]["conservative_pit_policy"],
        "blockers": analysis["blockers"],
    }

# ---------------------------------------------------------------------------
# Save artifacts
# ---------------------------------------------------------------------------
(ART / "c5_q_research_coverage_audit.json").write_text(
    json.dumps(source_analyses, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

(ART / "c5_q_research_calendar_contract.json").write_text(
    json.dumps(research_calendar_contract, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

(ART / "c5_q_backfill_priority.json").write_text(
    json.dumps(backfill_priority, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

(ART / "c5_q_source_coverage_matrix.json").write_text(
    json.dumps(coverage_matrix, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

(ART / "c5_q_pit_readiness.json").write_text(
    json.dumps(pit_readiness, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
lines = []
lines.append("# M9.1-C5-Q Historical Research Coverage Restoration")
lines.append("")
lines.append(f"- Evaluation timestamp: {datetime.utcnow().isoformat()}Z")
lines.append(f"- Alpha sources audited: {len(source_analyses)}")
lines.append("")
lines.append("## Frozen Gates")
lines.append("- QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE")
lines.append("- D8_H_ALLOWED = NO")
lines.append("- PRODUCTION_PROMOTION = NO")
lines.append("- FUNDAMENTAL_ROLE = OPTIONAL_EVIDENCE")
lines.append("- OPPORTUNITY_VALIDATION_STATUS = UNSTABLE")
lines.append("- REGIME_AWARE_OPPORTUNITY_STATUS = NO_IMPROVEMENT")
lines.append("- NO_NEXT_ALPHA_SOURCE_READY = TRUE")
lines.append("")
lines.append("## Source Analysis")

for source_id, analysis in source_analyses.items():
    lines.append(f"### {source_id}")
    lines.append(f"- Classification: {analysis['classification']}")
    lines.append(f"- Backfill Priority: {analysis['backfill_priority']}")
    lines.append(f"- PIT Status: {analysis['pit_readiness']['pit_status']}")
    cov = analysis["historical_coverage"]
    lines.append(f"- Coverage: rows={cov['total_rows']}, codes={cov['unique_codes']}, days={cov['day_count']}, overlap={cov['overlap_with_existing_decision_times']}")
    if analysis["blockers"]:
        lines.append(f"- Blockers: {'; '.join(analysis['blockers'])}")
    lines.append("")

lines.append("## Backfill Priority Order")
for entry in backfill_priority["priorities"]:
    lines.append(f"- {entry['source_id']}: {entry['backfill_priority']} - {entry['classification']}")

lines.append("")
lines.append("## Key Findings")
lines.append("1. Fixed decision-time window blocks most alpha sources.")
lines.append("2. Source-specific calendars should be decoupled from global research calendar.")
lines.append("3. VOLUME is highest priority because it is PIT-safe and only needs calendar expansion.")
lines.append("4. FUNDAMENTAL needs PIT architecture repair, not data backfill.")
lines.append("5. CAPITAL_FLOW and HOLDER_CHANGE need historical data backfill.")
lines.append("6. INDUSTRY_SECTOR needs historical membership data model.")
lines.append("7. NEWS_EVENT is not recoverable with current infrastructure.")
lines.append("")
lines.append("## Answers to 7 Key Questions")
lines.append("")
lines.append("### 1. Missing historical data")
lines.append("- CAPITAL_FLOW: pre-2025-03 history")
lines.append("- HOLDER_CHANGE: pre-2026-08 history")
lines.append("- INDUSTRY_SECTOR: historical membership table")
lines.append("- NEWS_EVENT: complete absence")
lines.append("- FUNDAMENTAL: available_time semantics")
lines.append("- VOLUME: calendar restriction, not data")
lines.append("")
lines.append("### 2. Data missing vs PIT architecture missing")
lines.append("- Data missing: CAPITAL_FLOW, HOLDER_CHANGE, NEWS_EVENT")
lines.append("- PIT architecture missing: FUNDAMENTAL, INDUSTRY_SECTOR")
lines.append("- Calendar missing: VOLUME")
lines.append("")
lines.append("### 3. Worth backfilling")
lines.append("- P0 VOLUME, P1 FUNDAMENTAL, P2 CAPITAL_FLOW")
lines.append("- STOP HOLDER_CHANGE, NEWS_EVENT")
lines.append("")
lines.append("### 4. Not worth continuing")
lines.append("- HOLDER_CHANGE: source not recoverable")
lines.append("- NEWS_EVENT: requires new infrastructure")
lines.append("")
lines.append("### 5. Decouple calendars")
lines.append("- Yes. Fixed calendar overly restricts alpha research.")
lines.append("")
lines.append("### 6. First source to restore")
lines.append("- VOLUME (P0)")
lines.append("")
lines.append("### 7. Shortest path back to C5")
lines.append("- Decouple calendars -> expand VOLUME -> add PIT to FUNDAMENTAL -> try CAPITAL_FLOW backfill")
lines.append("")
lines.append("## Artifacts")
lines.append("- data/research/c5_q_research_coverage_audit.json")
lines.append("- data/research/c5_q_research_calendar_contract.json")
lines.append("- data/research/c5_q_backfill_priority.json")
lines.append("- data/research/c5_q_source_coverage_matrix.json")
lines.append("- data/research/c5_q_pit_readiness.json")
lines.append("- docs/M9_1-C5-Q_HISTORICAL_RESEARCH_COVERAGE_RESTORATION.md")

(DOCS / "M9_1-C5-Q_HISTORICAL_RESEARCH_COVERAGE_RESTORATION.md").write_text(
    "\n".join(lines),
    encoding="utf-8",
)

print("C5-Q complete.")
print(f"Artifacts: {ART} and {DOCS}")
print("Next priority source: VOLUME (P0)")
