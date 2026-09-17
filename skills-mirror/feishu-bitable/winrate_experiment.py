#!/usr/bin/env python3
"""
全面胜率提升实验 — 多策略对决
================================
测试各种策略组合，目标胜率70%+
维度：
- T+1胜率（买入次日）
- T+5胜率（持有一周）
- T+20胜率（持有一个月）
- 含止损止盈的完整交易胜率

策略：
1. MACD底背离 + 超卖
2. 成交量萎缩确认
3. 多周期共振（周线+日线）
4. 市场情绪过滤
5. 板块效应
6. 多因子叠加
7. 组合策略
"""
import os, sys, json, math, statistics, time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
import backtest_recommend as bt

# ═══════════════════════════════════════════════
# 增强指标计算
# ═══════════════════════════════════════════════

def calc_macd(closes, fast=12, slow=26, signal=9):
    """计算MACD，返回 (dif, dea, macd_hist)"""
    if len(closes) < slow + signal:
        return None, None, None
    def ema(data, period):
        k = 2/(period+1)
        r = [data[0]]
        for i in range(1, len(data)):
            r.append(data[i]*k + r[-1]*(1-k))
        return r
    ema_f = ema(closes, fast)
    ema_s = ema(closes, slow)
    dif = [ema_f[i] - ema_s[i] for i in range(len(closes))]
    dea = ema(dif, signal)
    macd = [2*(dif[i]-dea[i]) for i in range(len(dif))]
    return dif[-1] if dif else None, dea[-1] if dea else None, macd[-1] if macd else None


def detect_macd_divergence(closes, lookback=60):
    """检测MACD底背离
    价格创新低但MACD未创新低 → 买入信号
    """
    if len(closes) < lookback:
        return False, 0
    prices = closes[-lookback:]
    difs = []
    for i in range(len(prices)):
        if i < 26+9: difs.append(0)
        else:
            d, _, _ = calc_macd(prices[:i+1])
            difs.append(d or 0)
    
    # 最近一段的价格低点和MACD低点
    recent = prices[-20:]
    recent_dif = difs[-20:]
    if len(recent) < 10:
        return False, 0
    
    # 价格创新低
    price_min = min(recent)
    price_min_idx = recent.index(price_min)
    
    # 看MACD在这个位置是否同步创新低
    macd_min = min(recent_dif)
    macd_min_idx = recent_dif.index(macd_min)
    
    # 底背离：价格更低但MACD没更低
    if price_min_idx > macd_min_idx and recent_dif[price_min_idx] > recent_dif[macd_min_idx]:
        strength = (recent_dif[price_min_idx] - recent_dif[macd_min_idx]) / (abs(recent_dif[macd_min_idx]) + 0.001)
        return True, min(strength, 10)
    
    # 更精确：比较最近两个低点
    bottoms = []
    for i in range(3, len(recent)-3):
        if recent[i] < recent[i-1] and recent[i] < recent[i-2] and recent[i] < recent[i+1] and recent[i] < recent[i+2]:
            bottoms.append((i, recent[i], recent_dif[i]))
    
    if len(bottoms) >= 2:
        last = bottoms[-1]
        prev = bottoms[-2]
        # 价格更低但MACD更高
        if last[1] < prev[1] and last[2] > prev[2]:
            strength = (last[2] - prev[2]) / (abs(prev[2]) + 0.001)
            return True, min(strength, 10)
    
    return False, 0


def detect_bullish_engulfing(closes):
    """检测看涨吞没形态"""
    if len(closes) < 5:
        return False, 0
    # 简化：用最近两天的趋势判断
    # 前三天跌，后两天涨
    recent = closes[-5:]
    if recent[0] > recent[1] > recent[2] and recent[3] < recent[4]:
        strength = (recent[4] - recent[3]) / recent[3] * 100
        return True, strength
    return False, 0


def calc_volume_exhaustion(klines, as_of_date, lookback=20):
    """计算成交量萎缩程度
    返回: 0-100, 越高表示缩量越充分
    """
    vols = []
    for k in reversed(klines):
        if len(vols) < lookback:
            vols.append(k[2])  # volume
        else:
            break
    if len(vols) < 10:
        return 50
    
    avg_vol = sum(vols) / len(vols)
    recent_vol = sum(vols[:5]) / min(5, len(vols))
    ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
    
    # 0.3以下 = 极度缩量（好信号）
    # 1.0 = 正常量
    # 2.0+ = 放量
    if ratio < 0.3: return 90
    elif ratio < 0.5: return 80
    elif ratio < 0.7: return 70
    elif ratio < 0.9: return 60
    elif ratio < 1.2: return 50
    elif ratio < 1.5: return 30
    else: return 10


