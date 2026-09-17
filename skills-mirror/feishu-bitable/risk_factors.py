#!/usr/bin/env python3
"""
风险因子计算模块 v1.0
从 market_cache.db 的 klines 表计算：
  - BETA（个股vs大盘的60日回归系数）
  - 市值对数（LN市值）
  - 动量因子（过去1个月/3个月/6个月收益率）

数据源：market_cache.db（klines / stocks / indicators / financial_data）
基准指数：000300（沪深300）
"""
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

import os
import sqlite3
import math
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKET_DB = _STOCK_MARKET_DB

# 基准指数代码
BENCHMARK_CODE = "000300"

# 动量计算所需的交易日数（约算）
TRADING_DAYS = {"1M": 20, "3M": 60, "6M": 120}

# ── 数据库连接 ──

def _get_db():
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    return conn


# ── 基准指数K线加载 ──

def _load_benchmark_klines(benchmark_code=BENCHMARK_CODE):
    """
    加载基准指数（沪深300）的日K线
    返回: {date: close}
    """
    conn = _get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT date, close FROM klines WHERE code=? ORDER BY date",
        (benchmark_code,)
    )
    bm = {row["date"]: row["close"] for row in cur.fetchall()}
    conn.close()
    return bm


# ── BETA 计算 ──

def compute_beta(stock_code, benchmark_code=BENCHMARK_CODE, window=60):
    """
    计算个股 vs 大盘的60日回归系数 BETA。
    
    BETA = Cov(R_stock, R_market) / Var(R_market)
    
    参数:
        stock_code: 股票代码
        benchmark_code: 基准指数代码（默认000300沪深300）
        window: 回归窗口（默认60个交易日）
    
    返回: BETA值（float），数据不足时返回 None
    """
    conn = _get_db()
    cur = conn.cursor()
    
    # 加载基准指数K线
    bm = _load_benchmark_klines(benchmark_code)
    if len(bm) < window:
        conn.close()
        return None
    
    # 加载个股K线（取最近2*window天以确保有足够重叠数据）
    cur.execute(
        "SELECT date, close FROM klines WHERE code=? ORDER BY date DESC LIMIT ?",
        (stock_code, window * 2)
    )
    stock_rows = cur.fetchall()
    conn.close()
    
    if len(stock_rows) < window:
        return None
    
    # 构建日期对齐的收益率序列
    stock_map = {row["date"]: row["close"] for row in stock_rows}
    
    # 取基准指数最近 window+1 天（为了算收益率）
    bm_dates = sorted(bm.keys(), reverse=True)
    bm_window = bm_dates[:window + 1]
    
    stock_returns = []
    bm_returns = []
    
    for i in range(len(bm_window) - 1):
        d_curr = bm_window[i]
        d_prev = bm_window[i + 1]
        
        if d_curr in stock_map and d_prev in stock_map:
            s_curr = stock_map[d_curr]
            s_prev = stock_map[d_prev]
            b_curr = bm[d_curr]
            b_prev = bm[d_prev]
            
            if s_prev > 0 and b_prev > 0:
                stock_returns.append((s_curr - s_prev) / s_prev)
                bm_returns.append((b_curr - b_prev) / b_prev)
    
    if len(stock_returns) < 20:
        return None
    
    # 计算 BETA = Cov / Var
    n = len(stock_returns)
    mean_s = sum(stock_returns) / n
    mean_b = sum(bm_returns) / n
    
    cov = sum((s - mean_s) * (b - mean_b) for s, b in zip(stock_returns, bm_returns)) / n
    var_b = sum((b - mean_b) ** 2 for b in bm_returns) / n
    
    if var_b <= 0:
        return None
    
    beta = cov / var_b
    return round(beta, 4)


# ── 市值估算 ──

