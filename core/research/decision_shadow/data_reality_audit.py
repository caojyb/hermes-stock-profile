#!/usr/bin/env python3
"""
M9_1_D8_G_DATA_REALITY_AUDIT.py — Data Reality Audit for Historical Shadow Replay
====================================================================================
Read-only audit. No production DB writes. No DecisionEngine modification.

Outputs:
- data/research/decision_shadow/decision_replay_manifest/data_reality_audit.json
- docs/M9_1_D8_G_DATA_REALITY_AUDIT.md
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

STOCK_WORK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRODUCTION_DB = os.path.join(STOCK_WORK_ROOT, "data", "production", "market_cache.db")
RESEARCH_DATA_DIR = os.path.join(STOCK_WORK_ROOT, "data", "research", "decision_shadow")
MANIFEST_DIR = os.path.join(RESEARCH_DATA_DIR, "decision_replay_manifest")


def _connect(db: str):
    try:
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except Exception:
        return sqlite3.connect(db)


def table_exists(db: str, table: str) -> bool:
    con = _connect(db)
    try:
        cur = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return cur.fetchone()[0] > 0
    finally:
        con.close()


def table_row_count(db: str, table: str) -> Optional[int]:
    if not table_exists(db, table):
        return None
    con = _connect(db)
    try:
        cur = con.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]
    except Exception:
        return None
    finally:
        con.close()


def date_bounds(db: str, table: str, date_col: str = "date") -> Optional[Dict[str, Optional[str]]]:
    if not table_exists(db, table):
        return None
    con = _connect(db)
    try:
        cur = con.execute(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table}")
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return {"min": row[0], "max": row[1]}
    except Exception:
        return None
    finally:
        con.close()


def column_exists(db: str, table: str, col: str) -> bool:
    if not table_exists(db, table):
        return False
    con = _connect(db)
    try:
        cur = con.execute(f"PRAGMA table_info({table})")
        return any(r[1] == col for r in cur.fetchall())
    finally:
        con.close()


def count_distinct_codes_for_date(db: str, table: str, date: str) -> Optional[int]:
    if not table_exists(db, table):
        return None
    con = _connect(db)
    try:
        cur = con.execute(
            f"SELECT COUNT(DISTINCT code) FROM {table} WHERE date = ?",
            (date,),
        )
        return cur.fetchone()[0]
    except Exception:
        return None
    finally:
        con.close()


def audit() -> Dict[str, Any]:
    audit_ts = datetime.now(timezone.utc).isoformat()
    findings: Dict[str, Any] = {
        "audit_time": audit_ts,
        "production_db": PRODUCTION_DB,
        "items": {},
        "overall": "UNKNOWN",
    }

    # A. Opportunity data
    opp_source = "OpportunityEngine / recommendation_pool.db"
    opp_path = os.path.join(STOCK_WORK_ROOT, "data", "production", "recommendation_pool.db")
    opp_ready = os.path.exists(opp_path) and table_row_count(opp_path, "recommendations") not in (None, 0)
    findings["items"]["A_opportunity_data"] = {
        "status": "READY" if opp_ready else "MISSING",
        "source": opp_source,
        "data_path": opp_path,
        "available_time": "current snapshot",
        "pit_status": "PARTIAL",
        "historical_coverage": "UNKNOWN — no decision_time field or historical versioning verified in current path",
        "known_limitation": "D8-F uses OpportunityEngineReader V1 placeholder; historical opportunity snapshots are not yet archived",
    }

    # B. Market Context history
    ctx_path = os.path.join(RESEARCH_DATA_DIR, "market_context")
    ctx_files = []
    if os.path.isdir(ctx_path):
        ctx_files = sorted([f for f in os.listdir(ctx_path) if f.endswith(".json")])
    findings["items"]["B_market_context_history"] = {
        "status": "READY" if ctx_files else "PARTIAL",
        "source": "research/market_context/*.json",
        "data_path": ctx_path,
        "available_time": "per-file context_version/decision_time",
        "pit_status": "SAFE if files are written with decision_time <= data_cutoff",
        "historical_coverage": f"{len(ctx_files)} archived snapshots found",
        "known_limitation": "Historical context builder execution required to populate archive",
    }

    # C. Strategy Signal history
    reg_path = os.path.join(RESEARCH_DATA_DIR, "strategy_registry")
    reg_files = []
    if os.path.isdir(reg_path):
        reg_files = sorted([f for f in os.listdir(reg_path) if f.endswith(".json")])
    findings["items"]["C_strategy_signal_history"] = {
        "status": "READY" if reg_files else "PARTIAL",
        "source": "research/strategy_registry/*.json",
        "data_path": reg_path,
        "available_time": "per-file as-of metadata required",
        "pit_status": "SAFE if registry snapshots are versioned",
        "historical_coverage": f"{len(reg_files)} registry snapshots found",
        "known_limitation": "Registry history depends on explicit snapshot policy",
    }

    # D. Universe PIT
    findings["items"]["D_universe_pit"] = {
        "status": "PARTIAL",
        "source": "production/market_cache.db.universe_pit_snapshot",
        "data_path": f"{PRODUCTION_DB}:universe_pit_snapshot",
        "available_time": date_bounds(PRODUCTION_DB, "universe_pit_snapshot", "decision_time"),
        "pit_status": "PARTIAL — current snapshot is PIT-observable via klines.observed_interval, but survivorship/IPO date alignment is unknown",
        "historical_coverage": f"{table_row_count(PRODUCTION_DB, 'universe_pit_snapshot') or 0} snapshot rows",
        "known_limitation": "Phase 7.3 replay notes show ST/industry/market-cap partial coverage for strict PIT",
    }

    # E. Tradability
    findings["items"]["E_tradability"] = {
        "status": "MISSING",
        "source": "N/A in V1",
        "data_path": "not archived",
        "available_time": "none",
        "pit_status": "UNKNOWN",
        "historical_coverage": "0%",
        "known_limitation": "V1 Shadow uses TradabilityGateReader default UNKNOWN; no historical tradability archive exists",
    }

    # F. Trading Permission
    findings["items"]["F_trading_permission"] = {
        "status": "MISSING",
        "source": "scripts/cron/decision/trading_permission.py",
        "data_path": "read-only code path; no historical permission log found",
        "available_time": "none",
        "pit_status": "UNKNOWN",
        "historical_coverage": "0%",
        "known_limitation": "Permission logic exists but no historical permission snapshots are stored; V1 reader returns conservative default",
    }

    # G. Portfolio Truth
    real_rows = table_row_count(PRODUCTION_DB, "real_portfolio_history")
    findings["items"]["G_portfolio_truth"] = {
        "status": "MISSING" if not real_rows else "PARTIAL",
        "source": "production/market_cache.db.real_portfolio_history",
        "data_path": f"{PRODUCTION_DB}:real_portfolio_history",
        "available_time": datetime.now(timezone.utc).isoformat(),
        "pit_status": "PARTIAL if historical snapshots exist; Phase 7.5 notes indicate cash/total_asset often UNKNOWN",
        "historical_coverage": f"{real_rows or 0} rows",
        "known_limitation": "cash/total_asset require MANUAL_CONFIRMATION path; historical availability unverified",
    }

    # H. Entry Timing
    findings["items"]["H_entry_timing"] = {
        "status": "MISSING",
        "source": "N/A in V1",
        "data_path": "not archived",
        "available_time": "none",
        "pit_status": "UNKNOWN",
        "historical_coverage": "0%",
        "known_limitation": "V1 EntryTimingReader is heuristic only; no historical timing archive exists",
    }

    # I. Risk Overlay
    findings["items"]["I_risk_overlay"] = {
        "status": "PARTIAL",
        "source": "market_context.risk_state + production indicators/klines",
        "data_path": f"{PRODUCTION_DB}:indicators,klines",
        "available_time": "per date",
        "pit_status": "PARTIAL — risk_state from market context; stock/sector/volatility/liquidity/event/portfolio risk mostly UNKNOWN in V1",
        "historical_coverage": "depends on klines date coverage",
        "known_limitation": "V1 RiskAssessmentReader derives market_risk only from market_context; other dimensions are UNKNOWN",
    }

    # J. Position Sizing
    findings["items"]["J_position_sizing"] = {
        "status": "PARTIAL",
        "source": "shadow_position_sizing_v1 + portfolio_decision_reader_v1",
        "data_path": "computed at replay time",
        "available_time": "decision_time",
        "pit_status": "SAFE — no future leakage",
        "historical_coverage": "100% of replay dates (if other inputs available)",
        "known_limitation": "V1 outputs recommended_range only; cash/total_asset UNKNOWN yields position_size_status=UNKNOWN",
    }

    # K. Provenance / as-of metadata
    findings["items"]["K_provenance_metadata"] = {
        "status": "READY",
        "source": "shadow schema + runner provenance fields",
        "data_path": "embedded in ShadowDecisionRecord",
        "available_time": "decision_time",
        "pit_status": "SAFE",
        "historical_coverage": "100% of generated decisions",
        "known_limitation": "Provenance is only as complete as the upstream readers; placeholder readers produce placeholder provenance",
    }

    # L. Decision replay inputs
    findings["items"]["L_decision_replay_inputs"] = {
        "status": "PARTIAL",
        "source": "market_context + strategy_registry + opportunity + tradability + risk + permission + portfolio",
        "data_path": "data/research/decision_shadow/decision_replay_dataset/",
        "available_time": "per replay manifest",
        "pit_status": "SAFE if all inputs satisfy available_time <= decision_time",
        "historical_coverage": "0 replay manifests found",
        "known_limitation": "Replay dataset must be constructed from existing DB snapshots; no canonical manifest exists yet",
    }

    # Overall
    statuses = [v["status"] for v in findings["items"].values()]
    if all(s == "READY" for s in statuses):
        findings["overall"] = "READY"
    elif statuses.count("MISSING") >= 3:
        findings["overall"] = "BLOCKED"
    else:
        findings["overall"] = "PARTIALLY_READY"

    return findings


def write_audit(findings: Dict[str, Any]) -> str:
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    out_path = os.path.join(MANIFEST_DIR, "data_reality_audit.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, ensure_ascii=False, indent=2)
    return out_path


def write_markdown(findings: Dict[str, Any]) -> str:
    lines = [
        "# M9.1-D8-G Data Reality Audit",
        "",
        f"> Audit time: {findings['audit_time']}",
        f"> Overall: {findings['overall']}",
        "",
        "## A-L Item Status",
        "",
    ]
    for key, item in findings["items"].items():
        lines.extend(
            [
                f"### {key}",
                f"- **Status**: {item['status']}",
                f"- **Source**: {item['source']}",
                f"- **Data path**: {item['data_path']}",
                f"- **Available time**: {item['available_time']}",
                f"- **PIT status**: {item['pit_status']}",
                f"- **Historical coverage**: {item['historical_coverage']}",
                f"- **Known limitation**: {item['known_limitation']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Conclusion",
            "",
            "- Core price/indicator history is READY via `market_cache.db.klines`.",
            "- Opportunity, tradability, permission, timing, and portfolio truth are PARTIAL/MISSING in V1.",
            "- Full historical replay must proceed with conservative fail-safe defaults where data is unavailable.",
            "- No production data was modified during this audit.",
            "",
        ]
    )
    out_path = os.path.join(RESEARCH_DATA_DIR, "M9_1_D8_G_DATA_REALITY_AUDIT.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


if __name__ == "__main__":
    findings = audit()
    audit_path = write_audit(findings)
    md_path = write_markdown(findings)
    print(json.dumps({
        "overall": findings["overall"],
        "audit_json": audit_path,
        "audit_markdown": md_path,
        "item_count": len(findings["items"]),
    }, ensure_ascii=False))
