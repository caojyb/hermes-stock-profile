#!/usr/bin/env python3
"""
策略优化器 — 参数扫描 + 胜率提升实验
===========================================
对三档推荐系统进行参数网格搜索，找到最优配置。
同时测试新增因子（成交量、MACD、市场情绪过滤）对胜率的提升效果。

用法：
  python3 optimize_strategy.py                            # 全参数扫描（慢）
  python3 optimize_strategy.py --quick                     # 快速扫描（只调关键参数）
  python3 optimize_strategy.py --tier aggressive --quick   # 只扫激进档
"""

import os, sys, json, math, copy, time
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

# 导入回测模块
import backtest_recommend as bt

# ═══════════════════════════════════════════════
# 参数网格
# ═══════════════════════════════════════════════

# 激进档参数扫描
AGGRESSIVE_GRID = {
    'rsi_max': [20, 25, 30, 35],
    'boll_pos_max': [15, 20, 25, 30],
    'stop_loss_pct': [0.05, 0.07, 0.10],
    'take_profit_pct': [0.08, 0.10, 0.12, 0.15],
    'hold_days_max': [5, 7, 10, 15],
    'rebalance_freq': [3, 5, 10],
}

# 稳健档参数扫描
STEADY_GRID = {
    'rsi_min': [35, 40, 45],
    'rsi_max': [65, 70, 75],
    'boll_pos_min': [15, 20, 25],
    'boll_pos_max': [65, 70, 75],
    'stop_loss_pct': [0.03, 0.05, 0.07],
    'take_profit_pct': [0.10, 0.15, 0.20],
    'hold_days_max': [15, 20, 30],
    'rebalance_freq': [3, 5, 10, 20],
}

# 价值档参数扫描
VALUE_GRID = {
    'roe_min': [10, 15, 20],
    'profit_growth_min': [5, 10, 15],
    'debt_ratio_max': [50, 60, 70],
    'pe_max': [30, 40, 50],
    'stop_loss_pct': [0.07, 0.10, 0.15],
    'take_profit_pct': [0.20, 0.30, 0.40],
    'hold_days_max': [60, 90, 120],
    'rebalance_freq': [10, 20, 30],
}

# ═══════════════════════════════════════════════
# 新增增强因子
# ═══════════════════════════════════════════════

def calc_macd(closes, fast=12, slow=26, signal=9):
    """计算MACD"""
    if len(closes) < slow + signal:
        return None, None, None
    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(data[i] * k + result[-1] * (1 - k))
        return result
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    dea = ema(dif[-signal:], signal) if len(dif) >= signal else [0]
    macd = 2 * (dif[-1] - dea[-1]) if dea else 0
    return dif[-1], dea[-1] if dea else 0, macd


def calc_volume_ratio(klines, as_of_date, lookback=5):
    """计算成交量比（当前量 / 5日均量）"""
    # 获取最近5天和之前20天的成交量
    recent_vol = []
    avg_vol = []
    for k in reversed(klines):
        if len(recent_vol) < lookback:
            recent_vol.append(k[2])  # volume
        elif len(avg_vol) < lookback * 4:
            avg_vol.append(k[2])
        else:
            break
    if not recent_vol or not avg_vol:
        return None
    return sum(recent_vol) / len(recent_vol) / (sum(avg_vol) / len(avg_vol)) if sum(avg_vol) > 0 else None


def calc_atr(closes, highs, lows, period=14):
    """计算平均真实波幅"""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i-1])
        lc = abs(lows[i] - closes[i-1])
        trs.append(max(hl, hc, lc))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def calc_market_sentiment(data_cache, as_of_date):
    """计算市场情绪（涨跌比）"""
    price_map = data_cache.get('price_map', {})
    day_prices = price_map.get(as_of_date, {})
    if not day_prices:
        return None
    
    # 找前一个交易日
    all_dates = sorted(data_cache.get('trading_dates', []))
    idx = all_dates.index(as_of_date) if as_of_date in all_dates else -1
    if idx < 1:
        return None
    prev_date = all_dates[idx - 1]
    prev_prices = price_map.get(prev_date, {})
    if not prev_prices:
        return None
    
    up = down = 0
    for code, price in day_prices.items():
        if code in prev_prices and prev_prices[code] > 0:
            ret = (price - prev_prices[code]) / prev_prices[code]
            if ret > 0.02:
                up += 1
            elif ret < -0.02:
                down += 1
    
    total = up + down
    if total == 0:
        return 0.5
    return up / total


