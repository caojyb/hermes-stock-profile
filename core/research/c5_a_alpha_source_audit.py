#!/usr/bin/env python3
"""
c5_a_alpha_source_audit.py — M9.1-C5-A Independent Alpha Source Coverage & PIT Readiness Audit.

Outputs:
- data/research/alpha_source/alpha_source_readiness.json
- data/research/alpha_source/alpha_source_independence_matrix.json
- data/research/alpha_source/alpha_source_priority.json
- docs/M9_1_C5_A_ALPHA_SOURCE_PIT_READINESS.md
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data/research/alpha_source"
DOC = BASE / "docs"
DB = BASE / "data/production/market_cache.db"
for p in [ART, DOC]:
    p.mkdir(parents=True, exist_ok=True)

ALPHA_SOURCES = [
    {
        "source_id": "PRICE_TECHNICAL",
        "source_family": "Price / Technical",
        "data_source": "market_cache.db: klines",
        "storage": "market_cache.db",
        "historical_coverage": "1991-01-29 to 2026-09-03",
        "available_time": "T+0 close / T+1 open",
        "PIT_status": "PIT_SAFE",
        "frequency": "daily",
        "coverage": "6,128 stock codes",
        "missing_rate": "low for A-share main board; gaps exist for delisted/suspended",
        "symbol_coverage": "broad",
        "known_limitations": "price-only; no corporate action adjustments beyond QFQ/前复权; microstructure not captured",
        "research_ready": True,
        "status": "READY",
        "note": "Core source for current strategy library; orthogonal value limited because all current strategies derive from this family.",
    },
    {
        "source_id": "VOLUME",
        "source_family": "Volume",
        "data_source": "market_cache.db: klines",
        "storage": "market_cache.db",
        "historical_coverage": "1991-01-29 to 2026-09-03",
        "available_time": "T+0 close",
        "PIT_status": "PIT_SAFE",
        "frequency": "daily",
        "coverage": "6,128 stock codes",
        "missing_rate": "low",
        "symbol_coverage": "broad",
        "known_limitations": "volume alone does not carry direction; often redundant with price action",
        "research_ready": True,
        "status": "READY",
        "note": "Used by price_volume variants; independence from PRICE_TECHNICAL is limited.",
    },
    {
        "source_id": "CAPITAL_FLOW",
        "source_family": "Capital Flow",
        "data_source": "market_cache.db: main_fund_flow, north_flow_data, margin_data",
        "storage": "market_cache.db",
        "historical_coverage": {
            "main_fund_flow": "2026-07-17 to 2026-09-04",
            "north_flow_data": "present but 0 rows",
            "margin_data": "2026-08-12 to 2026-09-07",
        },
        "available_time": "T+1 close for prior-day flow estimates",
        "PIT_status": "CONDITIONAL",
        "frequency": "daily",
        "coverage": "partial universe; limited history",
        "missing_rate": "high history gap; coverage not full universe",
        "symbol_coverage": "partial",
        "known_limitations": "North flow empty; margin data short; main fund flow recent only; release timing unclear for historical backtest",
        "research_ready": False,
        "status": "PARTIAL",
        "note": "Potentially orthogonal to price/volume, but historical depth insufficient for walk-forward research.",
    },
    {
        "source_id": "FUNDAMENTAL",
        "source_family": "Fundamental",
        "data_source": "market_cache.db: financial_data, pe_pb_data, cf_cache, equity_pledge",
        "storage": "market_cache.db",
        "historical_coverage": {
            "financial_data": "1988-12-31 to 2026-06-30",
            "pe_pb_data": "recent snapshot",
            "cf_cache": "recent snapshot",
            "equity_pledge": "0 rows",
        },
        "available_time": "report_date + publication lag; varies by quarter",
        "PIT_status": "CONDITIONAL",
        "frequency": "quarterly / snapshot",
        "coverage": "5,187 codes in financial_data",
        "missing_rate": "quarterly gaps; publication lag creates decision_time risk",
        "symbol_coverage": "broad for financial_data; thin for derived tables",
        "known_limitations": "report_date semantics not mapped to available_time in DB; publication lag not modeled; stale fundamentals can leak into T",
        "research_ready": False,
        "status": "PARTIAL",
        "note": "Fundamental alpha can be orthogonal to technicals, but current storage lacks explicit available_time and publication lag handling.",
    },
    {
        "source_id": "NEWS_EVENT",
        "source_family": "News / Event",
        "data_source": "data/quarantine/news_cache.db (empty)",
        "storage": "quarantine",
        "historical_coverage": "none",
        "available_time": "unknown",
        "PIT_status": "UNSAFE",
        "frequency": "event-driven",
        "coverage": "none",
        "missing_rate": "100%",
        "symbol_coverage": "none",
        "known_limitations": "cache exists but contains no tables/rows; event-to-decision_time mapping missing",
        "research_ready": False,
        "status": "NOT_READY",
        "note": "Cannot be used for research until ingestion pipeline and PIT semantics are established.",
    },
    {
        "source_id": "INDUSTRY_SECTOR",
        "source_family": "Industry / Sector",
        "data_source": "market_cache.db: double_up_scores, pipeline_status",
        "storage": "market_cache.db",
        "historical_coverage": "double_up_scores: scan_date coverage present but limited rows; no full historical sector index",
        "available_time": "scan_date + processing lag",
        "PIT_status": "PARTIAL",
        "frequency": "daily / ad-hoc",
        "coverage": "partial; sector score snapshots",
        "missing_rate": "high history gap",
        "symbol_coverage": "partial",
        "known_limitations": "no canonical industry classification table; no full sector return history; relative strength not yet formalized",
        "research_ready": False,
        "status": "PARTIAL",
        "note": "Industry rotation is potentially orthogonal, but lacks structured historical coverage and PIT-ready data.",
    },
    {
        "source_id": "MARKET_BREADTH",
        "source_family": "Market Breadth",
        "data_source": "not present in market_cache.db",
        "storage": "none",
        "historical_coverage": "none",
        "available_time": "N/A",
        "PIT_status": "UNSAFE",
        "frequency": "daily",
        "coverage": "none",
        "missing_rate": "100%",
        "symbol_coverage": "none",
        "known_limitations": "no advance/decline, new-high/new-low, or index breadth series found",
        "research_ready": False,
        "status": "NOT_READY",
        "note": "Breadth is orthogonal to individual stock price/volume, but absent from current storage.",
    },
    {
        "source_id": "REGIME",
        "source_family": "Market Regime",
        "data_source": "core/research/market_context",
        "storage": "runtime module; no historical regime series stored",
        "historical_coverage": "not reconstructed",
        "available_time": "runtime only",
        "PIT_status": "UNSAFE",
        "frequency": "runtime",
        "coverage": "current context only",
        "missing_rate": "N/A",
        "symbol_coverage": "N/A",
        "known_limitations": "regime state is descriptive/runtime; no PIT-safe historical regime time series; cannot be used for walk-forward research yet",
        "research_ready": False,
        "status": "NOT_READY",
        "note": "Current Market Context module does not provide historical regime reconstruction.",
    },
    {
        "source_id": "MACRO_GLOBAL",
        "source_family": "Macro / Global Market",
        "data_source": "not present in market_cache.db",
        "storage": "none",
        "historical_coverage": "none",
        "available_time": "N/A",
        "PIT_status": "UNSAFE",
        "frequency": "daily / monthly",
        "coverage": "none",
        "missing_rate": "100%",
        "symbol_coverage": "none",
        "known_limitations": "no macro series, FX, or global equity indices found in current DB",
        "research_ready": False,
        "status": "NOT_READY",
        "note": "Macro/global is likely orthogonal to stock-specific price/volume, but absent from current storage.",
    },
    {
        "source_id": "SENTIMENT_EVENT",
        "source_family": "Sentiment / Event",
        "data_source": "none",
        "storage": "none",
        "historical_coverage": "none",
        "available_time": "N/A",
        "PIT_status": "UNSAFE",
        "frequency": "event-driven",
        "coverage": "none",
        "missing_rate": "100%",
        "symbol_coverage": "none",
        "known_limitations": "no sentiment scores, news event counts, or announcement flags available",
        "research_ready": False,
        "status": "NOT_READY",
        "note": "Event/sentiment may be orthogonal, but no data source is currently operational.",
    },
    {
        "source_id": "CORPORATE_ACTION",
        "source_family": "Corporate Action",
        "data_source": "market_cache.db: lockup_release, equity_pledge",
        "storage": "market_cache.db",
        "historical_coverage": {
            "lockup_release": "schema present, 0 rows",
            "equity_pledge": "schema present, 0 rows",
        },
        "available_time": "release_date / pledge_date",
        "PIT_status": "CONDITIONAL",
        "frequency": "event-based",
        "coverage": "none in practice",
        "missing_rate": "100% populated tables",
        "symbol_coverage": "none",
        "known_limitations": "tables exist but are empty; corporate action history not ingested",
        "research_ready": False,
        "status": "NOT_READY",
        "note": "Corporate actions can provide orthogonal event alpha, but data ingestion is missing.",
    },
    {
        "source_id": "HOLDER_CHANGE",
        "source_family": "Shareholder Change",
        "data_source": "market_cache.db: holder_change",
        "storage": "market_cache.db",
        "historical_coverage": "2026-08-12 to 2026-09-07",
        "available_time": "change_date + ingestion lag",
        "PIT_status": "PARTIAL",
        "frequency": "daily / event",
        "coverage": "124 rows; partial universe",
        "missing_rate": "high for historical backtest",
        "symbol_coverage": "partial",
        "known_limitations": "very recent coverage only; publication lag and corporate action overlap unclear",
        "research_ready": False,
        "status": "PARTIAL",
        "note": "Holder change may offer orthogonal signal, but history too short for walk-forward.",
    },
    {
        "source_id": "TECHNICAL_INDICATOR",
        "source_family": "Technical Indicator",
        "data_source": "market_cache.db: indicators",
        "storage": "market_cache.db",
        "historical_coverage": "1997-02-28 to 2026-09-03",
        "available_time": "T+0 close",
        "PIT_status": "PIT_SAFE",
        "frequency": "daily",
        "coverage": "5,187 codes",
        "missing_rate": "low for listed universe",
        "symbol_coverage": "broad",
        "known_limitations": "indicators are derived from price/volume; not independent alpha source",
        "research_ready": True,
        "status": "READY",
        "note": "Not orthogonal to PRICE_TECHNICAL; useful as feature transform but not a new information source.",
    },
]


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

    # ------------------------------- readiness
    readiness = {
        "summary": {
            "total_sources": len(ALPHA_SOURCES),
            "ready_count": sum(1 for s in ALPHA_SOURCES if s["status"] == "READY"),
            "partial_count": sum(1 for s in ALPHA_SOURCES if s["status"] == "PARTIAL"),
            "not_ready_count": sum(1 for s in ALPHA_SOURCES if s["status"] == "NOT_READY"),
            "unsafe_count": sum(1 for s in ALPHA_SOURCES if s["PIT_status"] == "UNSAFE"),
        },
        "sources": ALPHA_SOURCES,
    }
    (ART / "alpha_source_readiness.json").write_text(
        json.dumps(readiness, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ------------------------------- independence matrix
    independent_families = {
        "PRICE_TECHNICAL",
        "VOLUME",
        "TECHNICAL_INDICATOR",
    }
    dependent_map = {
        "TECHNICAL_INDICATOR": ["PRICE_TECHNICAL", "VOLUME"],
        "VOLUME": ["PRICE_TECHNICAL"],
        "INDUSTRY_SECTOR": ["PRICE_TECHNICAL", "VOLUME", "TECHNICAL_INDICATOR"],
        "MARKET_BREADTH": ["PRICE_TECHNICAL", "VOLUME"],
        "REGIME": ["PRICE_TECHNICAL", "VOLUME", "TECHNICAL_INDICATOR", "MARKET_BREADTH"],
        "MACRO_GLOBAL": ["PRICE_TECHNICAL", "VOLUME", "TECHNICAL_INDICATOR", "REGIME", "MARKET_BREADTH"],
        "CAPITAL_FLOW": ["PRICE_TECHNICAL", "VOLUME"],
        "FUNDAMENTAL": ["PRICE_TECHNICAL", "VOLUME"],
        "NEWS_EVENT": ["PRICE_TECHNICAL", "VOLUME", "CAPITAL_FLOW", "FUNDAMENTAL"],
        "SENTIMENT_EVENT": ["PRICE_TECHNICAL", "VOLUME", "NEWS_EVENT"],
        "CORPORATE_ACTION": ["PRICE_TECHNICAL", "VOLUME", "FUNDAMENTAL"],
        "HOLDER_CHANGE": ["PRICE_TECHNICAL", "VOLUME", "CORPORATE_ACTION"],
    }
    sources = [s["source_id"] for s in ALPHA_SOURCES]
    matrix = {"summary": {}, "by_source": {}}
    for s in ALPHA_SOURCES:
        sid = s["source_id"]
        deps = dependent_map.get(sid, [])
        orthogonal = [x for x in sources if x != sid and x not in deps]
        matrix["by_source"][sid] = {
            "source_family": s["source_family"],
            "depends_on": deps,
            "potentially_orthogonal_to": orthogonal,
            "status": s["status"],
            "PIT_status": s["PIT_status"],
        }
    matrix["summary"] = {
        "total_sources": len(sources),
        "current_core_dependent_sources": sorted(independent_families),
        "potentially_orthogonal_sources": sorted([sid for sid in sources if sid not in independent_families]),
    }
    (ART / "alpha_source_independence_matrix.json").write_text(
        json.dumps(matrix, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ------------------------------- priority
    priority_rows = []
    for s in ALPHA_SOURCES:
        if s["status"] == "READY" and s["source_id"] not in {"PRICE_TECHNICAL", "VOLUME", "TECHNICAL_INDICATOR"}:
            level = "MEDIUM"
        elif s["status"] == "READY":
            level = "LOW"
        elif s["status"] == "PARTIAL":
            level = "MEDIUM"
        elif s["status"] == "NOT_READY" and s["PIT_status"] == "UNSAFE":
            level = "BLOCKED"
        else:
            level = "LOW"
        priority_rows.append({
            "source_id": s["source_id"],
            "source_family": s["source_family"],
            "status": s["status"],
            "PIT_status": s["PIT_status"],
            "priority": level,
            "rationale": s.get("note", ""),
        })
    priority = {
        "summary": {
            "HIGH": 0,
            "MEDIUM": sum(1 for r in priority_rows if r["priority"] == "MEDIUM"),
            "LOW": sum(1 for r in priority_rows if r["priority"] == "LOW"),
            "BLOCKED": sum(1 for r in priority_rows if r["priority"] == "BLOCKED"),
        },
        "sources": priority_rows,
        "next_alpha_research_source_1": "FUNDAMENTAL",
        "next_alpha_research_source_2": "CAPITAL_FLOW",
        "next_alpha_research_source_3": "INDUSTRY_SECTOR",
    }
    (ART / "alpha_source_priority.json").write_text(
        json.dumps(priority, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ------------------------------- docs
    doc_lines = [
        "# M9.1-C5-A Independent Alpha Source Coverage & PIT Readiness Audit",
        "",
        "## Summary",
        f"- Total sources audited: {len(ALPHA_SOURCES)}",
        f"- READY: {readiness['summary']['ready_count']}",
        f"- PARTIAL: {readiness['summary']['partial_count']}",
        f"- NOT_READY: {readiness['summary']['not_ready_count']}",
        "",
        "## Key Findings",
        "- Current core alpha sources are dominated by price/volume/technical indicators.",
        "- Potentially orthogonal sources exist but are mostly NOT_READY or PARTIAL.",
        "- PIT-unsafe sources: NEWS_EVENT, MARKET_BREADTH, REGIME, MACRO_GLOBAL, SENTIMENT_EVENT.",
        "- Historical coverage is sufficient for price/volume; capital flow/fundamental/industry coverage is limited or PIT-conditional.",
        "",
        "## Next Research Sources",
        "1. FUNDAMENTAL",
        "2. CAPITAL_FLOW",
        "3. INDUSTRY_SECTOR",
        "",
        "## Status",
        "- ALPHA_SOURCE_AUDIT = COMPLETE",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `alpha_source_readiness.json`",
        "- `alpha_source_independence_matrix.json`",
        "- `alpha_source_priority.json`",
        "",
    ]
    (DOC / "M9_1_C5_A_ALPHA_SOURCE_PIT_READINESS.md").write_text("\n".join(doc_lines), encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "ready_count": readiness["summary"]["ready_count"],
        "partial_count": readiness["summary"]["partial_count"],
        "not_ready_count": readiness["summary"]["not_ready_count"],
        "next_sources": priority["next_alpha_research_source_1"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
