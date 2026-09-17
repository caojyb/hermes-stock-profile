#!/usr/bin/env python3
"""
行业筛选自动化 v1.0

基于 IMA 行业研究方法论（华泰三因子 + 招商预期共振），
用 market_cache.db 数据对 A 股行业进行综合评分和排名。

数据源：market_cache.db (stocks, klines, indicators, financial_data, pe_pb_data)
输出：行业评分排名 + 推荐关注方向

用法：
  python3 industry_screener.py                  # 默认输出
  python3 industry_screener.py --top 10          # 前10个行业
  python3 industry_screener.py --level sw        # 申万一级行业
  python3 industry_screener.py --json            # JSON输出
"""
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

import os
import sys
import json
import sqlite3
import argparse
import math
import statistics
from datetime import datetime, timedelta
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKET_DB = _STOCK_MARKET_DB


def get_db():
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    return conn


def calc_momentum(code, days=20):
    """
    计算个股N日动量（N日涨跌幅）
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, days)
    )
    rows = [r["close"] for r in cur.fetchall() if r["close"]]
    conn.close()
    if len(rows) < days:
        return None
    return (rows[0] - rows[-1]) / rows[-1] * 100  # 百分比


def get_sector_info(sector_col="sector"):
    """获取行业列表及成分股"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT {sector_col} AS sector, code, name FROM stocks WHERE {sector_col} IS NOT NULL AND {sector_col} != ''")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    
    # 按行业分组
    sectors = defaultdict(list)
    for r in rows:
        sectors[r["sector"]].append({"code": r["code"], "name": r["name"]})
    return dict(sectors)


def sector_momentum(sector, stocks):
    """行业动量因子：成分股平均涨跌幅"""
    changes = []
    for s in stocks[:30]:  # 每行业取前30只计算
        mom = calc_momentum(s["code"], 20)
        if mom is not None:
            changes.append(mom)
    if not changes:
        return None
    return {
        "avg_momentum_20d": round(statistics.mean(changes), 2),
        "median_momentum_20d": round(statistics.median(changes), 2),
        "positive_ratio": round(sum(1 for c in changes if c > 0) / len(changes) * 100, 1),
        "sample_count": len(changes),
    }


def sector_valuation(sector, stocks):
    """行业估值因子：PE/PB中位数"""
    pes = []
    pbs = []
    conn = get_db()
    cur = conn.cursor()
    for s in stocks[:50]:
        cur.execute(
            "SELECT pe_ttm, pb_mrq FROM pe_pb_data WHERE code=? ORDER BY fetch_date DESC LIMIT 1",
            (s["code"],)
        )
        r = cur.fetchone()
        if r and r["pe_ttm"] and r["pe_ttm"] > 0:
            pes.append(r["pe_ttm"])
        if r and r["pb_mrq"] and r["pb_mrq"] > 0:
            pbs.append(r["pb_mrq"])
    conn.close()
    
    return {
        "pe_median": round(statistics.median(pes), 2) if pes else None,
        "pb_median": round(statistics.median(pbs), 2) if pbs else None,
        "pe_sample": len(pes),
    }


def sector_financial(sector, stocks):
    """行业财务因子：ROE/负债率中位数"""
    roes = []
    debts = []
    conn = get_db()
    cur = conn.cursor()
    for s in stocks[:50]:
        cur.execute(
            "SELECT roe, debt_ratio FROM financial_data WHERE code=? ORDER BY report_date DESC LIMIT 1",
            (s["code"],)
        )
        r = cur.fetchone()
        if r and r["roe"] and r["roe"] > 0:
            roes.append(r["roe"])
        if r and r["debt_ratio"] is not None:
            debts.append(r["debt_ratio"])
    conn.close()
    
    return {
        "roe_median": round(statistics.median(roes), 2) if roes else None,
        "debt_median": round(statistics.median(debts), 2) if debts else None,
        "roe_sample": len(roes),
    }


