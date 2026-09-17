#!/usr/bin/env python3
"""
因子IC分析模块 v1.1 — 支持风险因子（BETA/市值/动量）+ 传统因子
========================================================================
方法：截面Rank IC（Spearman秩相关系数）
  用因子值排序 vs 未来收益排序，计算秩相关系数。
  IC > 0: 因子值越大，未来收益越高（正向有效）
  IC < 0: 因子值越大，未来收益越低（反向有效）

因子范围：
  - 基本面：roe, net_margin, profit_growth, revenue_growth, gross_margin, debt_ratio
  - 估值：pe_ttm, pb_mrq
  - 技术：rsi_14, boll_position, macd_hist, ma_bullish, volatility_20d
  - 风险：beta, ln_market_cap, momentum_1m, momentum_3m, momentum_6m

用法：
  python3 factor_ic.py                    # 文本输出
  python3 factor_ic.py --json             # JSON输出（供factor_rotation.py使用）
  python3 factor_ic.py --risk-only        # 仅计算风险因子IC
  python3 factor_ic.py --all-factors      # 计算所有因子（含风险因子）

数据流：
  factor_ic.py → factor_rotation.py → score_upgrade.py
"""
from core.compat_paths import MARKET_DB as _DB_PATH
MARKET_DB = _DB_PATH


import os
import sys
import json
import sqlite3
import math
from datetime import datetime
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()

# ── 因子定义 ──

# 技术因子（从K线计算）
TECH_FACTORS = {
    "rsi_14": {"label": "RSI(14)", "reverse": False},
    "boll_position": {"label": "布林位置", "reverse": False},
    "macd_hist": {"label": "MACD直方图", "reverse": False},
    "ma_bullish": {"label": "均线形态", "reverse": False},
    "volatility_20d": {"label": "波动率(20日)", "reverse": True},
}

# 基本面因子（从financial_data）
FUNDAMENTAL_FACTORS = {
    "roe": {"label": "ROE", "reverse": False},
    "net_margin": {"label": "净利率", "reverse": False},
    "profit_growth": {"label": "利润增速", "reverse": False},
    "revenue_growth": {"label": "营收增速", "reverse": False},
    "gross_margin": {"label": "毛利率", "reverse": False},
    "debt_ratio": {"label": "负债率", "reverse": True},
}

# 估值因子（从pe_pb_data）
VALUATION_FACTORS = {
    "pe_ttm": {"label": "PE(TTM)", "reverse": True},
    "pb_mrq": {"label": "PB(MRQ)", "reverse": True},
}

# 风险因子（从K线计算）
RISK_FACTORS = {
    "beta": {"label": "BETA(60日)", "reverse": False},
    "ln_market_cap": {"label": "LN市值", "reverse": False},
    "momentum_1m": {"label": "动量(1月)", "reverse": False},
    "momentum_3m": {"label": "动量(3月)", "reverse": False},
    "momentum_6m": {"label": "动量(6月)", "reverse": False},
}

# 所有因子
ALL_FACTORS = {}
ALL_FACTORS.update(TECH_FACTORS)
ALL_FACTORS.update(FUNDAMENTAL_FACTORS)
ALL_FACTORS.update(VALUATION_FACTORS)
ALL_FACTORS.update(RISK_FACTORS)

# 因子分组
FACTOR_GROUPS = {
    "fundamental": list(FUNDAMENTAL_FACTORS.keys()),
    "valuation": list(VALUATION_FACTORS.keys()),
    "technical": list(TECH_FACTORS.keys()),
    "risk": list(RISK_FACTORS.keys()),
}


# ── 工具函数 ──

def _get_db():
    conn = sqlite3.connect(str(MARKET_DB))
    conn.row_factory = sqlite3.Row
    return conn


