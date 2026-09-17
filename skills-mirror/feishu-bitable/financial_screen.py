#!/usr/bin/env python3
"""
财务报表勾稽关系检查引擎 v1.1

基于 IMA 知识库的 10 条勾稽关系框架。
数据来源：market_cache.db + AKShare 同花顺现金流量表

v1.1 (2026-07-22): 接入 stock_financial_cash_ths (同花顺)
  补回 ②④⑥⑦ 号 OCF 相关检查
  ⑧⑨ 仍需更明细数据（利息收入/资产减值）

用法：
  python3 financial_screen.py --code 600519
  python3 financial_screen.py --scan [--limit 100]
  python3 financial_screen.py --help
"""

import os
import sys
import json
import sqlite3
import argparse
import warnings
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak

# THS 现金流数据解析：值形如 "269.10亿" 或 "-435.44亿"
_CNUM_MAP = {"亿": 1e8, "万": 1e4, "元": 1}
def parse_cn_number(s):
    """将中文金额字符串转为 float（单位：元）"""
    if s is None:
        return None
    if isinstance(s, bool):
        return None  # THS 某些季度字段标记为 True/False（无数据）
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(",", "").strip()
    unit = 1
    for u, mul in _CNUM_MAP.items():
        if u in s:
            unit = mul
            s = s.replace(u, "")
            break
    try:
        return float(s) * unit
    except (ValueError, TypeError):
        return None

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = "/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"
DB_PATH = os.path.normpath(DB_PATH)


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def get_financial(code):
    """获取最近3期的财务数据"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM financial_data WHERE code = ? ORDER BY report_date DESC LIMIT 3",
        (code,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows if rows else None


def get_stock_info(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stocks WHERE code = ?", (code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_pe_pb(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM pe_pb_data WHERE code = ? ORDER BY fetch_date DESC LIMIT 1",
        (code,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_cash_flow(code):
    """
    从本地缓存或同花顺(THS)获取现金流量表数据
    返回关键字段（单位：元）。
    ...
    """
    # 1. 先查本地缓存
    cache = _get_cash_flow_cache(code)
    if cache:
        return cache
    
    # 2. 缓存未命中，调THS API
    try:
        df = ak.stock_financial_cash_ths(symbol=code)
        if df is None or df.empty:
            return None
        row = df.iloc[0]
        period = str(row.get("报告期", ""))
        
        raw_np = row.get("净利润")
        if isinstance(raw_np, bool):
            raw_np = None
        np = parse_cn_number(raw_np)
        np_period = period
        period_note = ""
        if np is None:
            for idx in range(1, min(len(df), 5)):
                r = df.iloc[idx]
                v = r.get("净利润")
                if not isinstance(v, bool):
                    v = parse_cn_number(v)
                    if v is not None:
                        np = v
                        np_period = str(r.get("报告期", ""))
                        period_note = f"(净利润取自{np_period})"
                        break
        
        result = {
            "ocf_net": parse_cn_number(row.get("*经营活动产生的现金流量净额")),
            "invest_net": parse_cn_number(row.get("*投资活动产生的现金流量净额")),
            "finance_net": parse_cn_number(row.get("*筹资活动产生的现金流量净额")),
            "cash_net_change": parse_cn_number(row.get("*现金及现金等价物净增加额")),
            "end_cash": parse_cn_number(row.get("*期末现金及现金等价物余额")),
            "sales_cash_received": parse_cn_number(row.get("销售商品、提供劳务收到的现金")),
            "report_date": period,
            "net_profit": np,
            "np_period": np_period,
            "period_note": period_note,
        }
        
        # 3. 写入本地缓存
        _set_cash_flow_cache(code, result)
        return result
    except Exception as e:
        warnings.warn(f"获取现金流数据失败 ({code}): {e}")
        return None


# ---- 现金流本地缓存 ----

def _get_cash_flow_cache(code):
    """从本地SQLite读取现金流缓存"""
    with _get_cache_conn() as conn:
        cur = conn.execute(
            "SELECT json_data FROM cf_cache WHERE code = ? AND fetch_date = ?",
            (code, datetime.now().strftime("%Y-%m-%d"))
        )
        row = cur.fetchone()
        if row:
            return json.loads(row[0])
    return None


def _set_cash_flow_cache(code, data):
    """写入现金流缓存到本地SQLite"""
    with _get_cache_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cf_cache (code, fetch_date, json_data) VALUES (?, ?, ?)",
            (code, datetime.now().strftime("%Y-%m-%d"), json.dumps(data, ensure_ascii=False, default=str))
        )
        conn.commit()


def _get_cache_conn():
    """获取缓存数据库连接"""
    cache_db = DB_PATH
    conn = sqlite3.connect(cache_db, timeout=60)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cf_cache (
            code TEXT,
            fetch_date TEXT,
            json_data TEXT,
            PRIMARY KEY (code, fetch_date)
        )
    """)
    conn.commit()
    return conn


