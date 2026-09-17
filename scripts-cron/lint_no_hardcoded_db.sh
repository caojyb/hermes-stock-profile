#!/bin/bash
# 检查 scripts/cron/*.py 是否硬编码 DB 路径（忽略注释行）
set -u

FAILED=0

# H1: 直接硬编码 *.db 字符串
H1=$(grep -rnE "[A-Za-z_]*\.(market_cache|recommendation_pool|simulation|intraday_cache|news_cache)\.db" scripts/cron/*.py 2>/dev/null | grep -v "compat_paths\|get_db_path\|# " || true)
[ -n "$H1" ] && { echo "🚨 H1 直接硬编码 .db 路径："; echo "$H1"; FAILED=1; }

# H2: parents[N] 拼接 DB 文件名（盲点 A）
H2=$(grep -rnE "parents\[[0-9]+\].*(market_cache|recommendation_pool|simulation|intraday_cache|news_cache)" scripts/cron/*.py 2>/dev/null | grep -v "sys.path\|compat_paths\|# " || true)
[ -n "$H2" ] && { echo "🚨 H2 parents[] 拼接 DB 路径："; echo "$H2"; FAILED=1; }

# H3: Path('MARKET_DB') / Path('SIM_DB') / Path('POOL_DB') / Path('INTRADAY') / Path('NEWS_CACHE') 等字面量（收窄）
H3=$(grep -rnE "Path\(['\"](MARKET_DB|SIM_DB|POOL_DB|INTRADAY|NEWS_CACHE)[^'\"]*['\"]\)" scripts/cron/*.py 2>/dev/null || true)
[ -n "$H3" ] && { echo "🚨 H3 Path('DB字面量') 疑似硬编码："; echo "$H3"; FAILED=1; }

[ $FAILED -eq 1 ] && { echo "❌ 发现硬编码 DB 路径"; exit 1; }
echo "✅ 未发现硬编码 DB 路径"
exit 0
