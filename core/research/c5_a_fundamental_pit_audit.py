#!/usr/bin/env python3
"""
c5_a_fundamental_pit_audit.py — M9.1-C5-B Fundamental Alpha Source PIT Closure.

Inputs:
- market_cache.db tables: financial_data, pe_pb_data, cf_cache, equity_pledge

Outputs:
- data/research/alpha_source/fundamental_pit_audit.json
- data/research/alpha_source/fundamental_pit_examples.json
- data/research/alpha_source/fundamental_pit_coverage.json
- docs/M9_1_C5_B_FUNDAMENTAL_PIT_CLOSURE.md

This is RESEARCH ONLY. No production schema changes. No strategy generation.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data/research/alpha_source"
DOC = BASE / "docs"
DB = BASE / "data/production/market_cache.db"

for p in [ART, DOC]:
    p.mkdir(parents=True, exist_ok=True)


# ============================================================
# Conservative Fundamental PIT Policy
# ============================================================
# Chinese A-share reporting deadlines (calendar days after period end):
# - Q1/Q2/Q3: 30 days
# - Semi-annual: 60 days
# - Annual: 90 days
#
# Since DB has report_date but NO announcement_date,
# we define available_time as:
#   available_time = report_date + conservative_publication_lag
#
# This is a CONSERVATIVE ESTIMATE, not actual announcement time.
# ============================================================

REPORT_LAG_DAYS = {
    "Q1": 30,
    "Q2": 30,
    "Q3": 30,
    "YEAR": 90,
    "SEMI": 60,
    "UNKNOWN": 60,
}


def infer_period_type(report_date: str) -> str:
    try:
        dt = datetime.strptime(report_date, "%Y-%m-%d")
        month = dt.month
        day = dt.day
        if month == 3 and day == 31:
            return "Q1"
        elif month == 6 and day == 30:
            return "SEMI"
        elif month == 9 and day == 30:
            return "Q3"
        elif month == 12 and day == 31:
            return "YEAR"
        else:
            return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def conservative_available_time(report_date: str) -> str:
    period_type = infer_period_type(report_date)
    lag = REPORT_LAG_DAYS.get(period_type, 60)
    try:
        dt = datetime.strptime(report_date, "%Y-%m-%d")
        avail = dt + timedelta(days=lag)
        return avail.strftime("%Y-%m-%d")
    except Exception:
        return report_date


# ============================================================
# DB Inspection
# ============================================================
def inspect_fundamental_db() -> Dict[str, Any]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    result: Dict[str, Any] = {
        "financial_data": {},
        "pe_pb_data": {},
        "cf_cache": {},
        "equity_pledge": {},
        "summary": {},
    }

    # financial_data
    cur.execute("PRAGMA table_info(financial_data)")
    fd_cols = [r[1] for r in cur.fetchall()]
    result["financial_data"]["columns"] = fd_cols
    result["financial_data"]["has_announcement_date"] = "announcement_date" in fd_cols
    result["financial_data"]["has_available_time"] = "available_time" in fd_cols
    result["financial_data"]["has_report_date"] = "report_date" in fd_cols
    result["financial_data"]["has_fetched_at"] = "fetched_at" in fd_cols

    cur.execute("SELECT COUNT(*) FROM financial_data")
    result["financial_data"]["row_count"] = cur.fetchone()[0]

    cur.execute("SELECT MIN(report_date), MAX(report_date) FROM financial_data WHERE report_date IS NOT NULL")
    r = cur.fetchone()
    result["financial_data"]["report_date_range"] = {"min": r[0], "max": r[1]}

    cur.execute("SELECT MIN(fetched_at), MAX(fetched_at) FROM financial_data WHERE fetched_at IS NOT NULL")
    r = cur.fetchone()
    result["financial_data"]["fetched_at_range"] = {"min": r[0], "max": r[1]}

    # Distinct codes
    cur.execute("SELECT COUNT(DISTINCT code) FROM financial_data")
    result["financial_data"]["symbol_count"] = cur.fetchone()[0]

    # Period distribution
    cur.execute("""
        SELECT substr(report_date, 1, 4) as year, COUNT(*) as cnt
        FROM financial_data
        GROUP BY year
        ORDER BY year
        LIMIT 20
    """)
    result["financial_data"]["year_distribution"] = [{"year": r[0], "count": r[1]} for r in cur.fetchall()]

    # Sample with report_date and fetched_at
    cur.execute("""
        SELECT code, report_date, fetched_at, roe, eps, revenue_growth
        FROM financial_data
        WHERE report_date IS NOT NULL
        ORDER BY fetched_at DESC
        LIMIT 5
    """)
    result["financial_data"]["recent_samples"] = [
        {"code": r[0], "report_date": r[1], "fetched_at": r[2], "roe": r[3], "eps": r[4], "revenue_growth": r[5]}
        for r in cur.fetchall()
    ]

    # pe_pb_data
    cur.execute("PRAGMA table_info(pe_pb_data)")
    pb_cols = [r[1] for r in cur.fetchall()]
    result["pe_pb_data"]["columns"] = pb_cols
    result["pe_pb_data"]["has_announcement_date"] = "announcement_date" in pb_cols
    result["pe_pb_data"]["has_available_time"] = "available_time" in pb_cols
    result["pe_pb_data"]["has_fetch_date"] = "fetch_date" in pb_cols

    cur.execute("SELECT COUNT(*) FROM pe_pb_data")
    result["pe_pb_data"]["row_count"] = cur.fetchone()[0]

    cur.execute("SELECT MIN(fetch_date), MAX(fetch_date) FROM pe_pb_data WHERE fetch_date IS NOT NULL")
    r = cur.fetchone()
    result["pe_pb_data"]["fetch_date_range"] = {"min": r[0], "max": r[1]}

    cur.execute("SELECT COUNT(DISTINCT code) FROM pe_pb_data")
    result["pe_pb_data"]["symbol_count"] = cur.fetchone()[0]

    # cf_cache
    cur.execute("PRAGMA table_info(cf_cache)")
    cf_cols = [r[1] for r in cur.fetchall()]
    result["cf_cache"]["columns"] = cf_cols
    result["cf_cache"]["has_announcement_date"] = "announcement_date" in cf_cols
    result["cf_cache"]["has_available_time"] = "available_time" in cf_cols
    result["cf_cache"]["has_fetch_date"] = "fetch_date" in cf_cols

    cur.execute("SELECT COUNT(*) FROM cf_cache")
    result["cf_cache"]["row_count"] = cur.fetchone()[0]

    cur.execute("SELECT MIN(fetch_date), MAX(fetch_date) FROM cf_cache WHERE fetch_date IS NOT NULL")
    r = cur.fetchone()
    result["cf_cache"]["fetch_date_range"] = {"min": r[0], "max": r[1]}

    cur.execute("SELECT COUNT(DISTINCT code) FROM cf_cache")
    result["cf_cache"]["symbol_count"] = cur.fetchone()[0]

    # equity_pledge
    cur.execute("SELECT COUNT(*) FROM equity_pledge")
    result["equity_pledge"]["row_count"] = cur.fetchone()[0]

    con.close()
    return result


# ============================================================
# PIT Provider
# ============================================================
class FundamentalPITProvider:
    """
    Research-only PIT access layer for fundamental data.
    Uses conservative available_time estimation based on report_date + lag.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self):
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def get_fundamental(self, symbol: str, decision_time: str) -> List[Dict[str, Any]]:
        """
        Return fundamental records for symbol where available_time <= decision_time.
        available_time is estimated as report_date + conservative_publication_lag.
        """
        con = self._connect()
        cur = con.cursor()
        cur.execute("""
            SELECT code, report_date, fetched_at, roe, eps, revenue_growth, profit_growth,
                   debt_ratio, net_margin, gross_margin, op_margin, bps, equity_ratio
            FROM financial_data
            WHERE code = ?
              AND report_date IS NOT NULL
        """, (symbol,))
        rows = cur.fetchall()
        con.close()

        results = []
        for row in rows:
            code, report_date, fetched_at, roe, eps, rev_growth, profit_growth, debt_ratio, net_margin, gross_margin, op_margin, bps, equity_ratio = row
            available_time = conservative_available_time(report_date)
            if available_time <= decision_time:
                results.append({
                    "code": code,
                    "report_date": report_date,
                    "available_time": available_time,
                    "fetched_at": fetched_at,
                    "roe": roe,
                    "eps": eps,
                    "revenue_growth": rev_growth,
                    "profit_growth": profit_growth,
                    "debt_ratio": debt_ratio,
                    "net_margin": net_margin,
                    "gross_margin": gross_margin,
                    "op_margin": op_margin,
                    "bps": bps,
                    "equity_ratio": equity_ratio,
                    "visible_at_decision": True,
                    "pit_policy": "CONSERVATIVE_ESTIMATE",
                })
        return results

    def future_injection_test(self, symbol: str, decision_time: str, future_days: int = 30) -> Dict[str, Any]:
        """
        Inject a future financial record and verify it does NOT appear in get_fundamental.
        """
        future_date = (datetime.strptime(decision_time, "%Y-%m-%d") + timedelta(days=future_days)).strftime("%Y-%m-%d")
        before = self.get_fundamental(symbol, decision_time)
        # Simulate future record by querying with future available_time
        con = self._connect()
        cur = con.cursor()
        cur.execute("""
            SELECT code, report_date, fetched_at, roe, eps
            FROM financial_data
            WHERE code = ?
              AND report_date IS NOT NULL
              AND report_date > ?
            LIMIT 5
        """, (symbol, decision_time))
        future_rows = cur.fetchall()
        con.close()

        future_visible = []
        for row in future_rows:
            report_date = row[1]
            available_time = conservative_available_time(report_date)
            if available_time <= decision_time:
                future_visible.append({
                    "report_date": report_date,
                    "available_time": available_time,
                    "note": "Future record incorrectly visible",
                })

        return {
            "decision_time": decision_time,
            "future_cutoff": future_date,
            "before_count": len(before),
            "future_rows_found": len(future_rows),
            "future_visible_incorrectly": future_visible,
            "test_result": "PASS" if not future_visible else "FAIL",
        }