def get_net_profit(code, cf):
    """从 get_cash_flow 返回的 cf 中取净利润"""
    if cf:
        return cf.get("net_profit")
    return None


def all_codes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT code, name, sector FROM stocks ORDER BY code")
    rows = cur.fetchall()
    conn.close()
    return rows


# ── 10条勾稽检查（适配可用数据）──


def check_roe(fin, prev):
    """
    ① ROE质量：近3年平均ROE≥15%且非杠杆驱动
    数据源：roe, debt_ratio
    """
    r = {"pass": False, "score": 0, "detail": "", "flags": []}
    roe = fin.get("roe")
    if roe is None:
        r["detail"] = "ROE数据缺失（非全部股票都有最新ROE）"
        r["flags"].append("data_unavailable")
        return r
    debt = fin.get("debt_ratio", 0) or 0
    if roe >= 15:
        r["pass"] = True
        r["score"] = 10
        r["detail"] = f"ROE={roe:.1f}%≥15% ✅"
        if debt > 70:
            r["flags"].append("high_leverage")
            r["detail"] += f"，但负债率{debt:.0f}%偏高，利润可能杠杆驱动"
            r["score"] = 6
    else:
        r["detail"] = f"ROE={roe:.1f}%<15% ❌"
        r["flags"].append("low_roe")
    return r


def check_cash_flow(fin, prev, cf, net_profit):
    """
    ② 现金流含金量：OCF/净利润 > 1
    数据源：stock_financial_cash_ths (同花顺)
    净利润可能来自前一报告期（Q1/Q3无补充资料）
    """
    r = {"pass": False, "score": 0, "detail": "", "flags": []}
    if not cf:
        r["detail"] = "现金流数据不可用（akshare THS 接口无响应）"
        r["flags"].append("data_unavailable")
        return r
    
    ocf = cf.get("ocf_net")
    profit = net_profit
    period_note = cf.get("period_note", "")
    
    # 回退：从 financial_data 取净利润
    if profit is None and fin:
        profit = fin.get("parent_netprofit")
    
    if ocf is None:
        r["detail"] = "经营活动现金流净额缺失 ⚠️"
        r["flags"].append("data_unavailable")
        return r
    
    if profit and profit != 0:
        ratio = abs(ocf / profit)
        pn = f" {period_note}" if period_note else ""
        if ratio > 1.2:
            r["pass"] = True
            r["score"] = 10
            r["detail"] = f"OCF/净利润={ratio:.2f} > 1，利润含金量高 ✅{pn}"
        elif ratio > 0.8:
            r["pass"] = True
            r["score"] = 6
            r["detail"] = f"OCF/净利润={ratio:.2f}，利润含金量尚可 ✅{pn}"
        elif ratio > 0.5:
            r["pass"] = True
            r["score"] = 4
            r["detail"] = f"OCF/净利润={ratio:.2f} < 0.8，利润含金量偏低 ⚠️{pn}"
        else:
            r["detail"] = f"OCF/净利润={ratio:.2f} << 0.8，利润含金量差 ❌{pn}"
            r["flags"].append("low_cash_quality")
    else:
        if ocf > 0:
            r["pass"] = True
            r["score"] = 6
            r["detail"] = f"经营活动现金流净额={ocf:.2f}元（正数） ✅"
        else:
            r["detail"] = f"经营活动现金流净额={ocf:.2f}元（负数） ❌"
            r["flags"].append("negative_ocf")
    return r


