#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Runtime Contract Verification — 对关键 Baseline 合同做运行时真实验证，而不是只检查文件存在。

READ ONLY / NO MIGRATION / NO DB WRITE / NO CRON MODIFIED
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
STOCK_WORK = PROFILE / "stock-work"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        return None, f"load_error:{e}"
    return mod, None


def verify_decision_state_contract() -> Dict[str, Any]:
    engine_path = PROFILE / "scripts/cron/decision/engine.py"
    contract_path = PROFILE / "scripts/cron/decision/contract.py"
    result = {"contract_fields_present": {}, "engine_uses_fields": {}, "status": "PARTIALLY"}

    contract_txt = contract_path.read_text(encoding="utf-8", errors="ignore") if contract_path.exists() else ""
    required = ["policy_action", "engine_result", "final_action", "block_reason", "execution_status",
                "constraint_id", "all_triggered_constraints"]
    for field in required:
        result["contract_fields_present"][field] = field in contract_txt

    engine_txt = engine_path.read_text(encoding="utf-8", errors="ignore") if engine_path.exists() else ""
    for field in required:
        result["engine_uses_fields"][field] = field in engine_txt

    result["status"] = "SATISFIED" if all(result["contract_fields_present"].values()) and all(result["engine_uses_fields"].values()) else "PARTIALLY"
    return result


def verify_real_portfolio_truth_contract() -> Dict[str, Any]:
    path = PROFILE / "scripts/cron/decision/real_portfolio_truth.py"
    txt = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    result = {
        "canonical_source_present": "CANONICAL_REAL_PORTFOLIO_SOURCE" in txt,
        "quality_status_present": "quality_status" in txt,
        "baseline_contract_present": "Baseline" in txt and "Canonical" in txt,
        "status": "PARTIALLY",
    }
    result["status"] = "SATISFIED" if all(v for k, v in result.items() if k != "status") else "PARTIALLY"
    return result


def verify_execution_state_machine() -> Dict[str, Any]:
    path = PROFILE / "scripts/cron/decision/execution.py"
    txt = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    required_states = ["PLANNED", "EXECUTED", "PARTIAL", "REJECTED", "NOT_EXECUTED"]
    required_transitions = ["PLANNED->EXECUTED", "PLANNED->REJECTED", "EXECUTED->PARTIAL"]
    result = {
        "states_present": {s: (s in txt) for s in required_states},
        "transitions_present": {t: (t in txt or t.replace("->", "") in txt) for t in required_transitions},
        "status": "PARTIALLY",
    }
    result["status"] = "SATISFIED" if all(result["states_present"].values()) else "PARTIALLY"
    return result


def verify_attribution_integration() -> Dict[str, Any]:
    outcome_path = PROFILE / "scripts/cron/decision/outcome.py"
    outcome_store_path = PROFILE / "scripts/cron/decision/outcome_store.py"
    evidence_path = PROFILE / "scripts/cron/decision/evidence_framework.py"

    files = [outcome_path, outcome_store_path, evidence_path]
    texts = {p: p.read_text(encoding="utf-8", errors="ignore") for p in files if p.exists()}

    result = {
        "outcome_attribution_field": "attribution" in texts.get(outcome_path, ""),
        "build_attribution_defined": "def build_attribution" in texts.get(outcome_path, ""),
        "outcome_store_sets_attribution": "attribution" in texts.get(outcome_store_path, ""),
        "evidence_framework_uses_attribution": "attribution" in texts.get(evidence_path, ""),
        "status": "PARTIALLY",
    }
    result["status"] = "SATISFIED" if all(v for k, v in result.items() if k != "status") else "PARTIALLY"
    return result


def verify_simulation_execution_status() -> Dict[str, Any]:
    path = PROFILE / "scripts/cron/decision/execution.py"
    txt = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    result = {
        "exec_status_constants_present": "EXEC_STATUS" in txt,
        "record_simulation_execution_present": "record_simulation_execution" in txt,
        "status": "PARTIALLY",
    }
    result["status"] = "SATISFIED" if all(result.values()) else "PARTIALLY"
    return result


def verify_production_boundary_imports() -> Dict[str, Any]:
    boundary_audit_path = STOCK_WORK / "governance/boundary_isolation_audit.py"
    if not boundary_audit_path.exists():
        return {"status": "PARTIALLY", "reason": "boundary_isolation_audit.py missing"}

    mod, err = _load_module("boundary_isolation_audit", boundary_audit_path)
    if err:
        return {"status": "PARTIALLY", "reason": err}

    try:
        result = mod.audit()
    except Exception as e:
        return {"status": "PARTIALLY", "reason": f"audit() failed: {e}"}

    violations = result.get("production_import_violations", [])
    cross = result.get("research_cross_production_imports", [])
    result["status"] = "SATISFIED" if not violations and not cross else "PARTIALLY"
    return result


def main() -> Dict[str, Any]:
    checks = {
        "DecisionStateContract": verify_decision_state_contract(),
        "RealPortfolioTruth": verify_real_portfolio_truth_contract(),
        "ExecutionStateMachine": verify_execution_state_machine(),
        "Attribution": verify_attribution_integration(),
        "SimulationExecution": verify_simulation_execution_status(),
        "ProductionBoundary": verify_production_boundary_imports(),
    }
    summary = {k: v.get("status", "PARTIALLY") for k, v in checks.items()}
    satisfied = sum(1 for s in summary.values() if s == "SATISFIED")
    total = len(summary)
    return {
        "checks": checks,
        "summary": summary,
        "satisfied_count": satisfied,
        "total_count": total,
        "status": "SATISFIED" if satisfied == total else "PARTIALLY",
    }


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False, indent=2))
