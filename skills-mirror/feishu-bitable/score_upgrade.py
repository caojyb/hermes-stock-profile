#!/usr/bin/env python3
"""
|多因子评分卡升级模块 v1.1
|
|基于动态权重评分框架（从 factor_weights.json 读取），
|默认 IMA 47:35:18，每月因子轮动自动更新。
对 double_up_screener 的现有评分系统进行升级，增加 PE/PB 估值维度和
技术面综合评分。可作为独立模块使用或替换现有评分引擎。

用法：
  python3 score_upgrade.py --code 600519                # 单只评分
  python3 score_upgrade.py --scan [--limit 100]         # 批量扫描
  python3 score_upgrade.py --compare 600519              # 新旧对比
  python3 score_upgrade.py --json                        # JSON输出
"""
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

import os
import sys
import json
import sqlite3
import argparse
import math
import statistics
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKET_DB = _STOCK_MARKET_DB
WEIGHTS_FILE = os.path.join(SCRIPT_DIR, "factor_weights.json")

# 默认权重 (IMA 5:3:2 + 翻倍基因)
DEFAULT_WEIGHTS = {"fundamental": 0.45, "valuation": 0.27, "technical": 0.18, "doubling_gene": 0.10}

# 基础分: 满分100按权重分配
FUNDAMENTAL_BASE = 45  # 基本面子项满分（调整后）
VALUATION_BASE = 27    # 估值子项满分（调整后）
TECHNICAL_BASE = 18    # 技术子项满分（调整后）
DOUBLING_BASE = 10     # 翻倍基因子项满分（新增）


