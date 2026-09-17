#!/usr/bin/env python3
"""周度回撤检查：查最新 portfolio_snapshots.max_drawdown_pct，< 15% 发飞书提醒。"""
import sys
import os
import json
import time
from pathlib import Path
from datetime import date, datetime

# 依赖：feishu_sender、core.compat_paths
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'stock-work'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills' / 'stock' / 'stock-expert' / 'skills' / 'feishu-bitable'))

from core.compat_paths import SIMULATION_DB


def get_latest_drawdown(db_path: str) -> float | None:
    """查最新 portfolio_snapshots.max_drawdown_pct。"""
    import sqlite3
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT max_drawdown_pct FROM portfolio_snapshots ORDER BY date DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0] is not None:
            return float(row[0])
    except Exception as e:
        print(f"[WARN] 查询回撤失败: {e}")
    return None


def send_feishu(msg: str) -> None:
    """发飞书提醒。"""
    try:
        from feishu_sender import feishu_send_message
        feishu_send_message(msg)
    except Exception as e:
        print(f"[WARN] 飞书发送失败: {e}")



from heartbeat import write

def main() -> int:
    print("=== 周度回撤检查 ===")
    today = date.today().isoformat()
    print(f"检查日期: {today}")
    _t0 = time.time()

    drawdown = get_latest_drawdown(SIMULATION_DB)

    # 心跳：不管什么结果都写
    write(
        "check-drawdown-weekly",
        "ok",
        detail=f"drawdown={drawdown}",
        cost_ms=int((time.time() - _t0) * 1000),
        expected_interval_seconds=7 * 86400,
    )

    if drawdown is None:
        msg = "📊 周度回撤检查：暂无回撤数据"
        print(msg)
        send_feishu(msg)
        return 0

    print(f"最新 max_drawdown_pct: {drawdown:.2f}%")

    # 只有 < 15% 才发飞书提醒
    if drawdown < 15.0:
        msg = (
            f"✅ 回撤已恢复至 {drawdown:.2f}%，"
            f"可执行 buy_executor 集成验证"
        )
        print(msg)
        send_feishu(msg)
    else:
        # >= 15% 静默跳过
        print(f"  回撤 {drawdown:.2f}% >= 15%，静默跳过")

    return 0


if __name__ == "__main__":
    sys.exit(main())