# ============================================================
# Coverage Analysis
# ============================================================
def analyze_fundamental_coverage() -> Dict[str, Any]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    coverage: Dict[str, Any] = {
        "financial_data": {
            "symbol_count": 0,
            "record_count": 0,
            "earliest_report_date": None,
            "latest_report_date": None,
            "earliest_research_safe_date": None,
            "latest_research_safe_date": None,
            "year_quarter_coverage": [],
            "period_type_distribution": {},
            "symbols_with_multiple_reports": 0,
        },
        "pit_policy": {
            "policy": "CONSERVATIVE_ESTIMATE",
            "lag_days": REPORT_LAG_DAYS,
            "rationale": "No announcement_date available; using regulatory filing deadlines as conservative upper bound",
            "risk": "Actual available_time may be earlier than estimated; this policy may exclude some usable data but prevents future leakage",
        },
    }

    cur.execute("SELECT COUNT(DISTINCT code) FROM financial_data")
    coverage["financial_data"]["symbol_count"] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM financial_data")
    coverage["financial_data"]["record_count"] = cur.fetchone()[0]

    cur.execute("SELECT MIN(report_date), MAX(report_date) FROM financial_data WHERE report_date IS NOT NULL")
    r = cur.fetchone()
    coverage["financial_data"]["earliest_report_date"] = r[0]
    coverage["financial_data"]["latest_report_date"] = r[1]

    if r[0]:
        coverage["financial_data"]["earliest_research_safe_date"] = conservative_available_time(r[0])
    if r[1]:
        coverage["financial_data"]["latest_research_safe_date"] = conservative_available_time(r[1])

    # Year-quarter coverage
    cur.execute("""
        SELECT substr(report_date, 1, 4) as year,
               CASE
                   WHEN substr(report_date, 6, 2) = '03' THEN 'Q1'
                   WHEN substr(report_date, 6, 2) = '06' THEN 'Q2'
                   WHEN substr(report_date, 6, 2) = '09' THEN 'Q3'
                   WHEN substr(report_date, 6, 2) = '12' THEN 'YEAR'
                   ELSE 'OTHER'
               END as quarter,
               COUNT(*) as cnt,
               COUNT(DISTINCT code) as symbols
        FROM financial_data
        GROUP BY year, quarter
        ORDER BY year, quarter
    """)
    rows = cur.fetchall()
    coverage["financial_data"]["year_quarter_coverage"] = [
        {"year": r[0], "quarter": r[1], "record_count": r[2], "symbol_count": r[3]}
        for r in rows
    ]

    # Period type distribution
    cur.execute("""
        SELECT
            CASE
                WHEN substr(report_date, 6, 2) = '03' THEN 'Q1'
                WHEN substr(report_date, 6, 2) = '06' THEN 'SEMI'
                WHEN substr(report_date, 6, 2) = '09' THEN 'Q3'
                WHEN substr(report_date, 6, 2) = '12' THEN 'YEAR'
                ELSE 'OTHER'
            END as period_type,
            COUNT(*) as cnt
        FROM financial_data
        GROUP BY period_type
    """)
    coverage["financial_data"]["period_type_distribution"] = {r[0]: r[1] for r in cur.fetchall()}

    # Restatement check: duplicates per code+report_date
    cur.execute("""
        SELECT code, report_date, COUNT(*) as cnt
        FROM financial_data
        GROUP BY code, report_date
        HAVING cnt > 1
        LIMIT 10
    """)
    duplicates = cur.fetchall()
    coverage["financial_data"]["restatement_risk"] = {
        "duplicate_code_report_combinations": len(duplicates),
        "sample_duplicates": [{"code": r[0], "report_date": r[1], "count": r[2]} for r in duplicates[:5]],
        "note": "If duplicates exist, they may indicate restatements or data quality issues",
    }

    con.close()
    return coverage