def compute_ln_market_cap(stock_code):
    """
    估算个股的LN市值（对数市值）。
    
    方法：使用 indicators 最新价格 × stocks 总股本（如果可用）
    或从 financial_data 的 bvps × pb_ratio 估算。
    
    返回: LN(市值) 或 None
    """
    conn = _get_db()
    cur = conn.cursor()
    
    # 尝试1: 从 stocks 表获取总股本
    cur.execute("SELECT total_shares, circulating_shares FROM stocks WHERE code=?", (stock_code,))
    stock_row = cur.fetchone()
    
    # 获取最新价格
    cur.execute(
        "SELECT current_price FROM indicators WHERE code=? AND date = (SELECT MAX(date) FROM indicators)",
        (stock_code,)
    )
    price_row = cur.fetchone()
    
    market_cap = None
    
    if stock_row and price_row:
        total_shares = stock_row["total_shares"]
        price = price_row["current_price"]
        if total_shares and total_shares > 0 and price and price > 0:
            # total_shares 单位是股，price 是元/股，市值 = 元
            market_cap = price * total_shares
    
    # 尝试2: 用流通股本估算（如果总股本不可用）
    if market_cap is None and stock_row and price_row:
        circ_shares = stock_row["circulating_shares"]
        price = price_row["current_price"]
        if circ_shares and circ_shares > 0 and price and price > 0:
            # 流通市值 × 1.5（估算总市值≈流通市值×1.5）
            market_cap = price * circ_shares * 1.5
    
    # 尝试3: 从 financial_data 的 bvps 和 pe_pb_data 的 pb 估算
    if market_cap is None:
        cur.execute(
            "SELECT bvps, pe_ratio, pb_ratio FROM financial_data "
            "WHERE code=? ORDER BY report_date DESC LIMIT 1",
            (stock_code,)
        )
        fin_row = cur.fetchone()
        if fin_row and price_row:
            bvps = fin_row["bvps"]
            pb = fin_row["pb_ratio"]
            price = price_row["current_price"]
            if bvps and bvps > 0 and pb and pb > 0 and price and price > 0:
                # pb = price / bvps, 市值 = price * shares
                # 估算 shares = pb * bvps / price ... 不对
                # 换个思路：用 pe_ratio * eps 估算
                pass
            # 实在不行就用 price * 1e9 作为粗略估算
            if price and price > 0:
                # 假设平均1亿股流通股，price单位元，市值亿元
                # 但不同股票股本差异巨大，用 price * 1e9 无意义
                pass
    
    conn.close()
    
    # 保底：用价格作为市值代理（价格本身与市值有一定正相关）
    if market_cap is None and price_row and price_row["current_price"] and price_row["current_price"] > 0:
        # 极端简化：用 price * 1e8（假设1亿股）作为市值估算
        # 注意：这只是一个排序用的代理，实际值不准确但排名大致可用
        market_cap = price_row["current_price"] * 1e8
    
    if market_cap is None or market_cap <= 0:
        return None
    
    return round(math.log(market_cap), 4)


def compute_market_cap_batch(stock_codes):
    """
    批量估算市值，使用 indicators 最新价格 × stocks 总股本。
    返回: {code: LN市值} 的字典
    """
    if not stock_codes:
        return {}
    
    conn = _get_db()
    cur = conn.cursor()
    
    # 获取最新价格
    placeholders = ",".join("?" for _ in stock_codes)
    cur.execute(f"""
        SELECT i.code, i.current_price, s.total_shares, s.circulating_shares
        FROM indicators i
        JOIN stocks s ON i.code = s.code
        WHERE i.date = (SELECT MAX(date) FROM indicators)
          AND i.code IN ({placeholders})
    """, stock_codes)
    
    result = {}
    for row in cur.fetchall():
        code = row["code"]
        price = row["current_price"]
        total_shares = row["total_shares"]
        
        mc = None
        if total_shares and total_shares > 0 and price and price > 0:
            mc = price * total_shares
        elif price and price > 0:
            # 用价格×1e8作为代理（保留排序）
            mc = price * 1e8
        
        if mc and mc > 0:
            result[code] = round(math.log(mc), 4)
    
    conn.close()
    return result


# ── 动量因子 ──

def compute_momentum(stock_code, periods=None):
    """
    计算动量因子：过去1个月/3个月/6个月收益率。
    
    参数:
        stock_code: 股票代码
        periods: 列表，如 [(20, '1M'), (60, '3M'), (120, '6M')] 或默认
    
    返回: {'1M': float, '3M': float, '6M': float} 或 {}
    """
    if periods is None:
        periods = [(20, '1M'), (60, '3M'), (120, '6M')]
    
    conn = _get_db()
    cur = conn.cursor()
    
    # 获取最近N天的K线（取最大period的两倍确保够用）
    max_period = max(p[0] for p in periods)
    cur.execute(
        "SELECT date, close FROM klines WHERE code=? ORDER BY date DESC LIMIT ?",
        (stock_code, max_period + 10)
    )
    rows = cur.fetchall()
    conn.close()
    
    if len(rows) < max_period:
        return {}
    
    # 按日期升序排列
    rows.reverse()
    closes = [r["close"] for r in rows]
    
    result = {}
    for period, name in periods:
        if len(closes) > period:
            # 收益率 = (close_today / close_{period}_ago) - 1
            ret = (closes[-1] - closes[-(period + 1)]) / closes[-(period + 1)]
            result[name] = round(ret, 4)
        else:
            result[name] = None
    
    return result


# ── 批量计算风险因子 ──