def check_debt(fin, prev):
    """
    ③ 负债健康度：资产负债率<70%
    数据源：debt_ratio
    """
    r = {"pass": False, "score": 0, "detail": "", "flags": []}
    debt = fin.get("debt_ratio")
    if debt is None:
        r["detail"] = "负债率数据缺失"
        r["flags"].append("data_unavailable")
        return r
    if debt < 70:
        r["pass"] = True
        r["score"] = 10
        r["detail"] = f"负债率={debt:.1f}%<70% ✅"
    else:
        r["detail"] = f"负债率={debt:.1f}%≥70% ❌"
        r["flags"].append("high_debt")
    return r


def check_profit_quality(fin, prev):
    """
    ④ 盈利质量（近似）：用毛利率+净利率趋势判断
    数据源：gross_margin, net_margin
    """
    r = {"pass": False, "score": 0, "detail": "", "flags": []}
    gm = fin.get("gross_margin")
    nm = fin.get("net_margin")
    if gm is not None and nm is not None:
        if gm > 30 and nm > 10:
            r["pass"] = True
            r["score"] = 8
            r["detail"] = f"毛利率={gm:.1f}%>30%, 净利率={nm:.1f}%>10% ✅（近似盈利质量良好）"
        elif gm > 20 and nm > 5:
            r["pass"] = True
            r["score"] = 5
            r["detail"] = f"毛利率={gm:.1f}%, 净利率={nm:.1f}%，行业中游 ⚠️"
        else:
            r["detail"] = f"毛利率={gm:.1f}%, 净利率={nm:.1f}%，盈利质量偏低 ❌"
            r["flags"].append("low_margin")
    else:
        r["detail"] = "毛利率/净利率数据缺失"
        r["flags"].append("data_unavailable")
    return r


def check_revenue_vs_ar(fin, prev):
    """
    ⑤ 收入vs应收：应收增幅不应超过营收增幅
    数据源：revenue_growth, receivables_turn_days (部分股票有)
    """
    r = {"pass": True, "score": 6, "detail": "", "flags": []}
    rev_growth = fin.get("revenue_growth")
    # 检查应收周转天数趋势
    if prev and prev.get("receivables_turn_days") and fin.get("receivables_turn_days"):
        prev_ar = prev["receivables_turn_days"]
        curr_ar = fin["receivables_turn_days"]
        if prev_ar > 0 and curr_ar > prev_ar * 1.3:
            r["pass"] = False
            r["score"] = 3
            r["detail"] = f"应收周转天数从{prev_ar:.1f}天升至{curr_ar:.1f}天，增幅{(curr_ar/prev_ar-1)*100:.0f}%>30% ❌"
            r["flags"].append("ar_surge")
        else:
            r["detail"] = f"应收周转天数{curr_ar:.1f}天，趋势稳定 ✅"
    else:
        if rev_growth is not None:
            r["detail"] = f"营收增速={rev_growth:.1f}%，但应收周转数据不足 ⚠️"
            r["flags"].append("insufficient_ar_data")
        else:
            r["detail"] = "营收增速/应收数据缺失"
            r["flags"].append("data_unavailable")
    return r