# ═══════════════════════════════════════════════
# 增强版筛选函数（带额外因子）
# ═══════════════════════════════════════════════

def screen_aggressive_enhanced(data_cache, as_of_date, all_codes, max_candidates=10,
                                rsi_max=25, boll_pos_max=20, req_score=50,
                                use_macd=False, use_volume=False, use_sentiment=False,
                                min_vol_ratio=0.5, max_vol_ratio=5.0):
    """增强版激进档筛选"""
    cfg = bt.TIER_CONFIGS['aggressive']
    klines = data_cache['klines']
    financial = data_cache['financial']
    stocks = data_cache['stocks']
    candidates = []

    for code in all_codes:
        sinfo = stocks.get(code)
        if sinfo:
            if sinfo.get('is_st', 0) == 1:
                continue
            if any(sinfo.get('name', '').startswith(p) for p in ('ST', '*ST', 'S')):
                continue

        kdata = klines.get(code)
        if not kdata:
            continue

        sliced = bt.get_kline_slice(kdata, as_of_date, 120)
        if not sliced:
            continue
        closes, highs, lows = sliced

        current_price = closes[-1]
        if current_price <= 0:
            continue

        rsi = bt.calc_rsi_from_list(closes, 14)
        if rsi is None or rsi >= rsi_max:
            continue

        _, _, _, boll_pos = bt.calc_bollinger_from_list(closes, 20)
        if boll_pos is None or boll_pos >= boll_pos_max:
            continue

        # MACD确认（可选）
        if use_macd:
            dif, dea, macd = calc_macd(closes)
            if macd is None or macd > 0:  # 超跌反弹期望MACD在零轴下方
                continue

        # 成交量过滤（可选）
        if use_volume:
            vol_ratio = calc_volume_ratio(kdata, as_of_date)
            if vol_ratio is None or vol_ratio < min_vol_ratio or vol_ratio > max_vol_ratio:
                continue

        # 基本面
        fin = financial.get(code)
        if fin and fin.get('debt_ratio', 0) > 80:
            continue

        fin_score = bt.calc_fundamental_score(fin)
        tech_score = 0
        if rsi < 20: tech_score = 80
        elif rsi < rsi_max: tech_score = 70
        else: tech_score = 50
        if boll_pos < 10: tech_score += 20
        elif boll_pos < boll_pos_max: tech_score += 10

        signal_score = tech_score * 0.6 + fin_score * 0.4
        if signal_score < req_score:
            continue

        candidates.append({
            'code': code, 'name': sinfo.get('name', code) if sinfo else code,
            'price': current_price, 'rsi': rsi, 'boll_pos': boll_pos,
            'signal_score': signal_score, 'fin_score': fin_score,
        })

    candidates.sort(key=lambda x: x['signal_score'], reverse=True)
    return candidates[:max_candidates]


# ═══════════════════════════════════════════════
# 优化版回测（支持参数覆盖）
# ═══════════════════════════════════════════════

