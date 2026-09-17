#!/usr/bin/env python3
"""
快速参数实验 — 手动跑几个关键对比
====================================
每次只改一个参数，看对胜率的影响。
"""
import os, sys, json, copy, time
from pathlib import Path
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
import backtest_recommend as bt

# 加载数据
print("加载数据...", file=sys.stderr)
t0 = time.time()
data_cache = bt.load_all_data()
print(f"  耗时: {time.time()-t0:.1f}s\n", file=sys.stderr)

START = '2022-01-01'
END = '2026-07-31'

def run_tier(tier, params=None):
    """运行单次回测"""
    cfg = copy.deepcopy(bt.TIER_CONFIGS[tier])
    if params:
        cfg.update(params)
    
    rebalance_freq = params.get('rebalance_freq', 5) if params else 5
    trading_dates = [d for d in data_cache['trading_dates'] if START <= d <= END]
    price_map = data_cache['price_map']
    all_codes = list(data_cache['klines'].keys())
    
    initial_capital = 1_000_000
    positions = []
    closed_trades = []
    rebalance_dates = set()
    for i, d in enumerate(trading_dates):
        if i % rebalance_freq == 0:
            rebalance_dates.add(d)
    
    screen_fn = {
        'aggressive': bt.screen_aggressive_fast,
        'steady': bt.screen_steady_fast,
        'value': bt.screen_value_fast,
    }[tier]
    
    for i, current_date in enumerate(trading_dates):
        if i % 500 == 0:
            print(f"  {i}/{len(trading_dates)}", file=sys.stderr, end='\r')
        day_prices = price_map.get(current_date, {})
        if not day_prices:
            continue
        to_close = []
        for pos in positions:
            if pos.status != 'holding':
                continue
            pos.hold_days += 1
            if pos.code in day_prices:
                cp = day_prices[pos.code]
                if cp <= (pos.entry_price - pos.entry_price * pos.sl_pct):
                    to_close.append((pos, cp, '止损'))
                elif cp >= (pos.entry_price + pos.entry_price * pos.tp_pct):
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
        
        if current_date in rebalance_dates:
            held_codes = {p.code for p in positions if p.status == 'holding'}
            candidates = screen_fn(data_cache, current_date, all_codes, max_candidates=10)
            for c in candidates:
                code = c['code']
                if code in held_codes or code not in day_prices:
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
                    tier=tier,
                    sl_pct=cfg['stop_loss_pct'], tp_pct=cfg['take_profit_pct'],
                    hold_days_max=cfg['hold_days_max']
                )
                positions.append(pos)
    
    n = len(closed_trades)
    if n == 0:
        return {'n':0, 'wr':0, 'ar':0, 'plr':0}
    wins = [t for t in closed_trades if t.return_pct > 0]
    losses = [t for t in closed_trades if t.return_pct <= 0]
    wr = len(wins)/n*100
    avg_win = sum(t.return_pct for t in wins)/len(wins) if wins else 0
    avg_loss = abs(sum(t.return_pct for t in losses)/len(losses)) if losses else 0
    plr = avg_win/avg_loss if avg_loss>0 else 0
    total_r = sum(t.return_pct for t in closed_trades)
    years = (time.time() - time.mktime(time.strptime(START,'%Y-%m-%d')))/31536000
    ar = ((1+total_r/100)**(1/years)-1)*100 if years>0 else 0
    return {'n':n, 'wr':round(wr,1), 'ar':round(ar,2), 'plr':round(plr,2), 'win':len(wins)}

def report(tier, label, params, result):
    print(f"  {label:<25s} 胜率{result['wr']:>6.1f}%  年化{result['ar']:>7.2f}%  交易{result['n']:>4d}  盈亏比{result['plr']:>5.2f}")

# ═══════════════ 实验开始 ═══════════════

print("="*70)
print("🔥 激进档-超跌反弹 参数实验")
print("="*70)

# 基准
base = run_tier('aggressive')
report('aggressive', '基准(RSI<25,布林<20%,-7%/+10%,5天)', {}, base)

