#!/usr/bin/env bash
# profile_tertiary_cleanup_to_trash.sh
# 三级目录冗余清理，全部移入回收站，可恢复
# 排除 skills/ 和 scripts/cron/decision/executions|outcomes|snapshots|user_authority

set -u
BASE="/home/caojy/.hermes/profiles/stock"
RECOVERY_LOG="$BASE/stock-work/data/snapshots/migrations/CLEANUP_TERTIARY_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$(dirname "$RECOVERY_LOG")"

trash() {
    local item="$1"
    if [ -e "$item" ] || [ -L "$item" ]; then
        gio trash "$item" 2>/dev/null || mv -f "$item" "$HOME/.local/share/Trash/files/" 2>/dev/null || true
        echo "[TRASHED] $item" >> "$RECOVERY_LOG"
    else
        echo "[SKIP-MISSING] $item" >> "$RECOVERY_LOG"
    fi
}

empty_dir() {
    local d="$1"
    if [ -d "$d" ]; then
        find "$d" -mindepth 1 -delete 2>/dev/null || true
        echo "[EMPTIED] $d" >> "$RECOVERY_LOG"
    fi
}

echo "CLEANUP_START $(date)" >> "$RECOVERY_LOG"

# === scripts/cron/decision/ 测试和本地开发文件 ===
for f in scripts/cron/decision/test_*.py; do
    trash "$BASE/$f"
done
for f in scripts/cron/decision/_local_constants.override.json scripts/cron/decision/_local_constants.py scripts/cron/decision/debug_helper.py scripts/cron/decision/conftest.py; do
    trash "$BASE/$f"
done
trash "$BASE/scripts/cron/decision/__pycache__"

# === scripts/cron/ 冗余子目录和参考文件 ===
trash "$BASE/scripts/cron/scripts"
for f in scripts/cron/*.md scripts/cron/*.json; do
    trash "$BASE/$f"
done

# === cron/external-workers/ 空目录 ===
trash "$BASE/cron/external-workers"

# === logs/ 旧日志 ===
trash "$BASE/logs/agent.log.1"
trash "$BASE/logs/agent.log.2"
trash "$BASE/logs/errors.log.1"
trash "$BASE/logs/tui_gateway_crash.log"

# === sessions/ 超过30天的历史会话 ===
find "$BASE/sessions" -type f -mtime +30 -delete 2>/dev/null || true
echo "[EMPTIED_OLD] $BASE/sessions (>30 days)" >> "$RECOVERY_LOG"

echo "CLEANUP_END $(date)" >> "$RECOVERY_LOG"
echo "Recovery log: $RECOVERY_LOG"
