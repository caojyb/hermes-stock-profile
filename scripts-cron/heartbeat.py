"""
统一心跳模块
============
所有 cron 任务通过此模块写入心跳文件。
heartbeat 文件格式：
{
  "task": "task_name",
  "last_run": "2026-09-14T09:30:15+08:00",
  "status": "ok",
  "detail": "completed",
  "cost_ms": 45230,
  "run_id": "a1b2c3d4",
  "expected_interval_seconds": 86400
}
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

HEARTBEAT_DIR = Path(__file__).resolve().parent.parent.parent / "stock-work" / "data" / "state" / "heartbeats"


def write(task_name: str, status: str, detail: str = "", cost_ms: int = 0, expected_interval_seconds: int = 86400) -> dict:
    """
    写入心跳文件
    
    Args:
        task_name: 任务名，与 jobs.json 的 name 一致
        status: 状态，如 ok / fail / skip
        detail: 详情，如 completed / timeout / error
        cost_ms: 执行耗时（毫秒）
        expected_interval_seconds: 期望执行间隔（秒），用于过期判断
    
    Returns:
        heartbeat dict
    """
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    heartbeat = {
        "task": task_name,
        "last_run": datetime.now().isoformat(),
        "status": status,
        "detail": detail,
        "cost_ms": cost_ms,
        "run_id": str(uuid.uuid4())[:8],
        "expected_interval_seconds": expected_interval_seconds,
    }
    (HEARTBEAT_DIR / f"{task_name}.json").write_text(
        json.dumps(heartbeat, ensure_ascii=False, indent=2)
    )
    return heartbeat
