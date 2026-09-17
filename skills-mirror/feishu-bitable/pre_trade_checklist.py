#!/usr/bin/env python3
"""
开仓前检查清单 v1.0

基于 IMA 风控SOP，在买入前执行标准化检查。
用法：
  python3 pre_trade_checklist.py --code 600519     # 检查单只股票
  python3 pre_trade_checklist.py --code 600519 --price 188.50  # 指定入场价
  python3 pre_trade_checklist.py --scan            # 扫描持仓看是否需调整
"""
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

import os, sys, json, sqlite3, argparse, math, statistics
from datetime import datetime, date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKET_DB = _STOCK_MARKET_DB


def get_db():
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    return conn


# ── 检查项 ──

def check_data_freshness(code):
    """① 数据新鲜度：K线是否在5个交易日内"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT MAX(date) as last FROM klines WHERE code=?", (code,))
    r = cur.fetchone()
    conn.close()
    if not r or not r["last"]:
        return {"pass": False, "detail": "无K线数据", "score": 0}
    days_ago = (date.today() - datetime.strptime(r["last"], "%Y-%m-%d").date()).days
    if days_ago <= 5:
        return {"pass": True, "detail": f"最新K线: {r['last']} ({days_ago}天前) ✅", "score": 10}
    elif days_ago <= 10:
        return {"pass": True, "detail": f"最新K线: {r['last']} ({days_ago}天前) ⚠️", "score": 6}
    else:
        return {"pass": False, "detail": f"最新K线: {r['last']} ({days_ago}天前) ❌ 数据过期", "score": 0}


def check_financial_health(code):
    """② 财务健康：ROE、负债率、营收增速"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT roe, debt_ratio, revenue_growth FROM financial_data WHERE code=? ORDER BY report_date DESC LIMIT 1",
        (code,),
    )
    r = cur.fetchone()
    conn.close()
    if not r:
        return None, {"pass": None, "detail": "无财务数据", "score": 0}
    
    score = 0
    issues = []
    if r["roe"] and r["roe"] >= 15:
        score += 5
    else:
        issues.append(f"ROE={r['roe']}")
    if r["debt_ratio"] and r["debt_ratio"] < 60:
        score += 3
    else:
        issues.append(f"负债率={r['debt_ratio']}")
    if r["revenue_growth"] and r["revenue_growth"] > 5:
        score += 2
    else:
        issues.append(f"营收增速={r['revenue_growth']}")
    
    return r, {
        "pass": score >= 7,
        "detail": f"ROE={r['roe']}% | 负债率={r['debt_ratio']}% | 营收增速={r['revenue_growth']}% " + ("✅" if score >= 7 else "⚠️ 有红旗"),
        "score": score,
        "issues": issues,
    }


def check_valuation(code):
    """③ 估值水位：PE/PB分位"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT pe_ttm, pb_mrq, pe_pct, pb_pct FROM pe_pb_data WHERE code=? ORDER BY fetch_date DESC LIMIT 1",
        (code,),
    )
    r = cur.fetchone()
    conn.close()
    if not r:
        return {"pass": None, "detail": "无估值数据", "score": 0}
    
    pe_pct = r["pe_pct"]
    pb_pct = r["pb_pct"]
    if pe_pct is None and pb_pct is None:
        return {"pass": None, "detail": f"PE={r['pe_ttm']} PB={r['pb_mrq']} (无分位数据)", "score": 5}
    
    score = 0
    if pe_pct is not None:
        if pe_pct < 30:
            score += 6
        elif pe_pct < 50:
            score += 4
        elif pe_pct < 70:
            score += 2
    if pb_pct is not None:
        if pb_pct < 30:
            score += 4
        elif pb_pct < 50:
            score += 2
    
    is_overvalued = (pe_pct is not None and pe_pct > 80) or (pb_pct is not None and pb_pct > 80)
    
    return {
        "pass": not is_overvalued,
        "detail": f"PE分位={pe_pct}% PB分位={pb_pct}% " + ("❌ 估值过高" if is_overvalued else "✅"),
        "score": score,
    }


def check_technical_setup(code):
    """④ 技术面入场点：RSI、均线、布林"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT date, current_price, rsi_14, boll_middle, boll_lower, boll_upper "
        "FROM indicators WHERE code=? ORDER BY date DESC LIMIT 1",
        (code,),
    )
    r = cur.fetchone()
    conn.close()
    if not r:
        return {"pass": None, "detail": "无技术指标数据", "score": 0}
    
    score = 0
    issues = []
    rsi = r["rsi_14"]
    close = r["current_price"]
    boll_lower = r["boll_lower"]
    
    if rsi is not None:
        if rsi < 30:
            score += 5
        elif rsi < 45:
            score += 3
        elif rsi < 60:
            score += 1
        else:
            issues.append(f"RSI={rsi:.0f} 偏高")
    
    if boll_lower and close and close <= boll_lower * 1.03:
        score += 3
    elif boll_lower and close and close <= boll_lower * 1.1:
        score += 1
    
    # Calculate boll_position
    if boll_lower and r["boll_upper"] and r["boll_upper"] > boll_lower:
        boll_pos = f"{(close-boll_lower)/(r['boll_upper']-boll_lower)*100:.0f}%"
    else:
        boll_pos = "N/A"
    
    return {
        "pass": score >= 4,
        "detail": f"RSI={rsi} | 布林位置={boll_pos} " + ("✅" if score >= 4 else "⚠️"),
        "score": score,
        "issues": issues if issues else None,
    }