def load_weights():
    """从 factor_weights.json 加载动态权重"""
    try:
        with open(WEIGHTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        gw = data.get("groups", {})
        return {
            "fundamental": gw.get("fundamental", DEFAULT_WEIGHTS["fundamental"]),
            "valuation": gw.get("valuation", DEFAULT_WEIGHTS["valuation"]),
            "technical": gw.get("technical", DEFAULT_WEIGHTS["technical"]),
            "doubling_gene": DEFAULT_WEIGHTS["doubling_gene"],  # 翻倍基因固定10%
            "source": data.get("date", "默认"),
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {**DEFAULT_WEIGHTS, "source": "默认"}


def weights_str(weights):
    """格式化权重字符串"""
    f = weights.get("fundamental", 0.5) * 100
    v = weights.get("valuation", 0.3) * 100
    t = weights.get("technical", 0.2) * 100
    return f"{f:.0f}:{v:.0f}:{t:.0f}"


def get_db():
    """获取数据库连接，带文件存在性检查"""
    if not os.path.exists(MARKET_DB):
        msg = f"🔴 CRITICAL: 数据库文件不存在! {MARKET_DB}"
        print(f"\n{'='*60}\n{msg}\n{'='*60}", file=sys.stderr)
        raise FileNotFoundError(f"数据库文件不存在: {MARKET_DB}. 所有策略已暂停，请恢复数据库后重试。")
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    return conn


# ── 数据获取 ──

def get_financial(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM financial_data WHERE code=? ORDER BY report_date DESC LIMIT 3",
        (code,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    if not rows:
        return None, None
    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    # OCF fallback to annual report
    if prev:
        for f in ["ocf_to_profit", "ocf_to_revenue", "operating_cashflow"]:
            if latest.get(f) is None and prev.get(f) is not None:
                latest[f] = prev[f]
    return latest, prev


def get_pe_pb(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT pe_ttm, pb_mrq, pe_pct, pb_pct, dividend_yield FROM pe_pb_data WHERE code=? ORDER BY fetch_date DESC LIMIT 1",
        (code,),
    )
    r = cur.fetchone()
    conn.close()
    return dict(r) if r else None


def get_indicators(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM indicators WHERE code=? ORDER BY date DESC LIMIT 1",
        (code,),
    )
    r = cur.fetchone()
    conn.close()
    return dict(r) if r else None


def get_stock_info(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, sector, is_st FROM stocks WHERE code=?", (code,))
    r = cur.fetchone()
    conn.close()
    return dict(r) if r else None


# ── 基本面50%评分（5个子项） ──

def score_roe(fin):
    """ROE质量 (15分)"""
    if not fin or fin.get("roe") is None:
        return 0, "无数据"
    roe = fin["roe"]
    if roe >= 25:
        return 15, f"ROE={roe:.1f}%≥25% ✅"
    elif roe >= 20:
        return 12, f"ROE={roe:.1f}%≥20% ✅"
    elif roe >= 15:
        return 9, f"ROE={roe:.1f}%≥15% ✅"
    elif roe >= 10:
        return 6, f"ROE={roe:.1f}%≥10% ⚠️"
    else:
        return 2, f"ROE={roe:.1f}%<10% ❌"


def score_debt(fin):
    """负债健康度 (10分)"""
    if not fin or fin.get("debt_ratio") is None:
        return 0, "无数据"
    debt = fin["debt_ratio"]
    if debt < 30:
        return 10, f"负债率={debt:.0f}%<30% ✅"
    elif debt < 50:
        return 8, f"负债率={debt:.0f}%<50% ✅"
    elif debt < 70:
        return 4, f"负债率={debt:.0f}%<70% ⚠️"
    else:
        return 0, f"负债率={debt:.0f}%≥70% ❌"


def score_growth(fin):
    """成长性 (15分)"""
    if not fin:
        return 0, "无数据"
    rev = fin.get("revenue_growth") or 0
    prof = fin.get("profit_growth") or 0
    score = 0
    reasons = []
    if rev >= 30:
        score += 8
        reasons.append(f"营收+{rev:.0f}%")
    elif rev >= 15:
        score += 5
        reasons.append(f"营收+{rev:.0f}%")
    elif rev >= 5:
        score += 3
        reasons.append(f"营收+{rev:.0f}%")
    else:
        reasons.append(f"营收{rev:+.0f}%")
    
    if prof >= 30:
        score += 7
        reasons.append(f"利润+{prof:.0f}%")
    elif prof >= 15:
        score += 5
        reasons.append(f"利润+{prof:.0f}%")
    elif prof >= 5:
        score += 3
        reasons.append(f"利润+{prof:.0f}%")
    else:
        reasons.append(f"利润{prof:+.0f}%")
    
    icon = "✅" if score >= 10 else ("⚠️" if score >= 5 else "❌")
    return score, f"{'|'.join(reasons)} {icon}"


def score_margin(fin):
    """盈利能力 (10分)"""
    if not fin:
        return 0, "无数据"
    gm = fin.get("gross_margin") or 0
    nm = fin.get("net_margin") or 0
    score = 0
    if gm >= 50:
        score += 6
    elif gm >= 30:
        score += 4
    elif gm >= 15:
        score += 2
    
    if nm >= 20:
        score += 4
    elif nm >= 10:
        score += 2
    elif nm >= 5:
        score += 1
    
    icon = "✅" if score >= 7 else ("⚠️" if score >= 4 else "❌")
    return score, f"毛利率={gm:.1f}% 净利率={nm:.1f}% {icon}"


def score_fundamental(fin, max_score=50):
    """基本面综合 (动态权重)"""
    s1, d1 = score_roe(fin)
    s2, d2 = score_debt(fin)
    s3, d3 = score_growth(fin)
    s4, d4 = score_margin(fin)
    total = s1 + s2 + s3 + s4
    # 把得分按比例缩放到动态max_score
    scaled = round(total / FUNDAMENTAL_BASE * max_score, 1)
    max_score = round(max_score, 1)
    pct = round(scaled / max_score * 100, 1) if max_score > 0 else 0
    return {
        "score": scaled,
        "max": max_score,
        "pct": pct,
        "items": {"roe": (s1, d1), "debt": (s2, d2), "growth": (s3, d3), "margin": (s4, d4)},
        "detail": f"基本面 {scaled}/{max_score} ({pct}%)"
    }


# ── 估值30%评分 ──

def score_valuation(pe_pb, max_score=30):
    """估值评分 (动态权重)"""
    if not pe_pb:
        return {"score": round(max_score * 0.2, 1), "max": max_score, "pct": 20, "detail": "无估值数据"}
    
    pe = pe_pb.get("pe_ttm")
    pb = pe_pb.get("pb_mrq")
    pe_pct = pe_pb.get("pe_pct")
    
    score = 0
    reasons = []
    
    # PE分值 (15分)
    if pe and pe > 0:
        if pe < 10:
            score += 8
            reasons.append(f"PE={pe:.0f} 偏低")
        elif pe < 20:
            score += 12
            reasons.append(f"PE={pe:.0f} 合理偏低")
        elif pe < 35:
            score += 10
            reasons.append(f"PE={pe:.0f} 合理")
        elif pe < 50:
            score += 6
            reasons.append(f"PE={pe:.0f} 偏高")
        else:
            score += 2
            reasons.append(f"PE={pe:.0f} 过高")
    
    # PE历史分位加分 (5分)
    if pe_pct is not None:
        if pe_pct < 20:
            score += 5
            reasons.append(f"PE分位{pe_pct:.0f}% 低位")
        elif pe_pct < 40:
            score += 3
            reasons.append(f"PE分位{pe_pct:.0f}% 中低")
        elif pe_pct < 60:
            score += 1
        else:
            score -= 2  # 扣分
            reasons.append(f"PE分位{pe_pct:.0f}% 高位")
    
    # PB合理性 (5分)
    if pb and pb > 0:
        if pb < 2:
            score += 4
        elif pb < 5:
            score += 3
        elif pb < 10:
            score += 2
        elif pb < 20:
            score += 1
        reasons.append(f"PB={pb:.1f}")
    
    # 股息率加分 (5分)
    div = pe_pb.get("dividend_yield")
    if div and div > 3:
        score += 5
        reasons.append(f"股息率{div:.1f}%")
    elif div and div > 1:
        score += 2
        reasons.append(f"股息率{div:.1f}%")
    
    score = min(score, VALUATION_BASE)
    # 缩放到动态max_score
    scaled = round(score / VALUATION_BASE * max_score, 1)
    max_score = round(max_score, 1)
    return {
        "score": scaled,
        "max": max_score,
        "pct": round(scaled / max_score * 100, 1) if max_score > 0 else 0,
        "detail": f"估值 {scaled}/{max_score} | {' | '.join(reasons)}"
    }


# ── 技术20%评分 ──

def score_technical(indicators, fin=None, max_score=20):
    """技术面评分 (动态权重)"""
    if not indicators:
        return {"score": round(max_score * 0.2, 1), "max": max_score, "pct": 20, "detail": "无技术数据"}
    
    score = 0
    reasons = []
    
    # RSI判断 (8分)
    rsi = indicators.get("rsi_14")
    if rsi is not None:
        if rsi < 25:
            score += 7
            reasons.append(f"RSI={rsi:.0f} 严重超卖")
        elif rsi < 35:
            score += 8
            reasons.append(f"RSI={rsi:.0f} 超卖")
        elif rsi < 45:
            score += 6
            reasons.append(f"RSI={rsi:.0f} 中低位")
        elif rsi < 60:
            score += 4
            reasons.append(f"RSI={rsi:.0f} 中性")
        elif rsi < 75:
            score += 2
            reasons.append(f"RSI={rsi:.0f} 偏高")
        else:
            score += 0
            reasons.append(f"RSI={rsi:.0f} 超买")
    
    # MACD (5分)
    macd_hist = indicators.get("macd_hist")
    if macd_hist is not None:
        if macd_hist > 0:
            score += 5
            reasons.append("MACD红柱")
        else:
            score += 1
            reasons.append("MACD绿柱")
    
    # 均线排列 (4分)
    ma_bullish = indicators.get("ma_bullish")
    if ma_bullish is not None and ma_bullish > 0:
        score += 4
        reasons.append("均线多头")
    else:
        score += 1
    
    # 布林位置 (3分)
    boll_pos = indicators.get("boll_position")
    if boll_pos is not None:
        if boll_pos < 20:
            score += 3
            reasons.append(f"布林{boll_pos:.0f}%下轨")
        elif boll_pos < 40:
            score += 2
            reasons.append(f"布林{boll_pos:.0f}%中下轨")
        elif boll_pos > 90:
            score -= 1
            reasons.append(f"布林{boll_pos:.0f}%上轨近")
    
    score = min(max(score, 0), TECHNICAL_BASE)
    # 缩放到动态max_score
    scaled = round(score / TECHNICAL_BASE * max_score, 1)
    max_score = round(max_score, 1)
    return {
        "score": scaled,
        "max": max_score,
        "pct": round(scaled / max_score * 100, 1) if max_score > 0 else 0,
        "detail": f"技术 {scaled}/{max_score} | {' | '.join(reasons)}"
    }


# ── 综合 ──

def score_doubling_gene(code, max_score=10):
    """翻倍基因评分 (0-10)
    基于5个因子：市值、PE分位、换手率、ROE、利润增速
    各因子权重与doubling_gene.py保持一致
    """
    conn = get_db()
    c = conn.cursor()
    score = 0
    items = {}

    # 1. 市值 (权重25%，满分2.5)
    c.execute("SELECT total_shares_real FROM stocks WHERE code=?", [code])
    row = c.fetchone()
    if row and row[0]:
        c.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", [code])
        pr = c.fetchone()
        if pr and pr[0]:
            cap = row[0] * pr[0] / 1e8
            if 30 <= cap <= 100:
                m = 2.5
            elif cap < 200:
                m = 1.5
            else:
                m = 0.5
            score += m
            items["市值"] = (round(m, 1), f"{cap:.1f}亿")

    # 2. PE分位 (权重20%，满分2.0)
    c.execute("SELECT pe_pct FROM pe_pb_data WHERE code=? AND pe_pct IS NOT NULL ORDER BY fetch_date DESC LIMIT 1", [code])
    row = c.fetchone()
    if row and row[0]:
        v = row[0]
        if v <= 40:
            m = 2.0
        elif v <= 60:
            m = 1.0
        else:
            m = 0.0
        score += m
        items["PE分位"] = (m, f"{v:.0f}%")

    # 3. 换手率 (权重20%，满分2.0)
    c.execute("SELECT turnover_rate FROM indicators WHERE code=? AND turnover_rate IS NOT NULL ORDER BY date DESC LIMIT 1", [code])
    row = c.fetchone()
    if row and row[0]:
        v = row[0]
        if 3 <= v <= 8:
            m = 2.0
        elif 1 <= v <= 15:
            m = 1.0
        else:
            m = 0.0
        score += m
        items["换手率"] = (m, f"{v:.1f}%")

    # 4. ROE (权重20%，满分2.0)
    c.execute("SELECT roe FROM financial_data WHERE code=? AND roe IS NOT NULL ORDER BY report_date DESC LIMIT 1", [code])
    row = c.fetchone()
    if row and row[0]:
        v = row[0]
        if v >= 15:
            m = 2.0
        elif v >= 8:
            m = 1.0
        else:
            m = 0.0
        score += m
        items["ROE"] = (m, f"{v:.1f}%")

    # 5. 利润增速 (权重15%，满分1.5)
    c.execute("SELECT profit_growth FROM financial_data WHERE code=? AND profit_growth IS NOT NULL ORDER BY report_date DESC LIMIT 1", [code])
    row = c.fetchone()
    if row and row[0]:
        v = row[0]
        if v >= 20:
            m = 1.5
        elif v >= 5:
            m = 0.8
        else:
            m = 0.0
        score += m
        items["利润增速"] = (m, f"{v:.1f}%")

    conn.close()

    return {
        "score": round(score, 1),
        "max": max_score,
        "pct": round(score / max_score * 100, 1) if max_score > 0 else 0,
        "items": items,
    }


def score_stock(code):
    """执行动态权重评分（从 factor_weights.json 读取权重）"""
    fin, prev = get_financial(code)
    pe_pb = get_pe_pb(code)
    indicators = get_indicators(code)
    info = get_stock_info(code)

    # 加载动态权重
    w = load_weights()
    fw = round(w.get("fundamental", 0.45) * 100, 1)
    vw = round(w.get("valuation", 0.27) * 100, 1)
    tw = round(w.get("technical", 0.18) * 100, 1)
    dw = round(w.get("doubling_gene", 0.10) * 100, 1)

    basic = score_fundamental(fin, max_score=fw)
    val = score_valuation(pe_pb, max_score=vw)
    tech = score_technical(indicators, fin, max_score=tw)
    dg = score_doubling_gene(code, max_score=dw)

    total = basic["score"] + val["score"] + tech["score"] + dg["score"]
    max_score = basic["max"] + val["max"] + tech["max"] + dg["max"]
    pct = round(total / max_score * 100, 1) if max_score > 0 else 0
    
    # 等级
    if pct >= 80:
        grade = "AAA"
    elif pct >= 65:
        grade = "AA"
    elif pct >= 50:
        grade = "A"
    elif pct >= 35:
        grade = "BBB"
    elif pct >= 20:
        grade = "BB"
    else:
        grade = "C"
    
    # 红旗
    red_flags = []
    if fin and fin.get("roe") and fin["roe"] < 5:
        red_flags.append("ROE极低")
    if pe_pb and pe_pb.get("pe_ttm") and pe_pb["pe_ttm"] > 80:
        red_flags.append("PE过高")
    if info and info.get("is_st"):
        red_flags.append("ST股票")
    
    return {
        "code": code,
        "name": info.get("name", code) if info else code,
        "sector": info.get("sector", "") if info else "",
        "total_score": total,
        "max_score": max_score,
        "score_pct": pct,
        "grade": grade,
        "fundamental": basic,
        "valuation": val,
        "technical": tech,
        "doubling_gene": dg,
        "red_flags": red_flags,
        "recommendation": "✅ 强烈推荐" if pct >= 80 else 
                         ("🟢 推荐" if pct >= 65 else
                          ("🟡 关注" if pct >= 50 else
                           ("🔵 观察" if pct >= 35 else "❌ 回避"))),
    }


def scan_all(limit=200):
    codes = get_db().execute("SELECT code, name FROM stocks ORDER BY code LIMIT ?", (limit,)).fetchall()
    codes = [dict(r) for r in codes]
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(score_stock, r["code"]): r for r in codes}
        for f in as_completed(futures):
            r = f.result()
            results.append(r)
    
    results.sort(key=lambda x: x["score_pct"], reverse=True)
    w = load_weights()
    return {
        "scan_time": datetime.now().isoformat(),
        "total": len(results),
        "weights": {k: v for k, v in w.items() if k != "source"},
        "weights_source": w.get("source", "默认"),
        "results": results,
        "summary": {
            "aaa": sum(1 for r in results if r["grade"] == "AAA"),
            "aa": sum(1 for r in results if r["grade"] == "AA"),
            "a": sum(1 for r in results if r["grade"] == "A"),
            "bbb": sum(1 for r in results if r["grade"] == "BBB"),
            "bb": sum(1 for r in results if r["grade"] == "BB"),
            "c": sum(1 for r in results if r["grade"] == "C"),
            "avg_score": round(statistics.mean(r["score_pct"] for r in results), 1),
        }
    }


def format_report(r, weights=None):
    lines = []
    if weights is None:
        weights = load_weights()
    ws = weights_str(weights)
    icon = {"AAA": "🟢", "AA": "🟢", "A": "🟡", "BBB": "🟡", "BB": "🔴", "C": "🔴"}.get(r["grade"], "⚪")
    lines.append(f"\n{'='*60}")
    lines.append(f"{icon} {r['code']} {r['name']} ({r['sector']})")
    lines.append(f"{'='*60}")
    lines.append(f"总分: {r['total_score']}/{r['max_score']} ({r['score_pct']}%) | 等级: {r['grade']} | 权重: {ws}")
    lines.append(f"建议: {r['recommendation']}")
    
    lines.append(f"\n  基本面 (权重{w['fundamental']*100:.0f}%): {r['fundamental']['score']}/{r['fundamental']['max']} ({r['fundamental']['pct']}%)")
    for k, (s, d) in r['fundamental']['items'].items():
        lines.append(f"    {k}: {s}分 - {d[:50]}")
    
    lines.append(f"\n  估值 (权重{w['valuation']*100:.0f}%): {r['valuation']['score']}/{r['valuation']['max']} ({r['valuation']['pct']}%)")
    lines.append(f"    {r['valuation']['detail'][:80]}")
    
    lines.append(f"\n  技术 (权重{w['technical']*100:.0f}%): {r['technical']['score']}/{r['technical']['max']} ({r['technical']['pct']}%)")
    lines.append(f"    {r['technical']['detail'][:80]}")
    
    dg = r.get('doubling_gene', {})
    lines.append(f"\n  🧬 翻倍基因 (权重{w.get('doubling_gene',0.1)*100:.0f}%): {dg.get('score',0)}/{dg.get('max',10)} ({dg.get('pct',0)}%)")
    if dg.get('items'):
        for k, (s, d) in dg['items'].items():
            lines.append(f"    {k}: {s}分 ({d})")
    
    if r["red_flags"]:
        lines.append(f"\n  🚩 红旗: {' | '.join(r['red_flags'])}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    w = load_weights()
    ws = weights_str(w)
    wsrc = w.get("source", "默认")
    parser = argparse.ArgumentParser(description=f"多因子评分卡升级模块 v1.0 — 动态权重({ws}, 来源:{wsrc})")
    parser.add_argument("--code", type=str, help="股票代码")
    parser.add_argument("--scan", action="store_true", help="批量扫描")
    parser.add_argument("--limit", type=int, default=200, help="扫描上限")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()
    
    if not args.code and not args.scan:
        parser.print_help()
        sys.exit(0)
    
    if args.code:
        r = score_stock(args.code)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        else:
            print(format_report(r))
    
    elif args.scan:
        result = scan_all(args.limit)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            s = result["summary"]
            wsrc = result.get("weights_source", "默认")
            print(f"\n{'='*60}")
            print(f"📊 动态权重评分卡 (权重:{ws}, 来源:{wsrc}) — 批量扫描报告")
            print(f"{'='*60}")
            print(f"扫描: {result['total']} 只 | 平均分: {s['avg_score']}%")
            print(f"分布: AAA={s['aaa']} AA={s['aa']} A={s['a']} BBB={s['bbb']} BB={s['bb']} C={s['c']}")
            print(f"\nTop 10:")
            for r in result["results"][:10]:
                icon = {"AAA": "🟢", "AA": "🟢", "A": "🟡", "BBB": "🟡", "BB": "🔴", "C": "🔴"}.get(r["grade"], "⚪")
                print(f"  {icon} {r['code']:6s} {r['name']:<12s} {r['score_pct']:>5.1f}% {r['grade']:>3s} | 基{r['fundamental']['score']:.0f} 估{r['valuation']['score']:.0f} 技{r['technical']['score']:.0f} 翻倍{r.get('doubling_gene',{}).get('score',0):.1f}")