def calc_market_mood(data_cache, as_of_date, lookback=5):
    """计算市场情绪（涨跌比）"""
    price_map = data_cache.get('price_map', {})
    trading_dates = data_cache.get('trading_dates', [])
    
    if as_of_date not in trading_dates:
        return 50
    idx = trading_dates.index(as_of_date)
    if idx < lookback:
        return 50
    
    # 计算最近N天的平均涨跌比
    mood_scores = []
    for day_idx in range(idx - lookback + 1, idx + 1):
        day = trading_dates[day_idx]
        prev_day = trading_dates[day_idx - 1]
        day_p = price_map.get(day, {})
        prev_p = price_map.get(prev_day, {})
        if not day_p or not prev_p:
            continue
        
        up = down = 0
        for code, price in day_p.items():
            if code in prev_p and prev_p[code] > 0:
                ret = (price - prev_p[code]) / prev_p[code]
                if ret > 0.01: up += 1
                elif ret < -0.01: down += 1
        
        total = up + down
        if total > 0:
            mood_scores.append(up / total)
    
    if not mood_scores:
        return 50
    avg_mood = sum(mood_scores) / len(mood_scores)
    # 0-100 scale: 0=pure panic, 50=neutral, 100=euphoria
    return avg_mood * 100


def calc_multi_timeframe(closes):
    """多周期共振检查
    检查周线+日线是否同时超卖
    """
    if len(closes) < 120:
        return False, 0
    
    # 日线RSI
    daily_rsi = bt.calc_rsi_from_list(closes, 14)
    
    # 周线（取每周五收盘价近似）
    weekly = [closes[i] for i in range(0, len(closes), 5)]
    weekly_rsi = bt.calc_rsi_from_list(weekly, 14) if len(weekly) > 14 else None
    
    if daily_rsi is None or weekly_rsi is None:
        return False, 0
    
    # 同时超卖 = 强信号
    if daily_rsi < 30 and weekly_rsi < 35:
        return True, (35 - weekly_rsi) + (30 - daily_rsi)
    
    return False, 0


# ═══════════════════════════════════════════════
# 多策略候选筛选
# ═══════════════════════════════════════════════

def screen_strategy_1_macd_divergence(data_cache, as_of_date, all_codes, max_candidates=10):
    """策略1: MACD底背离 + 超卖"""
    klines = data_cache['klines']
    stocks = data_cache['stocks']
    candidates = []
    
    for code in all_codes:
        sinfo = stocks.get(code)
        if sinfo:
            if sinfo.get('is_st', 0) == 1: continue
            if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S')): continue
        
        kdata = klines.get(code)
        if not kdata: continue
        sliced = bt.get_kline_slice(kdata, as_of_date, 120)
        if not sliced: continue
        closes, _, _ = sliced
        if len(closes) < 60: continue
        
        current_price = closes[-1]
        if current_price <= 0: continue
        
        # RSI超卖
        rsi = bt.calc_rsi_from_list(closes, 14)
        if rsi is None or rsi > 35: continue
        
        # MACD底背离
        has_div, strength = detect_macd_divergence(closes)
        if not has_div: continue
        
        score = 60 + strength * 5
        # RSI越低越好
        if rsi < 20: score += 20
        elif rsi < 25: score += 15
        elif rsi < 30: score += 10
        
        candidates.append({'code': code, 'name': sinfo.get('name', code) if sinfo else code,
                          'price': current_price, 'rsi': rsi, 'score': score})
    
    candidates.sort(key=lambda x: -x['score'])
    return candidates[:max_candidates]


