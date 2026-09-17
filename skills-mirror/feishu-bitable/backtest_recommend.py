#!/usr/bin/env python3
"""
backtest_recommend.py — 三档推荐系统历史回测（优化版）
=====================================================
使用真实选股推荐逻辑（double_up_screener评分 + auto_recommend三档筛选）
模拟真实交易（止损止盈 + 仓位管理），输出各档位绩效指标。

数据来源：market_cache.db（不从外部API获取数据）

优化：预加载所有K线数据到内存，避免回测循环中的数据库查询。

用法:
  python3 backtest_recommend.py                       # 默认回测 2022-01 ~ 2026-07
  python3 backtest_recommend.py --start 2023-01 --end 2026-06
  python3 backtest_recommend.py --tier aggressive      # 只跑激进档
  python3 backtest_recommend.py --json                 # JSON输出
"""

import os, sys, json, math, sqlite3, argparse, statistics, calendar
from datetime import datetime, timedelta, date
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
MARKET_DB = Path("/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db")

# ═══════════════════════════════════════════════
# 三档配置（与 auto_recommend.py 一致）
# ═══════════════════════════════════════════════

TIER_CONFIGS = {
    'aggressive': {
        'name': '激进档-超跌反弹',
        'rsi_max': 25,
        'boll_pos_max': 20,
        'required_score': 50,
        'stop_loss_pct': 0.07,
        'take_profit_pct': 0.10,
        'hold_days_max': 10,
        'max_position_pct': 0.05,
        'max_positions': 10,
    },
    'steady': {
        'name': '稳健档-主升浪',
        'rsi_min': 40,
        'rsi_max': 70,
        'boll_pos_min': 20,
        'boll_pos_max': 70,
        'ma_required': True,
        'required_score': 40,
        'stop_loss_pct': 0.05,
        'take_profit_pct': 0.15,
        'hold_days_max': 20,
        'max_position_pct': 0.05,
        'max_positions': 10,
    },
    'value': {
        'name': '价值档-低估值成长',
        'roe_min': 15,
        'profit_growth_min': 10,
        'debt_ratio_max': 60,
        'pe_max': 40,
        'required_score': 30,
        'stop_loss_pct': 0.10,
        'take_profit_pct': 0.30,
        'hold_days_max': 120,
        'max_position_pct': 0.05,
        'max_positions': 10,
    },
}

# 交易成本
COMMISSION_RATE = 0.00025
STAMP_TAX_RATE = 0.0005
SLIPPAGE_RATE = 0.001

# ═══════════════════════════════════════════════
# 数据加载（一次性预加载到内存）
# ═══════════════════════════════════════════════