def check_sales_cash(fin, prev, cf):
    """
    ⑥ (新增) 销售商品现金 vs 营收收入
    比率 = 销售商品收到的现金 / 营业总收入
    正常 > 0.8
    数据源：stock_financial_cash_ths + financial_data.revenue_growth
    """
    r = {"pass": False, "score": 0, "detail": "", "flags": []}
    if not cf:
        r["detail"] = "现金流数据不可用"
        r["flags"].append("data_unavailable")
        return r
    
    sales_cash = cf.get("sales_cash_received")
    revenue = fin.get("total_revenue") if fin else None
    
    if sales_cash is None or not revenue or revenue == 0:
        # 营收绝对值不可用，用增速近似判断
        r["detail"] = f"销售商品收到现金流{sales_cash}, 但营收绝对值不可用 ⚠️"
        r["flags"].append("insufficient_data")
        r["pass"] = True if sales_cash and sales_cash > 0 else False
        r["score"] = 5 if r["pass"] else 0
        return r
    
    ratio = abs(sales_cash / revenue)
    if ratio > 1.0:
        r["pass"] = True
        r["score"] = 10
        r["detail"] = f"销售收现/营收={ratio:.2f} > 1，回款能力很强 ✅"
    elif ratio > 0.8:
        r["pass"] = True
        r["score"] = 7
        r["detail"] = f"销售收现/营收={ratio:.2f}，回款正常 ✅"
    elif ratio > 0.6:
        r["pass"] = True
        r["score"] = 4
        r["detail"] = f"销售收现/营收={ratio:.2f}，回款偏弱 ⚠️"
    else:
        r["detail"] = f"销售收现/营收={ratio:.2f} << 0.8，回款差 ❌"
        r["flags"].append("poor_collection")
    return r


def check_ocf_vs_profit(fin, prev, cf, net_profit):
    """
    ⑦ (新增) 经营现金流 vs 净利润（OCF/净利润比）
    交叉验证 check_cash_flow ②
    """
    r = {"pass": False, "score": 0, "detail": "", "flags": []}
    if not cf:
        r["detail"] = "现金流数据不可用"
        r["flags"].append("data_unavailable")
        return r
    
    ocf = cf.get("ocf_net")
    profit = net_profit
    pn = cf.get("period_note", "")
    
    if ocf is None:
        r["detail"] = "OCF缺失 ⚠️"
        r["flags"].append("data_unavailable")
        return r
    
    if profit and profit != 0:
        ratio = ocf / profit
        npn = f" {pn}" if pn else ""
        if ratio > 0:
            r["pass"] = True
            r["score"] = 6
            r["detail"] = f"OCF/净利润={ratio:.2f}（正数） ✅{npn}"
        else:
            r["detail"] = f"OCF/净利润={ratio:.2f}（负数） ❌{npn}"
            r["flags"].append("ocf_profit_divergence")
    else:
        r["detail"] = f"OCF={ocf}，但净利润数据缺失 ⚠️"
        r["flags"].append("insufficient_data")
    return r


def check_cash_interest(fin, prev, cf):
    """
    ⑧ 货币资金vs利息收入（存贷双高检测）
    数据不可用（需现金流量表明细）
    """
    r = {"pass": None, "score": 0, "detail": "数据不可用：需现金流量表明细 + 利息收入数据", "flags": ["data_unavailable"]}
    return r


def check_asset_impairment(fin, prev):
    """
    ⑨ 资产减值趋势
    数据不可用（需资产减值损失数据）
    """
    r = {"pass": None, "score": 0, "detail": "数据不可用：需资产减值损失/信用减值损失数据", "flags": ["data_unavailable"]}
    return r


def check_governance(fin, prev, stock):
    """
    ⑩ 公司治理：检查ST状态
    数据源：stocks.is_st
    """
    r = {"pass": True, "score": 10, "detail": "", "flags": []}
    if stock and stock.get("is_st"):
        r["pass"] = False
        r["score"] = 0
        r["detail"] = "ST/*ST股票 ❌"
        r["flags"].append("st_stock")
    else:
        r["detail"] = "非ST/非*ST ✅"
    return r