def run_optimized_backtest(tier_name, data_cache, start_date, end_date, 
                           param_overrides=None, use_macd=False, use_volume=False,
                           use_sentiment=False):
    """带参数覆盖的回测运行"""
    cfg = copy.deepcopy(bt.TIER_CONFIGS[tier_name])
    if param_overrides:
        cfg.update(param_overrides)
    
    rebalance_freq = param_overrides.get('rebalance_freq', 5) if param_overrides else 5

    trading_dates = [d for d in data_cache['trading_dates'] if start_date <= d <= end_date]
    price_map = data_cache['price_map']
    all_codes = list(data_cache['klines'].keys())

    if len(trading_dates) < 20:
        return {'tier': cfg['name'], 'error': f'交易日不足', 'n_trades': 0, 'win_rate': 0}

    initial_capital = 1_000_000
    capital = initial_capital
    positions = []
    closed_trades = []

    rebalance_dates = set()
    for i, d in enumerate(trading_dates):
        if i % rebalance_freq == 0:
            rebalance_dates.add(d)

    equity_curve = [1.0]

    for i, current_date in enumerate(trading_dates):
        day_prices = price_map.get(current_date, {})
        if not day_prices:
            continue

        # 止损止盈检查
        to_close = []
        for pos in positions:
            if pos.status != 'holding':
                continue
            pos.hold_days += 1
            if pos.code in day_prices:
                cp = day_prices[pos.code]
                if cp <= pos.stop_loss_price:
                    to_close.append((pos, cp, '止损'))
                elif cp >= pos.take_profit_price:
                    to_close.append((pos, cp, '止盈'))
                elif pos.hold_days >= pos.hold_days_max:
                    to_close.append((pos, cp, '到期'))

        for pos, exit_price, reason in to_close:
            pos.status = 'closed'
            pos.exit_date = current_date
            pos.exit_price = exit_price
            pos.exit_reason = reason
            buy_value = pos.entry_price * pos.shares
            sell_value = exit_price * pos.shares
            cost = bt.calc_trade_cost(buy_value, sell_value)
            net_return = (sell_value - buy_value - cost) / buy_value * 100
            pos.return_pct = net_return
            closed_trades.append(pos)

        # 调仓：筛选新候选
        if current_date in rebalance_dates:
            held_codes = {p.code for p in positions if p.status == 'holding'}
            
            # 使用增强版筛选（如果启用了额外因子）
            if tier_name == 'aggressive' and (use_macd or use_volume):
                rsi_max = cfg.get('rsi_max', 25)
                boll_pos_max = cfg.get('boll_pos_max', 20)
                candidates = screen_aggressive_enhanced(
                    data_cache, current_date, all_codes, max_candidates=10,
                    rsi_max=rsi_max, boll_pos_max=boll_pos_max,
                    use_macd=use_macd, use_volume=use_volume
                )
            else:
                screen_fn = {
                    'aggressive': bt.screen_aggressive_fast,
                    'steady': bt.screen_steady_fast,
                    'value': bt.screen_value_fast,
                }[tier_name]
                candidates = screen_fn(data_cache, current_date, all_codes, max_candidates=10)

            for c in candidates:
                code = c['code']
                if code in held_codes:
                    continue
                if code not in day_prices:
                    continue
                entry_price = day_prices[code]
                if entry_price <= 0:
                    continue

                n_holding = len([p for p in positions if p.status == 'holding'])
                if n_holding >= cfg['max_positions']:
                    break

                max_invest = initial_capital * cfg['max_position_pct']
                invest_amount = min(max_invest, max_invest)
                if invest_amount < entry_price * 100:
                    continue

                shares = int(invest_amount / entry_price / 100) * 100
                if shares < 100:
                    continue

                pos = bt.Position(
                    code=code, name=c.get('name', code),
                    entry_date=current_date, entry_price=entry_price,
                    shares=shares, capital_pct=cfg['max_position_pct'] * 100,
                    tier=tier_name,
                    sl_pct=cfg['stop_loss_pct'], tp_pct=cfg['take_profit_pct'],
                    hold_days_max=cfg['hold_days_max']
                )
                positions.append(pos)

    # 计算指标
    n_trades = len(closed_trades)
    if n_trades == 0:
        return {'tier': cfg['name'], 'n_trades': 0, 'win_rate': 0, 'total_return': 0}

    wins = [t for t in closed_trades if t.return_pct > 0]
    losses = [t for t in closed_trades if t.return_pct <= 0]
    win_rate = len(wins) / n_trades * 100
    avg_win = sum(t.return_pct for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t.return_pct for t in losses) / len(losses)) if losses else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    total_return = sum(t.return_pct for t in closed_trades)
    
    # 年化估算
    years = (datetime.strptime(end_date, '%Y-%m-%d') - datetime.strptime(start_date, '%Y-%m-%d')).days / 365.25
    annual_return = (1 + total_return / 100) ** (1 / years) - 1 if years > 0 else 0

    return {
        'tier': cfg['name'],
        'n_trades': n_trades,
        'win_rate': round(win_rate, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_loss_ratio': round(profit_loss_ratio, 2),
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return * 100, 2),
        'param': param_overrides or {},
        'use_macd': use_macd,
        'use_volume': use_volume,
    }


# ═══════════════════════════════════════════════
# 参数扫描主程序
# ═══════════════════════════════════════════════