def calc_tech_indicators(closes):
    """
    从收盘价序列计算技术指标。
    用于传统因子IC计算（与cron/factor_ic.py一致）。
    """
    if len(closes) < 45:
        return {}
    
    n = len(closes)
    
    # RSI(14)
    rsi = None
    if n >= 15:
        gains = losses = 0
        for i in range(1, 15):
            diff = closes[-i] - closes[-i-1]
            if diff >= 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / 14
        avg_loss = losses / 14
        rsi = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 100.0
    
    # 布林位置(20)
    boll = None
    if n >= 20:
        recent = closes[-20:]
        ma = sum(recent) / 20
        var = sum((p - ma) ** 2 for p in recent) / 20
        std = math.sqrt(var)
        upper = ma + 2 * std
        lower = ma - 2 * std
        boll = (closes[-1] - lower) / (upper - lower) * 100 if upper != lower else 50.0
    
    # MACD直方图
    macd_hist = None
    if n >= 35:
        def ema(data, period):
            k = 2.0 / (period + 1)
            result = [data[0]]
            for i in range(1, len(data)):
                result.append(data[i] * k + result[-1] * (1 - k))
            return result
        ema_fast = ema(closes, 12)
        ema_slow = ema(closes, 26)
        dif = [ema_fast[i] - ema_slow[i] for i in range(len(ema_fast))]
        dea = ema(dif, 9)
        macd_hist = dif[-1] - dea[-1]
    
    # 均线形态
    ma5 = sum(closes[-5:]) / 5 if n >= 5 else sum(closes) / n
    ma20 = sum(closes[-20:]) / 20 if n >= 20 else ma5
    ma_bullish = 1 if ma5 > ma20 else -1
    
    # 波动率
    returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(-19, 0) if len(closes) >= 20]
    if returns:
        avg_r = sum(returns) / len(returns) if returns else 0
        var_r = sum((r - avg_r) ** 2 for r in returns) / len(returns) if returns else 0
        volatility = math.sqrt(var_r) * 100 if var_r > 0 else 0
    else:
        volatility = 0
    
    return {
        'rsi_14': rsi,
        'boll_position': boll,
        'macd_hist': macd_hist,
        'ma_bullish': ma_bullish,
        'volatility_20d': volatility,
    }


# ── 风险因子计算（IC分析专用） ──

