#!/bin/bash
# ============================================================
# market_cache.db 全局写锁（串行化三个收盘写者）—— 公共实现
#
# 被三个入口脚本 source：
#   db_lock_refresh.run.sh  -> stock-market-cache-refresh (16:30)
#   db_lock_daily.run.sh    -> daily-data-refresh         (16:40)
#   db_lock_monitor.run.sh  -> double-monitor-daily       (16:50)
#
# 2026-09-22 审计整改（CHANGE-2026-09-22-047 根因链第②③环）:
#   17:18:42 三任务被 catch-up 补发成同一微秒的一簇，同时打 market_cache.db。
#   唯一写 klines 的任务 a6a60497fbb6 等锁 60s 仍拿不到写锁
#   → database is locked 崩溃，只写出 1206/5005 行，
#   下游 indicators/main_fund_flow 跟随崩塌（P0）。
#
#   实测耗时证明"错开时间"不可靠：cache-refresh 单次最长 1510s（25分钟），
#   16:30 起跑最坏辗到 16:55，任何固定间隔都会被跨越。
#   所以用 flock 全局写锁让后到者排队（refresh 是 daily 的上游，天然有序）。
#
# 退出码:
#   0   目标脚本成功
#   N   目标脚本的退出码（原样透传，cron 记 failed 而非假成功）
#   75  等锁超时（明示放弃，不排队挤爆 cron）
#   2   参数/target 错误
# ============================================================
set -uo pipefail

LOCK_DIR="/home/caojy/.hermes/profiles/stock/stock-work/data/runtime/locks"
LOCK_FILE="${LOCK_DIR}/market_cache_write.lock"
PYTHON_BIN="/home/caojy/.hermes/profiles/stock/.venv/bin/python3"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"
CRON_DIR="/home/caojy/.hermes/profiles/stock/scripts/cron"

# $1 = target；按 target 分级等锁超时。
# 上游 refresh 最坏 1510s（实测），给最大窗口；
# daily/monitor 是下游，等太久会把收盘链拖过 cron wrapper 的 600s 上限，
# 宁可失败退出让下一次 tick 重试，也不排队挤爆时段。
TARGET="${1:-}"
case "$TARGET" in
    refresh) LOCK_TIMEOUT=2100; CMD=(bash "$CRON_DIR/market_cache_refresh.sh") ;;
    daily)   LOCK_TIMEOUT=600;  CMD=("$PYTHON_BIN" "$CRON_DIR/daily_data_refresh.py") ;;
    monitor) LOCK_TIMEOUT=300;  CMD=("$PYTHON_BIN" "$CRON_DIR/double_monitor.py") ;;
    "")
        echo "[LOCK] 用法: db_lock_<target>.run.sh（缺少 target）"
        exit 2
        ;;
    *)
        echo "[LOCK] 未知 target: $TARGET"
        exit 2
        ;;
esac

mkdir -p "$LOCK_DIR"
exec 9>"$LOCK_FILE"

echo "[LOCK] $(date '+%H:%M:%S') 等待 market_cache 写锁 (target=$TARGET, timeout=${LOCK_TIMEOUT}s) ..."
if flock -x -w "$LOCK_TIMEOUT" 9; then
    echo "[LOCK] $(date '+%H:%M:%S') 获得写锁，开始 target=$TARGET"
    "${CMD[@]}"
    rc=$?
    echo "[LOCK] $(date '+%H:%M:%S') 释放写锁，target=$TARGET exit=$rc"
    exit $rc
else
    echo "[LOCK] ❌ ${LOCK_TIMEOUT}s 内未获得 market_cache 写锁 —— 放弃本次执行（不排队挤爆 cron）"
    exit 75
fi
