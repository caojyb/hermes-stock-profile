#!/usr/bin/env python3
"""
翻倍潜力三层过滤器 v3.0 — 分层放宽版
"""
from core.compat_paths import MARKET_DB as _DB_PATH
MARKET_DB = _DB_PATH

import os, sys, sqlite3
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
conn = sqlite3.connect(str(MARKET_DB))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=" * 70)
print("🔍 翻倍潜力三层过滤器 v3.0 — 分层放宽")
print("=" * 70)

# ── 数据准备 ──
cur.execute('SELECT code, name, sector, is_st, list_date FROM stocks')
stocks_info = {r['code']: dict(r) for r in cur.fetchall()}

cur.execute('SELECT code, close FROM (SELECT code, close, ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) as rn FROM klines) WHERE rn=1')
latest_prices = {r['code']: r['close'] for r in cur.fetchall()}

cur.execute("SELECT code, pe_ttm, pe_pct FROM pe_pb_data WHERE (code, fetch_date) IN (SELECT code, MAX(fetch_date) FROM pe_pb_data WHERE pe_pct IS NOT NULL GROUP BY code)")
pe_data = {r['code']: dict(r) for r in cur.fetchall()}

cur.execute('SELECT code, turnover_rate FROM indicators WHERE turnover_rate IS NOT NULL')
turnover_data = {r['code']: r['turnover_rate'] for r in cur.fetchall()}

cur.execute("SELECT code, date, close FROM klines WHERE date >= ? ORDER BY code, date", ((date.today()-timedelta(days=400)).isoformat(),))
kline_data = defaultdict(list)
for r in cur.fetchall():
    kline_data[r['code']].append(r['close'])

# 财务数据
cur.execute("""
    WITH ranked AS (
        SELECT code, report_date, revenue_growth, profit_growth, gross_margin, debt_ratio, roe, eps,
               ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) as rn
        FROM financial_data WHERE report_date IS NOT NULL
    )
    SELECT r1.code, r1.report_date as rd, 
           r1.revenue_growth as rev1, r2.revenue_growth as rev2,
           r1.profit_growth as pg1, r1.gross_margin as gm1, r2.gross_margin as gm2,
           r1.debt_ratio as dr1, r1.roe as roe1, r1.eps as eps1
    FROM ranked r1 JOIN ranked r2 ON r1.code = r2.code AND r2.rn = 2
    WHERE r1.rn = 1
""")
fin_data = {r['code']: dict(r) for r in cur.fetchall()}

def estimate_mcap(code, price):
    if price <= 0: return 0
    return price * 50000000 / 100000000

def basic_filter(code, rev_min=30, pg_min=20, dr_max=65, mcap_min=30, mcap_max=200, tr_min=3, dd_min=15, dd_max=45):
    """通用筛选器，返回 (通过, 原因)"""
    sinfo = stocks_info.get(code)
    if not sinfo: return False, '无股票信息'
    if sinfo.get('is_st', 0) == 1: return False, 'ST'
    if any(sinfo.get('name','').startswith(p) for p in ('ST','*ST','S','退')): return False, 'ST'
    list_date = sinfo.get('list_date')
    if list_date:
        try:
            if (date.today() - __import__('datetime').datetime.strptime(list_date, '%Y-%m-%d').date()).days < 180: return False, '上市不满180天'
        except: pass
    
    fin = fin_data.get(code)
    if not fin: return False, '无财务数据'
    rev1, rev2 = fin['rev1'], fin['rev2']
    pg1 = fin['pg1']
    dr1 = fin['dr1']
    if rev1 is None or rev2 is None or rev1 < rev_min or rev2 < rev_min: return False, f'营收增速<{rev_min}%'
    if pg1 is None or pg1 < pg_min: return False, f'利润增速<{pg_min}%'
    if dr1 is None or dr1 >= dr_max: return False, f'负债率>{dr_max}%'
    
    price = latest_prices.get(code)
    if not price or price <= 0: return False, '无价格'
    mcap = estimate_mcap(code, price)
    if mcap < mcap_min or mcap > mcap_max: return False, f'市值不在{mcap_min}-{mcap_max}亿'
    
    pe = pe_data.get(code)
    if pe:
        pe_pct = pe.get('pe_pct')
        if pe_pct is not None and pe_pct >= 40: return False, 'PE分位>=40%'
    
    tr = turnover_data.get(code)
    if tr is not None and tr < tr_min: return False, f'换手率<{tr_min}%'
    
    klines = kline_data.get(code, [])
    if len(klines) < 250: return False, 'K线不足'
    max_p = max(klines[-250:])
    cur_p = klines[-1]
    dd = (max_p - cur_p) / max_p * 100 if max_p > 0 else 0
    if dd < dd_min or dd > dd_max: return False, f'回撤不在{dd_min}-{dd_max}%'
    
    return True, f'通过'

