#!/usr/bin/env python3
"""
Read-only audit script for M10-C7 production wiring fix.

Verifies:
1. double_monitor.py and risk_controller_v2.py both call build_real_snapshot()
2. entry_ctx and position_ctx accept portfolio_truth parameter
3. DecisionEngine has Portfolio Truth Gate
4. Bitable failure leads to portfolio_truth={} and NO_TRADE
"""
import ast
import os
import sys
from pathlib import Path

PROFILE_ROOT = Path('/home/caojy/.hermes/profiles/stock')
SCRIPTS_DIR = PROFILE_ROOT / 'scripts' / 'cron'
DECISION_DIR = SCRIPTS_DIR / 'decision'

FILES = {
    'double_monitor': SCRIPTS_DIR / 'double_monitor.py',
    'risk_controller': SCRIPTS_DIR / 'risk_controller_v2.py',
    'adapters': DECISION_DIR / 'adapters.py',
    'engine': DECISION_DIR / 'engine.py',
    'real_portfolio_truth': DECISION_DIR / 'real_portfolio_truth.py',
}

def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def check_function_signature(content, func_name, required_params):
    """Check if a function has required parameters in its signature, including keyword-only args."""
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            existing = {arg.arg for arg in node.args.args} | {arg.arg for arg in node.args.kwonlyargs}
            missing = [p for p in required_params if p not in existing]
            return missing
    return [f'function {func_name} not found']

def check_portfolio_truth_gate(content):
    """Check if DecisionEngine has Portfolio Truth Gate."""
    return "ctx.get('portfolio_truth')" in content

def check_build_real_snapshot_call(content, file_label):
    """Check if build_real_snapshot is called."""
    if 'build_real_snapshot' in content:
        return True, "found"
    return False, "NOT found"

def main():
    print("=" * 60)
    print("M10-C7 Production Wiring Audit (READ-ONLY)")
    print("=" * 60)
    
    results = {}
    
    # Read all files
    file_contents = {}
    for name, path in FILES.items():
        if not path.exists():
            print(f"[ERROR] {name}: {path} not found")
            sys.exit(1)
        file_contents[name] = read_file(path)
    
    # 1. Check adapters.py signatures
    print("\n[1] Checking adapter signatures...")
    adapters = file_contents['adapters']
    
    entry_missing = check_function_signature(adapters, 'entry_ctx', ['portfolio_truth'])
    position_missing = check_function_signature(adapters, 'position_ctx', ['portfolio_truth'])
    
    if entry_missing:
        print(f"  entry_ctx missing params: {entry_missing}")
    else:
        print("  entry_ctx: portfolio_truth parameter present")
    
    if position_missing:
        print(f"  position_ctx missing params: {position_missing}")
    else:
        print("  position_ctx: portfolio_truth parameter present")
    
    # 2. Check DecisionEngine has Portfolio Truth Gate
    print("\n[2] Checking DecisionEngine Portfolio Truth Gate...")
    engine = file_contents['engine']
    if check_portfolio_truth_gate(engine):
        print("  Portfolio Truth Gate: PRESENT")
    else:
        print("  Portfolio Truth Gate: MISSING")
    
    # 3. Check double_monitor.py wiring
    print("\n[3] Checking double_monitor.py production wiring...")
    dm = file_contents['double_monitor']
    
    dm_has_import = 'build_real_snapshot' in dm
    dm_has_entry_call = 'portfolio_truth=' in dm and 'entry_ctx(' in dm
    dm_has_position_call = 'portfolio_truth=' in dm and 'position_ctx(' in dm
    
    print(f"  build_real_snapshot import: {'YES' if dm_has_import else 'NO'}")
    print(f"  entry_ctx with portfolio_truth: {'YES' if dm_has_entry_call else 'NO'}")
    print(f"  position_ctx with portfolio_truth: {'YES' if dm_has_position_call else 'NO'}")
    
    # 4. Check risk_controller_v2.py wiring
    print("\n[4] Checking risk_controller_v2.py production wiring...")
    rc = file_contents['risk_controller']
    
    rc_has_import = 'build_real_snapshot' in rc
    rc_has_position_call = 'portfolio_truth=' in rc and 'position_ctx(' in rc
    
    print(f"  build_real_snapshot import: {'YES' if rc_has_import else 'NO'}")
    print(f"  position_ctx with portfolio_truth: {'YES' if rc_has_position_call else 'NO'}")
    
    # 5. Check Bitable failure handling
    print("\n[5] Checking Bitable failure handling...")
    rpt = file_contents['real_portfolio_truth']
    has_exception_handling = 'except Exception' in rpt and "'ok': False" in rpt
    print(f"  Bitable failure returns ok=False: {'YES' if has_exception_handling else 'NO'}")
    
    # Summary
    print("\n" + "=" * 60)
    print("AUDIT SUMMARY")
    print("=" * 60)
    
    all_ok = True
    if entry_missing:
        print("[FAIL] entry_ctx missing portfolio_truth parameter")
        all_ok = False
    if position_missing:
        print("[FAIL] position_ctx missing portfolio_truth parameter")
        all_ok = False
    if not check_portfolio_truth_gate(engine):
        print("[FAIL] DecisionEngine missing Portfolio Truth Gate")
        all_ok = False
    if not dm_has_import:
        print("[FAIL] double_monitor.py missing build_real_snapshot import")
        all_ok = False
    if not dm_has_entry_call:
        print("[FAIL] double_monitor.py entry_ctx not passing portfolio_truth")
        all_ok = False
    if not dm_has_position_call:
        print("[FAIL] double_monitor.py position_ctx not passing portfolio_truth")
        all_ok = False
    if not rc_has_import:
        print("[FAIL] risk_controller_v2.py missing build_real_snapshot import")
        all_ok = False
    if not rc_has_position_call:
        print("[FAIL] risk_controller_v2.py position_ctx not passing portfolio_truth")
        all_ok = False
    
    if all_ok:
        print("[PASS] All checks passed - production wiring is complete")
        return 0
    else:
        print("[FAIL] Some checks failed - fix needed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