# 实验1: RSI阈值
for rsi in [20, 30, 35]:
    r = run_tier('aggressive', {'rsi_max': rsi})
    report('aggressive', f'RSI<{rsi}', {'rsi_max': rsi}, r)

# 实验2: 布林位置
for boll in [10, 15, 25, 30]:
    r = run_tier('aggressive', {'boll_pos_max': boll})
    report('aggressive', f'布林<{boll}%', {'boll_pos_max': boll}, r)

# 实验3: 止损止盈
for sl, tp in [(0.05, 0.08), (0.05, 0.10), (0.07, 0.12), (0.07, 0.15), (0.10, 0.15)]:
    r = run_tier('aggressive', {'stop_loss_pct': sl, 'take_profit_pct': tp})
    report('aggressive', f'止损-{sl*100:.0f}%止盈+{tp*100:.0f}%', {'stop_loss_pct': sl, 'take_profit_pct': tp}, r)

# 实验4: 持有天数
for days in [5, 7, 10, 15, 20]:
    r = run_tier('aggressive', {'hold_days_max': days})
    report('aggressive', f'持有最多{days}天', {'hold_days_max': days}, r)

# 实验5: 调仓频率
for freq in [3, 5, 10, 20]:
    r = run_tier('aggressive', {'rebalance_freq': freq})
    report('aggressive', f'每{freq}天调仓', {'rebalance_freq': freq}, r)

# 实验6: 最佳组合预测
best_params = {'rsi_max': 20, 'boll_pos_max': 15, 'stop_loss_pct': 0.05, 'take_profit_pct': 0.10, 'hold_days_max': 15, 'rebalance_freq': 10}
r = run_tier('aggressive', best_params)
report('aggressive', '最佳组合(RSI<20,布林<15%,-5%/+10%,15天,每10天)', best_params, r)

print()
print("="*70)
print("📈 稳健档-主升浪 参数实验")
print("="*70)

base = run_tier('steady')
report('steady', '基准(RSI40-70,布林20-70%,-5%/+15%,20天)', {}, base)

# RSI
for lo, hi in [(35,65), (40,70), (45,75), (50,80)]:
    r = run_tier('steady', {'rsi_min': lo, 'rsi_max': hi})
    report('steady', f'RSI{lo}-{hi}', {'rsi_min': lo, 'rsi_max': hi}, r)

# 止损止盈
for sl, tp in [(0.03, 0.10), (0.03, 0.15), (0.05, 0.15), (0.05, 0.20), (0.07, 0.20)]:
    r = run_tier('steady', {'stop_loss_pct': sl, 'take_profit_pct': tp})
    report('steady', f'止损-{sl*100:.0f}%止盈+{tp*100:.0f}%', {'stop_loss_pct': sl, 'take_profit_pct': tp}, r)

# 持有天数
for days in [10, 15, 20, 30]:
    r = run_tier('steady', {'hold_days_max': days})
    report('steady', f'持有最多{days}天', {'hold_days_max': days}, r)

# 调仓频率
for freq in [3, 5, 10, 20]:
    r = run_tier('steady', {'rebalance_freq': freq})
    report('steady', f'每{freq}天调仓', {'rebalance_freq': freq}, r)

print()
print("="*70)
print("💎 价值档 参数实验")
print("="*70)

base = run_tier('value')
report('value', '基准', {}, base)

for pe in [20, 30, 40, 50]:
    r = run_tier('value', {'pe_max': pe})
    report('value', f'PE<{pe}', {'pe_max': pe}, r)

for sl, tp in [(0.07, 0.20), (0.10, 0.25), (0.10, 0.30), (0.15, 0.40)]:
    r = run_tier('value', {'stop_loss_pct': sl, 'take_profit_pct': tp})
    report('value', f'止损-{sl*100:.0f}%止盈+{tp*100:.0f}%', {'stop_loss_pct': sl, 'take_profit_pct': tp}, r)

for freq in [10, 20, 30]:
    r = run_tier('value', {'rebalance_freq': freq})
    report('value', f'每{freq}天调仓', {'rebalance_freq': freq}, r)

print()
print("✅ 实验完成")