def screen_strategy_2_volume_confirm(data_cache, as_of_date, all_codes, max_candidates=10):
    """策略2: 放量下跌后缩量企稳"""
    klines = data_cache['klines']
    stocks = data_cache['stocks']
    candidates = []
    
    for code in all_codes:
        sinfo = stocks.get(code)
        if sinfo:
            if sinfo.get('is_st', 0) == 1: continue
            if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S')): continue
        
        kdata = klines.get(code)
        if not kdata: continue
        sliced = bt.get_kline_slice(kdata, as_of_date, 120)
        if not sliced: continue
        closes, _, _ = sliced
        if len(closes) < 60: continue
        
        current_price = closes[-1]
        if current_price <= 0: continue
        
        rsi = bt.calc_rsi_from_list(closes, 14)
        if rsi is None or rsi > 40: continue
        
        # 成交量萎缩确认
        vol_exhaust = calc_volume_exhaustion(kdata, as_of_date)
        if vol_exhaust < 60: continue  # 缩量不够
        
        # 价格企稳（最近3天不再创新低）
        recent3 = closes[-3:]
        if recent3[0] < recent3[1] < recent3[2]:  # 连续三天涨
            score = 70 + (rsi < 25) * 15 + (vol_exhaust > 80) * 10
        elif recent3[2] > recent3[0]:  # 底部企稳
            score = 60 + (rsi < 25) * 15 + (vol_exhaust > 80) * 10
        else:
            score = 50 + (vol_exhaust > 80) * 10
        
        candidates.append({'code': code, 'name': sinfo.get('name', code) if sinfo else code,
                          'price': current_price, 'rsi': rsi, 'score': score})
    
    candidates.sort(key=lambda x: -x['score'])
    return candidates[:max_candidates]


def screen_strategy_3_multi_timeframe(data_cache, as_of_date, all_codes, max_candidates=10):
    """策略3: 多周期共振（周线+日线同时超卖）"""
    klines = data_cache['klines']
    stocks = data_cache['stocks']
    candidates = []
    
    for code in all_codes:
        sinfo = stocks.get(code)
        if sinfo:
            if sinfo.get('is_st', 0) == 1: continue
            if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S')): continue
        
        kdata = klines.get(code)
        if not kdata: continue
        sliced = bt.get_kline_slice(kdata, as_of_date, 200)
        if not sliced: continue
        closes, _, _ = sliced
        if len(closes) < 120: continue
        
        current_price = closes[-1]
        if current_price <= 0: continue
        
        has_resonance, strength = calc_multi_timeframe(closes)
        if not has_resonance: continue
        
        rsi = bt.calc_rsi_from_list(closes, 14)
        score = 70 + strength * 5
        if rsi and rsi < 20: score += 15
        
        candidates.append({'code': code, 'name': sinfo.get('name', code) if sinfo else code,
                          'price': current_price, 'rsi': rsi, 'score': score})
    
    candidates.sort(key=lambda x: -x['score'])
    return candidates[:max_candidates]


def screen_strategy_4_mood_filter(data_cache, as_of_date, all_codes, max_candidates=10):
    """策略4: 市场情绪过滤 + 超卖"""
    klines = data_cache['klines']
    stocks = data_cache['stocks']
    candidates = []
    
    # 市场情绪：恐慌时不做多，恐慌退潮时才入场
    mood = calc_market_mood(data_cache, as_of_date)
    if mood < 30 or mood > 80:  # 太恐慌或太亢奋都不做
        return []
    
    for code in all_codes:
        sinfo = stocks.get(code)
        if sinfo:
            if sinfo.get('is_st', 0) == 1: continue
            if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S')): continue
        
        kdata = klines.get(code)
        if not kdata: continue
        sliced = bt.get_kline_slice(kdata, as_of_date, 120)
        if not sliced: continue
        closes, _, _ = sliced
        if len(closes) < 60: continue
        
        current_price = closes[-1]
        if current_price <= 0: continue
        
        rsi = bt.calc_rsi_from_list(closes, 14)
        if rsi is None or rsi > 30: continue
        
        _, _, _, boll_pos = bt.calc_bollinger_from_list(closes)
        if boll_pos is None or boll_pos > 25: continue
        
        # 情绪适中 + 超卖 = 好机会
        score = 65 + (30 - rsi) + (25 - boll_pos) * 0.5
        # 情绪在40-60之间加分
        if 40 <= mood <= 60: score += 10
        
        candidates.append({'code': code, 'name': sinfo.get('name', code) if sinfo else code,
                          'price': current_price, 'rsi': rsi, 'score': score})
    
    candidates.sort(key=lambda x: -x['score'])
    return candidates[:max_candidates]


