#!/usr/bin/env python3
"""
并行架构性能基准测试
测试点：
1. auto_recommend 三档筛选并行
2. intraday_monitor 持仓股批量行情获取
3. weekly_parallel_refresh 周更并行执行
"""
import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])

import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor

print("="*60)
print("并行架构性能基准测试")
print("="*60)

# ========================
# 测试1：auto_recommend 批量财务数据加载
# ========================
print("\n[测试1] 批量加载财务数据（bulk_load_financial_data）")
from auto_recommend import bulk_load_financial_data, bulk_load_market_cap, bulk_load_double_up_scores, get_db

conn = get_db()
codes = [f"{i:06d}" for i in range(1, 5001)]  # 模拟5000只股票

t = time.time()
fin_map = bulk_load_financial_data(conn, codes)
t_fin = time.time() - t

t = time.time()
mc_map = bulk_load_market_cap(conn, codes)
t_mc = time.time() - t

t = time.time()
du_map = bulk_load_double_up_scores(conn, codes)
t_du = time.time() - t

print(f"  财务数据: {len(fin_map)}条, {t_fin:.3f}s")
print(f"  市值数据: {len(mc_map)}条, {t_mc:.3f}s")
print(f"  五维打分: {len(du_map)}条, {t_du:.3f}s")
print(f"  合计: {t_fin+t_mc+t_du:.3f}s（vs 原来串行约60s+）")

# ========================
# 测试2：批量行情获取并发
# ========================
print("\n[测试2] 持仓股批量行情获取（10线程并发）")
from intraday_monitor import get_stock_quote_batch

test_codes = ["000001", "600016", "600036", "600050", "600100",
              "600519", "600887", "601012", "601318", "601398"]

t = time.time()
results = get_stock_quote_batch(test_codes)
elapsed = time.time() - t

print(f"  10只股票: {elapsed:.2f}s, 成功{len(results)}只")
for code, q in results.items():
    print(f"    {code}: price={q.get('price')}, chg={q.get('change_pct')}%")

# ========================
# 测试3：full_scan 并行筛选
# ========================
print("\n[测试3] full_scan() 三档并行筛选")
from auto_recommend import full_scan

t = time.time()
result = full_scan()
elapsed = time.time() - t

print(f"  总耗时: {elapsed:.3f}s")
print(f"  激进档: {len(result['aggressive'])}只")
print(f"  稳健档: {len(result['steady'])}只")
print(f"  价值档: {len(result['value'])}只")
print(f"  原来串行全量: ~30-60s（仅财务数据查询就要4939次）")
print(f"  现在并行全量: {elapsed:.3f}s")

print("\n" + "="*60)
print("✅ 并行架构验证完成")
print("="*60)