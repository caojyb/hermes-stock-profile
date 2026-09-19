#!/bin/bash
# saturday_mega.sh — 周六持仓/推荐池 mega wrapper（2026-09-19 Census 周末收尾）
# ============================================================
# 合并 2 个周六 job 为 1 个（10:30 起顺序执行）：
#   10:30 us-stock-weekly-update          → us_stock_weekly.sh（美股持仓技术分析）
#   11:30 stock-recommendation-pool-weekly → weekly_pool_report.sh（推荐池跟踪报告）
#
# 失败策略：任一步失败记录但不中断（两个任务数据源独立：美股 Finnhub vs A股推荐池），
# 最终 exit 非0 触发告警。

set -u
cd /home/caojy/.hermes/profiles/stock/scripts/cron || exit 2
export FEISHU_DISABLE=1   # 子脚本内部直推全禁默（us_stock_monitor 有内部 feishu 推送）
PY=/home/caojy/.hermes/profiles/stock/.venv/bin/python3

T0=$(date +%s)
echo "🗓️ 【周六组合日 $(date '+%Y-%m-%d')】美股持仓 → 推荐池周报"
echo "=================================================="

run_step() {
    local label="$1"; shift
    echo ""
    echo "===== [$label] $(date '+%H:%M:%S') ====="
    local t=$(date +%s)
    "$@"
    local rc=$?
    echo "----- [$label] exit=$rc, 耗时 $(( $(date +%s) - t ))s -----"
    return $rc
}

RC=0
run_step "美股持仓周报" bash us_stock_weekly.sh || RC=1
run_step "推荐池周报" bash weekly_pool_report.sh || RC=1

echo ""
echo "=================================================="
echo "总耗时 $(( $(date +%s) - T0 ))s | 结果: $([ $RC -eq 0 ] && echo '✅ 全部成功' || echo '⚠️ 有步骤失败(见上方 exit)')"
exit $RC
