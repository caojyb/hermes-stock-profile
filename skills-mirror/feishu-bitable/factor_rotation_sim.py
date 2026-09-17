#!/usr/bin/env python3
"""
因子轮动 v1.1 模拟测试 — 对比新旧规则
模拟2022年12个月因子轮动，对比：
- 旧规则：无波动率惩罚、无换手率上限
- 新规则：有波动率惩罚、有换手率上限(50%)
"""
import os, sys, json, math, statistics, random
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
import factor_rotation as fr

# 模拟2022年12个月的IC数据（基于2026-07-24真实IC分布≈历史均值）
# 基本面因子强但波动大，估值因子中等，技术因子弱且波动大
FACTOR_NAMES = {
    "fundamental": ["roe", "net_margin", "profit_growth", "revenue_growth", "gross_margin", "debt_ratio"],
    "valuation": ["pe_ttm", "pb_mrq"],
    "technical": ["rsi_14", "boll_position", "macd_hist", "ma_bullish", "volatility_20d"],
}

# 模拟IC数据：均值 + 随机波动
def generate_ic_data(seed=42):
    """生成12个月模拟IC数据"""
    random.seed(seed)
    months = []
    base_ic = {
        # 基本面（均值高，波动大）
        "roe": 0.25, "net_margin": 0.22, "profit_growth": 0.20,
        "revenue_growth": 0.15, "gross_margin": 0.12, "debt_ratio": 0.08,
        # 估值（均值中等，波动中等）
        "pe_ttm": 0.10, "pb_mrq": 0.08,
        # 技术（均值低，波动大）
        "rsi_14": 0.03, "boll_position": 0.02, "macd_hist": 0.04,
        "ma_bullish": 0.05, "volatility_20d": 0.01,
    }
    vol = {
        # 基本面波动大
        "roe": 0.15, "net_margin": 0.12, "profit_growth": 0.18,
        "revenue_growth": 0.14, "gross_margin": 0.10, "debt_ratio": 0.15,
        # 估值波动中等
        "pe_ttm": 0.08, "pb_mrq": 0.07,
        # 技术波动最大
        "rsi_14": 0.20, "boll_position": 0.18, "macd_hist": 0.15,
        "ma_bullish": 0.12, "volatility_20d": 0.22,
    }

    for m in range(12):
        ic = {}
        for name, base in base_ic.items():
            noise = random.gauss(0, vol[name])
            ic[name] = round(base + noise, 4)
        months.append({
            "date": f"2022-{m+1:02d}-01",
            "source_ic": ic,
        })
    return months


def simulate_rotation(ic_data, use_vol_penalty, max_turnover, ic_vol_override=None):
    """模拟因子轮动"""
    weights_history = []
    turnover_history = []
    current_weights = None

    for month_ic in ic_data:
        factor_ics = month_ic["source_ic"]
        result = fr.calc_ic_weights(
            factor_ics,
            smoothing=0.3,
            use_vol_penalty=use_vol_penalty,
            max_turnover=max_turnover,
            ic_vol_override=ic_vol_override,
        )
        if not result:
            continue

        # 计算换手率
        if current_weights:
            total_change = 0
            all_names = set(list(result["factors"].keys()) + list(current_weights.keys()))
            for n in all_names:
                nw = result["factors"].get(n, {}).get("effective_weight", 0)
                ow = current_weights.get(n, 0)
                total_change += abs(nw - ow)
            turnover = total_change / 2
            turnover_history.append(turnover)
        else:
            turnover_history.append(0)

        # 保存当前权重
        current_weights = {n: result["factors"][n]["effective_weight"] for n in result["factors"]}
        weights_history.append(result)

    return weights_history, turnover_history


