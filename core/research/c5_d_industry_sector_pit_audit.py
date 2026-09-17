#!/usr/bin/env python3
"""
c5_d_industry_sector_pit_audit.py — M9.1-C5-D Industry / Sector Alpha Source PIT Closure.

Inputs:
- market_cache.db tables: stocks, double_up_scores, universe_pit_snapshot

Outputs:
- data/research/alpha_source/industry_pit_audit.json
- data/research/alpha_source/industry_pit_coverage.json
- data/research/alpha_source/industry_pit_examples.json
- data/research/alpha_source/industry_source_readiness.json
- docs/M9_1_C5_D_INDUSTRY_SECTOR_PIT_CLOSURE.md

This is RESEARCH ONLY. No production schema changes. No strategy generation.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data/research/alpha_source"
DOC = BASE / "docs"
DB = BASE / "data/production/market_cache.db"

for p in [ART, DOC]:
    p.mkdir(parents=True, exist_ok=True)


def inspect_industry_db() -> Dict[str, Any]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    result: Dict[str, Any] = {
        "stocks_table": {},
        "double_up_scores_table": {},
        "universe_pit_table": {},
        "summary": {},
    }

    # stocks table
    cur.execute("PRAGMA table_info(stocks)")
    stocks_cols = [r[1] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM stocks")
    stocks_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT sector) FROM stocks WHERE sector IS NOT NULL")
    sector_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT sw_industry_code) FROM stocks WHERE sw_industry_code IS NOT NULL")
    sw_industry_count = cur.fetchone()[0]
    cur.execute("SELECT MIN(updated_at), MAX(updated_at) FROM stocks WHERE updated_at IS NOT NULL")
    updated_range = cur.fetchone()
    cur.execute("SELECT * FROM stocks LIMIT 5")
    stocks_samples = [{"code": r[0], "name": r[1], "sector": r[3], "sw_industry_code": r[6], "sw_industry_name": r[7], "updated_at": r[5]} for r in cur.fetchall()]

    result["stocks_table"] = {
        "columns": stocks_cols,
        "row_count": stocks_count,
        "sector_count": sector_count,
        "sw_industry_count": sw_industry_count,
        "updated_at_range": {"min": updated_range[0], "max": updated_range[1]} if updated_range else None,
        "has_effective_date": "effective_date" in stocks_cols,
        "has_available_time": "available_time" in stocks_cols,
        "has_classification_version": "classification_version" in stocks_cols,
        "has_valid_from": "valid_from" in stocks_cols,
        "has_valid_to": "valid_to" in stocks_cols,
        "samples": stocks_samples,
        "status": "PARTIAL",
        "note": "Current classification only; no historical versioning or effective_date",
    }

    # double_up_scores table
    cur.execute("PRAGMA table_info(double_up_scores)")
    dup_cols = [r[1] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM double_up_scores")
    dup_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT sector) FROM double_up_scores WHERE sector IS NOT NULL")
    dup_sectors = cur.fetchone()[0]
    cur.execute("SELECT MIN(scan_date), MAX(scan_date) FROM double_up_scores WHERE scan_date IS NOT NULL")
    dup_range = cur.fetchone()

    result["double_up_scores_table"] = {
        "columns": dup_cols,
        "row_count": dup_count,
        "sector_count": dup_sectors,
        "scan_date_range": {"min": dup_range[0], "max": dup_range[1]} if dup_range else None,
        "has_effective_date": "effective_date" in dup_cols,
        "has_available_time": "available_time" in dup_cols,
        "status": "PARTIAL",
        "note": "Sector scores are derived/aggregated; not canonical membership",
    }

    # universe_pit_snapshot
    cur.execute("SELECT COUNT(*) FROM universe_pit_snapshot")
    universe_count = cur.fetchone()[0]
    result["universe_pit_table"] = {
        "row_count": universe_count,
        "has_decision_time": True,
        "has_effective_start": True,
        "has_effective_end": True,
        "has_available_at": True,
        "note": "Universe PIT exists but for stock universe, not industry membership",
    }

    con.close()
    return result


def analyze_industry_coverage() -> Dict[str, Any]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    coverage: Dict[str, Any] = {
        "stocks_table": {},
        "double_up_scores_table": {},
        "summary": {},
    }

    # stocks coverage
    cur.execute("SELECT COUNT(DISTINCT sector) FROM stocks WHERE sector IS NOT NULL")
    coverage["stocks_table"]["sector_count"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT sw_industry_code) FROM stocks WHERE sw_industry_code IS NOT NULL")
    coverage["stocks_table"]["industry_count"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM stocks WHERE sector IS NOT NULL")
    coverage["stocks_table"]["assigned_count"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM stocks WHERE sector IS NULL")
    coverage["stocks_table"]["unassigned_count"] = cur.fetchone()[0]

    # Sector distribution
    cur.execute("""
        SELECT sector, COUNT(*) as cnt
        FROM stocks
        WHERE sector IS NOT NULL
        GROUP BY sector
        ORDER BY cnt DESC
        LIMIT 20
    """)
    coverage["stocks_table"]["top_sectors"] = [{"sector": r[0], "count": r[1]} for r in cur.fetchall()]

    # Historical membership check: look for any table with effective_date
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%industry%' OR name LIKE '%sector%' OR name LIKE '%classif%')")
    related_tables = [r[0] for r in cur.fetchall()]
    coverage["related_tables_found"] = related_tables
    coverage["historical_membership_available"] = False
    for t in related_tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cur.fetchall()]
        if any(c in cols for c in ["effective_date", "valid_from", "valid_to", "available_time", "classification_version"]):
            coverage["historical_membership_available"] = True
            break

    con.close()
    return coverage


def assess_industry_readiness(inventory: Dict[str, Any], coverage: Dict[str, Any]) -> Dict[str, Any]:
    has_historical = coverage.get("historical_membership_available", False)
    stocks = inventory.get("stocks_table", {})

    data_ready = "YES" if stocks.get("row_count", 0) > 0 else "NO"
    pit_ready = "NO" if not has_historical else "PARTIAL"
    research_ready = "NO"
    historical_membership_ready = "NO"

    if data_ready == "YES" and has_historical:
        research_ready = "PARTIAL"
        historical_membership_ready = "PARTIAL"
    elif data_ready == "YES" and not has_historical:
        research_ready = "NO"
        historical_membership_ready = "NO"
    else:
        research_ready = "NO"
        historical_membership_ready = "NO"

    return {
        "INDUSTRY_DATA_READY": data_ready,
        "INDUSTRY_PIT_READY": pit_ready,
        "INDUSTRY_RESEARCH_READY": research_ready,
        "HISTORICAL_MEMBERSHIP_READY": historical_membership_ready,
        "sector_count": stocks.get("sector_count", 0),
        "industry_count": stocks.get("industry_count", 0),
        "assigned_symbols": stocks.get("assigned_count", 0),
        "unassigned_symbols": stocks.get("unassigned_count", 0),
        "has_historical_membership_table": has_historical,
        "related_tables": coverage.get("related_tables_found", []),
        "pit_policy": "CONSERVATIVE_CURRENT_MEMBERSHIP",
        "pit_note": "No historical industry membership table with effective_date/available_time found. Current classification cannot be safely backfilled to historical decision dates.",
        "next_alpha_source": "INDUSTRY_SECTOR remains blocked; proceed to CAPITAL_FLOW refinement or new data acquisition",
    }


def generate_industry_examples() -> Dict[str, Any]:
    symbols = ["000001", "000002", "600519", "000858", "601318"]
    examples = []
    for symbol in symbols:
        examples.append({
            "symbol": symbol,
            "type": "current_membership_check",
            "decision_time": "2025-01-01",
            "current_sector": "unknown_without_db_query",
            "current_industry": "unknown_without_db_query",
            "historical_sector": "UNAVAILABLE",
            "historical_industry": "UNAVAILABLE",
            "visible": False,
            "reason": "No historical membership table with effective_date",
        })
    return {
        "examples": examples,
        "note": "Cannot generate meaningful PIT examples without historical membership data",
    }


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

    # 1. Inventory
    inventory = inspect_industry_db()
    (ART / "industry_pit_audit.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 2. Coverage
    coverage = analyze_industry_coverage()
    (ART / "industry_pit_coverage.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 3. Examples
    examples = generate_industry_examples()
    (ART / "industry_pit_examples.json").write_text(
        json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 4. Readiness
    readiness = assess_industry_readiness(inventory, coverage)
    (ART / "industry_source_readiness.json").write_text(
        json.dumps(readiness, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 5. Documentation
    doc_lines = [
        "# M9.1-C5-D Industry / Sector Alpha Source PIT Closure",
        "",
        "## Summary",
        f"- INDUSTRY_DATA_READY: {readiness['INDUSTRY_DATA_READY']}",
        f"- INDUSTRY_PIT_READY: {readiness['INDUSTRY_PIT_READY']}",
        f"- INDUSTRY_RESEARCH_READY: {readiness['INDUSTRY_RESEARCH_READY']}",
        f"- HISTORICAL_MEMBERSHIP_READY: {readiness['HISTORICAL_MEMBERSHIP_READY']}",
        "",
        "## Key Findings",
        f"- stocks table has current sector/industry for {readiness['assigned_symbols']} symbols",
        f"- No historical industry membership table with effective_date/available_time found",
        f"- Related tables: {readiness['related_tables']}",
        f"- PIT policy: {readiness['pit_policy']}",
        "",
        "## Status",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `industry_pit_audit.json`",
        "- `industry_pit_coverage.json`",
        "- `industry_pit_examples.json`",
        "- `industry_source_readiness.json`",
        "",
    ]
    (DOC / "M9_1_C5_D_INDUSTRY_SECTOR_PIT_CLOSURE.md").write_text("\n".join(doc_lines), encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "readiness": readiness,
        "artifacts": [
            "data/research/alpha_source/industry_pit_audit.json",
            "data/research/alpha_source/industry_pit_coverage.json",
            "data/research/alpha_source/industry_pit_examples.json",
            "data/research/alpha_source/industry_source_readiness.json",
            "docs/M9_1_C5_D_INDUSTRY_SECTOR_PIT_CLOSURE.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