def grid_search(tier_name, data_cache, start_date, end_date, grid, quick=False):
    """网格搜索最优参数"""
    import itertools
    
    if tier_name == 'aggressive':
        grid = AGGRESSIVE_GRID
        default = bt.TIER_CONFIGS['aggressive']
    elif tier_name == 'steady':
        grid = STEADY_GRID
        default = bt.TIER_CONFIGS['steady']
    else:
        grid = VALUE_GRID
        default = bt.TIER_CONFIGS['value']

    # 生成所有参数组合
    keys = list(grid.keys())
    values = list(grid.values())
    
    if quick:
        # 快速扫描：只取每个参数的两端+中间
        quick_values = []
        for v in values:
            if len(v) >= 3:
                quick_values.append([v[0], v[len(v)//2], v[-1]])
            else:
                quick_values.append(v)
        values = quick_values
    
    all_combos = list(itertools.product(*values))
    print(f"  参数组合数: {len(all_combos)}", file=sys.stderr)
    
    results = []
    for i, combo in enumerate(all_combos):
        params = dict(zip(keys, combo))
        if i % 20 == 0:
            print(f"  进度: {i}/{len(all_combos)}", file=sys.stderr)
        
        r = run_optimized_backtest(tier_name, data_cache, start_date, end_date, 
                                    param_overrides=params)
        results.append((r['win_rate'], r['annual_return'], r['n_trades'], r['profit_loss_ratio'], params))
    
    # 按胜率排序
    results.sort(key=lambda x: -x[0])
    
    print(f"\n  📊 {tier_name} 参数扫描 Top 10（按胜率）", file=sys.stderr)
    print(f"  {'排名':<4} {'胜率':<8} {'年化':<8} {'交易':<6} {'盈亏比':<8} {'关键参数'}", file=sys.stderr)
    print(f"  {'-'*60}", file=sys.stderr)
    for i, (wr, ar, nt, plr, params) in enumerate(results[:10]):
        key_params = {k: v for k, v in params.items() if k in ['rsi_max', 'boll_pos_max', 'stop_loss_pct', 'take_profit_pct', 'rsi_min', 'hold_days_max']}
        print(f"  {i+1:<4} {wr:<8.1f} {ar:<8.2f} {nt:<6} {plr:<8.2f} {key_params}", file=sys.stderr)
    
    return results[:5]


def test_enhancements(tier_name, data_cache, start_date, end_date):
    """测试增强因子对胜率的影响"""
    print(f"\n  🔬 测试增强因子: {tier_name}", file=sys.stderr)
    
    # 基准
    base = run_optimized_backtest(tier_name, data_cache, start_date, end_date)
    print(f"  {'因子':<20} {'胜率':<8} {'年化':<8} {'交易':<6} {'盈亏比':<8}", file=sys.stderr)
    print(f"  {'-'*55}", file=sys.stderr)
    print(f"  {'基准':<20} {base['win_rate']:<8.1f} {base['annual_return']:<8.2f} {base['n_trades']:<6} {base['profit_loss_ratio']:<8.2f}", file=sys.stderr)
    
    # +MACD
    if tier_name == 'aggressive':
        r_macd = run_optimized_backtest(tier_name, data_cache, start_date, end_date, use_macd=True)
        print(f"  {'+MACD过滤':<20} {r_macd['win_rate']:<8.1f} {r_macd['annual_return']:<8.2f} {r_macd['n_trades']:<6} {r_macd['profit_loss_ratio']:<8.2f}", file=sys.stderr)
    
    # 调整止损 (aggressive: -5%→-7%, steady: -3%→-5%)
    if tier_name == 'aggressive':
        r_sl = run_optimized_backtest(tier_name, data_cache, start_date, end_date, 
                                      param_overrides={'stop_loss_pct': 0.05, 'take_profit_pct': 0.10})
        print(f"  {'止损-5%':<20} {r_sl['win_rate']:<8.1f} {r_sl['annual_return']:<8.2f} {r_sl['n_trades']:<6} {r_sl['profit_loss_ratio']:<8.2f}", file=sys.stderr)
        
        r_sl2 = run_optimized_backtest(tier_name, data_cache, start_date, end_date, 
                                       param_overrides={'stop_loss_pct': 0.10, 'take_profit_pct': 0.15})
        print(f"  {'止损-10%止盈+15%':<20} {r_sl2['win_rate']:<8.1f} {r_sl2['annual_return']:<8.2f} {r_sl2['n_trades']:<6} {r_sl2['profit_loss_ratio']:<8.2f}", file=sys.stderr)
    
    elif tier_name == 'steady':
        r_sl = run_optimized_backtest(tier_name, data_cache, start_date, end_date,
                                      param_overrides={'stop_loss_pct': 0.03, 'take_profit_pct': 0.15})
        print(f"  {'止损-3%':<20} {r_sl['win_rate']:<8.1f} {r_sl['annual_return']:<8.2f} {r_sl['n_trades']:<6} {r_sl['profit_loss_ratio']:<8.2f}", file=sys.stderr)
        
        r_sl2 = run_optimized_backtest(tier_name, data_cache, start_date, end_date,
                                       param_overrides={'stop_loss_pct': 0.07, 'take_profit_pct': 0.20})
        print(f"  {'止损-7%止盈+20%':<20} {r_sl2['win_rate']:<8.1f} {r_sl2['annual_return']:<8.2f} {r_sl2['n_trades']:<6} {r_sl2['profit_loss_ratio']:<8.2f}", file=sys.stderr)
    
    # 调仓频率
    for freq in [3, 10]:
        r_freq = run_optimized_backtest(tier_name, data_cache, start_date, end_date,
                                        param_overrides={'rebalance_freq': freq})
        print(f"  {'每'+str(freq)+'天调仓':<20} {r_freq['win_rate']:<8.1f} {r_freq['annual_return']:<8.2f} {r_freq['n_trades']:<6} {r_freq['profit_loss_ratio']:<8.2f}", file=sys.stderr)
    
    # RSI阈值调整
    if tier_name == 'aggressive':
        for rsi_thresh in [20, 30]:
            r_rsi = run_optimized_backtest(tier_name, data_cache, start_date, end_date,
                                           param_overrides={'rsi_max': rsi_thresh})
            print(f"  {'RSI<'+str(rsi_thresh):<20} {r_rsi['win_rate']:<8.1f} {r_rsi['annual_return']:<8.2f} {r_rsi['n_trades']:<6} {r_rsi['profit_loss_ratio']:<8.2f}", file=sys.stderr)
    
    elif tier_name == 'steady':
        for rsi_min, rsi_max in [(35, 65), (45, 75)]:
            r_rsi = run_optimized_backtest(tier_name, data_cache, start_date, end_date,
                                           param_overrides={'rsi_min': rsi_min, 'rsi_max': rsi_max})
            print(f"  {'RSI'+str(rsi_min)+'-'+str(rsi_max):<20} {r_rsi['win_rate']:<8.1f} {r_rsi['annual_return']:<8.2f} {r_rsi['n_trades']:<6} {r_rsi['profit_loss_ratio']:<8.2f}", file=sys.stderr)


# ═══════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='策略优化器')
    parser.add_argument('--tier', choices=['aggressive', 'steady', 'value', 'all'], default='aggressive')
    parser.add_argument('--quick', action='store_true', help='快速扫描')
    parser.add_argument('--start', default='2022-01-01')
    parser.add_argument('--end', default='2026-07-31')
    args = parser.parse_args()
    
    print("📊 策略优化器启动", file=sys.stderr)
    print(f"   期间: {args.start} ~ {args.end}", file=sys.stderr)
    
    # 加载数据
    t0 = time.time()
    data_cache = bt.load_all_data()
    print(f"   数据加载: {time.time()-t0:.1f}s", file=sys.stderr)
    
    tiers = ['aggressive', 'steady', 'value'] if args.tier == 'all' else [args.tier]
    
    for tier in tiers:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"  {tier}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        
        # 1. 参数网格扫描
        print(f"\n  📐 参数网格扫描...", file=sys.stderr)
        t1 = time.time()
        best = grid_search(tier, data_cache, args.start, args.end, 
                          {'aggressive': AGGRESSIVE_GRID, 'steady': STEADY_GRID, 'value': VALUE_GRID}[tier],
                          quick=args.quick)
        print(f"   耗时: {time.time()-t1:.1f}s", file=sys.stderr)
        
        # 2. 增强因子测试
        print(f"\n  🔬 增强因子测试...", file=sys.stderr)
        test_enhancements(tier, data_cache, args.start, args.end)
    
    print(f"\n✅ 优化完成", file=sys.stderr)


if __name__ == '__main__':
    main()