def run_tier(label, rev_min, pg_min, dr_max, mcap_min, mcap_max, tr_min, dd_min, dd_max):
    """运行一个版本"""
    results = []
    for code in list(fin_data.keys())[:]:
        ok, reason = basic_filter(code, rev_min, pg_min, dr_max, mcap_min, mcap_max, tr_min, dd_min, dd_max)
        if ok:
            fin = fin_data[code]
            price = latest_prices.get(code, 0)
            mcap = estimate_mcap(code, price)
            klines = kline_data.get(code, [])
            max_p = max(klines[-250:]) if len(klines) >= 250 else 0
            cur_p = klines[-1] if klines else 0
            dd = (max_p - cur_p) / max_p * 100 if max_p > 0 else 0
            tr = turnover_data.get(code, 0) or 0
            pe = pe_data.get(code, {})
            pe_pct = pe.get('pe_pct', 'N/A')
            
            results.append({
                'code': code, 'name': stocks_info[code]['name'] if code in stocks_info else code,
                'sector': stocks_info[code]['sector'] if code in stocks_info else '',
                'mcap': round(mcap, 1), 'rev_growth': round(fin['rev1'], 1),
                'profit_growth': round(fin['pg1'], 1), 'debt_ratio': round(fin['dr1'], 1),
                'pe_pct': round(pe_pct, 1) if isinstance(pe_pct, float) else pe_pct,
                'turnover': round(tr, 2), 'drawdown': round(dd, 1),
            })
    return results

# 跑三个版本
print("\n" + "=" * 70)
strict = run_tier('严格版', 30, 20, 65, 30, 200, 3, 15, 45)
moderate = run_tier('适度放宽版', 30, 0, 65, 30, 200, 3, 15, 45)
flexible = run_tier('灵活版', 30, 0, 65, 20, 200, 1, 15, 45)

# 排除已在上层出现的
strict_codes = {s['code'] for s in strict}
moderate_new = [s for s in moderate if s['code'] not in strict_codes]
flexible_new = [s for s in flexible if s['code'] not in strict_codes.union({s['code'] for s in moderate})]

# 输出
print(f"\n{'='*70}")
print(f"📊 版本对比")
print(f"{'='*70}")

versions = [
    ('严格版', strict, '利润增速>20%, 换手率>3%, 市值30-200亿'),
    ('适度放宽版', moderate_new, '利润增速>0%, 其他不变'),
    ('灵活版', flexible_new, '利润增速>0%, 换手率>1%, 市值20-200亿'),
]

for label, stocks, desc in versions:
    print(f"\n{'─'*70}")
    print(f"📌 {label}（{desc}）")
    print(f"   数量: {len(stocks)} 只")
    if stocks:
        print(f"{'代码':<8} {'名称':<12} {'行业':<10} {'市值':<6} {'营收%':<8} {'利润%':<8} {'PE分位':<7} {'换手':<6} {'回撤%':<6}")
        print("-" * 70)
        for s in stocks:
            print(f"{s['code']:<8} {s['name']:<12} {s['sector'][:8]:<10} {s['mcap']:<6.1f} {s['rev_growth']:<8.1f} {s['profit_growth']:<8.1f} {str(s['pe_pct']):<7} {s['turnover']:<6.2f} {s['drawdown']:<6.1f}")
        
        # 利润增速分布
        pgs = [s['profit_growth'] for s in stocks]
        micro = len([p for p in pgs if 0 <= p < 5])
        low = len([p for p in pgs if 5 <= p < 20])
        med = len([p for p in pgs if 20 <= p < 100])
        high = len([p for p in pgs if p >= 100])
        print(f"   利润增速分布: 0-5%={micro}只, 5-20%={low}只, 20-100%={med}只, >100%={high}只")
        if micro > 0:
            print(f"   ⚠️ 其中{micro}只利润增速在0-5%微利区间，质量偏低")
    else:
        print("   无新增标的")

print(f"\n{'='*70}")
print("📈 3只候选股基数分析")
print(f"{'='*70}")

for code, name in [('603991','领先股份'), ('688353','华盛锂电'), ('002192','融捷股份')]:
    cur.execute("""
        SELECT report_date, revenue_growth, profit_growth, eps, net_margin, roe, gross_margin
        FROM financial_data WHERE code = ? AND report_date IS NOT NULL
        ORDER BY report_date DESC LIMIT 4
    """, (code,))
    rows = cur.fetchall()
    print(f"\n{code} {name}:")
    for r in rows:
        sign = '⚠️' if r['eps'] and r['eps'] < 0 else '✅' if r['eps'] and r['eps'] > 0 else '❓'
        print(f"  {r['report_date']:<12} {sign} 营收增速{r['revenue_growth'] or 0:>8.1f}% 利润增速{r['profit_growth'] or 0:>8.1f}% EPS={r['eps'] or 0:.4f} 净利率{r['net_margin'] or 0:.1f}%")
    
    # 判断基数
    eps_vals = [r['eps'] or 0 for r in rows]
    latest_eps = eps_vals[0] if eps_vals else 0
    base_eps = eps_vals[-1] if len(eps_vals) >= 4 else (eps_vals[-1] if eps_vals else 0)
    
    print(f"  最新EPS={latest_eps:.4f}, 去年同期EPS={base_eps:.4f}")
    if base_eps <= 0 and latest_eps > 0:
        print(f"  → 判断: 扭亏为盈型（去年亏损基数），利润增速高但不可持续")
    elif base_eps > 0 and latest_eps / base_eps > 5:
        print(f"  → 判断: 低基数暴增型（去年EPS={base_eps:.4f}→今年{latest_eps:.4f}），需确认是否可持续")
    else:
        print(f"  → 判断: 正常增长型")

conn.close()
print(f"\n✅ 完成")