#!/usr/bin/env bash
# profile_root_cleanup_to_trash.sh
# 将 stock profile 根目录下的冗余/遗留项移入回收站
# 使用 gio trash，可恢复

set -u
BASE="/home/caojy/.hermes/profiles/stock"
RECOVERY_LOG="$BASE/stock-work/data/snapshots/migrations/CLEANUP_TRASH_$(date +%Y%m%d_%H%M%S).log"

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

echo "CLEANUP_START $(date)" >> "$RECOVERY_LOG"

# 冗余 symlink
trash "$BASE/data"

# 冗余/遗留目录
for d in docs .curator_backups desktop home hooks image_cache lsp pairing pending_messages plans platforms runtime sandboxes skins spawn-trees terminal-sessions watcher-state workspace; do
    trash "$BASE/$d"
done

# 临时/缓存文件
for f in .hermes_history .skills_prompt_snapshot.json .update_check context_length_cache.yaml; do
    trash "$BASE/$f"
done

# 缓存目录内容清空（保留目录结构）
empty_dir() {
    local d="$1"
    if [ -d "$d" ]; then
        find "$d" -mindepth 1 -delete 2>/dev/null || true
        echo "[EMPTIED] $d" >> "$RECOVERY_LOG"
    fi
}

empty_dir "$BASE/pastes"
empty_dir "$BASE/cache"

# 模型缓存文件
for f in models_dev_cache.etag models_dev_cache.json ollama_cloud_models_cache.json provider_models_cache.json; do
    trash "$BASE/$f"
done

# 临时状态文件
for f in processes.json resolver.market_cache_db; do
    trash "$BASE/$f"
done

# 审计临时库
trash "$BASE/verification_evidence.db"

echo "CLEANUP_END $(date)" >> "$RECOVERY_LOG"
echo "Recovery log: $RECOVERY_LOG"