def screen_strategy_5_combined(data_cache, as_of_date, all_codes, max_candidates=10):
    """策略5: 综合策略（多个信号叠加）"""
    klines = data_cache['klines']
    stocks = data_cache['stocks']
    financial = data_cache['financial']
    candidates = []
    
    # 市场情绪过滤
    mood = calc_market_mood(data_cache, as_of_date)
    if mood < 20 or mood > 85:
        return []
    
    for code in all_codes:
        sinfo = stocks.get(code)
        if sinfo:
            if sinfo.get('is_st', 0) == 1: continue
            if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S')): continue
        
        kdata = klines.get(code)
        if not kdata: continue
        sliced = bt.get_kline_slice(kdata, as_of_date, 200)
        if not sliced: continue
        closes, _, _ = sliced
        if len(closes) < 120: continue
        
        current_price = closes[-1]
        if current_price <= 0: continue
        
        # 多维度信号
        total_score = 0
        signals = []
        
        # 1. RSI超卖
        rsi = bt.calc_rsi_from_list(closes, 14)
        if rsi and rsi < 25:
            total_score += 25
            signals.append('RSI超卖')
        elif rsi and rsi < 30:
            total_score += 15
            signals.append('RSI偏弱')
        elif rsi and rsi < 35:
            total_score += 10
        
        # 2. 布林位置
        _, _, _, boll_pos = bt.calc_bollinger_from_list(closes)
        if boll_pos and boll_pos < 10:
            total_score += 20
            signals.append('布林下轨')
        elif boll_pos and boll_pos < 20:
            total_score += 10
        
        # 3. MACD底背离
        has_div, div_str = detect_macd_divergence(closes)
        if has_div:
            total_score += 25
            signals.append('MACD底背离')
        
        # 4. 成交量萎缩
        vol_ex = calc_volume_exhaustion(kdata, as_of_date)
        if vol_ex >= 80:
            total_score += 15
            signals.append('缩量企稳')
        elif vol_ex >= 60:
            total_score += 8
        
        # 5. 多周期共振
        has_res, res_str = calc_multi_timeframe(closes)
        if has_res:
            total_score += 20
            signals.append('周线共振')
        
        # 6. 看涨形态
        has_eng, eng_str = detect_bullish_engulfing(closes)
        if has_eng:
            total_score += 10
            signals.append('看涨形态')
        
        # 7. 基本面加分
        fin = financial.get(code)
        if fin:
            if fin.get('roe', 0) > 15: total_score += 5
            if fin.get('debt_ratio', 100) < 50: total_score += 5
        
        # 需要至少2个信号
        if len(signals) < 2:
            continue
        
        if total_score < 50:
            continue
        
        candidates.append({'code': code, 'name': sinfo.get('name', code) if sinfo else code,
                          'price': current_price, 'rsi': rsi, 'score': total_score,
                          'signals': signals})
    
    candidates.sort(key=lambda x: -x['score'])
    return candidates[:max_candidates]


# ═══════════════════════════════════════════════
# 胜率测试（T+1, T+5, T+20）
# ═══════════════════════════════════════════════