# ── 主流程 ──


def check_stock(code, name=""):
    """对单只股票执行全部可用检查"""
    rows = get_financial(code)
    fin = rows[0] if rows else None
    prev = rows[1] if rows and len(rows) > 1 else None
    stock = get_stock_info(code)
    pe_pb = get_pe_pb(code)
    
    # 获取现金流数据（v1.1 新增）
    cf = get_cash_flow(code)
    np = get_net_profit(code, cf)

    if not fin:
        return {
            "code": code,
            "name": name or "",
            "error": "无财务数据（可能未上市/退市/数据获取失败）",
            "total_score": 0,
            "max_score": 100,
            "checks": {},
        }

    checks = {
        "roe_quality": check_roe(fin, prev),
        "cash_flow_quality": check_cash_flow(fin, prev, cf, np),
        "debt_health": check_debt(fin, prev),
        "profit_quality": check_profit_quality(fin, prev),
        "revenue_vs_ar": check_revenue_vs_ar(fin, prev),
        "sales_cash_ratio": check_sales_cash(fin, prev, cf),
        "ocf_vs_profit": check_ocf_vs_profit(fin, prev, cf, np),
        "cash_interest": check_cash_interest(fin, prev, cf),
        "asset_impairment": check_asset_impairment(fin, prev),
        "governance": check_governance(fin, prev, stock),
    }

    total = sum(c["score"] for c in checks.values())

    # 有效得分基数 = 所有非「数据不可用」检查的满分之和
    available_max = sum(
        10 for c in checks.values()
        if "data_unavailable" not in c.get("flags", [])
    )

    all_flags = []
    for c in checks.values():
        all_flags.extend(c.get("flags", []))

    # 评级（基于可用检查的得分率）
    if available_max > 0:
        pct = total / available_max * 100
    else:
        pct = 0

    if pct >= 85:
        rating = "AAA"
    elif pct >= 75:
        rating = "AA"
    elif pct >= 65:
        rating = "A"
    elif pct >= 55:
        rating = "BBB"
    elif pct >= 45:
        rating = "BB"
    else:
        rating = "C"

    red_flags = [
        c["detail"] for c in checks.values()
        if not c["pass"] and c["score"] < 5 and "data_unavailable" not in c.get("flags", [])
    ]
    warnings = [
        c["detail"] for c in checks.values()
        if not c["pass"] and c["score"] >= 5 and "data_unavailable" not in c.get("flags", [])
    ]
    skipped = [
        c["detail"] for c in checks.values()
        if "data_unavailable" in c.get("flags", [])
    ]

    fs = fin or {}
    return {
        "code": code,
        "name": name or (stock.get("name", "") if stock else ""),
        "total_score": total,
        "available_max": available_max,
        "score_pct": round(pct, 1),
        "rating": rating,
        "checks": {k: {"pass": v["pass"], "score": v["score"], "detail": v["detail"]} for k, v in checks.items()},
        "red_flags": red_flags,
        "warnings": warnings,
        "skipped": skipped,
        "data_unavailable_count": len(skipped),
        "financial_summary": {
            "roe": fs.get("roe"),
            "debt_ratio": fs.get("debt_ratio"),
            "gross_margin": fs.get("gross_margin"),
            "net_margin": fs.get("net_margin"),
            "revenue_growth": fs.get("revenue_growth"),
            "profit_growth": fs.get("profit_growth"),
            "current_ratio": fs.get("current_ratio"),
            "quick_ratio": fs.get("quick_ratio"),
            "pe_ttm": pe_pb.get("pe_ttm") if pe_pb else None,
            "pb_mrq": pe_pb.get("pb_mrq") if pe_pb else None,
        },
    }


