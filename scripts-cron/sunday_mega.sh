#!/bin/bash
# sunday_mega.sh — 周日数据+报告 mega wrapper（2026-09-19 Census 周末收尾）
# ============================================================
# 合并 4 个周日 job 为 1 个（16:00 起顺序执行）：
#   16:00 weekly-fundamental-refresh → weekly_fundamental_refresh.sh（PE/PB/财务，最慢, 打头）
#   17:20 stock-weekly-screener      → stock_screener_wrapper.sh（候选池+环境分析段, 已含 env 合并）
#   17:50 stock-weekly-pipeline      → stock_pipeline_wrapper.sh（全流程引擎+知识库+学习记录）
#   18:30 lockup-refresh-weekly      → refresh_lockup.py（解禁+减持, deliver=local 不推）
#
# 顺序依据（数据依赖）：fundamental(PE/财务) 是 screener 基本面预筛的输入 → 必须先跑；
# pipeline 读 screener 产出的候选池 → 其次；lockup 只写本地库无下游依赖 → 垫尾。
# 原 4 个独立 job 的触发点（16:00/17:20/17:50/18:30）天然就是顺序执行的，合并不改变依赖语义。
#
# 失败策略（承各 wrapper 原有语义）：
#   - fundamental 失败 → 继续跑 screener（预筛会用旧 PE, wrapper 内有日志可查），但 job 最终 exit 1
#   - screener 失败 → 继续跑 pipeline（后者不依赖前者产物时才安全, 实测 pipeline 读 market_cache 独立）
#   - 任一步失败都记录但不中断——与"周末任务尽量跑完"的原语义一致, 最终 exit 非0 触发告警

set -u
cd /home/caojy/.hermes/profiles/stock/scripts/cron || exit 2
export FEISHU_DISABLE=1   # 子脚本内部直推全禁默, 由 cron 对本 wrapper stdout 整体投递一条
PY=/home/caojy/.hermes/profiles/stock/.venv/bin/python3

T0=$(date +%s)
echo "🗓️ 【周日数据日 $(date '+%Y-%m-%d')】基本面 → 周选 → 全流程 → 解禁"
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

# 1) 基本面刷新（PE/PB/PS/PCF + 财务增量）
run_step "基本面刷新" bash weekly_fundamental_refresh.sh || RC=1

# 2) 翻倍周选 + 市场环境分析段（原 17:20）
run_step "翻倍周选+环境分析" bash stock_screener_wrapper.sh || RC=1

# 3) 全流程引擎 + 知识库 + 学习记录（原 17:50）
run_step "全流程引擎" bash stock_pipeline_wrapper.sh || RC=1

# 4) 解禁+减持刷新（原 18:30, 本地库）
run_step "解禁减持刷新" "$PY" refresh_lockup.py || RC=1

echo ""
echo "=================================================="
echo "总耗时 $(( $(date +%s) - T0 ))s | 结果: $([ $RC -eq 0 ] && echo '✅ 全部成功' || echo '⚠️ 有步骤失败(见上方 exit)')"
exit $RC