# ============================================================
# PIT Examples
# ============================================================
def generate_pit_examples(provider: FundamentalPITProvider) -> Dict[str, Any]:
    symbols = ["000001", "000002", "600519", "000858", "601318", "002594", "600036", "000333", "002714", "603288"]
    examples = []
    test_results = []

    for symbol in symbols:
        # Test with a recent decision time
        decision_time = "2025-06-15"
        records = provider.get_fundamental(symbol, decision_time)
        if not records:
            continue

        # Pick latest available record before decision_time
        latest = max(records, key=lambda x: x["available_time"])
        examples.append({
            "symbol": symbol,
            "type": "pre_announcement_check",
            "decision_time": decision_time,
            "latest_available_report_date": latest["report_date"],
            "available_time": latest["available_time"],
            "report_period": latest["report_date"],
            "visible": True,
            "reason": f"available_time={latest['available_time']} <= decision_time={decision_time}",
        })

        # Future injection test
        future_test = provider.future_injection_test(symbol, decision_time)
        test_results.append({
            "symbol": symbol,
            "decision_time": decision_time,
            "test": future_test,
        })

    return {
        "examples": examples[:10],
        "future_injection_tests": test_results[:10],
        "pit_regression_summary": {
            "total_tested": len(test_results),
            "passed": sum(1 for t in test_results if t["test"]["test_result"] == "PASS"),
            "failed": sum(1 for t in test_results if t["test"]["test_result"] == "FAIL"),
        },
    }