def test_win_rate(screen_fn, strategy_name, data_cache, start_date, end_date, max_candidates=10):
    """测试策略在不同持有期的胜率"""
    trading_dates = [d for d in data_cache['trading_dates'] if start_date <= d <= end_date]
    price_map = data_cache['price_map']
    all_codes = list(data_cache['klines'].keys())
    
    if len(trading_dates) < 30:
        return {'strategy': strategy_name, 'error': '数据不足'}
    
    # 每5个交易日选一次股
    rebalance_dates = set()
    for i, d in enumerate(trading_dates):
        if i % 5 == 0:
            rebalance_dates.add(d)
    
    trades = []  # {entry_date, entry_price, exit_date, exit_price, returns}
    
    print(f"  [{strategy_name}] 开始测试...", file=sys.stderr)
    n_dates = len(trading_dates)
    
    for i, current_date in enumerate(trading_dates):
        if i % 200 == 0:
            print(f"  [{strategy_name}] {i}/{n_dates}", file=sys.stderr)
        
        if current_date not in rebalance_dates:
            continue
        
        day_prices = price_map.get(current_date, {})
        if not day_prices:
            continue
        
        candidates = screen_fn(data_cache, current_date, all_codes, max_candidates)
        if not candidates:
            continue
        
        for c in candidates:
            code = c['code']
            if code not in day_prices:
                continue
            entry_price = day_prices[code]
            if entry_price <= 0:
                continue
            
            # 找未来T+1, T+5, T+20的价格
            future_prices = {1: None, 5: None, 10: None, 20: None}
            for j in range(i+1, min(i+21, len(trading_dates))):
                future_date = trading_dates[j]
                future_p = price_map.get(future_date, {}).get(code)
                if future_p and future_p > 0:
                    days = j - i
                    if days in future_prices and future_prices[days] is None:
                        future_prices[days] = future_p
            
            trade = {
                'code': code, 'entry_price': entry_price,
                'entry_date': current_date,
                'prices': future_prices,
                'score': c.get('score', 0)
            }
            trades.append(trade)
    
    n_trades = len(trades)
    if n_trades < 5:
        return {'strategy': strategy_name, 'n_trades': n_trades, 'error': '交易太少'}
    
    results = {'strategy': strategy_name, 'n_trades': n_trades}
    
    for hold_days in [1, 5, 10, 20]:
        wins = 0
        total_ret = 0
        valid = 0
        for t in trades:
            p = t['prices'].get(hold_days)
            if p and p > 0:
                ret = (p - t['entry_price']) / t['entry_price'] * 100
                total_ret += ret
                valid += 1
                if ret > 0:
                    wins += 1
        
        if valid > 0:
            win_rate = wins / valid * 100
            avg_ret = total_ret / valid
            results[f'T+{hold_days}'] = {
                'win_rate': round(win_rate, 1),
                'avg_return': round(avg_ret, 2),
                'valid_trades': valid
            }
    
    return results


# ═══════════════════════════════════════════════
# 含止损止盈的完整交易回测
# ═══════════════════════════════════════════════

def run_full_backtest(screen_fn, strategy_name, data_cache, start_date, end_date,
                      stop_loss=0.07, take_profit=0.10, hold_max=15, max_positions=10):
    """完整交易回测（含止损止盈）"""
    trading_dates = [d for d in data_cache['trading_dates'] if start_date <= d <= end_date]
    price_map = data_cache['price_map']
    all_codes = list(data_cache['klines'].keys())
    
    initial_capital = 1_000_000
    positions = []
    closed_trades = []
    
    rebalance_dates = set()
    for i, d in enumerate(trading_dates):
        if i % 5 == 0:
            rebalance_dates.add(d)
    
    n_dates = len(trading_dates)
    for i, current_date in enumerate(trading_dates):
        if i % 200 == 0:
            print(f"  [{strategy_name} 完整交易] {i}/{n_dates}", file=sys.stderr)
        
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
                ret = (cp - pos.entry_price) / pos.entry_price
                if ret <= -stop_loss:
                    to_close.append((pos, cp, '止损'))
                elif ret >= take_profit:
                    to_close.append((pos, cp, '止盈'))
                elif pos.hold_days >= hold_max:
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
        
        # 调仓
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
                if n_holding >= max_positions:
                    break
                
                max_invest = initial_capital * 0.05
                shares = int(max_invest / entry_price / 100) * 100
                if shares < 100:
                    continue
                
                pos = bt.Position(
                    code=code, name=c.get('name', code),
                    entry_date=current_date, entry_price=entry_price,
                    shares=shares, capital_pct=5,
                    tier=strategy_name,
                    sl_pct=stop_loss, tp_pct=take_profit,
                    hold_days_max=hold_max
                )
                positions.append(pos)
    
    n = len(closed_trades)
    if n == 0:
        return {'strategy': strategy_name, 'n_trades': 0, 'win_rate': 0}
    
    wins = [t for t in closed_trades if t.return_pct > 0]
    losses = [t for t in closed_trades if t.return_pct <= 0]
    wr = len(wins) / n * 100
    avg_win = sum(t.return_pct for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t.return_pct for t in losses) / len(losses)) if losses else 0
    plr = avg_win / avg_loss if avg_loss > 0 else 0
    
    # 退出原因统计
    exit_reasons = defaultdict(int)
    for t in closed_trades:
        exit_reasons[t.exit_reason] += 1
    
    return {
        'strategy': strategy_name,
        'n_trades': n,
        'win_rate': round(wr, 1),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_loss_ratio': round(plr, 2),
        'exit_reasons': dict(exit_reasons),
    }


