#!/usr/bin/env python3
"""
Cron Contract Gap Remediation
Adds Baseline Cron Contract fields to jobs.json without breaking existing structure.
READ ONLY source, writes output to temp for review? No, this is remediation, but we'll be surgical.
"""
import json, re
from pathlib import Path

jobs_path = Path("/home/caojy/.hermes/profiles/stock/cron/jobs.json")
backup_path = jobs_path.with_suffix(".json.bak")

data = json.loads(jobs_path.read_text())
jobs = data.get("jobs", [])
backup_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def derive_purpose(job):
    name = job.get("name", "")
    prompt = job.get("prompt", "")
    # Try first non-empty line of prompt
    lines = [l.strip() for l in prompt.splitlines() if l.strip()]
    if lines:
        first = lines[0]
        # Remove markdown headers
        first = re.sub(r'^#+\s*', '', first)
        first = re.sub(r'\*\*.*?\*\*', '', first)
        if len(first) > 80:
            first = first[:77] + "..."
        return first or name
    return name

def derive_input(job):
    parts = []
    if job.get("script"):
        parts.append(f"script={job['script']}")
    if job.get("skills"):
        parts.append(f"skills={','.join(job['skills'])}")
    if job.get("skill"):
        parts.append(f"skill={job['skill']}")
    # extract bash commands from prompt
    prompt = job.get("prompt", "")
    cmds = re.findall(r'```bash\n(.*?)\n```', prompt, re.DOTALL)
    if cmds:
        parts.append(f"commands={len(cmds)} blocks")
    return "; ".join(parts) if parts else "NONE"

def derive_output(job):
    deliver = job.get("deliver", "")
    if deliver:
        if deliver.startswith("feishu:"):
            return f"FEISHU_DELIVERY chat={deliver}"
        return f"DELIVER={deliver}"
    # fallback: check prompt for output format
    prompt = job.get("prompt", "")
    if "输出格式" in prompt or "输出" in prompt:
        return "TEXT_REPORT"
    return "UNKNOWN"

def derive_consumer(job):
    deliver = job.get("deliver", "")
    if deliver.startswith("feishu:"):
        return f"FEISHU_CHAT:{deliver}"
    if deliver == "local":
        return "LOCAL_STORAGE"
    return "UNKNOWN"

def derive_dependency(job):
    deps = []
    ctx = job.get("context_from")
    if ctx:
        deps.extend(ctx if isinstance(ctx, list) else [ctx])
    # crude script dependency detection
    prompt = job.get("prompt", "")
    if "先运行" in prompt or "等待" in prompt or "然后运行" in prompt:
        deps.append("SEQUENTIAL_SCRIPT_DEP")
    return ",".join(deps) if deps else "NONE"

def derive_failure_behavior(job):
    # explicit failure streak or last_status error -> more strict
    if job.get("failure_streak", 0) > 0:
        return "LOG_AND_ALERT"
    # jobs with no_agent and script usually expect silent failure handling
    if job.get("no_agent") and job.get("script"):
        return "LOG_AND_CONTINUE"
    if job.get("no_agent"):
        return "LOG_AND_CONTINUE"
    return "LOG_AND_RETRY"

def derive_domain(job):
    name = job.get("name", "").lower()
    # research pilots
    if "pilot" in name or "research" in name:
        return "RESEARCH"
    # simulation/backtest
    if "sim" in name or "backtest" in name or "walk" in name:
        return "SIMULATION"
    # real-facing
    if "real" in name or "portfolio" in name or "position" in name or "stop-loss" in name or "execution" in name:
        return "REAL"
    # data refresh tends to be production infrastructure
    if "refresh" in name or "cache" in name or "update" in name:
        return "PRODUCTION"
    return "PRODUCTION"

def derive_production_or_research(job):
    domain = derive_domain(job)
    if domain in ("RESEARCH", "SIMULATION"):
        return "RESEARCH"
    return "PRODUCTION"

updated = 0
for job in jobs:
    # Flatten into Baseline-required top-level keys; preserve existing keys
    job["purpose"] = derive_purpose(job)
    job["input"] = derive_input(job)
    job["output"] = derive_output(job)
    job["consumer"] = derive_consumer(job)
    job["frequency"] = job.get("schedule_display") or job.get("schedule", {}).get("expr") or "UNKNOWN"
    job["dependency"] = derive_dependency(job)
    job["failure_behavior"] = derive_failure_behavior(job)
    job["domain"] = derive_domain(job)
    job["production_or_research"] = derive_production_or_research(job)
    updated += 1

jobs_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f"Updated {updated} jobs with baseline cron contract fields.")
print(f"Backup saved to: {backup_path}")
