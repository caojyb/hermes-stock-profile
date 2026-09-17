#!/usr/bin/env python3
"""
周日并行数据刷新脚本
将原来的串行三步（PE/PB → 财务数据 → 五维打分）改为并行执行
调度：每周日 16:00 并行执行，三路同时跑，完成后串行执行五维打分

用法：python3 weekly_parallel_refresh.py
"""
import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])

import time
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPTS = {
    "PE/PB": "fetch_pe_pb.py",
    "财务数据": "fetch_financial_data.py",
}

def run_script(name, script):
    """运行单个脚本，返回成功/失败"""
    start = time.time()
    try:
        result = subprocess.run(
            ["python3", script],
            cwd=__file__.rsplit('/', 1)[0],
            capture_output=True,
            text=True,
            timeout=900  # 15分钟超时
        )
        elapsed = time.time() - start
        ok = result.returncode == 0
        print(f"  [{name}] {'✅' if ok else '❌'} ({elapsed:.0f}s) {'成功' if ok else '失败'}")
        if not ok:
            print(f"    错误: {result.stderr[:200]}")
        return name, ok
    except subprocess.TimeoutExpired:
        print(f"  [{name}] ❌ 超时(900s)")
        return name, False
    except Exception as e:
        print(f"  [{name}] ❌ 异常: {e}")
        return name, False

def main():
    print("="*50)
    print("周日并行数据刷新开始")
    print("="*50)
    
    start_total = time.time()
    
    # 第一波：PE/PB + 财务数据 并行
    print("\n[第一波] PE/PB + 财务数据 并行执行...")
    results = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(run_script, name, script): name
            for name, script in SCRIPTS.items()
        }
        for future in as_completed(futures):
            name, ok = future.result()
            results[name] = ok
    
    elapsed_pe_fin = time.time() - start_total
    pe_ok = results.get("PE/PB", False)
    fin_ok = results.get("财务数据", False)
    
    # 第二波：五维打分（等PE/PB和财务完成后再跑）
    print(f"\n[第二波] 五维打分（依赖: PE/PB={'✅' if pe_ok else '❌'} 财务={'✅' if fin_ok else '❌'}）...")
    if pe_ok and fin_ok:
        _, du_ok = run_script("五维打分", "double_up_screener.py --market-outlook")
    else:
        print("  [五维打分] ⚠️ 前置数据未就绪，跳过")
        du_ok = False
    
    total = time.time() - start_total
    print(f"\n总耗时: {total:.0f}s")
    print(f"结果: PE/PB={'✅' if pe_ok else '❌'} 财务={'✅' if fin_ok else '❌'} 五维={'✅' if du_ok else '❌'}")
    print("="*50)
    
    # exit code: 0 if all success, 1 if any failed
    sys.exit(0 if all([pe_ok, fin_ok, du_ok]) else 1)

if __name__ == "__main__":
    main()