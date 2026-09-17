#!/usr/bin/env bash
# profile_secondary_cleanup_to_trash.sh
# 二级目录冗余清理，全部移入回收站，可恢复
# 排除 skills/ 不动

set -u
BASE="/home/caojy/.hermes/profiles/stock"
RECOVERY_LOG="$BASE/stock-work/data/snapshots/migrations/CLEANUP_SECONDARY_$(date +%Y%m%d_%H%M%S).log"

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

# === scripts/ 顶层独立 .py（保留 heartbeat.py，其余移入回收站）===
for f in scripts/akshare_financial_backfill.py scripts/audit_runtime_status_20260908.py scripts/daily_model_rankings.py scripts/emquantapi_full_sync.py scripts/emquantapi_priority_sync.py scripts/mx_finance_data.py scripts/recalc_stale_indicators.py; do
    trash "$BASE/$f"
done

# === scripts/cron/ 调试/临时文件 ===
for f in scripts/cron/_k2_debug_shunt.py scripts/cron/_m10c6_baseline_check.py scripts/cron/_m10c6_repro.py scripts/cron/_m10c6_repro2.py scripts/cron/_m10c6_repro3.py scripts/cron/_m10c6_repro4.py scripts/cron/_m10c6_repro5.py scripts/cron/_tmp_diagnose_positions.py scripts/cron/_tmp_position_diagnose_report.py scripts/cron/_tmp_send_long_test.py scripts/cron/_tmp_send_position_report.py scripts/cron/_tmp_send_test.py; do
    trash "$BASE/$f"
done

# === scripts/cron/ 冗余子目录 ===
for d in scripts/cron/__pycache__ scripts/cron/docs scripts/cron/archived scripts/cron/artifacts scripts/cron/charts scripts/cron/fixtures scripts/cron/receipts scripts/cron/reports scripts/cron/research scripts/cron/scripts scripts/cron/signals scripts/cron/logs; do
    trash "$BASE/$d"
done

# === stock-work/ 冗余子目录（不动 production/、governance/、core/、data/、config/、app/）===
for d in stock-work/docs stock-work/tests stock-work/runtime stock-work/outputs stock-work/logs; do
    trash "$BASE/$d"
done

# === cron/ 冗余 ===
empty_dir "$BASE/cron/output"
empty_dir "$BASE/cron/ticker_heartbeat"
empty_dir "$BASE/cron/ticker_last_success"
trash "$BASE/cron/backup_stock-weekly-screener_prompt.json"
trash "$BASE/cron/jobs.json.bak"

echo "CLEANUP_END $(date)" >> "$RECOVERY_LOG"
echo "Recovery log: $RECOVERY_LOG"