def compute_risk_factors_for_ic(stock_codes, stock_data, klines_full):
    """
    为IC分析批量计算风险因子。
    
    参数:
        stock_codes: 股票代码列表
        stock_data: {code: [(date, close), ...]} 全部K线数据
        klines_full: 原始K线数据（用于BETA计算需要基准指数）
    
    返回: {code: {'beta': float, 'ln_market_cap': float, 
                   'momentum_1m': float, 'momentum_3m': float, 'momentum_6m': float}}
    """
    result = {}
    
    # 加载基准指数数据
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT date, close FROM klines WHERE code='000300' ORDER BY date")
    bm_rows = cur.fetchall()
    bm_map = {r["date"]: r["close"] for r in bm_rows}
    bm_dates = sorted(bm_map.keys())
    
    # 加载市值数据
    cur.execute("""
        SELECT i.code, i.current_price, s.total_shares
        FROM indicators i
        JOIN stocks s ON i.code = s.code
        WHERE i.date = (SELECT MAX(date) FROM indicators)
          AND i.code IN ({})
    """.format(",".join("?" for _ in stock_codes)), stock_codes)
    
    mc_map = {}
    for row in cur.fetchall():
        code = row["code"]
        price = row["current_price"]
        total_shares = row["total_shares"]
        if total_shares and total_shares > 0 and price and price > 0:
            mc_map[code] = math.log(price * total_shares)
        elif price and price > 0:
            mc_map[code] = math.log(price * 1e8)
    
    conn.close()
    
    for code in stock_codes:
        klines = stock_data.get(code, [])
        if len(klines) < 66:
            continue
        
        closes = [c for _, c in klines]
        risk = {}
        
        # BETA: 用前60天 vs 基准指数
        if len(bm_dates) >= 60:
            # 取个股最近60天收盘价
            stock_60d = closes[-60:] if len(closes) >= 60 else closes
            # 取对应基准指数数据
            bm_60d_dates = bm_dates[-61:]  # 需要61个点算60个收益率
            bm_60d = [bm_map[d] for d in bm_60d_dates if d in bm_map]
            
            if len(stock_60d) >= 30 and len(bm_60d) >= 30:
                # 对齐计算：取个股和基准都有数据的日期
                # 简化：用个股最近60天和基准最近60天直接算
                s_ret = [(stock_60d[i] - stock_60d[i-1]) / stock_60d[i-1] 
                         for i in range(1, len(stock_60d)) if stock_60d[i-1] > 0]
                b_ret = [(bm_60d[i] - bm_60d[i-1]) / bm_60d[i-1] 
                         for i in range(1, len(bm_60d)) if bm_60d[i-1] > 0]
                
                # 截取相同长度
                min_len = min(len(s_ret), len(b_ret))
                if min_len >= 20:
                    s_ret = s_ret[-min_len:]
                    b_ret = b_ret[-min_len:]
                    n = len(s_ret)
                    mean_s = sum(s_ret) / n
                    mean_b = sum(b_ret) / n
                    cov = sum((s - mean_s) * (b - mean_b) for s, b in zip(s_ret, b_ret)) / n
                    var_b = sum((b - mean_b) ** 2 for b in b_ret) / n
                    risk["beta"] = round(cov / var_b, 4) if var_b > 0 else None
                else:
                    risk["beta"] = None
            else:
                risk["beta"] = None
        else:
            risk["beta"] = None
        
        # 动量
        if len(closes) > 20:
            risk["momentum_1m"] = round((closes[-1] - closes[-21]) / closes[-21], 4)
        else:
            risk["momentum_1m"] = None
            
        if len(closes) > 60:
            risk["momentum_3m"] = round((closes[-1] - closes[-61]) / closes[-61], 4)
        else:
            risk["momentum_3m"] = None
            
        if len(closes) > 120:
            risk["momentum_6m"] = round((closes[-1] - closes[-121]) / closes[-121], 4)
        else:
            risk["momentum_6m"] = None
        
        # LN市值
        risk["ln_market_cap"] = mc_map.get(code)
        
        result[code] = risk
    
    return result


# ── Spearman Rank IC ──

def spearman_rank_ic(values, forward_returns, reverse=False):
    """
    计算Spearman秩相关系数（Rank IC）。
    
    参数:
        values: 因子值列表
        forward_returns: 对应的未来收益列表
        reverse: 是否反向（True=值越小越好）
    
    返回: (IC值, 有效样本数)
    """
    # 过滤无效数据
    valid = [(v, r) for v, r in zip(values, forward_returns) 
             if v is not None and r is not None]
    
    if len(valid) < 30:
        return 0, 0
    
    n = len(valid)
    
    # 因子值排序
    sorted_by_factor = sorted(valid, key=lambda x: x[0])
    
    # 计算秩差平方和
    sum_d2 = 0
    factor_ranks = [i for i in range(n)]
    # 收益排序
    ret_sorted = sorted([r for _, r in sorted_by_factor])
    
    for i, (fv, ret) in enumerate(sorted_by_factor):
        f_rank = i
        r_rank = ret_sorted.index(ret)  # 这里可能有重复值问题
        d = f_rank - r_rank
        sum_d2 += d * d
    
    # Spearman公式
    ic = 1 - (6 * sum_d2) / (n * (n * n - 1))
    
    if reverse:
        ic = -ic
    
    return round(ic, 4), n


# ── 分组收益分析 ──

