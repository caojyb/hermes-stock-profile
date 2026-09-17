#!/usr/bin/env python3
"""
持仓压力测试套件 v1.0

基于 IMA 风控SOP，对当前持仓运行4套压力剧本。
数据源：飞书Bitable（持仓） + market_cache.db（技术/财务）

用法：
  python3 portfolio_stress_test.py               # 压力测试当前全部持仓
  python3 portfolio_stress_test.py --codes 600519,000001  # 指定股票
  python3 portfolio_stress_test.py --json         # JSON输出
"""

import os
import sys
import json
import sqlite3
import argparse
import math
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKET_DB = "/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"


def get_db():
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_kline(code, limit=120):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT date, close, high, low, amplitude, change_pct FROM klines WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, limit)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_financial(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT roe, debt_ratio, gross_margin, net_margin, revenue_growth, profit_growth FROM financial_data WHERE code=? ORDER BY report_date DESC LIMIT 1",
        (code,),
    )
    r = cur.fetchone()
    conn.close()
    return dict(r) if r else None


def get_pe_pb(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT pe_ttm, pb_mrq FROM pe_pb_data WHERE code=? ORDER BY fetch_date DESC LIMIT 1",
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


def max_drawdown_from_klines(klines):
    """从K线数据计算最大回撤"""
    if len(klines) < 10:
        return None
    peak = klines[0]["close"]
    max_dd = 0
    for k in klines:
        price = k["close"]
        if price > peak:
            peak = price
        dd = (peak - price) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def recent_volatility(klines, days=20):
    """计算近N日波动率"""
    if len(klines) < days:
        return None
    closes = [k["close"] for k in klines[:days]]
    logs = []
    for i in range(len(closes)-1):
        if closes[i] > 0 and closes[i+1] > 0:
            logs.append(math.log(closes[i+1]/closes[i]))
    if len(logs) < 5:
        return None
    import statistics
    return statistics.stdev(logs) * math.sqrt(252)


def stress_scenario_rate_hike(stock, klines, fin, pe_pb):
    """
    压力剧本1：加息冲击
    假设加息200bp，估值压缩20%，高负债股额外受压
    """
    current_price = klines[0]["close"] if klines else 0
    pe = pe_pb.get("pe_ttm") if pe_pb else None
    debt_ratio = fin.get("debt_ratio", 50) if fin else 50
    
    # 基础冲击：估值压缩20%
    est_drop = 0.20
    # 高负债(>60%)额外-10%
    if debt_ratio > 60:
        est_drop += 0.10
    # 高PE(>40)额外-5%
    if pe and pe > 40:
        est_drop += 0.05
    
    return {
        "name": "加息冲击 (+200bp)",
        "est_drop_pct": round(est_drop * 100, 1),
        "est_price": round(current_price * (1 - est_drop), 2) if current_price else 0,
        "risk_level": "high" if est_drop > 0.30 else ("medium" if est_drop > 0.15 else "low"),
    }


def stress_scenario_geopolitical(stock, klines, fin, pe_pb):
    """
    压力剧本2：地缘冲突
    假设大盘-15%，个股跟随，关注度敏感行业额外受压
    """
    current_price = klines[0]["close"] if klines else 0
    sector = stock.get("sector", "") if stock else ""
    
    est_drop = 0.15
    # 高风险行业
    high_risk_sectors = ["军工", "半导体", "电子", "计算机"]
    if any(s in sector for s in high_risk_sectors):
        est_drop += 0.08
    
    # 历史最大回撤作为参考
    max_dd = max_drawdown_from_klines(klines[:60]) if klines else None
    if max_dd and max_dd > est_drop:
        est_drop = max(max_dd, est_drop)
    
    return {
        "name": "地缘冲突 (-15%市场)",
        "est_drop_pct": round(est_drop * 100, 1),
        "est_price": round(current_price * (1 - est_drop), 2) if current_price else 0,
        "risk_level": "high" if est_drop > 0.25 else ("medium" if est_drop > 0.15 else "low"),
    }


def stress_scenario_liquidity(stock, klines, fin, pe_pb):
    """
    压力剧本3：流动性危机
    假设换手率骤降，小市值股流动性枯竭
    """
    current_price = klines[0]["close"] if klines else 0
    vol = recent_volatility(klines, 20) if klines else None
    
    est_drop = 0.20
    # 高波动率(>50%)额外-10%
    if vol and vol > 0.50:
        est_drop += 0.10
    
    # 查看近期振幅
    if klines:
        recent_amp = sum(k["amplitude"] for k in klines[:5] if k.get("amplitude")) / 5
        if recent_amp > 8:
            est_drop += 0.05  # 高振幅股流动性更差
    
    return {
        "name": "流动性危机",
        "est_drop_pct": round(est_drop * 100, 1),
        "est_price": round(current_price * (1 - est_drop), 2) if current_price else 0,
        "risk_level": "high" if est_drop > 0.30 else ("medium" if est_drop > 0.18 else "low"),
    }


def stress_scenario_policy_shock(stock, klines, fin, pe_pb):
    """
    压力剧本4：政策突变
    对特定行业政策打击
    """
    current_price = klines[0]["close"] if klines else 0
    sector = stock.get("sector", "") if stock else ""
    name = stock.get("name", "") if stock else ""
    
    # 行业政策敏感性
    policy_sensitive = {
        "教育": 0.40, "房地产": 0.30, "游戏": 0.25, "医药": 0.20,
        "金融": 0.20, "互联网": 0.25, "新能源": 0.15,
    }
    
    est_drop = 0.10
    for kw, drop in policy_sensitive.items():
        if kw in sector or kw in name:
            est_drop = max(est_drop, drop)
            break
    
    # 亏损股（无净利润）额外受压
    profit_growth = fin.get("profit_growth") if fin else None
    if profit_growth is not None and profit_growth < -50:
        est_drop += 0.08
    
    return {
        "name": "政策突变",
        "est_drop_pct": round(est_drop * 100, 1),
        "est_price": round(current_price * (1 - est_drop), 2) if current_price else 0,
        "risk_level": "high" if est_drop > 0.30 else ("medium" if est_drop > 0.15 else "low"),
    }


def test_stock(code):
    """对单只股票运行全部压力测试"""
    klines = get_kline(code)
    if len(klines) < 20:
        return {"code": code, "error": "K线数据不足(<20天)"}
    
    fin = get_financial(code)
    pe_pb = get_pe_pb(code)
    stock = get_stock_info(code)
    
    scenarios = [
        stress_scenario_rate_hike(stock, klines, fin, pe_pb),
        stress_scenario_geopolitical(stock, klines, fin, pe_pb),
        stress_scenario_liquidity(stock, klines, fin, pe_pb),
        stress_scenario_policy_shock(stock, klines, fin, pe_pb),
    ]
    
    # 综合风险：最坏情景回撤
    worst = max(s["est_drop_pct"] for s in scenarios)
    avg = sum(s["est_drop_pct"] for s in scenarios) / len(scenarios)
    
    # 综合风险评级
    if worst > 30:
        overall_risk = "🔴 high"
    elif worst > 20:
        overall_risk = "🟡 medium"
    else:
        overall_risk = "🟢 low"
    
    return {
        "code": code,
        "name": stock.get("name", code) if stock else code,
        "sector": stock.get("sector", "") if stock else "",
        "current_price": klines[0]["close"],
        "latest_date": klines[0]["date"],
        "max_drawdown_60d": round(max_drawdown_from_klines(klines) * 100, 1) if max_drawdown_from_klines(klines) else None,
        "scenarios": scenarios,
        "worst_case_drop": worst,
        "avg_drop": round(avg, 1),
        "overall_risk": overall_risk,
    }


def read_bitable_positions():
    """
    从 Bitable 读取持仓列表
    返回 list of {"code": "600519", "name": "贵州茅台", ...}
    """
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from bitable_reader import get_holdings
        positions = get_holdings()
        return [{"code": p.get("code", "").strip(), "name": p.get("name", "")} for p in positions if p.get("code")]
    except Exception as e:
        print(f"⚠️ 无法读取Bitable持仓: {e}", file=sys.stderr)
        print("  使用 --codes 指定要测试的股票", file=sys.stderr)
        return []


def format_report(result):
    lines = []
    if "error" in result:
        return f"❌ {result['code']} — {result['error']}"
    
    lines.append(f"\n{'='*60}")
    lines.append(f"📊 持仓压力测试 — {result['name']} ({result['code']})")
    lines.append(f"{'='*60}")
    lines.append(f"行业: {result['sector']} | 现价: {result['current_price']} ({result['latest_date']})")
    lines.append(f"60日最大回撤: {result['max_drawdown_60d']}% | 综合风险: {result['overall_risk']}")
    
    lines.append(f"\n  压力剧本:")
    lines.append(f"  {'情景':25s} {'预估回撤':>10s} {'风险等级':>10s}")
    lines.append(f"  {'-'*45}")
    for s in result["scenarios"]:
        icon = {"high": "🚩", "medium": "⚠️", "low": "🟢"}[s["risk_level"]]
        lines.append(f"  {icon} {s['name']:23s} {s['est_drop_pct']:>8.1f}% {s['risk_level']:>10s}")
    
    lines.append(f"\n  最坏情景: {result['worst_case_drop']:.1f}% | 平均: {result['avg_drop']:.1f}%")
    if result['worst_case_drop'] > 25:
        lines.append(f"  ⚠️ 建议: 降低该仓位或设更紧止损")
    elif result['worst_case_drop'] > 15:
        lines.append(f"  📌 建议: 维持现有止损，关注压力情景变化")
    else:
        lines.append(f"  ✅ 建议: 风险可控，正常持有")
    
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="持仓压力测试套件 v1.0")
    parser.add_argument("--codes", type=str, help="股票代码，逗号分隔")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()
    
    codes = []
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    else:
        codes = [r["code"] for r in read_bitable_positions()]
        if not codes:
            print("⚠️ 未从Bitable读到持仓，使用测试股票", file=sys.stderr)
            codes = ["600519", "000001", "300750"]
    
    results = []
    for code in codes:
        r = test_stock(code)
        results.append(r)
    
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        for r in results:
            print(format_report(r))