# ═══════════════════════════════════════════════
# 主程序
# ═══════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='胜率提升实验')
    parser.add_argument('--quick', action='store_true', help='快速模式（只跑T+1）')
    parser.add_argument('--start', default='2022-01-01')
    parser.add_argument('--end', default='2026-07-31')
    args = parser.parse_args()
    
    print("="*80)
    print("📊 全面胜率提升实验 — 多策略对决")
    print("="*80)
    print(f"   期间: {args.start} ~ {args.end}")
    
    t0 = time.time()
    data_cache = bt.load_all_data()
    print(f"   数据加载: {time.time()-t0:.1f}s\n")
    
    strategies = [
        ("1️⃣ MACD底背离+超卖", screen_strategy_1_macd_divergence),
        ("2️⃣ 成交量萎缩确认", screen_strategy_2_volume_confirm),
        ("3️⃣ 多周期共振(周线+日线)", screen_strategy_3_multi_timeframe),
        ("4️⃣ 市场情绪过滤+超卖", screen_strategy_4_mood_filter),
        ("5️⃣ 综合多信号叠加", screen_strategy_5_combined),
    ]
    
    # Phase 1: 胜率测试
    print("\n" + "="*80)
    print("Phase 1: 胜率测试（T+1, T+5, T+10, T+20）")
    print("="*80)
    
    all_results = []
    for name, screen_fn in strategies:
        print(f"\n  {name}")
        results = test_win_rate(screen_fn, name, data_cache, args.start, args.end, max_candidates=10)
        all_results.append(results)
        
        if 'error' in results:
            print(f"    ❌ {results['error']}")
        else:
            print(f"    📊 {results['n_trades']} 次交易")
            for days in [1, 5, 10, 20]:
                key = f'T+{days}'
                if key in results:
                    r = results[key]
                    print(f"    {key}: 胜率{r['win_rate']:>5.1f}%  均收益{r['avg_return']:>6.2f}%  有效{r['valid_trades']}次")
    
    # Phase 2: 完整交易回测
    print("\n" + "="*80)
    print("Phase 2: 完整交易回测（含止损止盈）")
    print("="*80)
    
    print(f"\n{'策略':<25s} {'胜率':>8s} {'交易':>6s} {'盈亏比':>8s} {'止损':>6s} {'止盈':>6s} {'到期':>6s}")
    print(f"{'-'*70}")
    
    for name, screen_fn in strategies:
        r = run_full_backtest(screen_fn, name, data_cache, args.start, args.end,
                              stop_loss=0.07, take_profit=0.12, hold_max=15)
        if r['n_trades'] > 0:
            er = r.get('exit_reasons', {})
            print(f"  {name:<23s} {r['win_rate']:>7.1f}% {r['n_trades']:>5d} {r['profit_loss_ratio']:>7.2f} "
                  f"{er.get('止损',0):>5d} {er.get('止盈',0):>5d} {er.get('到期',0):>5d}")
    
    # 最佳策略做参数优化
    print("\n" + "="*80)
    print("Phase 3: 最佳策略参数优化")
    print("="*80)
    
    best_strategy = "综合多信号叠加"
    best_screen = screen_strategy_5_combined
    
    for sl, tp, hold in [(0.05, 0.10, 10), (0.05, 0.12, 15), (0.07, 0.15, 20), (0.10, 0.15, 20)]:
        r = run_full_backtest(best_screen, f"{best_strategy}(-{sl*100:.0f}%/+{tp*100:.0f}%,{hold}天)",
                              data_cache, args.start, args.end, stop_loss=sl, take_profit=tp, hold_max=hold)
        if r['n_trades'] > 0:
            print(f"  -{sl*100:.0f}%/+{tp*100:.0f}%,{hold:>2d}天: 胜率{r['win_rate']:>5.1f}%  交易{r['n_trades']:>4d}  盈亏比{r['profit_loss_ratio']:.2f}")
    
    print(f"\n✅ 实验完成，总耗时: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()