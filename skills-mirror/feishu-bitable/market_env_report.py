#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场环境分析报告 — 周度策略参考（P2-2 接线）
==============================================
调用 market_env_classifier 输出当前市场环境标签 + 各维度得分 + 历史相似期，
并对比 V1 翻倍 / 主升浪 两策略在该环境下的历史表现，推送飞书群。

用法:
  python3 market_env_report.py           # 生成并推送报告
  python3 market_env_report.py --local   # 只输出不推送
"""
import os, sys, json, subprocess
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
CLASSIFIER = SCRIPT_DIR / "market_env_classifier.py"

# ── 策略历史表现（诚实回测结果，PROJECT.md 决策记录） ──
STRATEGY_PERF = {
    "v1_double": {
        "name": "翻倍V1 (Top3)",
        "cagr": "+124.8%",
        "dd": "17.5%",
        "winrate": "54.5%",
        "note": "低位放量小市值，适合低位反转/震荡反弹",
        "best_env": "震荡/低位反弹",
        "risk": "高波动下回撤可能放大（压力测试验证中）",
    },
    "main_up": {
        "name": "主升浪",
        "cagr": "+27.26%",
        "dd": "8.78%",
        "winrate": "64.7%",
        "note": "ROE≥15%+均线多头+RSI40-70，趋势跟踪",
        "best_env": "强趋势/多头排列",
        "risk": "2024-2025 震荡市信号不稳定",
    },
}

# ── 环境 → 策略适配建议 ──
ENV_GUIDE = {
    "🟢 强趋势": "适合主升浪策略（趋势跟踪吃主升段）；V1 低位反弹也可参与",
    "🟡 震荡市": "适合 V1 低位放量反弹（低吸）；主升浪信号不稳应减配",
    "🔴 高波动": "⚠️ 两策略都应降仓/收紧止损，V1 需压力测试确认回撤容忍度",
    "⚫ 低量能": "需要极度保守，减少开仓频率，等待量能恢复",
    "交织状态": "方向不明，建议轻仓或观望，等趋势明确",
}


def classify():
    """运行 classifier，返回 dict"""
    r = subprocess.run(
        [sys.executable, str(CLASSIFIER)],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0:
        return {"error": r.stderr[-500:]}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"解析失败: {e}\n输出: {r.stdout[-500:]}"}


def build_report(data):
    lines = []
    lines.append("🌐 市场环境分析 · 周度策略参考")
    lines.append(f"📅 {data.get('date', datetime.now().strftime('%Y-%m-%d'))}")
    lines.append("")
    env = data.get("environment", {})
    lines.append(f"📊 当前环境: **{env.get('label', '未知')}** (总分 {env.get('total_score', '?')})")
    lines.append(f"   {env.get('description', '')}")
    lines.append("")
    lines.append("### 各维度得分")
    dims = data.get("dimensions", {})
    for k, v in dims.items():
        label_map = {"trend": "趋势", "volatility": "波动", "liquidity": "量能", "style": "风格"}
        lines.append(f"- {label_map.get(k, k)}: {v.get('score', '?')}分 ({v.get('label', '')})")
    lines.append("")
    # 环境适配建议
    env_label = env.get("label", "")
    guide = ENV_GUIDE.get(env_label) or ENV_GUIDE.get(dims.get("trend", {}).get("label", ""))
    if guide:
        lines.append(f"### 策略建议")
        lines.append(f"- {guide}")
    lines.append("")
    lines.append("### 历史相似时期")
    similar = data.get("similar_periods", [])
    if similar:
        lines.append(f"- 相似月份: {'、'.join(similar)}")
    else:
        lines.append("- 未找到显著相似期")
    lines.append("")
    lines.append("### 两策略在该环境下的参考表现")
    lines.append("| 策略 | 年化 | 最大回撤 | 胜率 | 适配场景 |")
    lines.append("|------|:----:|:-------:|:----:|---------|")
    for sid, p in STRATEGY_PERF.items():
        lines.append(f"| {p['name']} | {p['cagr']} | {p['dd']} | {p['winrate']} | {p['best_env']} |")
    lines.append("")
    lines.append("> 说明: 以上为历史诚实回测结果，极端行情下回撤可能放大，具体以压力测试报告为准。")
    lines.append("")
    return "\n".join(lines)


def send_feishu(text):
    """推送飞书群"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from feishu_sender import feishu_send_message
        r = feishu_send_message(text)
        return r
    except Exception as e:
        print(f"[ERROR] 飞书推送失败: {e}", file=sys.stderr)
        return None


def main():
    local_only = "--local" in sys.argv
    data = classify()
    if "error" in data:
        print(f"❌ 环境分类失败: {data['error']}", file=sys.stderr)
        return 1

    report = build_report(data)
    print(report)

    if not local_only:
        r = send_feishu(report)
        if r:
            print("\n✅ 已推送飞书")
        else:
            print("\n⚠️ 飞书推送失败（报告已输出）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
