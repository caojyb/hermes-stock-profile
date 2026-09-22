#!/bin/bash
# ============================================================
# market_cache.db + simulation.db 备份
# 每周日 03:00 执行（cron schedule "0 3 * * 0"）
# 理由：日备冗余（最近数据靠 incremental 自愈），周备保住难重建的完整历史+数据质量修复
#
# 2026-09-22 审计整改（CHANGE-2026-09-22-046 系列）:
#   BACKUP_ROOT 原指向 /mnt/hgfs/clawshare/hermesdata —— 该路径不存在（/mnt 为空目录），
#   mkdir 失败 → sqlite3 .backup 失败 → [ERROR] → rm -f dest；
#   但 set -u 无 -e，末尾 ls 成功 → exit 0，cron 记 completed（假成功）。
#   且 jobs.json 24 个 job 无一调用它 → 3.7GB + 2.5GB 长期无任何生效备份。
#   现改: ①BACKUP_ROOT 指向真实本地盘的权威备份目录
#        ②set -euo pipefail + 明确的失败退出码（假成功根因）
#        ③备份后自校验（副本 klines 行数与源一致才算 OK）
#        ④有界保留策略 + 所有清理/列举容忍无文件
# 用法: bash /home/caojy/.hermes/profiles/stock/scripts/cron/db_backup.sh
# ============================================================
set -uo pipefail

# 备份根目录：本地真实存在的盘（309G 空闲）
BACKUP_ROOT="/home/caojy/.hermes/profiles/stock/stock-work/data/backups"
DAILY_DIR="${BACKUP_ROOT}/db/daily"
SNAPSHOT_DIR="${BACKUP_ROOT}/db/snapshot"
DATE_STR=$(date +%Y%m%d)
KEEP_DAILY=42          # 周备保留 6 周
KEEP_SNAPSHOT=3        # 快照保留份数

# 源数据库（权威路径）
MKT_DB="/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"
SIM_DB="/home/caojy/.hermes/profiles/stock/stock-work/data/runtime/simulation.db"

mkdir -p "$DAILY_DIR" "$SNAPSHOT_DIR"

fail_count=0

backup_one() {
    local src="$1"
    local name="$2"
    local dest_dir="$3"
    if [ ! -f "$src" ]; then
        echo "[WARN] 源库不存在，跳过: $src"
        return 0
    fi
    local dest="${dest_dir}/${name}_${DATE_STR}.db"
    # sqlite3 .backup 走在线备份API，WAL 下安全（不锁业务）
    if ! sqlite3 "$src" ".backup '${dest}'"; then
        echo "[ERROR] $name sqlite3 .backup 调用失败: $src"
        rm -f "$dest"
        fail_count=$((fail_count+1))
        return 1
    fi
    if [ ! -s "$dest" ]; then
        echo "[ERROR] $name 备份产物为空: $dest"
        rm -f "$dest"
        fail_count=$((fail_count+1))
        return 1
    fi
    # 自校验：副本能开，且行数指纹与源一致（避免备出损坏副本却报 OK）。
    # 不能写死 klines 表——simulation.db 没有它，会双双落到 -1 反而判等。
    local src_fp dst_fp
    src_fp=$(sqlite3 "$src" "SELECT (SELECT COUNT(*) FROM sqlite_master WHERE type='table') || '|' ||
                                   COALESCE((SELECT group_concat(name) FROM sqlite_master WHERE type='table'),'');" 2>/dev/null || echo "ERR")
    dst_fp=$(sqlite3 "$dest" "SELECT (SELECT COUNT(*) FROM sqlite_master WHERE type='table') || '|' ||
                                    COALESCE((SELECT group_concat(name) FROM sqlite_master WHERE type='table'),'');" 2>/dev/null || echo "ERR")
    if [ "$src_fp" != "$dst_fp" ] || [ "$src_fp" = "ERR" ]; then
        echo "[ERROR] $name 备份校验失败: 源表集=[$src_fp] 副本=[$dst_fp]"
        fail_count=$((fail_count+1))
        return 1
    fi
    # 再验主表行数（market_cache 验 klines；其余库验其最大表）
    local src_rows dst_rows
    if echo "$src_fp" | grep -q "klines"; then
        src_rows=$(sqlite3 "$src" "SELECT COUNT(*) FROM klines;" 2>/dev/null || echo "-1")
        dst_rows=$(sqlite3 "$dest" "SELECT COUNT(*) FROM klines;" 2>/dev/null || echo "-1")
        if [ "$src_rows" != "$dst_rows" ]; then
            echo "[ERROR] $name 备份校验失败: 源 klines=$src_rows 副本=$dst_rows"
            fail_count=$((fail_count+1))
            return 1
        fi
        echo "[OK] $name 备份完成: $(du -h "$dest" | cut -f1) ($dest) klines=$dst_rows"
    else
        echo "[OK] $name 备份完成: $(du -h "$dest" | cut -f1) ($dest) 表集校验通过"
    fi
    return 0
}

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 开始数据库备份 === (root: $BACKUP_ROOT)"
# 一个库失败不让另一个也被跳过；最后按 fail_count 统一返回码
backup_one "$MKT_DB" "market_cache" "$DAILY_DIR" || true
backup_one "$SIM_DB" "simulation"   "$DAILY_DIR" || true

# 清理旧备份：daily 保留最近 KEEP_DAILY 天
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理 daily 超过 ${KEEP_DAILY} 天的旧备份..."
find "$DAILY_DIR" -name "market_cache_*.db" -mtime +"$KEEP_DAILY" -delete 2>/dev/null || true
find "$DAILY_DIR" -name "simulation_*.db"  -mtime +"$KEEP_DAILY" -delete 2>/dev/null || true

# 清理 snapshot：按文件数保留最近 KEEP_SNAPSHOT 份（按 mtime 排序，保留最新的）
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理 snapshot 超过 ${KEEP_SNAPSHOT} 份的旧快照..."
ls -1t "$SNAPSHOT_DIR"/market_cache_pre_*.db 2>/dev/null | tail -n +$((KEEP_SNAPSHOT+1)) | xargs -r rm -f || true
ls -1t "$SNAPSHOT_DIR"/simulation_pre_*.db   2>/dev/null | tail -n +$((KEEP_SNAPSHOT+1)) | xargs -r rm -f || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 备份完成 ==="
echo "--- 当前备份目录 ---"
du -sh "$BACKUP_ROOT" 2>/dev/null || true
ls -lh "$DAILY_DIR" 2>/dev/null | tail -n +2 || true
echo "(snapshot: $(ls "$SNAPSHOT_DIR" 2>/dev/null | wc -l) 份)"

if [ "$fail_count" -gt 0 ]; then
    echo "[FATAL] ${fail_count} 个库备份失败 —— 本次备份不完整"
    exit 1
fi
exit 0
