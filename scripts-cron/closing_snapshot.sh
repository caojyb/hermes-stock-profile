#!/bin/bash
# closing_snapshot.sh — 收盘快照（2026-09-19 Census 合并工单#2）
# ============================================================
# 合并对象（原 3 个独立 job + 3 条独立飞书）：
#   15:30 daily-sentiment-report  → sentiment_thermo.py --learn
#   15:35 stock-lhb-daily         → lhb_monitor.py
#   15:40 stock-news-sentiment-pilot → news_sentiment.py
# 合并后：周一至五 15:35 一条 [信息] 收盘快照，三段拼接一次投递。
#
# 设计约束：
# 1) FEISHU_DISABLE=1 全局禁推——三段子脚本全部静默（不再有内部直推），
#    快照由 cron no_agent 模式对 wrapper stdout 整体投递（一条消息）
# 2) news_sentiment 段失败不拖垮主体（独立退出码，仅文字段降级）
# 3) sentiment 段保留 --learn（学习日志回写不受合并影响）
# 4) 数据缺失诚实标注：不编造、不静默跳过（承 sentiment_thermo 原行为）

set -u
cd /home/caojy/.hermes/profiles/stock/scripts/cron || exit 2
export FEISHU_DISABLE=1
export PYTHONPATH="/home/caojy/.hermes/profiles/stock/stock-work:/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable:${PYTHONPATH:-}"
PY=/home/caojy/.hermes/profiles/stock/.venv/bin/python3
SKILL_DIR=/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable

TODAY=$(date '+%Y-%m-%d')
echo "📸 【收盘快照 ${TODAY}】情绪 · 龙虎榜 · 舆情"
echo "=================================================="

# ── 段1: 情绪温度计 ──
echo ""
echo "🌡️ 情绪面"
echo "--------------------------------------------------"
out1=$(cd "$SKILL_DIR" && $PY sentiment_thermo.py --learn 2>/dev/null); c1=$?
echo "$out1"
[ $c1 -ne 0 ] && echo "⚠️ [sentiment_thermo exit $c1] 情绪温度计失败（已降级为文字段）"

# ── 段2: 龙虎榜 ──
echo ""
echo "🏛️ 龙虎榜"
echo "--------------------------------------------------"
out2=$($PY lhb_monitor.py 2>/dev/null); c2=$?
echo "$out2"
[ $c2 -ne 0 ] && echo "⚠️ [lhb_monitor exit $c2] 龙虎榜失败（已降级为文字段）"

# ── 段3: 舆情（仅写库不推, 有 🔴 利空命中才在快照里提示）──
# 2026-09-19: 原全文 119 条中性新闻刷屏无信息量——只保留利好/利空汇总行 + 涉及股票，
# 全文分析仍写 sentiment_results 库供下游因子查询（news_sentiment 内部行为不变）
echo ""
echo "📰 舆情"
echo "--------------------------------------------------"
out3=$($PY news_sentiment.py 2>/dev/null); c3=$?
echo "$out3" | grep -E '利好|利空|降一级|HTTP获取|候选池相关' || echo "（无利好/利空命中）"
[ $c3 -ne 0 ] && echo "⚠️ [news_sentiment exit $c3] 舆情分析失败（已降级为文字段）"

echo ""
echo "=================================================="
# 段1/2 是快照主体（任一小败即 job 失败告警）；段3 是旁路观察员，失败仅降级
if [ $c1 -ne 0 ] || [ $c2 -ne 0 ]; then
  echo "⚠️ 收盘快照部分失败: sentiment=$c1 lhb=$c2 news=$c3"
  exit 1
fi
echo "✅ 收盘快照生成完成（sentiment=$c1 lhb=$c2 news=$c3）"
exit 0
