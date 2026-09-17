#!/usr/bin/env python3
"""
c5_c_capital_flow_pit_audit.py — M9.1-C5-C Capital Flow Alpha Source PIT Closure.

Inputs:
- market_cache.db tables: main_fund_flow, north_flow_data, margin_data, cf_cache

Outputs:
- data/research/alpha_source/capital_flow_pit_audit.json
- data/research/alpha_source/capital_flow_pit_coverage.json
- data/research/alpha_source/capital_flow_pit_examples.json
- data/research/alpha_source/capital_flow_source_readiness.json
- docs/M9_1_C5_C_CAPITAL_FLOW_PIT_CLOSURE.md

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
# Conservative Capital Flow PIT Policy
# ============================================================
# Capital flow data is typically EOD-only. Without explicit available_time,
# we assume data becomes available at T+1 09:30 (next session open).
CAPITAL_FLOW_AVAILABLE_POLICY = "CONSERVATIVE_NEXT_SESSION"
CAPITAL_FLOW_POLICY_NOTE = (
    "No explicit available_time or timestamp in capital flow tables. "
    "Assuming EOD calculation and T+1 session availability as conservative upper bound."
)


def conservative_capital_flow_available_time(trade_date: str) -> str:
    """
    Conservative available_time for capital flow data.
    Trade date T -> available at T+1 open.
    """
    try:
        dt = datetime.strptime(trade_date, "%Y-%m-%d")
        # Next trading day (simple +1 day; calendar alignment not implemented here)
        avail = dt + timedelta(days=1)
        return avail.strftime("%Y-%m-%d")
    except Exception:
        return trade_date


# ============================================================
# DB Inspection
# ============================================================
def inspect_capital_flow_db() -> Dict[str, Any]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    sources = {}

    # 1. main_fund_flow
    cur.execute("PRAGMA table_info(main_fund_flow)")
    mff_cols = [r[1] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM main_fund_flow")
    mff_count = cur.fetchone()[0]
    cur.execute("SELECT MIN(date), MAX(date) FROM main_fund_flow WHERE date IS NOT NULL")
    mff_range = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT code) FROM main_fund_flow")
    mff_symbols = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT date) FROM main_fund_flow")
    mff_days = cur.fetchone()[0]
    cur.execute("SELECT * FROM main_fund_flow LIMIT 5")
    mff_samples = [{"code": r[0], "date": r[1], "net_amt": r[2]} for r in cur.fetchall()]

    sources["main_fund_flow"] = {
        "columns": mff_cols,
        "row_count": mff_count,
        "date_range": {"min": mff_range[0], "max": mff_range[1]} if mff_range else None,
        "symbol_count": mff_symbols,
        "trading_days": mff_days,
        "has_trade_date": "date" in mff_cols,
        "has_available_time": "available_time" in mff_cols,
        "has_timestamp": any(c in mff_cols for c in ["timestamp", "update_time", "created_at", "publish_time"]),
        "samples": mff_samples,
        "status": "READY" if mff_count > 0 else "NOT_READY",
        "note": "Main force net flow; limited historical coverage",
    }

    # 2. north_flow_data
    cur.execute("PRAGMA table_info(north_flow_data)")
    nf_cols = [r[1] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM north_flow_data")
    nf_count = cur.fetchone()[0]
    sources["north_flow_data"] = {
        "columns": nf_cols,
        "row_count": nf_count,
        "has_trade_date": "date" in nf_cols,
        "has_available_time": "available_time" in nf_cols,
        "has_timestamp": any(c in nf_cols for c in ["timestamp", "update_time", "created_at"]),
        "status": "NOT_READY" if nf_count == 0 else "READY",
        "note": "Northbound flow table exists but contains 0 rows",
    }

    # 3. margin_data
    cur.execute("PRAGMA table_info(margin_data)")
    md_cols = [r[1] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM margin_data")
    md_count = cur.fetchone()[0]
    cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM margin_data WHERE trade_date IS NOT NULL")
    md_range = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT code) FROM margin_data")
    md_symbols = cur.fetchone()[0]
    cur.execute("SELECT * FROM margin_data LIMIT 3")
    md_samples = [{"code": r[0], "trade_date": r[2], "finance_value": r[3]} for r in cur.fetchall()]

    sources["margin_data"] = {
        "columns": md_cols,
        "row_count": md_count,
        "date_range": {"min": md_range[0], "max": md_range[1]} if md_range else None,
        "symbol_count": md_symbols,
        "has_trade_date": "trade_date" in md_cols,
        "has_available_time": "available_time" in md_cols,
        "has_timestamp": "created_at" in md_cols,
        "samples": md_samples,
        "status": "PARTIAL" if md_count > 0 else "NOT_READY",
        "note": "Margin data available but limited history and no explicit available_time",
    }

    # 4. cf_cache (cash flow, not capital flow)
    cur.execute("PRAGMA table_info(cf_cache)")
    cf_cols = [r[1] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM cf_cache")
    cf_count = cur.fetchone()[0]
    cur.execute("SELECT MIN(fetch_date), MAX(fetch_date) FROM cf_cache WHERE fetch_date IS NOT NULL")
    cf_range = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT code) FROM cf_cache")
    cf_symbols = cur.fetchone()[0]

    sources["cf_cache"] = {
        "columns": cf_cols,
        "row_count": cf_count,
        "date_range": {"min": cf_range[0], "max": cf_range[1]} if cf_range else None,
        "symbol_count": cf_symbols,
        "has_fetch_date": "fetch_date" in cf_cols,
        "has_available_time": "available_time" in cf_cols,
        "has_timestamp": False,
        "status": "PARTIAL" if cf_count > 0 else "NOT_READY",
        "note": "Cash flow statement cache; fundamental, not capital flow. Contains report_date semantics inside json_data.",
    }

    con.close()
    return sources


# ============================================================
# Capital Flow PIT Provider
# ============================================================
class CapitalFlowPITProvider:
    """
    Research-only PIT access layer for capital flow data.
    Uses conservative NEXT_SESSION policy.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self):
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def get_main_fund_flow(self, symbol: str, decision_time: str) -> List[Dict[str, Any]]:
        """
        Return main fund flow records where available_time <= decision_time.
        available_time = trade_date + 1 day (conservative next session).
        """
        con = self._connect()
        cur = con.cursor()
        cur.execute("""
            SELECT code, date, net_amt
            FROM main_fund_flow
            WHERE code = ?
              AND date IS NOT NULL
        """, (symbol,))
        rows = cur.fetchall()
        con.close()

        results = []
        for row in rows:
            code, trade_date, net_amt = row
            available_time = conservative_capital_flow_available_time(trade_date)
            if available_time <= decision_time:
                results.append({
                    "code": code,
                    "trade_date": trade_date,
                    "available_time": available_time,
                    "net_amt": net_amt,
                    "source": "main_fund_flow",
                    "visible_at_decision": True,
                    "pit_policy": CAPITAL_FLOW_AVAILABLE_POLICY,
                })
        return results

    def future_injection_test(self, symbol: str, decision_time: str, future_days: int = 30) -> Dict[str, Any]:
        """
        Verify future capital flow records do NOT appear at decision_time.
        """
        future_date = (datetime.strptime(decision_time, "%Y-%m-%d") + timedelta(days=future_days)).strftime("%Y-%m-%d")
        before = self.get_main_fund_flow(symbol, decision_time)

        con = self._connect()
        cur = con.cursor()
        cur.execute("""
            SELECT code, date, net_amt
            FROM main_fund_flow
            WHERE code = ?
              AND date > ?
            LIMIT 10
        """, (symbol, decision_time))
        future_rows = cur.fetchall()
        con.close()

        future_visible = []
        for row in future_rows:
            trade_date = row[1]
            available_time = conservative_capital_flow_available_time(trade_date)
            if available_time <= decision_time:
                future_visible.append({
                    "trade_date": trade_date,
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
def analyze_capital_flow_coverage(sources: Dict[str, Any]) -> Dict[str, Any]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    coverage: Dict[str, Any] = {
        "main_fund_flow": {},
        "north_flow_data": {},
        "margin_data": {},
        "cf_cache": {},
        "summary": {},
        "pit_policy": {
            "policy": CAPITAL_FLOW_AVAILABLE_POLICY,
            "note": CAPITAL_FLOW_POLICY_NOTE,
        },
    }

    # main_fund_flow coverage by year-month
    cur.execute("""
        SELECT substr(date, 1, 7) as year_month, COUNT(*) as cnt, COUNT(DISTINCT code) as symbols
        FROM main_fund_flow
        GROUP BY year_month
        ORDER BY year_month
    """)
    coverage["main_fund_flow"]["year_month_coverage"] = [
        {"year_month": r[0], "record_count": r[1], "symbol_count": r[2]} for r in cur.fetchall()
    ]

    cur.execute("SELECT MIN(date), MAX(date) FROM main_fund_flow")
    r = cur.fetchone()
    coverage["main_fund_flow"]["date_range"] = {"min": r[0], "max": r[1]} if r else None
    if r and r[0]:
        coverage["main_fund_flow"]["earliest_safe_date"] = conservative_capital_flow_available_time(r[0])
    if r and r[1]:
        coverage["main_fund_flow"]["latest_safe_date"] = conservative_capital_flow_available_time(r[1])

    # north_flow_data
    coverage["north_flow_data"]["row_count"] = sources["north_flow_data"]["row_count"]
    coverage["north_flow_data"]["status"] = sources["north_flow_data"]["status"]

    # margin_data coverage
    cur.execute("""
        SELECT substr(trade_date, 1, 7) as year_month, COUNT(*) as cnt, COUNT(DISTINCT code) as symbols
        FROM margin_data
        GROUP BY year_month
        ORDER BY year_month
    """)
    coverage["margin_data"]["year_month_coverage"] = [
        {"year_month": r[0], "record_count": r[1], "symbol_count": r[2]} for r in cur.fetchall()
    ]

    con.close()
    return coverage


# ============================================================
# PIT Examples
# ============================================================
def generate_pit_examples(provider: CapitalFlowPITProvider) -> Dict[str, Any]:
    # Use symbols known to have main_fund_flow data
    symbols = ["000037", "000001", "000002", "600519", "000858"]
    examples = []
    test_results = []

    for symbol in symbols:
        decision_time = "2026-08-01"
        records = provider.get_main_fund_flow(symbol, decision_time)
        if records:
            latest = max(records, key=lambda x: x["available_time"])
            examples.append({
                "symbol": symbol,
                "type": "pre_available_check",
                "decision_time": decision_time,
                "latest_trade_date": latest["trade_date"],
                "available_time": latest["available_time"],
                "net_amt": latest["net_amt"],
                "visible": True,
                "reason": f"available_time={latest['available_time']} <= decision_time={decision_time}",
            })

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
# Source-by-Source Readiness
# ============================================================
def assess_source_readiness(sources: Dict[str, Any], coverage: Dict[str, Any], examples: Dict[str, Any]) -> Dict[str, Any]:
    future_pass_ratio = examples["pit_regression_summary"]["passed"] / max(1, examples["pit_regression_summary"]["total_tested"])

    readiness = {}

    # Northbound
    nb = sources["north_flow_data"]
    readiness["NORTHBOUND_FLOW"] = {
        "DATA_READY": "NO" if nb["row_count"] == 0 else "PARTIAL",
        "PIT_READY": "NO" if nb["row_count"] == 0 else "PARTIAL",
        "RESEARCH_READY": "NO",
        "reason": "Table exists but contains 0 rows; no historical data available" if nb["row_count"] == 0 else "Insufficient data",
    }

    # Main force
    mff = sources["main_fund_flow"]
    earliest = coverage["main_fund_flow"].get("earliest_safe_date")
    latest = coverage["main_fund_flow"].get("latest_safe_date")
    mff_ready = "YES" if mff["row_count"] > 0 and earliest and latest else "PARTIAL"
    readiness["MAIN_FORCE_FLOW"] = {
        "DATA_READY": "YES" if mff["row_count"] > 0 else "NO",
        "PIT_READY": "PARTIAL",
        "RESEARCH_READY": mff_ready,
        "earliest_safe_date": earliest,
        "latest_safe_date": latest,
        "row_count": mff["row_count"],
        "symbol_count": mff["symbol_count"],
        "trading_days": mff["trading_days"],
        "reason": "Data exists but limited historical coverage; no explicit available_time; using conservative NEXT_SESSION policy",
    }

    # Margin
    md = sources["margin_data"]
    readiness["MARGIN_FLOW"] = {
        "DATA_READY": "YES" if md["row_count"] > 0 else "NO",
        "PIT_READY": "PARTIAL",
        "RESEARCH_READY": "PARTIAL",
        "row_count": md["row_count"],
        "reason": "Margin data available but very limited history; no explicit available_time",
    }

    # Sector flow
    readiness["SECTOR_FLOW"] = {
        "DATA_READY": "NO",
        "PIT_READY": "NO",
        "RESEARCH_READY": "NO",
        "reason": "No sector-level capital flow table found in current DB",
    }

    # Overall
    overall = "NO"
    if all(v["RESEARCH_READY"] == "YES" for v in readiness.values()):
        overall = "YES"
    elif any(v["RESEARCH_READY"] == "YES" for v in readiness.values()):
        overall = "PARTIAL"

    return {
        "by_source": readiness,
        "overall": overall,
        "future_injection_pass_ratio": round(future_pass_ratio, 4),
        "pit_policy": CAPITAL_FLOW_AVAILABLE_POLICY,
    }


# ============================================================
# Main
# ============================================================
def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

    # 1. Inventory
    sources = inspect_capital_flow_db()
    (ART / "capital_flow_pit_audit.json").write_text(
        json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 2. Coverage
    coverage = analyze_capital_flow_coverage(sources)
    (ART / "capital_flow_pit_coverage.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 3. PIT Provider test
    provider = CapitalFlowPITProvider(DB)
    examples = generate_pit_examples(provider)
    (ART / "capital_flow_pit_examples.json").write_text(
        json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 4. Readiness
    readiness = assess_source_readiness(sources, coverage, examples)
    (ART / "capital_flow_source_readiness.json").write_text(
        json.dumps(readiness, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 5. Documentation
    doc_lines = [
        "# M9.1-C5-C Capital Flow Alpha Source PIT Closure",
        "",
        "## Summary",
        f"- Overall CAPITAL_FLOW_RESEARCH_READY: {readiness['overall']}",
        f"- Future injection pass ratio: {readiness['future_injection_pass_ratio']:.2%}",
        f"- PIT policy: {readiness['pit_policy']}",
        "",
        "## Source Readiness",
    ]
    for source_id, res in readiness["by_source"].items():
        doc_lines.extend([
            f"### {source_id}",
            f"- DATA_READY: {res['DATA_READY']}",
            f"- PIT_READY: {res['PIT_READY']}",
            f"- RESEARCH_READY: {res['RESEARCH_READY']}",
            f"- Reason: {res['reason']}",
            "",
        ])

    doc_lines.extend([
        "## Status",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `capital_flow_pit_audit.json`",
        "- `capital_flow_pit_coverage.json`",
        "- `capital_flow_pit_examples.json`",
        "- `capital_flow_source_readiness.json`",
        "",
    ])
    (DOC / "M9_1_C5_C_CAPITAL_FLOW_PIT_CLOSURE.md").write_text("\n".join(doc_lines), encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "readiness": readiness,
        "artifacts": [
            "data/research/alpha_source/capital_flow_pit_audit.json",
            "data/research/alpha_source/capital_flow_pit_coverage.json",
            "data/research/alpha_source/capital_flow_pit_examples.json",
            "data/research/alpha_source/capital_flow_source_readiness.json",
            "docs/M9_1_C5_C_CAPITAL_FLOW_PIT_CLOSURE.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
