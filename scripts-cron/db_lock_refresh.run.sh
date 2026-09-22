#!/bin/bash
# 入口：stock-market-cache-refresh（16:30，三写者中的上游）
# 见 db_lock_common.sh 的锁设计说明。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/db_lock_common.sh" refresh