def main():
    print("=" * 60)
    print("因子轮动 v1.1 模拟测试 — 2022年12个月数据")
    print("=" * 60)

    # 生成模拟数据
    ic_data = generate_ic_data()

    # 计算IC波动率（使用整个12个月的数据）
    ic_vol = {}
    for name in FACTOR_NAMES["fundamental"] + FACTOR_NAMES["valuation"] + FACTOR_NAMES["technical"]:
        ics = [m["source_ic"].get(name, 0) for m in ic_data if name in m["source_ic"]]
        if len(ics) >= 3:
            ic_vol[name] = statistics.stdev(ics)

    print(f"\n📊 因子IC波动率（12个月）:")
    for name, vol in sorted(ic_vol.items(), key=lambda x: -x[1]):
        print(f"  {name:<20s} IC_std={vol:.4f}")

    # 旧规则：无波动率惩罚，无换手率上限
    print(f"\n{'='*60}")
    print("📉 旧规则：无波动率惩罚 + 无换手率上限")
    print(f"{'='*60}")
    old_weights, old_turnover = simulate_rotation(ic_data, use_vol_penalty=False, max_turnover=1.0)
    avg_old_to = sum(old_turnover) / len(old_turnover) * 100 if old_turnover else 0
    max_old_to = max(old_turnover) * 100 if old_turnover else 0
    print(f"  平均换手率: {avg_old_to:.1f}%")
    print(f"  最大换手率: {max_old_to:.1f}%")
    print(f"  超过50%的月份: {sum(1 for t in old_turnover if t > 0.50)}/{len(old_turnover)}")

    # 显示12个月组权重变化
    print(f"\n  {'月份':<10s} {'基本面':<8s} {'估值':<8s} {'技术':<8s} {'换手率':<8s}")
    for i, (r, t) in enumerate(zip(old_weights, old_turnover)):
        g = r["groups"]
        print(f"  2022-{i+1:02d}  {g.get('fundamental',0)*100:>5.1f}%  {g.get('valuation',0)*100:>5.1f}%  {g.get('technical',0)*100:>5.1f}%  {t*100:>5.1f}%")

    # 新规则：有波动率惩罚，换手率上限50%
    print(f"\n{'='*60}")
    print("📈 新规则：有波动率惩罚 + 换手率上限50%")
    print(f"{'='*60}")
    new_weights, new_turnover = simulate_rotation(ic_data, use_vol_penalty=True, max_turnover=0.50, ic_vol_override=ic_vol)
    avg_new_to = sum(new_turnover) / len(new_turnover) * 100 if new_turnover else 0
    max_new_to = max(new_turnover) * 100 if new_turnover else 0
    print(f"  平均换手率: {avg_new_to:.1f}%")
    print(f"  最大换手率: {max_new_to:.1f}%")
    print(f"  超过50%的月份（裁剪前）: {sum(1 for t in new_turnover if t > 0.50)}/{len(new_turnover)}")

    print(f"\n  {'月份':<10s} {'基本面':<8s} {'估值':<8s} {'技术':<8s} {'换手率':<8s}")
    for i, (r, t) in enumerate(zip(new_weights, new_turnover)):
        g = r["groups"]
        print(f"  2022-{i+1:02d}  {g.get('fundamental',0)*100:>5.1f}%  {g.get('valuation',0)*100:>5.1f}%  {g.get('technical',0)*100:>5.1f}%  {t*100:>5.1f}%")

    # 对比总结
    print(f"\n{'='*60}")
    print("📋 对比总结")
    print(f"{'='*60}")
    print(f"  {'指标':<20s} {'旧规则':<15s} {'新规则':<15s} {'变化':<15s}")
    print(f"  {'-'*65}")
    print(f"  {'平均换手率':<20s} {avg_old_to:>6.1f}%         {avg_new_to:>6.1f}%         {'↓' if avg_new_to < avg_old_to else '↑'}{abs(avg_new_to-avg_old_to):.1f}%")
    print(f"  {'最大换手率':<20s} {max_old_to:>6.1f}%         {max_new_to:>6.1f}%         {'↓' if max_new_to < max_old_to else '↑'}{abs(max_new_to-max_old_to):.1f}%")

    # 计算最大回撤（模拟组合净值）
    print(f"\n  📊 模拟组合净值回撤比较（简化等权组合）:")
    for label, wh, to in [("旧规则", old_weights, old_turnover), ("新规则", new_weights, new_turnover)]:
        equity = [1.0]
        for i in range(1, len(wh)):
            # 模拟月收益：假设基本面因子月收益2%，估值1%，技术0.5%
            g = wh[i]["groups"]
            monthly_ret = (g.get("fundamental", 0.33) * 0.02 +
                          g.get("valuation", 0.33) * 0.01 +
                          g.get("technical", 0.33) * 0.005)
            # 扣除换手成本（单边换手成本0.3%）
            tc = to[i] * 0.003
            equity.append(equity[-1] * (1 + monthly_ret - tc))
        peak = max(equity)
        mdd = max((peak - v) / peak for v in equity)
        final_ret = (equity[-1] / equity[0] - 1) * 100
        print(f"    {label:<8s}: 累计收益{final_ret:+.2f}%, 最大回撤{mdd*100:.2f}%")

    # 显示波动率惩罚对不同因子的影响
    print(f"\n  📐 因子波动率惩罚效果（12月平均）:")
    for name in sorted(ic_vol.keys(), key=lambda n: -ic_vol[n]):
        # 计算旧规则平均权重 vs 新规则平均权重
        old_avg = sum(r["factors"].get(name, {}).get("effective_weight", 0) for r in old_weights) / len(old_weights) * 100
        new_avg = sum(r["factors"].get(name, {}).get("effective_weight", 0) for r in new_weights) / len(new_weights) * 100
        change = new_avg - old_avg
        vol = ic_vol[name]
        print(f"    {name:<20s} IC_std={vol:.4f}  旧权重{old_avg:>5.2f}% → 新权重{new_avg:>5.2f}%  ({'+' if change>0 else ''}{change:+.2f}%)")


if __name__ == "__main__":
    main()