def format_report(result, verbose=False):
    """输出可读报告"""
    lines = []
    if "error" in result:
        lines.append(f"❌ {result.get('code')} {result.get('name')} — {result['error']}")
        return "\n".join(lines)

    rating_colors = {"AAA": "🟢", "AA": "🟢", "A": "🟡", "BBB": "🟡", "BB": "🔴", "C": "🔴"}
    color = rating_colors.get(result["rating"], "⚪")
    fs = result["financial_summary"]

    lines.append(f"\n{'='*50}")
    lines.append(f"{color} {result['code']} {result['name']}")
    lines.append(f"   得分: {result['total_score']}/{result['available_max']} ({result['score_pct']}%) | 评级: {result['rating']}")
    lines.append(f"   不可用检查项: {result['data_unavailable_count']}/10（数据源限制，不影响评级）")
    if fs.get("roe") is not None and fs.get("debt_ratio") is not None:
        lines.append(f"   关键指标: ROE={fs['roe']:.1f}% | 负债率={fs['debt_ratio']:.0f}% | 毛利率={fs['gross_margin']:.1f}%")
    if fs.get("revenue_growth") is not None:
        lines.append(f"   营收增速={fs['revenue_growth']:.1f}% | 利润增速={fs.get('profit_growth','N/A')}%")

    if result["red_flags"]:
        lines.append(f"\n   🚩 红旗警告:")
        for f in result["red_flags"]:
            lines.append(f"     ❌ {f}")
    if result["warnings"]:
        lines.append(f"\n   ⚠️ 提醒:")
        for w in result["warnings"]:
            lines.append(f"     ⚠️ {w}")
    if result["skipped"] and verbose:
        lines.append(f"\n   ⏭️ 跳过（数据不可用）:")
        for s in result["skipped"]:
            lines.append(f"     → {s[:90]}...")

    if verbose:
        lines.append(f"\n   明细:")
        for name, check in result["checks"].items():
            if check["pass"] is None:
                icon = "⏭️"
            elif check["pass"]:
                icon = "✅"
            else:
                icon = "❌"
            lines.append(f"     {icon} {name}: {check['score']}分 - {check['detail'][:80]}")

    return "\n".join(lines)


def scan_all(limit=500):
    """全市场批量扫描"""
    codes = all_codes()
    print(f"扫描全市场共 {len(codes)} 只股票，限制 {limit} 只...", file=sys.stderr)

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(check_stock, r["code"], r["name"]): r for r in codes[:limit]}
        for i, f in enumerate(as_completed(futures), 1):
            r = f.result()
            results.append(r)
            if i % 50 == 0:
                print(f"  进度: {i}/{min(limit, len(codes))}", file=sys.stderr)

    results.sort(key=lambda x: x.get("score_pct", 0), reverse=True)

    ratings = {}
    for r in results:
        rt = r.get("rating", "N/A")
        ratings[rt] = ratings.get(rt, 0) + 1

    output = {
        "scan_time": datetime.now().isoformat(),
        "total_scanned": len(results),
        "rating_distribution": ratings,
        "results": results,
    }
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="财务报表勾稽关系检查引擎 v1.0")
    parser.add_argument("--code", type=str, help="股票代码，如 600519")
    parser.add_argument("--scan", action="store_true", help="全市场批量扫描")
    parser.add_argument("--limit", type=int, default=500, help="扫描上限")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()

    if not args.code and not args.scan:
        parser.print_help()
        sys.exit(0)

    if args.code:
        result = check_stock(args.code)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print(format_report(result, args.verbose))

    elif args.scan:
        result = scan_all(args.limit)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            ratings = result["rating_distribution"]
            print(f"\n{'='*60}")
            print(f"全市场财报扫描报告 ({result['scan_time']})")
            print(f"{'='*60}")
            print(f"扫描总数: {result['total_scanned']}")
            print(f"评级分布:")
            for rt in ["AAA", "AA", "A", "BBB", "BB", "C"]:
                cnt = ratings.get(rt, 0)
                bar = "█" * (cnt // 5)
                print(f"  {rt}: {cnt:4d} {bar}")
