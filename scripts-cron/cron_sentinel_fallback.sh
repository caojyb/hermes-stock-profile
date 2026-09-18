#!/usr/bin/env bash
# 系统 crontab 兜底哨兵（2026-09-18 二轮审计 P0-1）
# 仅当 hermes gateway 进程不存在时才运行完整哨兵并推飞书；
# gateway 存活时静默退出（hermes cron 08:05 的哨兵 job 负责日常检查）。
GATEWAY_ALIVE=$(pgrep -fc "hermes_cli.main gateway run" 2>/dev/null || echo 0)
if [ "$GATEWAY_ALIVE" -gt 0 ]; then
    exit 0
fi
python3 /home/caojy/.hermes/profiles/stock/scripts/cron/cron_health_sentinel.py --send
