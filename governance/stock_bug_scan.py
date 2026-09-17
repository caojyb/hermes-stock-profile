#!/usr/bin/env python3
"""
stock_bug_scan.py
大范围 bug/regression 扫描：路径、import、数据表、合同字段、cron、gateway
只读扫描，不修改任何文件。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
REPO = PROFILE / "stock-work"
SCRIPTS = PROFILE / "scripts/cron"

PYTHON = sys.executable

issues = []

def add(sev, category, msg):
    issues.append({"severity": sev, "category": category, "msg": msg})

# 1. 关键表存在性与行数
def check_tables():
    db = REPO / "data/production/market_cache.db"
    try:
        conn = sqlite3.connect(db, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {r[0] for r in cur.fetchall()}
        required = {"klines", "financial_data", "indicators", "pe_pb_data", "stocks", "double_up_scores", "main_fund_flow", "north_flow_data", "chip_data", "margin_data"}
        missing = required - tables
        if missing:
            add("HIGH", "database", f"MARKET_DB missing tables: {missing}")
        else:
            print("[OK] MARKET_DB required tables present")
        # 行数
        for t in ["klines", "financial_data", "indicators", "double_up_scores"]:
            if t in tables:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                n = cur.fetchone()[0]
                print(f"[OK] {t}: {n} rows")
        conn.close()
    except Exception as e:
        add("HIGH", "database", f"MARKET_DB error: {e}")

# 2. 核心模块可导入性
def _try_import(module_path: str):
    full_path = PROFILE / module_path
    if not full_path.exists():
        return None, f"missing:{module_path}"

    if module_path.startswith("scripts/cron/decision/") or module_path == "scripts/cron/decision/__init__.py":
        decision_pkg_path = PROFILE / "scripts/cron/decision"
        if str(decision_pkg_path) not in sys.path:
            sys.path.insert(0, str(decision_pkg_path.parent))
        pkg_name = "decision"
        if pkg_name not in sys.modules:
            pkg_path = decision_pkg_path / "__init__.py"
            if pkg_path.exists():
                spec = importlib.util.spec_from_file_location(pkg_name, str(pkg_path))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[pkg_name] = mod
                spec.loader.exec_module(mod)
            else:
                import types
                pkg_mod = types.ModuleType(pkg_name)
                pkg_mod.__path__ = [str(decision_pkg_path)]
                sys.modules[pkg_name] = pkg_mod

        mod_name = module_path.split("/")[-1].replace(".py", "")
        full_mod_name = f"decision.{mod_name}"
        if full_mod_name in sys.modules:
            return sys.modules[full_mod_name], None
        try:
            mod = importlib.import_module(full_mod_name)
            return mod, None
        except Exception as e:
            return None, f"load_error:{e}"

    if "skills/stock/stock-expert" in module_path:
        skills_base = PROFILE / "skills"
        if str(skills_base) not in sys.path:
            sys.path.insert(0, str(skills_base))
        parts = module_path.replace("skills/stock/stock-expert/skills/feishu-bitable/", "").replace(".py", "")
        if not parts:
            return None, "invalid_module_path"
        full_mod_name = f"feishu_bitable.{parts}"
        if full_mod_name in sys.modules:
            return sys.modules[full_mod_name], None
        try:
            mod = importlib.import_module(full_mod_name)
            return mod, None
        except ModuleNotFoundError as e:
            if "feishu_bitable" in str(e):
                return None, f"blocker:skills_dir_has_hyphen_no_init:feishu-bitable/{parts}.py"
            return None, f"load_error:{e}"

    return None, f"unsupported_path:{module_path}"


def check_imports():
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(PROFILE / "skills/stock/stock-expert"))
    modules = [
        "core/compat_paths",
        "core/bootstrap",
        "scripts.cron.decision.contract",
        "scripts.cron.decision.engine",
        "scripts.cron.decision.execution",
        "scripts.cron.decision.outcome",
        "scripts.cron.decision.real_portfolio_truth",
        "scripts.cron.decision.portfolio",
        "scripts.cron.decision.real_portfolio",
        "scripts.cron.decision.validation_readback",
        "scripts.cron.decision.presentation",
        "scripts.cron.decision.real_sizing",
    ]
    for m in modules:
        try:
            spec = importlib.util.find_spec(m)
            if spec is None:
                add("HIGH", "import", f"Module not found: {m}")
            else:
                importlib.import_module(m)
                print(f"[OK] import {m}")
        except Exception as e:
            add("HIGH", "import", f"import {m} failed: {e}")

# 3. Decision Engine 合同字段
def check_decision_contract():
    sys.path.insert(0, str(REPO))
    try:
        from decision.contract import Decision
        required = {
            "policy_action", "engine_result", "final_action", "block_reason",
            "execution_status", "constraint_id", "all_triggered_constraints",
            "decision_cycle_version", "policy_version", "config_version",
        }
        fields = {f.name for f in Decision.__dataclass_fields__.values()}
        missing = required - fields
        if missing:
            add("HIGH", "contract", f"Decision missing fields: {missing}")
        else:
            print("[OK] Decision contract fields complete")
    except Exception as e:
        add("HIGH", "contract", f"Decision contract check failed: {e}")

# 4. Execution 状态机字段
def check_execution_contract():
    sys.path.insert(0, str(REPO))
    try:
        from decision.execution import EXEC_STATUS
        required = {"PLANNED", "EXECUTED", "PARTIAL", "REJECTED", "NOT_EXECUTED"}
        if not required.issubset(set(EXEC_STATUS.__members__)):
            add("HIGH", "contract", f"EXEC_STATUS missing states: {required - set(EXEC_STATUS.__members__)}")
        else:
            print("[OK] Execution EXEC_STATUS states complete")
    except Exception as e:
        add("HIGH", "contract", f"Execution contract check failed: {e}")

# 5. Rollback 函数存在
def check_rollback():
    sys.path.insert(0, str(REPO))
    try:
        from decision.engine import DecisionEngine
        if not hasattr(DecisionEngine, "record_rollback"):
            add("MEDIUM", "rollback", "DecisionEngine missing record_rollback()")
        else:
            print("[OK] DecisionEngine.record_rollback exists")
    except Exception as e:
        add("HIGH", "rollback", f"Rollback check failed: {e}")

# 6. Real Portfolio Truth 来源
def check_real_portfolio_source():
    sys.path.insert(0, str(REPO))
    try:
        from decision.real_portfolio_truth import CANONICAL_REAL_PORTFOLIO_SOURCE
        if not CANONICAL_REAL_PORTFOLIO_SOURCE or CANONICAL_REAL_PORTFOLIO_SOURCE == "UNKNOWN":
            add("HIGH", "source_of_truth", "CANONICAL_REAL_PORTFOLIO_SOURCE is UNKNOWN")
        else:
            print(f"[OK] CANONICAL_REAL_PORTFOLIO_SOURCE={CANONICAL_REAL_PORTFOLIO_SOURCE}")
    except Exception as e:
        add("HIGH", "source_of_truth", f"Real portfolio source check failed: {e}")

# 7. Cron jobs.json 结构
def check_cron_contracts():
    jobs_path = PROFILE / "cron/jobs.json"
    try:
        data = json.loads(jobs_path.read_text())
        jobs = data if isinstance(data, list) else data.get("jobs", [])
        required_keys = {"purpose", "input", "output", "consumer", "frequency", "dependency", "failure_behavior", "domain", "production_or_research"}
        bad = []
        for job in jobs:
            missing = required_keys - job.keys()
            if missing:
                bad.append(f"{job.get('id','?')}: missing {missing}")
        if bad:
            add("MEDIUM", "cron", f"jobs.json contract gaps: {bad}")
        else:
            print(f"[OK] cron jobs.json: {len(jobs)} jobs, all have contract keys")
    except Exception as e:
        add("HIGH", "cron", f"jobs.json error: {e}")

# 8. Hermes gateway/cron 运行状态
def check_gateway_cron():
    try:
        r = subprocess.run(
            [PYTHON, "-m", "hermes_cli.main", "--profile", "stock", "cron", "status"],
            capture_output=True, text=True, timeout=15
        )
        out = r.stdout + r.stderr
        if "22 active job(s)" in out:
            print("[OK] cron status shows 22 active jobs")
        else:
            add("MEDIUM", "cron", f"cron status unexpected output: {out[:200]}")
        if "Gateway is running" in out:
            print("[OK] gateway running")
        else:
            add("MEDIUM", "gateway", "gateway may not be running")
    except Exception as e:
        add("HIGH", "gateway", f"cron status check failed: {e}")

# 9. K线数据新鲜度
def check_data_freshness():
    db = REPO / "data/production/market_cache.db"
    try:
        conn = sqlite3.connect(db, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM klines")
        print("[WARN] klines freshness check returned:", cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM klines")
        print("[OK] klines count:", cur.fetchone()[0])
        conn.close()
    except Exception as e:
        add("HIGH", "database", f"klines freshness check failed: {e}")

if __name__ == "__main__":
    check_tables()
    check_imports()
    check_decision_contract()
    check_execution_contract()
    check_rollback()
    check_real_portfolio_source()
    check_cron_contracts()
    check_gateway_cron()
    check_data_freshness()

    print("\n=== BUG SCAN SUMMARY ===")
    for issue in issues:
        print(f"[{issue['severity']}] {issue['category']}: {issue['msg']}")
    if not issues:
        print("No issues found.")
    else:
        print(f"Total issues: {len(issues)}")
