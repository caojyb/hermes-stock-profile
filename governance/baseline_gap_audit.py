#!/usr/bin/env python3
"""
Baseline v1.2.1 Gap Audit
READ ONLY / NO MIGRATION / NO DB WRITE / NO CRON MODIFIED / NO SYSTEMD MODIFIED / NO GATEWAY RESTART / AUTO_TRADING=OFF
"""
import os, json, subprocess, hashlib, re
from pathlib import Path

REPO = Path("/home/caojy/.hermes/profiles/stock/stock-work")
PROFILE = Path("/home/caojy/.hermes/profiles/stock")
GIT_BRANCH_EXPECTED = "main"

def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=REPO)
    return r.stdout.strip(), r.returncode

def read(p):
    p = Path(p)
    return p.read_text() if p.exists() else None

# 1. Git state
branch, _ = sh("git branch --show-current")
commit, _ = sh("git rev-parse HEAD")
tag, _ = sh("git tag --points-at HEAD")
status, _ = sh("git status --porcelain")
wt_status = "CLEAN" if not status else "DIRTY"

print("=== GIT STATE ===")
print(f"branch: {branch}")
print(f"commit: {commit}")
print(f"tag_at_head: {tag}")
print(f"working_tree: {wt_status}")
print(f"status_lines: {len(status.splitlines())}")

# 2. Governance files
baseline = read(REPO / "governance/BASELINE.md")
code_baseline = read(REPO / "governance/CODE_BASELINE.md")
agent_proto = read(REPO / "governance/AGENT_PROTOCOL.md")
change_policy = read(REPO / "governance/CHANGE_POLICY.md")
change_ledger = read(REPO / "governance/CHANGE_LEDGER.md")

print("\n=== GOVERNANCE FILES ===")
for name, content in [("BASELINE.md", baseline), ("CODE_BASELINE.md", code_baseline), ("AGENT_PROTOCOL.md", agent_proto), ("CHANGE_POLICY.md", change_policy), ("CHANGE_LEDGER.md", change_ledger)]:
    print(f"{name}: {'PRESENT' if content else 'MISSING'}")

# 3. CODE_BASELINE accuracy
issues = []
if code_baseline:
    if "git_branch: master" in code_baseline and branch != "master":
        issues.append(f"CODE_BASELINE branch mismatch: recorded master, actual {branch}")
    if "git_commit: 63779d4" in code_baseline and commit != "63779d4":
        issues.append(f"CODE_BASELINE commit mismatch: recorded 63779d4, actual {commit}")
    if "working_tree_status: CLEAN" in code_baseline and wt_status != "CLEAN":
        issues.append(f"CODE_BASELINE working_tree mismatch: recorded CLEAN, actual {wt_status}")
    if "CODE_BASELINE_ESTABLISHED = YES" not in code_baseline:
        issues.append("CODE_BASELINE missing CODE_BASELINE_ESTABLISHED flag")
    if "BASELINE_COMPLIANCE_VALIDATED" not in code_baseline:
        issues.append("CODE_BASELINE missing BASELINE_COMPLIANCE_VALIDATED flag")

print("\n=== CODE_BASELINE ISSUES ===")
for i in issues:
    print(f"- {i}")

# 4. Boundary scan: production code outside stock-work
prod_paths = [
    PROFILE / "scripts/cron/decision/engine.py",
    PROFILE / "scripts/cron/decision/real_portfolio_truth.py",
    PROFILE / "scripts/cron/decision/execution.py",
    PROFILE / "scripts/cron/double_monitor.py",
    PROFILE / "cron/jobs.json",
]

print("\n=== PRODUCTION BOUNDARY ===")
for p in prod_paths:
    in_repo = str(p).startswith(str(REPO))
    exists = p.exists()
    print(f"{'IN REPO' if in_repo else 'OUT OF REPO'}: {p} (exists={exists})")

