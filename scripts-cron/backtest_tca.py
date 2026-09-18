#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测 TCA（交易成本分析）模块（2026-09-18 二轮审计 30 天路线 ⑩）
==============================================================
现状核查结论：backtest_engine 已含基础成本模型（佣金万2.5 双向 + 印花税
0.05% 卖出 + 滑点 0.1% 固定），calc_trade_cost 在月度调仓路径生效。

本模块补齐缺口：
1. 冲击成本（impact cost）——固定滑点对大额/低流动性成交低估成本。
   按 kyle lambda 近似: impact = k * amount / adv20（成交额占20日均额比例）
2. 成本分解报告 —— 对一次回测的交易序列输出成本构成：
   佣金/印花税/固定滑点/冲击成本 各占比，评估策略容量
3. cost_scenario —— 三档成本（乐观/基准/悲观）敏感性，alpha 需在三档下
   均为正才算稳健

成本常量与 backtest_engine 保持一致（单一真值），冲击成本参数可调。
"""
from __future__ import annotations

# 与 backtest_engine.py L29-31 一致（单一真值原则）
COMMISSION_RATE = 0.00025   # 佣金万2.5（双向）
STAMP_TAX_RATE = 0.0005     # 印花税 0.05%（仅卖出）
SLIPPAGE_RATE = 0.001       # 固定滑点 0.1%

# 冲击成本参数
IMPACT_K = 0.1              # kyle-lambda 近似系数（个人资金规模保守取 0.1）
IMPACT_CAP = 0.01           # 冲击成本上限 1%（防止极小 adv 爆炸）


def total_cost(buy_amount: float, sell_amount: float,
               adv20: float | None = None, holding_days: int | None = None) -> dict:
    """完整成本（含冲击成本）。

    Args:
        buy_amount / sell_amount: 双边金额
        adv20: 标的 20 日均成交额（None 则跳过冲击成本项）
    Returns:
        {'total', 'commission', 'stamp', 'slippage', 'impact', 'bps'}
        bps = 总成本 / (buy+sell) * 10000，便于跨策略比较
    """
    commission = (buy_amount + sell_amount) * COMMISSION_RATE
    stamp = sell_amount * STAMP_TAX_RATE
    slippage = (buy_amount + sell_amount) * SLIPPAGE_RATE
    impact = 0.0
    if adv20 and adv20 > 0:
        # 双边各按 kyle-lambda 近似: 冲击比率 = k * sqrt(amount/adv20)
        # 买入侧与卖出侧分别计算后按金额加权
        buy_ratio = min(IMPACT_K * (buy_amount / adv20) ** 0.5, IMPACT_CAP)
        sell_ratio = min(IMPACT_K * (sell_amount / adv20) ** 0.5, IMPACT_CAP)
        impact = buy_ratio * buy_amount + sell_ratio * sell_amount
    total = commission + stamp + slippage + impact
    denom = buy_amount + sell_amount
    return {
        'total': total,
        'commission': commission,
        'stamp': stamp,
        'slippage': slippage,
        'impact': impact,
        'bps': total / denom * 10000 if denom > 0 else 0.0,
    }


def decompose(trades: list[dict]) -> dict:
    """成本分解报告。

    Args:
        trades: [{'buy_amount', 'sell_amount', 'adv20'(可选)}, ...]
    Returns:
        汇总: 各成本项绝对值/占比、平均 bps、冲击成本占比（容量压力指标）
    """
    agg = {'commission': 0.0, 'stamp': 0.0, 'slippage': 0.0, 'impact': 0.0, 'total': 0.0}
    denom = 0.0
    for t in trades:
        c = total_cost(t['buy_amount'], t['sell_amount'], t.get('adv20'))
        for k in agg:
            agg[k] += c[k]
        denom += t['buy_amount'] + t['sell_amount']
    if denom <= 0:
        return {'error': 'no trades'}
    shares = {k: agg[k] / agg['total'] for k in agg if k != 'total'}
    return {
        'total': agg['total'],
        'avg_bps': agg['total'] / denom * 10000,
        'shares': shares,
        'capacity_warning': shares.get('impact', 0) > 0.3,  # 冲击成本>30% → 容量受限
    }


def cost_scenario(base_annual_return_pct: float, monthly_turnover: float = 2.0) -> dict:
    """成本敏感性：月频调仓年化收益在三档成本下的净值。

    Args:
        base_annual_return_pct: 不计成本的年化收益 %
        monthly_turnover: 月换手率（月频全换 = 2.0，双边）
    Returns:
        乐观(固定滑点减半)/基准/悲观(滑点×3+冲击) 三档的净年化
    """
    turnover_annual = monthly_turnover * 12
    scenarios = {}
    for label, slip_mult, with_impact in (('optimistic', 0.5, False),
                                          ('base', 1.0, False),
                                          ('pessimistic', 3.0, True)):
        commission = turnover_annual * COMMISSION_RATE
        stamp = turnover_annual / 2 * STAMP_TAX_RATE
        slip = turnover_annual * SLIPPAGE_RATE * slip_mult
        impact = turnover_annual * SLIPPAGE_RATE * 0.5 if with_impact else 0.0
        cost = commission + stamp + slip + impact
        scenarios[label] = {
            'cost_pct': round(cost * 100, 3),
            'net_return_pct': round(base_annual_return_pct - cost * 100, 2),
        }
    scenarios['robust'] = all(v['net_return_pct'] > 0 for k, v in scenarios.items() if k != 'robust')
    return scenarios


if __name__ == '__main__':
    # 自检
    c = total_cost(100_000, 105_000, adv20=50_000_000)
    assert c['total'] > 0 and c['impact'] >= 0
    # 小流动性冲击成本应显著更大
    c2 = total_cost(100_000, 105_000, adv20=2_000_000)
    assert c2['impact'] > c['impact'], '小 adv 冲击成本应更大'
    d = decompose([{'buy_amount': 100_000, 'sell_amount': 105_000, 'adv20': 5_000_000}] * 12)
    assert 'avg_bps' in d
    s = cost_scenario(15.0)
    assert s['pessimistic']['net_return_pct'] < s['optimistic']['net_return_pct']
    print('TCA_SELFTEST_OK')
    print(f"基准成本: {c['bps']:.1f} bps/round-trip; 冲击占比: {d['shares']['impact']*100:.0f}%")
