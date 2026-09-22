#!/bin/bash
# 入口：daily-data-refresh（16:40，依赖上游 refresh 的 klines）
# 见 db_lock_common.sh 的锁设计说明。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$DIR/db_lock_common.sh" daily