def check_sentiment(code):
    """⑤ 情绪温度（简易版）：近期涨跌幅"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT change_pct, amplitude FROM klines WHERE code=? ORDER BY date DESC LIMIT 5",
        (code,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    if len(rows) < 3:
        return {"pass": None, "detail": "数据不足", "score": 0}
    
    avg_change = sum(r["change_pct"] for r in rows if r["change_pct"]) / len(rows)
    avg_amp = sum(r["amplitude"] for r in rows if r["amplitude"]) / len(rows)
    
    score = 5
    if avg_change < -3:
        score -= 2  # 过度恐慌
    elif avg_change > 5:
        score -= 2  # 短期过热
    if avg_amp > 6:
        score -= 1  # 波动过大
    
    return {
        "pass": score >= 3,
        "detail": f"5日平均涨跌幅={avg_change:.1f}% | 平均振幅={avg_amp:.1f}% " + ("✅" if score >= 3 else "⚠️"),
        "score": score,
    }


def check(code, entry_price=None):
    """执行完整开仓前检查"""
    fin_data, fin_check = check_financial_health(code)
    checks = {
        "data_freshness": check_data_freshness(code),
        "financial_health": fin_check,
        "valuation": check_valuation(code),
        "technical_setup": check_technical_setup(code),
        "sentiment": check_sentiment(code),
    }
    
    total = sum(c["score"] for c in checks.values())
    max_score = 40
    pct = total / max_score * 100
    
    # 红牌：只包括没通过且非「无数据」的检查
    red_flags = [c["detail"] for c in checks.values() if c["pass"] is False]
    
    # 获取基本信息
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, sector, is_st FROM stocks WHERE code=?", (code,))
    info = cur.fetchone()
    cur.execute("SELECT pe_ttm, pb_mrq FROM pe_pb_data WHERE code=? ORDER BY fetch_date DESC LIMIT 1", (code,))
    pe_pb = cur.fetchone()
    cur.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
    price_row = cur.fetchone()
    conn.close()
    
    current_price = entry_price or (price_row["close"] if price_row else None)
    
    return {
        "code": code,
        "name": info["name"] if info else code,
        "sector": info["sector"] if info else "",
        "is_st": bool(info["is_st"]) if info else False,
        "current_price": current_price,
        "total_score": total,
        "max_score": max_score,
        "score_pct": round(pct, 1),
        "checks": checks,
        "red_flags": red_flags,
        "verdict": "✅ 可以开仓" if (pct >= 60 and not red_flags) else ("⚠️ 谨慎开仓" if pct >= 40 else "❌ 不建议开仓"),
        "summary": {
            "roe": fin_data["roe"] if fin_data else None,
            "debt_ratio": fin_data["debt_ratio"] if fin_data else None,
            "pe_ttm": pe_pb["pe_ttm"] if pe_pb else None,
            "pb_mrq": pe_pb["pb_mrq"] if pe_pb else None,
        },
    }


def format_report(result):
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"{'📋 开仓前检查清单':60s}")
    lines.append(f"{'='*60}")
    lines.append(f"{result['code']} {result['name']} ({result['sector']})")
    lines.append(f"现价: {result['current_price']} | 综合得分: {result['total_score']}/{result['max_score']} ({result['score_pct']}%)")
    if result["is_st"]:
        lines.append(f"❌ ST/*ST — 一票否决")
    
    lines.append(f"\n  {'检查项':25s} {'得分':>5s} {'结果':>40s}")
    lines.append(f"  {'-'*70}")
    for name, c in result["checks"].items():
        icon = "✅" if c["pass"] else ("❌" if c["pass"] is False else "⏭️")
        lines.append(f"  {icon} {name:22s} {c['score']:3d}/10 {c['detail'][:45]}")
    
    if result["red_flags"]:
        lines.append(f"\n  🚩 红旗:")
        for f in result["red_flags"]:
            lines.append(f"    ❌ {f[:70]}")
    
    lines.append(f"\n  📌 结论: {result['verdict']}")
    
    if result["score_pct"] < 60:
        if result["score_pct"] < 40:
            lines.append(f"  💡 建议: 等待更好的入场点。关注RSI<30时机")
        else:
            lines.append(f"  💡 建议: 可轻仓试探，严格止损。等条件改善再加仓")
    else:
        lines.append(f"  💡 建议: 符合开仓标准，设置好止损后入场")
    
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="开仓前检查清单 v1.0")
    parser.add_argument("--code", type=str, required=True, help="股票代码")
    parser.add_argument("--price", type=float, help="计划入场价")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()
    
    result = check(args.code, args.price)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_report(result))