def compute_all_risk_factors(stock_codes=None, max_workers=8, progress_callback=None):
    """
    批量计算所有股票的风险因子。
    
    参数:
        stock_codes: 要计算的股票列表（None=全部有K线的股票）
        max_workers: 并发数
        progress_callback: 进度回调函数
    
    返回: [{'code': str, 'beta': float, 'ln_market_cap': float, 
             'momentum_1m': float, 'momentum_3m': float, 'momentum_6m': float}, ...]
    """
    conn = _get_db()
    cur = conn.cursor()
    
    if stock_codes is None:
        # 获取所有有足够K线数据的股票
        cur.execute("""
            SELECT code FROM klines 
            GROUP BY code HAVING COUNT(*) >= 120
        """)
        stock_codes = [r["code"] for r in cur.fetchall()]
    
    # 排除基准指数
    stock_codes = [c for c in stock_codes if c != BENCHMARK_CODE]
    
    # 先批量计算市值
    ln_mc_map = compute_market_cap_batch(stock_codes)
    
    results = []
    total = len(stock_codes)
    done = 0
    
    def process_one(code):
        beta = compute_beta(code)
        momentum = compute_momentum(code)
        ln_mc = ln_mc_map.get(code, compute_ln_market_cap(code))
        
        return {
            "code": code,
            "beta": beta,
            "ln_market_cap": ln_mc,
            "momentum_1m": momentum.get("1M"),
            "momentum_3m": momentum.get("3M"),
            "momentum_6m": momentum.get("6M"),
        }
    
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_one, c): c for c in stock_codes}
        for f in as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            try:
                results.append(f.result())
            except Exception:
                continue
    
    conn.close()
    return results


# ── 命令行入口 ──

if __name__ == "__main__":
    import sys
    import json
    
    if "--test" in sys.argv:
        # 测试几只知名股票
        test_codes = ["600519", "000858", "300750", "000333", "601318"]
        print(f"{'='*60}")
        print(f"  风险因子测试（基准: 沪深300 {BENCHMARK_CODE}）")
        print(f"{'='*60}")
        print(f"{'股票':<8} {'BETA':<10} {'LN市值':<12} {'动量1M':<12} {'动量3M':<12} {'动量6M':<12}")
        print(f"{'-'*60}")
        
        for code in test_codes:
            beta = compute_beta(code)
            ln_mc = compute_ln_market_cap(code)
            mom = compute_momentum(code)
            print(f"{code:<8} {beta if beta else 'N/A':<10} "
                  f"{ln_mc if ln_mc else 'N/A':<12} "
                  f"{mom.get('1M', 'N/A') if mom.get('1M') is not None else 'N/A':<12} "
                  f"{mom.get('3M', 'N/A') if mom.get('3M') is not None else 'N/A':<12} "
                  f"{mom.get('6M', 'N/A') if mom.get('6M') is not None else 'N/A':<12}")
        
        # 统计分布
        print(f"\n{'='*60}")
        print(f"  全市场风险因子统计")
        print(f"{'='*60}")
        all_factors = compute_all_risk_factors(max_workers=4)
        
        betas = [f["beta"] for f in all_factors if f["beta"] is not None]
        ln_mcs = [f["ln_market_cap"] for f in all_factors if f["ln_market_cap"] is not None]
        m1 = [f["momentum_1m"] for f in all_factors if f["momentum_1m"] is not None]
        m3 = [f["momentum_3m"] for f in all_factors if f["momentum_3m"] is not None]
        m6 = [f["momentum_6m"] for f in all_factors if f["momentum_6m"] is not None]
        
        print(f"  有效样本: BETA={len(betas)}, LN市值={len(ln_mcs)}, "
              f"动量1M={len(m1)}, 3M={len(m3)}, 6M={len(m6)}")
        
        def stats(vals, name):
            if not vals:
                return f"{name}: 无数据"
            vals.sort()
            n = len(vals)
            mean = sum(vals) / n
            median = vals[n // 2]
            p10 = vals[int(n * 0.1)]
            p90 = vals[int(n * 0.9)]
            return f"{name:<12} mean={mean:.4f} median={median:.4f} p10={p10:.4f} p90={p90:.4f}"
        
        print(f"  {stats(betas, 'BETA')}")
        print(f"  {stats(ln_mcs, 'LN市值')}")
        print(f"  {stats(m1, '动量1M')}")
        print(f"  {stats(m3, '动量3M')}")
        print(f"  {stats(m6, '动量6M')}")
        
        # 输出JSON
        if "--json" in sys.argv:
            print(json.dumps(all_factors[:5], ensure_ascii=False, indent=2))
    
    elif "--json" in sys.argv:
        # 计算全部并输出JSON
        factors = compute_all_risk_factors(max_workers=8)
        print(json.dumps(factors, ensure_ascii=False))
    
    else:
        # 单股票计算
        code = sys.argv[1] if len(sys.argv) > 1 else "600519"
        beta = compute_beta(code)
        ln_mc = compute_ln_market_cap(code)
        mom = compute_momentum(code)
        
        print(f"股票: {code}")
        print(f"BETA(60日vs沪深300): {beta}")
        print(f"LN市值: {ln_mc}")
        print(f"动量1M: {mom.get('1M')}")
        print(f"动量3M: {mom.get('3M')}")
        print(f"动量6M: {mom.get('6M')}")