# 5. Research inside stock-work boundary
research_dirs = list((REPO / "core").rglob("research")) + list((REPO / "data").rglob("research"))
print("\n=== RESEARCH ARTIFACTS INSIDE STOCK-WORK ===")
for d in research_dirs:
    files = list(d.rglob("*"))
    print(f"DIR: {d} ({len(files)} files)")

# 6. Baseline contract presence
contracts = {
    "Decision State Contract": ["policy_action", "engine_result", "final_action", "block_reason", "execution_status"],
    "Hard Constraint Registry": ["constraint_id", "domain", "trigger", "stage", "action_scope", "priority", "block_reason", "fail_safe"],
    "Recommendation Object": ["decision_id", "decision_time", "symbol", "policy_action", "policy_target_weight", "engine_result", "final_action", "block_reason"],
    "Entry Timing Contract": ["entry_condition", "expected_trigger", "valid_until", "timing_policy_version"],
    "Exit Policy Contract": ["HOLD", "REDUCE", "EXIT"],
    "Simulation Execution Model": ["Signal at T", "Next valid trading session T+1", "Execution at T+1 Open"],
    "Real Manual Execution": ["AUTO_TRADING = OFF", "USER_CONFIRMATION", "MANUAL_INPUT", "IMPORTED_RECORD"],
    "Evidence Fusion": ["source", "symbol", "feature / claim", "value", "available_time", "as_of", "quality", "availability", "provenance", "version"],
    "PIT Contract": ["available_time <= decision_time"],
    "Cron Contract": ["purpose", "input", "output", "consumer", "frequency", "dependency", "failure_behavior", "domain", "production_or_research"],
}

print("\n=== BASELINE CONTRACT PRESENCE ===")
if baseline:
    for cname, keywords in contracts.items():
        present = all(k in baseline for k in keywords)
        print(f"{cname}: {'PRESENT' if present else 'MISSING/INCOMPLETE'}")

# 7. jobs.json cron contract audit
jobs_json = PROFILE / "cron/jobs.json"
print("\n=== CRON CONTRACT AUDIT ===")
if jobs_json.exists():
    try:
        jobs = json.loads(jobs_json.read_text())
        if isinstance(jobs, dict):
            jobs = jobs.get("jobs", jobs.get("crons", []))
        elif isinstance(jobs, list):
            pass
        else:
            jobs = []
        print(f"jobs count: {len(jobs)}")
        for j in jobs:
            name = j.get("name", j.get("id", "unknown"))
            has_contract = all(k in j for k in ["purpose", "input", "output", "consumer", "frequency", "dependency", "failure_behavior", "domain", "production_or_research"])
            print(f"- {name}: contract_complete={has_contract}")
    except Exception as e:
        print(f"ERROR parsing jobs.json: {e}")
else:
    print("jobs.json not found at expected production path")

# 8. Real portfolio truth audit
rpt = PROFILE / "scripts/cron/decision/real_portfolio_truth.py"
print("\n=== REAL PORTFOLIO TRUTH ===")
if rpt.exists():
    txt = rpt.read_text()
    print(f"file exists: True")
    print(f"contains CANONICAL: {'CANONICAL' in txt or 'canonical' in txt}")
    print(f"contains source_timestamp: {'source_timestamp' in txt}")
    print(f"contains quality_status: {'quality_status' in txt}")
else:
    print("real_portfolio_truth.py not found")

# 9. engine.py constraint registry audit
engine = PROFILE / "scripts/cron/decision/engine.py"
print("\n=== DECISION ENGINE ===")
if engine.exists():
    txt = engine.read_text()
    print(f"file exists: True")
    print(f"contains BLOCKED: {'BLOCKED' in txt}")
    print(f"contains ALLOWED: {'ALLOWED' in txt}")
    print(f"contains NOT_EXECUTABLE: {'NOT_EXECUTABLE' in txt}")
    print(f"contains block_reason: {'block_reason' in txt}")
    print(f"contains constraint_id: {'constraint_id' in txt}")
else:
    print("engine.py not found")

print("\n=== AUDIT COMPLETE ===")