def score_sector(sector, stocks):
    """
    对单个行业综合评分
    
    三因子评分框架（华泰）：
    - 估值因子（30%）：PE分位低得分高
    - 动量因子（40%）：近1月涨幅高得分高
    - 财务因子（30%）：ROE高得分高
    """
    size = len(stocks)
    mom = sector_momentum(sector, stocks)
    val = sector_valuation(sector, stocks)
    fin = sector_financial(sector, stocks)
    
    if not mom or mom["sample_count"] < 5:
        return None
    
    # 评分（各因子0-100）
    # 动量得分：正收益占比越高越好
    mom_score = min(mom["positive_ratio"] * 1.5, 100) if mom["positive_ratio"] is not None else 0
    
    # 估值得分：PE适中（15-25）最好
    pe = val.get("pe_median") if val else None
    if pe and pe > 0:
        if pe < 10:
            val_score = 50  # 可能价值陷阱
        elif pe < 15:
            val_score = 80
        elif pe < 25:
            val_score = 100
        elif pe < 40:
            val_score = 60
        elif pe < 60:
            val_score = 30
        else:
            val_score = 10
    else:
        val_score = 0
    
    # 财务得分：ROE中位数
    roe = fin.get("roe_median") if fin else None
    if roe:
        fin_score = min(roe * 3, 100)
    else:
        fin_score = 0
    
    # 综合 = 估值30% + 动量40% + 财务30%
    total = val_score * 0.30 + mom_score * 0.40 + fin_score * 0.30
    
    return {
        "sector": sector,
        "stock_count": size,
        "total_score": round(total, 1),
        "val_score": round(val_score, 1),
        "mom_score": round(mom_score, 1),
        "fin_score": round(fin_score, 1),
        "momentum": mom,
        "valuation": val,
        "financial": fin,
    }


def run_screening(sector_level="sector", top_n=20):
    """执行全行业筛选"""
    sectors = get_sector_info(sector_level)
    print(f"行业总数: {len(sectors)}", file=sys.stderr)
    
    results = []
    for sector, stocks in sectors.items():
        if len(stocks) < 3:
            continue  # 跳过极小型行业
        r = score_sector(sector, stocks)
        if r:
            results.append(r)
    
    # 按综合评分排序
    results.sort(key=lambda x: x["total_score"], reverse=True)
    
    top = results[:top_n]
    bottom = results[-min(top_n, len(results)):]
    
    return {
        "run_time": datetime.now().isoformat(),
        "sector_level": sector_level,
        "total_sectors": len(results),
        "top_sectors": top,
        "bottom_sectors": bottom,
        "summary": {
            "top_avg_score": round(statistics.mean(r["total_score"] for r in top), 1) if top else 0,
            "top_names": [r["sector"] for r in top[:5]],
            "avg_momentum_top": round(statistics.mean(r["momentum"]["avg_momentum_20d"] for r in top if r.get("momentum")), 2) if top else 0,
        }
    }


def format_sector(r):
    icon = "🟢" if r["total_score"] >= 70 else ("🟡" if r["total_score"] >= 50 else "🔴")
    mom_avg = r["momentum"]["avg_momentum_20d"] if r.get("momentum") else 0
    pe = r["valuation"]["pe_median"] if r.get("valuation") else "N/A"
    roe = r["financial"]["roe_median"] if r.get("financial") else "N/A"
    return (
        f"{icon} {r['sector']:<20s} "
        f"总分{r['total_score']:>5.1f} "
        f"动量{mom_avg:>+.1f}% "
        f"PE={pe} ROE={roe}% "
        f"{r['stock_count']}只"
    )


def format_output(result):
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"🏭 行业筛选报告 ({result['sector_level']})")
    lines.append(f"{'='*60}")
    lines.append(f"扫描时间: {result['run_time']}")
    lines.append(f"有效行业: {result['total_sectors']} | 推荐前5: {', '.join(result['summary']['top_names'])}")
    lines.append(f"Top平均分: {result['summary']['top_avg_score']} | Top平均动量: {result['summary']['avg_momentum_top']:+.1f}%")
    
    lines.append(f"\n{'▸ 推荐行业 (Top)':60s}")
    lines.append("-"*60)
    for r in result["top_sectors"]:
        lines.append(format_sector(r))
    
    lines.append(f"\n{'▸ 回避行业 (Bottom)':60s}")
    lines.append("-"*60)
    for r in result["bottom_sectors"][:5]:
        lines.append(format_sector(r))
    
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行业筛选自动化 v1.0")
    parser.add_argument("--top", type=int, default=15, help="Top N 行业")
    parser.add_argument("--level", choices=["sector", "sw"], default="sector", help="行业分类级别")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()
    
    result = run_screening(args.level, args.top)
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_output(result))
