#!/bin/bash
# 周度基本面数据刷新 wrapper
# 顺序执行：PE/PB/PS/PCF + 财务数据增量刷新
# 调度时间：周日 16:00
set -u

_t0=$(date +%s%N)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/home/caojy/.hermes/logs"
LOG_FILE="$LOG_DIR/weekly_fundamental_refresh.log"
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

exit_code=0

# 1. PE/PB/PS/PCF 刷新
bash "$SCRIPT_DIR/fetch_pe_pb_refresh.sh"; rc=$?
if [ $rc -eq 0 ]; then
    log "✅ PE/PB 刷新成功"
else
    log "❌ PE/PB 刷新失败 (exit=$rc)"
    exit_code=2
fi

# 2. 财务数据增量刷新（加 timeout 保护）
timeout 600 bash "$SCRIPT_DIR/fetch_financial_refresh.sh"; rc=$?
if [ $rc -eq 0 ]; then
    log "✅ 财务刷新成功"
elif [ $rc -eq 124 ]; then
    log "❌ 财务刷新超时 (600s)"
    exit_code=2
else
    log "❌ 财务刷新失败 (exit=$rc)"
    exit_code=2
fi

# 心跳：记录本周度刷新完成
if [ "$exit_code" != "0" ]; then
    _status="error"
    _detail="failed: exit_code=$exit_code"
else
    _status="ok"
    _detail="completed"
fi
PYTHONPATH="/home/caojy/.hermes/profiles/stock/scripts/cron:${PYTHONPATH:-}" python3 -c "from heartbeat import write; write('weekly-fundamental-refresh', '$_status', detail='$_detail', cost_ms=$(( ($(date +%s%N) - _t0) / 1000000 )), expected_interval_seconds=604800)" 2>/dev/null || true

exit $exit_code
