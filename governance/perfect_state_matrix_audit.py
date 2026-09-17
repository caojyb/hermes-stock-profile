#!/usr/bin/env python3
"""
Baseline v1.2.1 Perfect-State Matrix Gap Audit（runtime-backed）
READ ONLY / NO MIGRATION / NO DB WRITE / NO CRON MODIFIED / NO SYSTEMD MODIFIED / NO GATEWAY RESTART / AUTO_TRADING=OFF
"""
import os, json, subprocess, sys
from pathlib import Path

REPO = Path("/home/caojy/.hermes/profiles/stock/stock-work")
PROFILE = Path("/home/caojy/.hermes/profiles/stock")
GIT_BRANCH_EXPECTED = "main"

# Ensure governance package is importable
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=REPO)
    return r.stdout.strip(), r.returncode

print("=== GIT STATE ===")
branch, _ = sh("git branch --show-current")
commit, _ = sh("git rev-parse HEAD")
tag, _ = sh("git tag --points-at HEAD")
status, _ = sh("git status --porcelain")
wt_status = "CLEAN" if not status else "DIRTY"
print(f"branch: {branch}")
print(f"commit: {commit}")
print(f"tag_at_head: {tag}")
print(f"working_tree: {wt_status}")
print(f"status_lines: {len(status.splitlines())}")

print("\n=== PERFECT-STATE MATRIX AUDIT ===")
matrix = {}

# Helper: runtime-first audit
import importlib.util
_rv_spec = importlib.util.spec_from_file_location("runtime_state_matrix_verification", str(REPO / "governance/runtime_state_matrix_verification.py"))
_rv_mod = importlib.util.module_from_spec(_rv_spec)
_rv_spec.loader.exec_module(_rv_mod)
_rv = _rv_mod.RuntimeVerifier()

checks = {
    "Market": _rv.verify_market,
    "Risk": _rv.verify_risk,
    "Opportunity": _rv.verify_opportunity,
    "Evidence": _rv.verify_evidence,
    "PIT": _rv.verify_pit,
    "Entry": _rv.verify_entry,
    "Sizing": _rv.verify_sizing,
    "Tradability": _rv.verify_tradability,
    "Constraints": _rv.verify_constraints,
    "Policy": _rv.verify_policy,
    "DecisionEngine": _rv.verify_decision_engine,
    "Recommendation": _rv.verify_recommendation,
    "Simulation": _rv.verify_simulation,
    "SimulationExecution": _rv.verify_simulation_execution,
    "SimulationPortfolio": _rv.verify_simulation_portfolio,
    "Real": _rv.verify_real,
    "ExecutionFeedback": _rv.verify_execution_feedback,
    "RealPortfolio": _rv.verify_real_portfolio,
    "Outcome": _rv.verify_outcome,
    "Attribution": _rv.verify_attribution,
    "Learning": _rv.verify_learning,
    "Research": _rv.verify_research,
    "Quality": _rv.verify_quality,
    "Promotion": _rv.verify_promotion,
    "Reproducibility": _rv.verify_reproducibility,
    "Rollback": _rv.verify_rollback,
    "Config": _rv.verify_config,
    "Cron": _rv.verify_cron,
    "Failure": _rv.verify_failure,
    "ProductOutput": _rv.verify_product_output,
}

labels = {
    "Market": "可形成 Market Regime",
    "Risk": "可形成 Risk Mode",
    "Opportunity": "可进入 Investment Policy",
    "Evidence": "有 provenance / as_of / availability",
    "PIT": "available_time <= decision_time",
    "Entry": "独立 Entry Contract",
    "Sizing": "Policy / Account / Execution 三层分离",
    "Tradability": "覆盖 A 股交易关键条件",
    "Constraints": "Registry + domain",
    "Policy": "有明确版本",
    "DecisionEngine": "唯一 Hard Constraint 仲裁器",
    "Recommendation": "可完整追溯",
    "Simulation": "自动执行",
    "SimulationExecution": "确定性、可重放",
    "SimulationPortfolio": "与 Simulation Fill 一致",
    "Real": "人工执行",
    "ExecutionFeedback": "Execution Record",
    "RealPortfolio": "Canonical Truth",
    "Outcome": "Decision→Execution→Outcome",
    "Attribution": "可分析经济贡献",
    "Learning": "不绕过 Promotion",
    "Research": "与 Production 隔离",
    "Quality": "有统一测量方法",
    "Promotion": "有版本化流程",
    "Reproducibility": "有 Manifest",
    "Rollback": "Code + Policy 成对回滚",
    "Config": "Versioned",
    "Cron": "有生命周期职责",
    "Failure": "有显式 Fail-Safe",
    "ProductOutput": "回答买什么/什么时候/买多少/什么时候卖",
}

for key, fn in checks.items():
    try:
        result = fn()
        status = result.get("status", "PARTIALLY")
        detail = result.get("detail") or result.get("blocker") or ""
        matrix[key] = status
        print(f"{key} ({labels.get(key, key)}): {status} - runtime:{detail}")
    except Exception as e:
        matrix[key] = "PARTIALLY"
        print(f"{key} ({labels.get(key, key)}): PARTIALLY - runtime_error:{e}")

print("\n=== MATRIX SUMMARY ===")
for k, v in matrix.items():
    print(f"{k}: {v}")

from collections import Counter
c = Counter(matrix.values())
print(f"\nTotal: {len(matrix)}, SATISFIED: {c.get('SATISFIED',0)}, PARTIALLY: {c.get('PARTIALLY',0)}, MISSING: {c.get('MISSING',0)}")
