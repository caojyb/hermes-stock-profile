#!/usr/bin/env python3
"""
market_cache_refresh 健康检查脚本
每天 17:30 执行，验证 9-15 及之后的市场缓存刷新是否正常。
"""
import os
import sys
import json
import sqlite3
import re
from datetime import date, datetime
from pathlib import Path

# 路径设置
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / 'stock-work'))
from core.compat_paths import MARKET_DB
MARKET_DB = Path(MARKET_DB)
LOG_FILE = Path.home() / '.hermes/logs/market_cache_refresh.log'
HEARTBEAT_DIR = BASE_DIR / 'stock-work' / 'data' / 'state' / 'heartbeats'

sys.path.insert(0, str(BASE_DIR / 'skills' / 'stock' / 'stock-expert' / 'skills' / 'feishu-bitable'))


def send_feishu(msg: str):
    try:
        from feishu_sender import feishu_send_message
        feishu_send_message(msg)
    except Exception as e:
        print(f"[WARN] 飞书发送失败: {e}")


def check_klines_count() -> tuple[bool, str]:
    """检查今天 klines 数量是否 > 5000"""
    try:
        conn = sqlite3.connect(MARKET_DB, timeout=60)
        cur = conn.cursor()
        today = date.today().isoformat()
        cur.execute("SELECT COUNT(DISTINCT code) FROM klines WHERE date = ?", (today,))
        count = cur.fetchone()[0]
        conn.close()
        if count > 5000:
            return True, f"✅ 今日K线股票数: {count}"
        else:
            return False, f"⚠️ 今日K线股票数仅 {count}（预期 >5000）"
    except Exception as e:
        return False, f"❌ K线数量检查失败: {e}"


def check_market_cache_log() -> tuple[bool, str]:
    """检查日志中今天是否有 stocks 列表长度日志"""
    if not LOG_FILE.exists():
        return False, f"⚠️ 日志文件不存在: {LOG_FILE}"
    
    try:
        content = LOG_FILE.read_text()
        today = date.today().isoformat()
        # 查找今天的日志
        today_pattern = re.compile(rf'{today}.*?待更新 stocks=(\d+)', re.DOTALL)
        matches = today_pattern.findall(content)
        
        if not matches:
            return False, f"⚠️ 今日无 market_cache 日志（可能未执行）"
        
        # 取最后一次的 stocks 数
        last_stocks = int(matches[-1])
        if last_stocks > 5000:
            return True, f"✅ 今日 stocks 列表长度: {last_stocks}"
        elif last_stocks > 0:
            return False, f"⚠️ 今日 stocks 列表长度仅 {last_stocks}（预期 >5000）"
        else:
            return False, f"🚨 今日 stocks 列表为空（可能 DB_PATH 切换或数据异常）"
    except Exception as e:
        return False, f"❌ 日志检查失败: {e}"


def check_duration() -> tuple[bool, str]:
    """检查 executions.db 中今天 market_cache 的 duration"""
    try:
        executions_db = BASE_DIR / 'cron' / 'executions.db'
        if not executions_db.exists():
            return False, "⚠️ executions.db 不存在"
        
        conn = sqlite3.connect(executions_db, timeout=60)
        cur = conn.cursor()
        today = date.today().isoformat()
        # 查找今天的 market_cache 任务
        cur.execute("""
            SELECT job_id, strftime('%s', finished_at) - strftime('%s', started_at) as duration_sec
            FROM executions
            WHERE job_id = 'a6a60497fbb6'
              AND DATE(claimed_at) = ?
            ORDER BY claimed_at DESC LIMIT 1
        """, (today,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return False, "⚠️ 今日无 market_cache 执行记录"
        
        job_id, duration_sec = row
        if duration_sec is None:
            return False, "⚠️ market_cache duration 为 NULL"
        
        if duration_sec > 100:
            return True, f"✅ market_cache duration: {duration_sec}s"
        else:
            return False, f"⚠️ market_cache duration 仅 {duration_sec}s（预期 >100s，可能假成功）"
    except Exception as e:
        return False, f"❌ duration 检查失败: {e}"


def main():
    today = date.today().isoformat()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始 market_cache 健康检查...")
    
    checks = [
        ("K线数量", check_klines_count),
        ("日志 stocks 列表", check_market_cache_log),
        ("执行 duration", check_duration),
    ]
    
    issues = []
    report_lines = []
    
    for name, check_fn in checks:
        passed, msg = check_fn()
        report_lines.append(msg)
        if not passed:
            issues.append(f"❌ {name}: {msg}")
    
    # 输出报告
    print("\n" + "=" * 55)
    print("🏥 market_cache 健康检查")
    print(f"   检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)
    
    for line in report_lines:
        print(line)
    
    if issues:
        print("\n" + "!" * 55)
        print(f"⚠️ 发现 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  {issue}")
        print("!" * 55)
        
        # 飞书告警
        feishu_msg = f"🚨 market_cache 健康检查异常 [{today}]\n\n"
        feishu_msg += "\n".join(issues)
        send_feishu(feishu_msg)
        return 1
    else:
        print(f"\n✅ market_cache 运行正常")
        return 0


if __name__ == '__main__':
    sys.exit(main())