def group_returns(values, forward_returns, n_groups=5):
    """
    按因子值分组，计算每组平均收益。
    用于判断单调性。
    """
    valid = [(v, r) for v, r in zip(values, forward_returns) 
             if v is not None and r is not None]
    if len(valid) < n_groups * 2:
        return [], 0, 0
    
    n = len(valid)
    sorted_by_factor = sorted(valid, key=lambda x: x[0])
    group_size = n // n_groups
    
    groups = []
    for g in range(n_groups):
        start = g * group_size
        end = start + group_size if g < n_groups - 1 else n
        group = sorted_by_factor[start:end]
        avg_ret = sum(p[1] for p in group) / len(group)
        groups.append(round(avg_ret, 4))
    
    long_short = groups[-1] - groups[0]
    monotonic = "是" if (groups[-1] > groups[0]) else "否"
    
    return groups, round(long_short, 4), monotonic


# ── 主分析函数 ──

def analyze_factor_ic(include_risk=True, json_output=False):
    """
    主分析函数：计算所有因子的截面IC。
    
    参数:
        include_risk: 是否包含风险因子
        json_output: 是否JSON输出
    
    返回: (effective_factors, ineffective_factors)
    """
    _print = lambda *a, **kw: None if json_output else print(*a, **kw)
    
    conn = _get_db()
    cur = conn.cursor()
    
    # ── 1. 加载K线数据 ──
    _print(f"\n[1/5] 加载K线数据...")
    cur.execute("SELECT code, date, close FROM klines ORDER BY code, date")
    all_klines = defaultdict(list)
    for code, date, close in cur.fetchall():
        all_klines[code].append((date, close))
    conn.close()
    
    all_codes = list(all_klines.keys())
    _print(f"   共 {len(all_codes)} 只股票")
    
    # ── 2. 构建截面 ──
    _print("[2/5] 构建截面数据...")
    
    snapshot = []
    cutoff_date = None
    
    for code in all_codes:
        klines = all_klines[code]
        if len(klines) < 66:
            continue
        
        # 前45天计算指标
        indicator_closes = [c for _, c in klines[:45]]
        tech_factors = calc_tech_indicators(indicator_closes)
        if not tech_factors:
            continue
        
        # 后21天收益（未来收益）
        start_price = klines[44][1]
        end_price = klines[-1][1]
        if start_price <= 0:
            continue
        forward_ret = (end_price - start_price) / start_price * 100
        
        if cutoff_date is None:
            cutoff_date = klines[44][0]
        
        snapshot.append({
            'code': code,
            'tech_factors': tech_factors,
            'forward_ret': forward_ret,
        })
    
    _print(f"   截面日期: {cutoff_date} → 未来21天")
    _print(f"   有效样本: {len(snapshot)} 只股票")
    
    if len(snapshot) < 100:
        _print("   样本不足")
        return [], []
    
    # ── 3. 加载基本面+估值数据 ──
    _print("[3/5] 加载基本面/估值数据...")
    fin_conn = _get_db()
    fcur = fin_conn.cursor()
    
    # 基本面数据
    fcur.execute("""
        SELECT f.code, f.roe, f.profit_growth, f.revenue_growth,
               f.debt_ratio, f.gross_margin, f.net_margin
        FROM financial_data f
        INNER JOIN (
            SELECT code, MAX(report_date) as max_date
            FROM financial_data GROUP BY code
        ) l ON f.code = l.code AND f.report_date = l.max_date
    """)
    fin_data = {}
    for row in fcur.fetchall():
        fin_data[row[0]] = {
            'roe': row[1], 'profit_growth': row[2],
            'revenue_growth': row[3], 'debt_ratio': row[4],
            'gross_margin': row[5], 'net_margin': row[6],
        }
    
    # PE/PB数据
    fcur.execute("""
        SELECT code, pe_ttm, pb_mrq FROM pe_pb_data
        WHERE fetch_date = (SELECT MAX(fetch_date) FROM pe_pb_data)
    """)
    for row in fcur.fetchall():
        if row[0] in fin_data:
            fin_data[row[0]]['pe_ttm'] = row[1]
            fin_data[row[0]]['pb_mrq'] = row[2]
    
    fin_conn.close()
    
    # 合并基本面数据
    for s in snapshot:
        fd = fin_data.get(s['code'], {})
        for k, v in fd.items():
            s['tech_factors'][k] = v
    
    # ── 4. 计算风险因子 ──
    if include_risk:
        _print("[4/5] 计算风险因子（BETA/市值/动量）...")
        risk_factors = compute_risk_factors_for_ic(
            [s['code'] for s in snapshot], all_klines, all_klines
        )
        for s in snapshot:
            rf = risk_factors.get(s['code'], {})
            s['tech_factors'].update(rf)
    
    # ── 5. 计算IC ──
    _print("[5/5] 计算截面Rank IC...\n")
    
    # 确定要分析的因子
    if include_risk:
        factor_names = list(ALL_FACTORS.keys())
    else:
        factor_names = (list(TECH_FACTORS.keys()) + 
                       list(FUNDAMENTAL_FACTORS.keys()) + 
                       list(VALUATION_FACTORS.keys()))
    
    factor_labels = {k: v["label"] for k, v in ALL_FACTORS.items()}
    reverse_factors = {k: v["reverse"] for k, v in ALL_FACTORS.items()}
    
    _print(f"{'因子名称':<16} {'IC值':<10} {'多空收益':<12} {'单调':<6} {'样本':<8}")
    _print("-" * 55)
    
    effective = []
    ineffective = []
    all_ic_results = {}
    
    for fn in factor_names:
        label = factor_labels.get(fn, fn)
        valid = [(s['tech_factors'].get(fn), s['forward_ret']) 
                 for s in snapshot if s['tech_factors'].get(fn) is not None]
        
        if len(valid) < 50:
            _print(f"{label:<16} {'数据不足':<10}")
            continue
        
        values = [v for v, _ in valid]
        returns = [r for _, r in valid]
        
        ic, n = spearman_rank_ic(values, returns, reverse=reverse_factors.get(fn, False))
        groups, ls, mono = group_returns(values, returns)
        
        all_ic_results[fn] = ic
        
        _print(f"{label:<16} {ic:+.4f}    {ls:+.2f}%     {mono:<6} {n}")
        
        if abs(ic) > 0.03:
            effective.append((label, ic, ls))
        else:
            ineffective.append((label, ic))
    
    _print(f"\n{'=' * 55}")
    _print(f"🔥 有效因子 (|IC| > 0.03): {len(effective)} 个")
    for name, ic, ls in sorted(effective, key=lambda x: -abs(x[1])):
        _print(f"  {name:<16} IC={ic:+.4f} 多空收益={ls:+.2f}%")
    
    _print(f"\n❌ 失效因子 (|IC| <= 0.03): {len(ineffective)} 个")
    for name, ic in sorted(ineffective, key=lambda x: -abs(x[1])):
        _print(f"  {name:<16} IC={ic:+.4f}")
    
    return effective, ineffective


# ── 命令行入口 ──

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="因子IC分析模块")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--risk-only", action="store_true", help="仅计算风险因子IC")
    parser.add_argument("--all-factors", action="store_true", help="计算所有因子（含风险因子）")
    
    args = parser.parse_args()
    
    if args.risk_only:
        # 仅风险因子
        from risk_factors import compute_all_risk_factors
        # 简单测试：直接输出风险因子统计
        print("风险因子统计模式（请使用 --all-factors 计算完整IC）")
        sys.exit(0)
    
    if args.all_factors:
        include_risk = True
    else:
        include_risk = True  # 默认包含风险因子
    
    effective, ineffective = analyze_factor_ic(
        include_risk=include_risk,
        json_output=args.json
    )
    
    if args.json:
        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "factors": {},
            "effective": [{"name": n, "ic": ic, "long_short": ls} for n, ic, ls in effective],
            "ineffective": [{"name": n, "ic": ic} for n, ic in ineffective],
        }
        for name, ic, _ in effective:
            result["factors"][name] = ic
        for name, ic in ineffective:
            result["factors"][name] = ic
        print(json.dumps(result, ensure_ascii=False, indent=2))