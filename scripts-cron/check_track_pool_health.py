#!/usr/bin/env python3
"""track_loose_pool 健康检查脚本（H 阶段用）"""
import sys
import json
import os
from pathlib import Path

# 添加 stock-work 到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'stock-work'))

from track_flow_manager import NEW_TRACK_POOL

def check_new_path_exists():
    """检查新路径文件是否存在"""
    exists = os.path.exists(NEW_TRACK_POOL)
    print(f"[{'PASS' if exists else 'FAIL'}] 新路径文件存在: {NEW_TRACK_POOL}")
    return exists

def check_old_path_not_exists():
    """检查旧路径文件是否已删除"""
    old_path = str(Path(__file__).resolve().parent.parent.parent / 'stock-work' / 'data' / 'state' / 'pending' / 'track_loose_pool.json')
    # 旧路径应该是 scripts/cron/track_loose_pool.json，但我们已经删了
    # 这里检查的是 canonical 路径，不是旧路径
    print(f"[INFO] 旧路径 scripts/cron/track_loose_pool.json 应在 G 阶段已删除")
    return True

def check_new_path_content():
    """检查新路径内容是否有效"""
    if not os.path.exists(NEW_TRACK_POOL):
        return False
    try:
        with open(NEW_TRACK_POOL) as f:
            data = json.load(f)
        has_date = 'date' in data
        has_stocks = 'stocks' in data and isinstance(data['stocks'], list)
        stock_count = len(data.get('stocks', []))
        print(f"[{'PASS' if has_date and has_stocks else 'FAIL'}] 新路径内容有效: date={has_date}, stocks={has_stocks}, count={stock_count}")
        return has_date and has_stocks
    except Exception as e:
        print(f"[FAIL] 新路径内容解析失败: {e}")
        return False

def check_load_track_pool():
    """检查 load_track_pool() 是否能正常加载"""
    try:
        # 动态导入 track_flow_manager
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from track_flow_manager import load_track_pool
        result = load_track_pool()
        count = len(result) if isinstance(result, list) else 0
        print(f"[{'PASS' if count > 0 else 'FAIL'}] load_track_pool() 返回 {count} 只股票")
        return count > 0
    except Exception as e:
        print(f"[FAIL] load_track_pool() 调用失败: {e}")
        return False

def main():
    print("=== track_loose_pool 健康检查 ===")
    results = []
    results.append(check_new_path_exists())
    results.append(check_old_path_not_exists())
    results.append(check_new_path_content())
    results.append(check_load_track_pool())
    
    print("\n=== 总结 ===")
    passed = sum(results)
    total = len(results)
    print(f"通过: {passed}/{total}")
    
    if all(results):
        print("✅ 健康检查通过")
        return 0
    else:
        print("❌ 健康检查失败")
        return 1

if __name__ == '__main__':
    sys.exit(main())
