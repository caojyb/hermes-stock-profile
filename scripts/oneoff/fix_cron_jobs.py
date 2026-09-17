#!/usr/bin/env python3
"""
Fix cron jobs script paths and hardcoded paths in prompts.
"""
import json
from pathlib import Path
from datetime import datetime

PROFILE = Path("/home/caojy/.hermes/profiles/stock")
JOBS_FILE = PROFILE / "cron/jobs.json"
BACKUP = PROFILE / "stock-work/data/snapshots/migrations" / f"CRON_REPAIR_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

OLD_SCRIPT_MAP = {
    "cron/market_cache_refresh.sh": "scripts/cron/market_cache_refresh.sh",
    "cron/stock_opportunity_scan.py": "scripts/cron/stock_opportunity_scan.py",
    "cron/us_stock_weekly.sh": "scripts/cron/us_stock_weekly.sh",
    "cron/fetch_financial_refresh.sh": "scripts/cron/fetch_financial_refresh.sh",
    "cron/fetch_pe_pb_refresh.sh": "scripts/cron/fetch_pe_pb_refresh.sh",
    "cron/weekly_pool_report.sh": "scripts/cron/weekly_pool_report.sh",
    "cron/stock_screener_wrapper.sh": "scripts/cron/stock_screener_wrapper.sh",
    "cron/sentiment_thermo.sh": "scripts/cron/sentiment_thermo.sh",
    "cron/stock_pipeline_wrapper.sh": "scripts/cron/stock_pipeline_wrapper.sh",
    "cron/double_refresh.py": "scripts/cron/double_refresh.py",
    "cron/double_monitor.py": "scripts/cron/double_monitor.py",
    "cron/intraday_cache.py": "scripts/cron/intraday_cache.py",
    "cron/lhb_monitor.py": "scripts/cron/lhb_monitor.py",
    "cron/news_sentiment.py": "scripts/cron/news_sentiment.py",
    "cron/position_stop_loss_alert.py": "scripts/cron/position_stop_loss_alert.py",
    "cron/market_env_report.sh": "scripts/cron/market_env_report.sh",
    "cron/daily_data_refresh.py": "scripts/cron/daily_data_refresh.py",
    "cron/hot_sector_scanner.py": "scripts/cron/hot_sector_scanner.py",
    "cron/health_check.py": "scripts/cron/health_check.py",
    "cron/system_health_check.py": "scripts/cron/system_health_check.py",
    "cron/fetch_holdings_westock.py": "scripts/cron/fetch_holdings_westock.py",
    "cron/long_term_holding.py": "scripts/cron/long_term_holding.py",
    "cron/historical_market_state.py": "scripts/cron/historical_market_state.py",
    "cron/ps_pcf_update.py": "scripts/cron/ps_pcf_update.py",
    "cron/stock_fortune.py": "scripts/cron/stock_fortune.py",
    "cron/pre_market_brief.py": "scripts/cron/pre_market_brief.py",
    "cron/stock_opportunity_scan.py": "scripts/cron/stock_opportunity_scan.py",
}

def backup_jobs():
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(JOBS_FILE, BACKUP / "jobs.json")
    print(f"BACKUP: {BACKUP / 'jobs.json'}")

def fix_job(job):
    if not isinstance(job, dict):
        return False
    
    changed = False
    name = job.get('name', 'unknown')
    
    # Fix script path
    script = job.get('script')
    if script and isinstance(script, str):
        # Check if it's a relative path that needs updating
        if script.startswith('cron/') or script.startswith('scripts/cron/'):
            old_script = script
            # Direct mapping
            if script in OLD_SCRIPT_MAP:
                job['script'] = OLD_SCRIPT_MAP[script]
                changed = True
                print(f"  [{name}] SCRIPT: {old_script} -> {OLD_SCRIPT_MAP[script]}")
            else:
                # Generic replacement
                new_script = script.replace('cron/', 'scripts/cron/')
                if new_script != script:
                    # Verify file exists
                    new_path = PROFILE / new_script
                    if new_path.exists():
                        job['script'] = new_script
                        changed = True
                        print(f"  [{name}] SCRIPT: {script} -> {new_script}")
                    else:
                        print(f"  [{name}] SCRIPT: {script} -> {new_script} (WARNING: file not found)")
    
    # Fix prompt hardcoded paths
    prompt = job.get('prompt', '')
    if prompt:
        new_prompt = prompt
        # Fix common patterns
        replacements = [
            ('/home/caojy/.hermes/profiles/stock/scripts/cron/', '/home/caojy/.hermes/profiles/stock/scripts/cron/'),
            ('~/.hermes/profiles/stock/scripts/cron/', '/home/caojy/.hermes/profiles/stock/scripts/cron/'),
            ('/home/caojy/.hermes/profiles/stock/data/', '/home/caojy/.hermes/profiles/stock/stock-work/data/production/'),
            ('~/.hermes/profiles/stock/data/', '/home/caojy/.hermes/profiles/stock/stock-work/data/production/'),
        ]
        for old, new in replacements:
            if old in new_prompt:
                new_prompt = new_prompt.replace(old, new)
        if new_prompt != prompt:
            job['prompt'] = new_prompt
            changed = True
            print(f"  [{name}] PROMPT: updated hardcoded paths")
    
    # Fix contract input/output
    contract = job.get('contract', {})
    if isinstance(contract, dict):
        for field in ['input', 'output', 'consumer']:
            val = contract.get(field, '')
            if isinstance(val, str):
                new_val = val
                for old, new in [
                    ('/home/caojy/.hermes/profiles/stock/scripts/cron/', '/home/caojy/.hermes/profiles/stock/scripts/cron/'),
                    ('~/.hermes/profiles/stock/scripts/cron/', '/home/caojy/.hermes/profiles/stock/scripts/cron/'),
                ]:
                    new_val = new_val.replace(old, new)
                if new_val != val:
                    contract[field] = new_val
                    changed = True
    
    # Fix top-level input/output
    for field in ['input', 'output', 'consumer']:
        val = job.get(field, '')
        if isinstance(val, str):
            new_val = val
            for old, new in [
                ('/home/caojy/.hermes/profiles/stock/scripts/cron/', '/home/caojy/.hermes/profiles/stock/scripts/cron/'),
                ('~/.hermes/profiles/stock/scripts/cron/', '/home/caojy/.hermes/profiles/stock/scripts/cron/'),
            ]:
                new_val = new_val.replace(old, new)
            if new_val != val:
                job[field] = new_val
                changed = True
    
    return changed

def main():
    print("=" * 80)
    print("CRON JOB REPAIR")
    print("=" * 80)
    
    backup_jobs()
    
    with open(JOBS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    jobs = data.get('jobs', [])
    fixed = 0
    for job in jobs:
        if fix_job(job):
            fixed += 1
    
    if fixed > 0:
        with open(JOBS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nUPDATED {fixed} jobs")
    else:
        print("\nNO CHANGES NEEDED")
    
    print("=" * 80)
    return fixed

if __name__ == '__main__':
    main()