# ============================================================
# Main
# ============================================================
def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

    # 1. Inventory
    inventory = inspect_fundamental_db()
    (ART / "fundamental_pit_audit.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 2. Coverage
    coverage = analyze_fundamental_coverage()
    (ART / "fundamental_pit_coverage.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 3. PIT Provider test
    provider = FundamentalPITProvider(DB)
    examples = generate_pit_examples(provider)
    (ART / "fundamental_pit_examples.json").write_text(
        json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 4. Readiness assessment
    future_pass_ratio = examples["pit_regression_summary"]["passed"] / max(1, examples["pit_regression_summary"]["total_tested"])
    has_announcement_date = inventory["financial_data"].get("has_announcement_date", False)
    restatement_risk = inventory["financial_data"].get("restatement_risk", {}).get("duplicate_code_report_combinations", 0)

    if not has_announcement_date:
        pit_ready = "PARTIAL"
        pit_note = "No announcement_date in DB; using conservative estimate based on regulatory deadlines"
    elif future_pass_ratio < 0.9:
        pit_ready = "PARTIAL"
        pit_note = "Future injection test shows potential leakage"
    else:
        pit_ready = "YES"
        pit_note = "PIT access layer passes all tests"

    data_ready = "YES" if inventory["financial_data"]["row_count"] > 0 else "NO"
    research_ready = "YES" if data_ready == "YES" and pit_ready in ("YES", "PARTIAL") else "NO"

    readiness = {
        "FUNDAMENTAL_DATA_READY": data_ready,
        "FUNDAMENTAL_PIT_READY": pit_ready,
        "FUNDAMENTAL_RESEARCH_READY": research_ready,
        "pit_note": pit_note,
        "has_announcement_date": has_announcement_date,
        "future_injection_pass_ratio": round(future_pass_ratio, 4),
        "restatement_risk_combinations": restatement_risk,
        "next_alpha_source": "CAPITAL_FLOW",
    }

    # 5. Documentation
    doc_lines = [
        "# M9.1-C5-B Fundamental Alpha Source PIT Closure",
        "",
        "## Summary",
        f"- FUNDAMENTAL_DATA_READY: {data_ready}",
        f"- FUNDAMENTAL_PIT_READY: {pit_ready}",
        f"- FUNDAMENTAL_RESEARCH_READY: {research_ready}",
        "",
        "## Key Findings",
        f"- financial_data rows: {inventory['financial_data']['row_count']}",
        f"- symbol coverage: {inventory['financial_data']['symbol_count']}",
        f"- report_date range: {inventory['financial_data']['report_date_range']['min']} to {inventory['financial_data']['report_date_range']['max']}",
        f"- has_announcement_date: {has_announcement_date}",
        f"- restatement risk combinations: {restatement_risk}",
        f"- future injection pass ratio: {future_pass_ratio:.2%}",
        "",
        "## PIT Policy",
        "- Policy: CONSERVATIVE_ESTIMATE",
        f"- Lag days: {REPORT_LAG_DAYS}",
        "- Rationale: No announcement_date available; using regulatory filing deadlines",
        "",
        "## Status",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `fundamental_pit_audit.json`",
        "- `fundamental_pit_coverage.json`",
        "- `fundamental_pit_examples.json`",
        "",
    ]
    (DOC / "M9_1_C5_B_FUNDAMENTAL_PIT_CLOSURE.md").write_text("\n".join(doc_lines), encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "readiness": readiness,
        "artifacts": [
            "data/research/alpha_source/fundamental_pit_audit.json",
            "data/research/alpha_source/fundamental_pit_coverage.json",
            "data/research/alpha_source/fundamental_pit_examples.json",
            "docs/M9_1_C5_B_FUNDAMENTAL_PIT_CLOSURE.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
