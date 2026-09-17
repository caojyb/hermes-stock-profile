#!/usr/bin/env python3
"""
行业拥挤度监控 v1.0

检查持仓和候选池的行业集中度，防止单一行业过度暴露。

用法：
  python3 sector_crowding.py                        # 检查持仓行业集中度
  python3 sector_crowding.py --scan                 # 扫描全市场行业热度
  python3 sector_crowding.py --json                 # JSON输出
"""
from core.compat_paths import MARKET_DB as _DB_PATH
MARKET_DB = _DB_PATH


import os, sys, json, sqlite3, argparse
from datetime import datetime
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).parent.resolve()


def get_db():
    conn = sqlite3.connect(str(MARKET_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_portfolio_sectors():
    """从Bitable获取持仓行业分布"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from bitable_reader import BitableReader
        reader = BitableReader()
        positions = reader.get_hold_positions()
    except ImportError:
        return {"error": "无法读取Bitable"}

    conn = get_db()
    sectors = Counter()
    for p in positions:
        cur = conn.execute("SELECT sector FROM stocks WHERE code=?", (p.code,))
        r = cur.fetchone()
        sector = r["sector"] if r else "未知"
        sectors[sector] += 1
    conn.close()
    return sectors


def get_market_sector_heat(limit=20):
    """获取全市场行业热度（涨跌幅+资金流向）"""
    try:
        # 使用 MCP 工具获取行业板块排行
        import httpx
        url = "https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14,f2,f3,f62,f184,f66"
        r = httpx.get(url, timeout=10)
        data = r.json()
        diff = data.get("data", {}).get("diff", []) or []
        sectors = []
        for d in diff[:limit]:
            sectors.append({
                "name": d.get("f14", ""),
                "code": d.get("f12", ""),
                "change_pct": d.get("f3", 0),
                "fund_flow": d.get("f62", 0),
                "turnover": d.get("f66", 0),
            })
        return sectors
    except Exception as e:
        return {"error": str(e)}


def check_crowding(portfolio_sectors, max_pct=0.30):
    """
    检查行业拥挤度

    规则:
      - 单个行业持仓占比 > 30% → 🔴 过度集中
      - 单个行业持仓占比 > 20% → 🟡 偏高
      - 前3行业合计占比 > 60% → 🟡 集中度高
    """
    if not portfolio_sectors or isinstance(portfolio_sectors, dict) and "error" in portfolio_sectors:
        return {"error": "无持仓数据"}

    total = sum(portfolio_sectors.values())
    if total == 0:
        return {"error": "空持仓"}

    results = []
    flags = []

    # 排序
    sorted_sectors = portfolio_sectors.most_common()
    for sector, count in sorted_sectors:
        pct = count / total
        level = "normal"
        if pct > max_pct:
            level = "danger"
            flags.append(f"🔴 {sector} 占比{pct*100:.0f}% 超过{max_pct*100:.0f}%上限")
        elif pct > max_pct * 0.67:
            level = "warning"
            flags.append(f"🟡 {sector} 占比{pct*100:.0f}% 偏高")
        results.append({"sector": sector, "count": count, "pct": round(pct * 100, 1), "level": level})

    # 前3行业合计
    top3_pct = sum(r["pct"] for r in results[:3])
    if top3_pct > 60:
        flags.append(f"🟡 前3行业合计{top3_pct:.0f}% > 60% 集中度高")

    return {
        "total_stocks": total,
        "sectors": results,
        "flags": flags,
        "top3_concentration": round(top3_pct, 1),
        "healthy": len(flags) == 0,
    }


def format_report(crowding, market_heat=None):
    lines = []
    lines.append(f"\n{'='*55}")
    lines.append(f"  行业拥挤度监控  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"{'='*55}")

    if not crowding or "error" in crowding:
        lines.append(f"\n⚠️ {crowding.get('error', '未知错误')}")
        return "\n".join(lines)

    lines.append(f"\n持仓总数: {crowding['total_stocks']} 只")
    lines.append(f"健康度: {'✅ 良好' if crowding['healthy'] else '⚠️ 需关注'}")

    if crowding['flags']:
        lines.append(f"\n🚩 预警:")
        for f in crowding['flags']:
            lines.append(f"  {f}")

    lines.append(f"\n📊 行业分布:")
    for s in crowding['sectors']:
        icon = "🔴" if s['level'] == 'danger' else ("🟡" if s['level'] == 'warning' else "🟢")
        bar = "█" * max(1, int(s['pct'] / 5))
        lines.append(f"  {icon} {s['sector']:<12s} {bar} {s['pct']:.0f}% ({s['count']}只)")

    if market_heat and not isinstance(market_heat, dict):
        lines.append(f"\n🔥 热门行业 (涨跌幅):")
        for s in market_heat[:5]:
            arrow = "▲" if s['change_pct'] >= 0 else "▼"
            lines.append(f"  {s['name']:<12s} {arrow}{abs(s['change_pct']):+.1f}%")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行业拥挤度监控")
    parser.add_argument("--scan", action="store_true", help="扫描全市场行业热度")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()

    portfolio = get_portfolio_sectors()
    crowding = check_crowding(portfolio)

    market_heat = None
    if args.scan:
        market_heat = get_market_sector_heat()

    if args.json:
        result = {"crowding": crowding, "market_heat": market_heat}
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_report(crowding, market_heat))