def load_all_data():
    """
    预加载所有数据到内存。
    返回: {
        'trading_dates': [str],
        'klines': {code: [(date, close, high, low), ...]},  # 按日期升序
        'financial': {code: {report_date, roe, profit_growth, revenue_growth, debt_ratio, gross_margin, net_margin}},
        'stocks': {code: {name, sector, is_st}},
        'pe_pb': {code: {pe_ttm, pb_mrq, pe_pct, pb_pct, fetch_date}},
        'price_map': {date: {code: close, ...}},
    }
    """
    print("  [数据加载] 开始加载...", file=sys.stderr)
    conn = sqlite3.connect(str(MARKET_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 交易日
    cur.execute("SELECT DISTINCT date FROM klines WHERE date >= '2019-01-01' ORDER BY date")
    trading_dates = [r['date'] for r in cur.fetchall()]
    trading_date_set = set(trading_dates)
    print(f"  [数据加载] 交易日: {len(trading_dates)}", file=sys.stderr)

    # 股票信息
    cur.execute("SELECT code, name, sector, COALESCE(is_st, 0) as is_st FROM stocks")
    stocks = {}
    for r in cur.fetchall():
        stocks[r['code']] = {'name': r['name'], 'sector': r['sector'] or '', 'is_st': r['is_st']}
    print(f"  [数据加载] 股票: {len(stocks)}", file=sys.stderr)

    # K线数据（只保留有足够数据的股票）
    print(f"  [数据加载] 加载K线数据...", file=sys.stderr)
    klines = defaultdict(list)
    cur.execute(
        "SELECT code, date, close, high, low FROM klines WHERE date >= '2019-01-01' ORDER BY code, date"
    )
    count = 0
    for r in cur.fetchall():
        klines[r['code']].append((r['date'], r['close'], r['high'], r['low']))
        count += 1
    print(f"  [数据加载] K线: {count} 条, {len(klines)} 只股票", file=sys.stderr)

    # 过滤掉数据不足的股票
    codes_to_keep = [c for c, data in klines.items() if len(data) >= 200]
    klines = {c: klines[c] for c in codes_to_keep}
    print(f"  [数据加载] 过滤后: {len(klines)} 只（≥200天K线）", file=sys.stderr)

    # 财务数据
    print(f"  [数据加载] 加载财务数据...", file=sys.stderr)
    financial = {}
    cur.execute("""
        WITH ranked AS (
            SELECT code, report_date, roe, profit_growth, revenue_growth,
                   debt_ratio, gross_margin, net_margin,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) as rn
            FROM financial_data
            WHERE roe IS NOT NULL
        )
        SELECT * FROM ranked WHERE rn = 1
    """)
    for r in cur.fetchall():
        financial[r['code']] = {
            'report_date': r['report_date'],
            'roe': r['roe'],
            'profit_growth': r['profit_growth'],
            'revenue_growth': r['revenue_growth'],
            'debt_ratio': r['debt_ratio'],
            'gross_margin': r['gross_margin'],
            'net_margin': r['net_margin'],
        }
    print(f"  [数据加载] 财务数据: {len(financial)} 只", file=sys.stderr)

    # PE/PB数据
    print(f"  [数据加载] 加载PE/PB数据...", file=sys.stderr)
    pe_pb = {}
    cur.execute("""
        WITH ranked AS (
            SELECT code, pe_ttm, pb_mrq, pe_pct, pb_pct, fetch_date,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY fetch_date DESC) as rn
            FROM pe_pb_data
            WHERE pe_ttm IS NOT NULL AND pe_ttm > 0
        )
        SELECT * FROM ranked WHERE rn = 1
    """)
    for r in cur.fetchall():
        pe_pb[r['code']] = {
            'pe_ttm': r['pe_ttm'],
            'pb_mrq': r['pb_mrq'],
            'pe_pct': r['pe_pct'],
            'pb_pct': r['pb_pct'],
            'fetch_date': r['fetch_date'],
        }
    print(f"  [数据加载] PE/PB数据: {len(pe_pb)} 只", file=sys.stderr)

    # 价格映射（按日期的价格快照）
    print(f"  [数据加载] 构建价格映射...", file=sys.stderr)
    price_map = defaultdict(dict)
    for code, data in klines.items():
        for dt, close, _, _ in data:
            price_map[dt][code] = close

    conn.close()
    print(f"  [数据加载] 完成！", file=sys.stderr)

    return {
        'trading_dates': trading_dates,
        'trading_date_set': trading_date_set,
        'klines': dict(klines),
        'financial': financial,
        'stocks': stocks,
        'pe_pb': pe_pb,
        'price_map': dict(price_map),
    }


# ═══════════════════════════════════════════════
# 技术指标计算
# ═══════════════════════════════════════════════

def calc_rsi_from_list(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = 0, 0
    for i in range(len(closes) - period, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_bollinger_from_list(closes, period=20, std_dev=2.0):
    if len(closes) < period:
        return None, None, None, None
    recent = closes[-period:]
    ma = sum(recent) / period
    variance = sum((p - ma) ** 2 for p in recent) / period
    std = math.sqrt(variance)
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    current = closes[-1]
    if upper == lower:
        pos = 50.0
    else:
        pos = (current - lower) / (upper - lower) * 100
    return ma, upper, lower, pos


def is_ma_bullish_from_list(closes):
    if len(closes) < 60:
        return False
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    return ma5 > ma10 > ma20 > ma60


def calc_fundamental_score(fin, for_value=False):
    """基本面评分 0-100"""
    if not fin:
        return 30
    score = 0
    if fin.get('roe'):
        roe = fin['roe']
        if roe > 20: score += 30
        elif roe > 15: score += 25
        elif roe > 10: score += 15
        elif roe > 5: score += 10
        elif roe > 0: score += 5
    pg = fin.get('profit_growth')
    if pg and pg > 0:
        if pg > 30: score += 30
        elif pg > 20: score += 25
        elif pg > 10: score += 20
        elif pg > 5: score += 15
        else: score += 10
    elif pg and pg < 0:
        score += max(0, 10 + pg)
    dr = fin.get('debt_ratio')
    if dr:
        if dr < 40: score += 20
        elif dr < 60: score += 15
        elif dr < 80: score += 8
        else: score += 0
    gm = fin.get('gross_margin')
    if gm:
        if gm > 50: score += 20
        elif gm > 30: score += 15
        elif gm > 20: score += 10
        elif gm > 10: score += 5
    return min(100, max(0, score))


# ═══════════════════════════════════════════════
# 三档筛选（基于预加载的内存数据）
# ═══════════════════════════════════════════════

def get_kline_slice(data, as_of_date, lookback=120):
    """
    从预加载的K线数据中获取截至 as_of_date 的最近 lookback 条。
    data: [(date, close, high, low), ...] 按日期升序
    返回: (closes, highs, lows) 或 None
    """
    if not data:
        return None
    # 找到 as_of_date 的位置（二分查找）
    dates = [d[0] for d in data]
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] <= as_of_date:
            lo = mid + 1
        else:
            hi = mid
    end_idx = lo
    if end_idx == 0:
        return None
    start_idx = max(0, end_idx - lookback)
    segment = data[start_idx:end_idx]
    if len(segment) < 40:
        return None
    closes = [s[1] for s in segment]
    highs = [s[2] for s in segment]
    lows = [s[3] for s in segment]
    return closes, highs, lows


def screen_aggressive_fast(data_cache, as_of_date, all_codes, max_candidates=10):
    """激进档：超跌反弹筛选（基于内存数据）"""
    cfg = TIER_CONFIGS['aggressive']
    klines = data_cache['klines']
    financial = data_cache['financial']
    stocks = data_cache['stocks']
    candidates = []

    for code in all_codes:
        # 检查ST
        sinfo = stocks.get(code)
        if sinfo:
            if sinfo.get('is_st', 0) == 1:
                continue
            if any(sinfo.get('name', '').startswith(p) for p in ('ST', '*ST', 'S')):
                continue

        kdata = klines.get(code)
        if not kdata:
            continue

        sliced = get_kline_slice(kdata, as_of_date, 120)
        if not sliced:
            continue
        closes, _, _ = sliced

        current_price = closes[-1]
        if current_price <= 0:
            continue

        rsi = calc_rsi_from_list(closes, 14)
        if rsi is None or rsi >= cfg['rsi_max']:
            continue

        _, _, _, boll_pos = calc_bollinger_from_list(closes, 20)
        if boll_pos is None or boll_pos >= cfg['boll_pos_max']:
            continue

        # 基本面
        fin = financial.get(code)
        if fin and fin.get('debt_ratio', 0) > 80:
            continue

        fin_score = calc_fundamental_score(fin)
        # 技术评分
        tech_score = 0
        if rsi < 20: tech_score = 80
        elif rsi < 25: tech_score = 70
        elif rsi < 30: tech_score = 50
        else: tech_score = 30
        if boll_pos < 10: tech_score += 20
        elif boll_pos < 20: tech_score += 10

        signal_score = tech_score * 0.6 + fin_score * 0.4
        if signal_score < cfg['required_score']:
            continue

        candidates.append({
            'code': code,
            'name': sinfo.get('name', code) if sinfo else code,
            'price': current_price,
            'rsi': rsi,
            'boll_pos': boll_pos,
            'signal_score': signal_score,
            'fin_score': fin_score,
        })

    candidates.sort(key=lambda x: x['signal_score'], reverse=True)
    return candidates[:max_candidates]


def screen_steady_fast(data_cache, as_of_date, all_codes, max_candidates=10):
    """稳健档：主升浪筛选（基于内存数据）"""
    cfg = TIER_CONFIGS['steady']
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

        sliced = get_kline_slice(kdata, as_of_date, 120)
        if not sliced:
            continue
        closes, _, _ = sliced

        current_price = closes[-1]
        if current_price <= 0:
            continue

        rsi = calc_rsi_from_list(closes, 14)
        if rsi is None or rsi < cfg['rsi_min'] or rsi > cfg['rsi_max']:
            continue

        _, _, _, boll_pos = calc_bollinger_from_list(closes, 20)
        if boll_pos is None or boll_pos < cfg['boll_pos_min'] or boll_pos > cfg['boll_pos_max']:
            continue

        if cfg['ma_required'] and not is_ma_bullish_from_list(closes):
            continue

        fin = financial.get(code)
        if fin and fin.get('debt_ratio', 0) > 80:
            continue

        fin_score = calc_fundamental_score(fin)
        tech_score = 50
        if is_ma_bullish_from_list(closes):
            tech_score += 30
        if 40 <= rsi <= 60:
            tech_score += 20

        signal_score = tech_score * 0.5 + fin_score * 0.5
        if signal_score < cfg['required_score']:
            continue

        candidates.append({
            'code': code,
            'name': sinfo.get('name', code) if sinfo else code,
            'price': current_price,
            'rsi': rsi,
            'boll_pos': boll_pos,
            'signal_score': signal_score,
            'fin_score': fin_score,
        })

    candidates.sort(key=lambda x: x['signal_score'], reverse=True)
    return candidates[:max_candidates]


def screen_value_fast(data_cache, as_of_date, all_codes, max_candidates=10):
    """价值档：低估值成长筛选（基于内存数据）"""
    cfg = TIER_CONFIGS['value']
    klines = data_cache['klines']
    financial = data_cache['financial']
    pe_pb = data_cache['pe_pb']
    stocks = data_cache['stocks']
    candidates = []

    for code in all_codes:
        sinfo = stocks.get(code)
        if sinfo:
            if sinfo.get('is_st', 0) == 1:
                continue
            if any(sinfo.get('name', '').startswith(p) for p in ('ST', '*ST', 'S')):
                continue

        fin = financial.get(code)
        if not fin:
            continue

        roe = fin.get('roe') or 0
        profit_growth = fin.get('profit_growth')
        debt_ratio = fin.get('debt_ratio') or 999

        if roe < cfg['roe_min']:
            continue
        if profit_growth is None or profit_growth < cfg['profit_growth_min']:
            continue
        if debt_ratio > cfg['debt_ratio_max']:
            continue

        pp = pe_pb.get(code)
        pe = pp.get('pe_ttm') if pp else None
        if pe is not None and pe > cfg['pe_max']:
            continue

        kdata = klines.get(code)
        if not kdata:
            continue
        sliced = get_kline_slice(kdata, as_of_date, 120)
        if not sliced:
            continue
        closes, _, _ = sliced

        current_price = closes[-1]
        if current_price <= 0:
            continue

        _, _, _, boll_pos = calc_bollinger_from_list(closes, 20)
        if boll_pos is not None and boll_pos > 90:
            continue

        rsi = calc_rsi_from_list(closes, 14) or 50
        fin_score = calc_fundamental_score(fin, for_value=True)
        signal_score = fin_score * 0.7 + 30 * 0.3

        if signal_score < cfg['required_score']:
            continue

        candidates.append({
            'code': code,
            'name': sinfo.get('name', code) if sinfo else code,
            'price': current_price,
            'rsi': rsi,
            'boll_pos': boll_pos or 50,
            'signal_score': signal_score,
            'fin_score': fin_score,
        })

    candidates.sort(key=lambda x: x['signal_score'], reverse=True)
    return candidates[:max_candidates]


# ═══════════════════════════════════════════════
# 交易模拟
# ═══════════════════════════════════════════════

class Position:
    def __init__(self, code, name, entry_date, entry_price, shares, capital_pct, tier, sl_pct, tp_pct, hold_days_max):
        self.code = code
        self.name = name
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.capital_pct = capital_pct
        self.tier = tier
        self.stop_loss_price = entry_price * (1 - sl_pct)
        self.take_profit_price = entry_price * (1 + tp_pct)
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self.hold_days_max = hold_days_max
        self.entry_value = entry_price * shares
        self.status = 'holding'
        self.exit_date = None
        self.exit_price = None
        self.exit_reason = None
        self.return_pct = None
        self.hold_days = 0


def calc_trade_cost(buy_amount, sell_amount):
    buy_commission = buy_amount * COMMISSION_RATE
    sell_commission = sell_amount * COMMISSION_RATE
    sell_stamp = sell_amount * STAMP_TAX_RATE
    slippage = (buy_amount + sell_amount) * SLIPPAGE_RATE
    return buy_commission + sell_commission + sell_stamp + slippage


# ═══════════════════════════════════════════════
# 回测主逻辑
# ═══════════════════════════════════════════════

def run_backtest_tier(tier_name, data_cache, start_date, end_date):
    """
    对单个档位运行回测。
    tier_name: 'aggressive', 'steady', 'value'
    """
    cfg = TIER_CONFIGS[tier_name]
    screen_fn = {
        'aggressive': screen_aggressive_fast,
        'steady': screen_steady_fast,
        'value': screen_value_fast,
    }[tier_name]

    trading_dates = [d for d in data_cache['trading_dates'] if start_date <= d <= end_date]
    price_map = data_cache['price_map']
    all_codes = list(data_cache['klines'].keys())

    if len(trading_dates) < 20:
        return {'tier': cfg['name'], 'error': f'交易日不足 ({len(trading_dates)})', 'n_trades': 0}

    # 交易模拟器
    initial_capital = 1_000_000
    capital = initial_capital
    positions = []
    closed_trades = []

    rebalance_freq = 5  # 每周调仓
    rebalance_dates = set()
    for i, d in enumerate(trading_dates):
        if i % rebalance_freq == 0:
            rebalance_dates.add(d)

    # 日收益率
    daily_returns = []
    equity_curve = [1.0]
    prev_equity = initial_capital
    n_days = len(trading_dates)

    print(f"    [回测] 开始 {cfg['name']}...", file=sys.stderr)
    last_progress = 0

    for i, current_date in enumerate(trading_dates):
        # 进度
        pct = i * 100 // n_days
        if pct >= last_progress + 10:
            last_progress = pct
            print(f"    [回测] {cfg['name']} {pct}%...", file=sys.stderr)

        day_prices = price_map.get(current_date, {})
        if not day_prices:
            continue

        # 每日检查持仓（止损止盈）
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
            cost = calc_trade_cost(buy_value, sell_value)
            net_return = (sell_value - buy_value - cost) / buy_value * 100
            pos.return_pct = net_return
            closed_trades.append(pos)

        # 调仓日：筛选新候选股
        if current_date in rebalance_dates:
            held_codes = {p.code for p in positions if p.status == 'holding'}
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

                # 仓位计算
                n_holding = len([p for p in positions if p.status == 'holding'])
                if n_holding >= cfg['max_positions']:
                    break

                max_invest = initial_capital * cfg['max_position_pct']
                invest_amount = min(max_invest, max_invest)
                if invest_amount < entry_price * 100:
                    continue

                shares = max(1, int(invest_amount / entry_price / 100) * 100)
                actual_amount = shares * entry_price
                cost = calc_trade_cost(actual_amount, 0)
                capital_pct = actual_amount / initial_capital

                pos = Position(
                    code=code, name=c['name'],
                    entry_date=current_date,
                    entry_price=entry_price,
                    shares=shares,
                    capital_pct=capital_pct,
                    tier=cfg['name'],
                    sl_pct=cfg['stop_loss_pct'],
                    tp_pct=cfg['take_profit_pct'],
                    hold_days_max=cfg['hold_days_max'],
                )
                positions.append(pos)
                held_codes.add(code)

        # 计算当日总资产
        holdings_value = 0
        for pos in positions:
            if pos.status == 'holding' and pos.code in day_prices:
                holdings_value += pos.shares * day_prices[pos.code]
        current_equity = capital + holdings_value
        if current_equity > 0 and prev_equity > 0:
            daily_return = (current_equity - prev_equity) / prev_equity
            daily_returns.append(daily_return)
            equity_curve.append(current_equity / initial_capital)
        prev_equity = current_equity

    # ═══════════════════════════════════════════
    # 计算绩效指标
    # ═══════════════════════════════════════════

    trades = closed_trades
    n_trades = len(trades)

    print(f"    [回测] {cfg['name']} 完成: {n_trades} 笔交易", file=sys.stderr)

    if n_trades < 2:
        return {
            'tier': cfg['name'],
            'error': f'交易次数不足 ({n_trades})',
            'n_trades': n_trades,
        }

    win_trades = [t for t in trades if t.return_pct > 0]
    loss_trades = [t for t in trades if t.return_pct <= 0]
    win_rate = len(win_trades) / n_trades * 100 if n_trades > 0 else 0

    avg_win = statistics.mean([t.return_pct for t in win_trades]) if win_trades else 0
    avg_loss = abs(statistics.mean([t.return_pct for t in loss_trades])) if loss_trades else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')

    total_return = (equity_curve[-1] - 1) * 100
    years = len(daily_returns) / 252
    cagr = ((equity_curve[-1]) ** (1 / years) - 1) * 100 if years > 0.1 else 0

    peak = equity_curve[0]
    max_dd = 0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    if len(daily_returns) > 1:
        avg_ret = statistics.mean(daily_returns)
        std_ret = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.001
        excess_avg = avg_ret - 0.02 / 252
        sharpe = excess_avg / std_ret * math.sqrt(252) if std_ret > 0 else 0
    else:
        sharpe = 0

    calmar = cagr / (max_dd * 100) if max_dd > 0 else 0

    avg_holding_days = statistics.mean([t.hold_days for t in trades]) if trades else 0
    max_consecutive_losses = 0
    curr_losses = 0
    for t in trades:
        if t.return_pct <= 0:
            curr_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, curr_losses)
        else:
            curr_losses = 0

    return {
        'tier': cfg['name'],
        'n_trades': n_trades,
        'win_trades': len(win_trades),
        'loss_trades': len(loss_trades),
        'win_rate_pct': round(win_rate, 2),
        'avg_win_pct': round(avg_win, 2),
        'avg_loss_pct': round(avg_loss, 2),
        'profit_loss_ratio': round(profit_loss_ratio, 2) if profit_loss_ratio != float('inf') else '∞',
        'total_return_pct': round(total_return, 2),
        'cagr_pct': round(cagr, 2),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'sharpe_ratio': round(sharpe, 2),
        'calmar_ratio': round(calmar, 2),
        'avg_holding_days': round(avg_holding_days, 1),
        'max_consecutive_losses': max_consecutive_losses,
        'final_equity': round(equity_curve[-1], 4),
        'total_days': len(daily_returns),
        'exit_reasons': {
            '止损': sum(1 for t in trades if t.exit_reason == '止损'),
            '止盈': sum(1 for t in trades if t.exit_reason == '止盈'),
            '到期': sum(1 for t in trades if t.exit_reason == '到期'),
        },
        'best_trade': round(max(t.return_pct for t in trades), 2) if trades else 0,
        'worst_trade': round(min(t.return_pct for t in trades), 2) if trades else 0,
    }


# ═══════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════

def generate_markdown_report(all_results, benchmark_return, trading_dates, start_date, end_date):
    lines = []
    lines.append(f"# 📊 三档推荐系统历史回测报告")
    lines.append(f"")
    lines.append(f"> **回测期间**: {start_date} ~ {end_date}")
    lines.append(f"> **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> **数据源**: market_cache.db（{len(trading_dates)}个交易日）")
    lines.append(f"> **初始资金**: ¥1,000,000")
    lines.append(f"> **仓位管理**: 单只≤5%总仓，每档≤10只")
    lines.append(f"> **交易成本**: 佣金万2.5双向 + 印花税0.05%卖出 + 滑点0.1%")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # 整理数据
    infos = {}
    for tier_key in ['aggressive', 'steady', 'value']:
        r = all_results.get(tier_key, {})
        if r and 'error' not in r:
            infos[tier_key] = r
        else:
            infos[tier_key] = {}

    lines.append(f"## 🏆 总体概览")
    lines.append(f"")
    lines.append(f"| 指标 | 激进档-超跌反弹 | 稳健档-主升浪 | 价值档-低估值成长 | 上证指数基准 |")
    lines.append(f"|------|:---------------:|:-------------:|:-----------------:|:-----------:|")

    def _cell(tier_key, metric, fmt='.2f', prefix='', suffix=''):
        r = infos.get(tier_key, {})
        v = r.get(metric)
        if v is None or v == '':
            return '—'
        if isinstance(v, str):
            return v
        return f"{prefix}{v:{fmt}}{suffix}"

    metrics_rows = [
        ('年化收益率', 'cagr_pct', '.2f', '', '%'),
        ('累计收益', 'total_return_pct', '.2f', '', '%'),
        ('夏普比率', 'sharpe_ratio', '.2f'),
        ('最大回撤', 'max_drawdown_pct', '.2f', '', '%'),
        ('卡玛比率', 'calmar_ratio', '.2f'),
        ('交易次数', 'n_trades', '.0f'),
        ('胜率', 'win_rate_pct', '.2f', '', '%'),
        ('盈亏比', 'profit_loss_ratio', '.2f'),
        ('平均持仓(天)', 'avg_holding_days', '.1f'),
        ('最大连续亏损', 'max_consecutive_losses', '.0f'),
        ('最佳单笔收益', 'best_trade', '.2f', '', '%'),
        ('最差单笔收益', 'worst_trade', '.2f', '', '%'),
    ]

    for label, metric, *fmt_info in metrics_rows:
        fmt = fmt_info[0] if fmt_info else '.2f'
        prefix = fmt_info[1] if len(fmt_info) > 1 else ''
        suffix = fmt_info[2] if len(fmt_info) > 2 else ''
        row = f"| {label} |"
        for tier_key in ['aggressive', 'steady', 'value']:
            row += f" {_cell(tier_key, metric, fmt, prefix, suffix)} |"
        row += " — |"
        lines.append(row)

    lines.append(f"| 基准收益 | — | — | — | {benchmark_return:.2f}% |")

    # 退出原因
    lines.append(f"")
    lines.append(f"### 退出原因分布")
    lines.append(f"")
    lines.append(f"| 退出原因 | 激进档 | 稳健档 | 价值档 |")
    lines.append(f"|----------|:------:|:------:|:------:|")
    for reason in ['止损', '止盈', '到期']:
        row = f"| {reason} |"
        for tier_key in ['aggressive', 'steady', 'value']:
            r = infos.get(tier_key, {})
            reasons = r.get('exit_reasons', {})
            row += f" {reasons.get(reason, 0)} |"
        lines.append(row)

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # 各档详情
    for tier_key, tier_label in [('aggressive', '🔥 激进档-超跌反弹'), ('steady', '📈 稳健档-主升浪'), ('value', '💎 价值档-低估值成长')]:
        r = infos.get(tier_key, {})
        if not r:
            continue
        cfg = TIER_CONFIGS[tier_key]
        lines.append(f"## {tier_label}")
        lines.append(f"")
        lines.append(f"**配置**: 止损 -{cfg['stop_loss_pct']*100:.0f}% / +{cfg['take_profit_pct']*100:.0f}% | 仓位≤{cfg['max_position_pct']*100:.0f}% | 最多持有{cfg['hold_days_max']}天")
        lines.append(f"")
        lines.append(f"- **交易次数**: {r['n_trades']} 次（胜:{r['win_trades']} 负:{r['loss_trades']}）")
        lines.append(f"- **胜率**: {r['win_rate_pct']}%")
        lines.append(f"- **平均盈利**: {r['avg_win_pct']}% | **平均亏损**: {r['avg_loss_pct']}%")
        lines.append(f"- **盈亏比**: {r['profit_loss_ratio']}")
        lines.append(f"- **年化收益**: {r['cagr_pct']}%")
        lines.append(f"- **累计收益**: {r['total_return_pct']}%")
        lines.append(f"- **夏普比率**: {r['sharpe_ratio']}")
        lines.append(f"- **最大回撤**: {r['max_drawdown_pct']}%")
        lines.append(f"- **卡玛比率**: {r['calmar_ratio']}")
        lines.append(f"- **平均持仓**: {r['avg_holding_days']} 天")
        lines.append(f"- **最大连续亏损**: {r['max_consecutive_losses']} 次")
        lines.append(f"- **最佳单笔**: {r['best_trade']}% | **最差单笔**: {r['worst_trade']}%")
        lines.append(f"")

    # 基准对比
    lines.append(f"## 📉 基准对比（上证指数）")
    lines.append(f"")
    lines.append(f"| 档位 | 策略收益 | 基准收益 | 超额收益 | 年化Alpha |")
    lines.append(f"|------|:--------:|:--------:|:--------:|:---------:|")
    for tier_key in ['aggressive', 'steady', 'value']:
        r = infos.get(tier_key, {})
        if not r:
            continue
        tr = r.get('total_return_pct', 0)
        excess = tr - benchmark_return
        alpha = r.get('cagr_pct', 0) - 0.02
        lines.append(f"| {r['tier']} | {tr:.2f}% | {benchmark_return:.2f}% | {excess:+.2f}% | {alpha:.2f}% |")
    lines.append(f"")

    # 总结
    lines.append(f"## 💡 总结与建议")
    lines.append(f"")
    best_tier = None
    best_sharpe = -999
    for tier_key in ['aggressive', 'steady', 'value']:
        r = infos.get(tier_key, {})
        if r and r.get('sharpe_ratio', -999) > best_sharpe:
            best_sharpe = r['sharpe_ratio']
            best_tier = tier_key

    if best_tier:
        lines.append(f"**最佳夏普档位**: {infos[best_tier]['tier']}（夏普={best_sharpe}）")
        lines.append(f"")
        lines.append(f"### 各档位适用场景")
        lines.append(f"")
        agg_win = infos.get('aggressive', {}).get('win_rate_pct', '?')
        std_win = infos.get('steady', {}).get('win_rate_pct', '?')
        val_win = infos.get('value', {}).get('win_rate_pct', '?')
        lines.append(f"- **激进档（超跌反弹）**: 适合震荡市/下跌后的反弹行情，快进快出，{agg_win}%胜率")
        lines.append(f"- **稳健档（主升浪）**: 适合趋势市，顺势而为，{std_win}%胜率")
        lines.append(f"- **价值档（低估值成长）**: 适合价值投资，长线持有，{val_win}%胜率")
        lines.append(f"")
        lines.append(f"### 风险提示")
        lines.append(f"")
        lines.append(f"- 回测结果基于历史数据，不代表未来表现")
        lines.append(f"- 未考虑流动性冲击（大资金买卖影响）")
        lines.append(f"- 滞后价格假设：调仓日以收盘价成交（实际可能滑点更大）")
        lines.append(f"- 未考虑分红、送股、配股等事件")
        lines.append(f"- 回测期间市场风格可能轮换，各档位表现会因市场环境变化")

    return '\n'.join(lines)


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='三档推荐系统历史回测')
    parser.add_argument('--start', default='2022-01-01', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', default='2026-07-24', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--tier', choices=['aggressive', 'steady', 'value', 'all'], default='all',
                        help='回测档位 (默认: all)')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    parser.add_argument('--save', action='store_true', help='保存报告到文件')
    args = parser.parse_args()

    start_date = args.start
    end_date = args.end
    tiers_to_run = ['aggressive', 'steady', 'value'] if args.tier == 'all' else [args.tier]

    print(f"🚀 开始三档推荐系统回测", file=sys.stderr)
    print(f"   期间: {start_date} ~ {end_date}", file=sys.stderr)
    print(f"   档位: {', '.join(tiers_to_run)}", file=sys.stderr)

    # 加载数据
    data_cache = load_all_data()

    trading_dates = [d for d in data_cache['trading_dates'] if start_date <= d <= end_date]
    print(f"   交易日: {len(trading_dates)} 天", file=sys.stderr)

    if len(trading_dates) < 20:
        print(f"❌ 交易日不足，请检查日期范围", file=sys.stderr)
        return

    # 基准收益
    price_map = data_cache['price_map']
    benchmark_prices = {}
    for d in trading_dates:
        if d in price_map and '000001' in price_map[d]:
            benchmark_prices[d] = price_map[d]['000001']

    if benchmark_prices:
        bm_dates = sorted(benchmark_prices.keys())
        bm_start_px = benchmark_prices[bm_dates[0]]
        bm_end_px = benchmark_prices[bm_dates[-1]]
        benchmark_return = (bm_end_px - bm_start_px) / bm_start_px * 100 if bm_start_px > 0 else 0
    else:
        bm_start_px = 0
        bm_end_px = 0
        benchmark_return = 0
    print(f"   上证指数基准: {bm_start_px:.2f} → {bm_end_px:.2f} ({benchmark_return:+.2f}%)", file=sys.stderr)

    # 运行各档位回测
    all_results = {}
    for tier in tiers_to_run:
        print(f"", file=sys.stderr)
        result = run_backtest_tier(tier, data_cache, start_date, end_date)
        all_results[tier] = result
        if 'error' in result:
            print(f"   ⚠️ {result['error']}", file=sys.stderr)
        else:
            print(f"   ✅ {result['tier']}: {result['n_trades']}笔交易, 胜率{result['win_rate_pct']}%, 年化{result['cagr_pct']}%, 夏普{result['sharpe_ratio']}", file=sys.stderr)

    # 输出
    if args.json:
        output = {
            'backtest_period': f"{start_date} ~ {end_date}",
            'trading_days': len(trading_dates),
            'stock_universe': len(data_cache['klines']),
            'results': all_results,
            'benchmark': {
                'benchmark_name': '上证指数',
                'benchmark_return_pct': round(benchmark_return, 2),
            }
        }
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    else:
        report = generate_markdown_report(all_results, benchmark_return, trading_dates, start_date, end_date)
        print(report)

    if args.save:
        out_dir = Path(__file__).parent.resolve() / "backtest_reports"
        out_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.json:
            out_path = out_dir / f"backtest_recommend_{ts}.json"
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        else:
            out_path = out_dir / f"backtest_recommend_{ts}.md"
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(report)
        print(f"📁 报告已保存: {out_path}", file=sys.stderr)


if __name__ == '__main__':
    main()