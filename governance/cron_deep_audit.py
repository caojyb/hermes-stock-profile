#!/usr/bin/env python3
"""
Cron job deep audit and repair.
Checks:
- script path existence
- prompt hardcoded paths
- input/output contract consistency
- last_status error patterns
- dependency on moved directories
"""
import json, re, os
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
JOBS_FILE = PROFILE / "cron/jobs.json"
NEW_BASE = PROFILE / "stock-work/production"
OLD_BASE = PROFILE

def rel(p):
    return str(p.relative_to(PROFILE))

def audit_jobs():
    with open(JOBS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    jobs = data.get('jobs', [])
    report = []
    fixes = []
    
    for job in jobs:
        name = job.get('name', 'unknown')
        script = job.get('script', '')
        prompt = job.get('prompt', '')
        workdir = job.get('workdir', str(PROFILE))
        last_status = job.get('last_status', 'unknown')
        last_error = job.get('last_error', '')
        failure_streak = job.get('failure_streak', 0)
        
        issues = []
        path_issues = []
        
        # 1. Check script path existence
        if script and isinstance(script, str) and script.endswith(('.sh', '.py')):
            # Resolve relative to workdir if not absolute
            if not script.startswith('/'):
                script_path = Path(workdir) / script
            else:
                script_path = Path(script)
            
            if not script_path.exists():
                # Try new location
                new_script = script
                if 'scripts/cron' in script:
                    new_script = script.replace(
                        '/home/caojy/.hermes/profiles/stock/scripts/cron',
                        '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron'
                    )
                    new_script = new_script.replace(
                        '~/.hermes/profiles/stock/scripts/cron',
                        '/home/caojy/.hermes/profiles/stock/stock-work/production/scripts/cron'
                    )
                    new_path = Path(new_script) if new_script.startswith('/') else Path(workdir) / new_script
                    if new_path.exists():
                        path_issues.append(f"SCRIPT_MOVED: {script} -> {new_script}")
                        fixes.append({
                            'job_id': job.get('id'),
                            'name': name,
                            'field': 'script',
                            'old': script,
                            'new': new_script,
                            'reason': 'script path moved to stock-work/production'
                        })
                    else:
                        path_issues.append(f"SCRIPT_MISSING: {script} (tried {new_path})")
                else:
                    path_issues.append(f"SCRIPT_MISSING: {script}")
        
        # 2. Check prompt for hardcoded paths
        prompt_paths = []
        if '/home/caojy/.hermes/profiles/stock/scripts/cron' in prompt:
            prompt_paths.append('/home/caojy/.hermes/profiles/stock/scripts/cron')
        if '/home/caojy/.hermes/profiles/stock/data/' in prompt:
            prompt_paths.append('/home/caojy/.hermes/profiles/stock/data/')
        if '~/.hermes/profiles/stock/scripts/cron' in prompt:
            prompt_paths.append('~/.hermes/profiles/stock/scripts/cron')
        if '~/.hermes/profiles/stock/data/' in prompt:
            prompt_paths.append('~/.hermes/profiles/stock/data/')
        
        if prompt_paths:
            issues.append(f"HARDCODED_PATHS_IN_PROMPT: {prompt_paths}")
        
        # 3. Check contract input/output consistency
        contract = job.get('contract', {})
        inp = contract.get('input', '') or job.get('input', '')
        out = contract.get('output', '') or job.get('output', '')
        
        if 'scripts/cron' in inp and 'stock-work/production/scripts/cron' not in inp:
            issues.append("CONTRACT_INPUT_OLD_PATH: input contains scripts/cron but not new path")
        
        # 4. Check for error patterns
        if last_status == 'error' or failure_streak > 0:
            if 'no such table' in str(last_error).lower():
                issues.append(f"DB_SCHEMA_ERROR: {last_error[:200]}")
            elif 'no such file' in str(last_error).lower():
                issues.append(f"FILE_NOT_FOUND: {last_error[:200]}")
            elif 'importerror' in str(last_error).lower() or 'ModuleNotFoundError' in str(last_error):
                issues.append(f"IMPORT_ERROR: {last_error[:200]}")
            elif failure_streak > 0:
                issues.append(f"FAILURE_STREAK: {failure_streak} consecutive failures")
        
        # 5. Check workdir
        if workdir != str(PROFILE):
            issues.append(f"WORKDIR_MISMATCH: {workdir} != {PROFILE}")
        
        if path_issues or issues:
            report.append({
                'name': name,
                'id': job.get('id'),
                'issues': issues,
                'path_issues': path_issues,
                'last_status': last_status,
                'failure_streak': failure_streak
            })
    
    return report, fixes, jobs

def main():
    print("=" * 80)
    print("CRON JOB DEEP AUDIT")
    print("=" * 80)
    
    report, fixes, all_jobs = audit_jobs()
    
    print(f"\nTotal jobs: {len(all_jobs)}")
    print(f"Jobs with issues: {len(report)}")
    print(f"Path fixes needed: {len(fixes)}")
    
    if report:
        print("\n## ISSUES ##\n")
        for item in report:
            print(f"\n[{item['name']}] (id={item['id']})")
            print(f"  last_status: {item['last_status']}, failure_streak: {item['failure_streak']}")
            for issue in item['issues']:
                print(f"  ISSUE: {issue}")
            for pi in item['path_issues']:
                print(f"  PATH: {pi}")
    
    if fixes:
        print("\n## PROPOSED FIXES ##\n")
        for fix in fixes:
            print(f"  {fix['name']}: {fix['field']} {fix['old']} -> {fix['new']}")
    
    # Save report
    report_file = PROFILE / "stock-work/data/snapshots/migrations/cron_audit_report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump({
            'generated': datetime.now().isoformat(),
            'total_jobs': len(all_jobs),
            'jobs_with_issues': len(report),
            'fixes_needed': len(fixes),
            'issues': report,
            'fixes': fixes
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\nReport: {report_file}")
    print("=" * 80)
    
    return len(report) == 0

if __name__ == '__main__':
    ok = main()
    exit(0 if ok else 1)
