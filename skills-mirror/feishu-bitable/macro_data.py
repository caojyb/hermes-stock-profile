#!/usr/bin/env python3
"""
宏观环境监控 v1.0

基于现有数据源（push2delay）的宏观指标汇总。
数据源限制：东方财富 datacenter API 不可用，无法获取CPI/GDP/LPR。
使用可获取的 proxy 指标：指数趋势、成交量、资金流向、北向资金。

用法：
  python3 macro_data.py                     # 输出宏观报告
  python3 macro_data.py --json              # JSON输出
  python3 macro_data.py --sentiment-score   # 输出宏观情绪分（0-100）
"""

import os, sys, json, argparse
from datetime import datetime, timedelta
from pathlib import Path

# 强制直连
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    os.environ.pop(k, None)

import httpx

QUOTE_HOST = "https://push2delay.eastmoney.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

_client = None
def _get_client():
    global _client
    if _client is None:
        _client = httpx.Client(verify=False, follow_redirects=True)
    return _client


def fetch_index_data():
    """获取主要指数数据"""
    try:
        url = (f"{QUOTE_HOST}/api/qt/ulist.np/get?fields=f2,f3,f4,f12,f14,f15,f16,f17,f18"
               f"&secids=1.000001,0.399001,0.399006,1.000688,1.000016")
        r = _get_client().get(url, headers=HEADERS, timeout=10)
        data = r.json()
        diff = data.get("data", {}).get("diff", []) or []
        indices = {}
        for d in diff:
            name = d.get("f14", "")
            indices[name] = {
                "price": d.get("f2", 0) / 100 if d.get("f2") else 0,
                "change_pct": d.get("f3", 0) / 100 if d.get("f3") else 0,
                "high": d.get("f15", 0) / 100 if d.get("f15") else 0,
                "low": d.get("f16", 0) / 100 if d.get("f16") else 0,
                "open": d.get("f17", 0) / 100 if d.get("f17") else 0,
                "volume": d.get("f18", 0) or 0,
            }
        return indices
    except Exception as e:
        return {"error": str(e)}


def fetch_sector_performance():
    """获取行业板块涨跌统计数据"""
    try:
        url = (f"{QUOTE_HOST}/api/qt/clist/get?pn=1&pz=100&po=1&np=1&fltt=2&invt=2"
               f"&fid=f3&fs=m:90+t:2&fields=f12,f14,f3,f4,f62,f66")
        r = _get_client().get(url, headers=HEADERS, timeout=10)
        data = r.json()
        diff = data.get("data", {}).get("diff", []) or []
        if not diff:
            return {"error": "no data"}
        up = sum(1 for d in diff if (d.get("f3") or 0) > 0)
        down = sum(1 for d in diff if (d.get("f3") or 0) < 0)
        flat = len(diff) - up - down
        return {
            "total": len(diff),
            "up": up,
            "down": down,
            "flat": flat,
            "up_ratio": round(up / len(diff) * 100, 1) if diff else 0,
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_market_volume():
    """获取全市场成交量（沪深两市合计）"""
    try:
        url = (f"{QUOTE_HOST}/api/qt/ulist.np/get?fields=f2,f3,f4,f12,f14,f18"
               f"&secids=1.000001,0.399001")
        r = _get_client().get(url, headers=HEADERS, timeout=10)
        data = r.json()
        diff = data.get("data", {}).get("diff", []) or []
        total_vol = sum(d.get("f18", 0) or 0 for d in diff)
        return {"total_volume": total_vol}
    except Exception as e:
        return {"error": str(e)}


def calc_macro_score(indices, sector, volume):
    """计算宏观环境评分（0-100）"""
    comps = {}

    # 1. 指数趋势 (权重40%)
    idx_score = 50
    if indices and not isinstance(indices, dict) and "error" not in indices:
        # 取上证和深证的平均
        sse = indices.get("上证指数", {})
        szse = indices.get("深证成指", {})
        changes = []
        if sse.get("change_pct") is not None:
            changes.append(sse["change_pct"])
        if szse.get("change_pct") is not None:
            changes.append(szse["change_pct"])
        if changes:
            avg = sum(changes) / len(changes)
            idx_score = max(0, min(100, 50 + avg * 50 / 2))
    comps["指数趋势"] = {"score": round(idx_score, 1), "weight": "40%"}

    # 2. 行业广度 (权重30%)
    if sector and not sector.get("error"):
        up_ratio = sector.get("up_ratio", 50)
        breadth_score = max(0, min(100, up_ratio * 100 / 60))
    else:
        breadth_score = 50
    comps["行业广度"] = {"score": round(breadth_score, 1), "weight": "30%"}

    # 3. 成交量 (权重30%)
    if volume and not volume.get("error"):
        # 用成交量相对历史均值判断活跃度
        # 成交量在 50亿-150亿之间视为正常
        vol = volume.get("total_volume", 0) / 10000  # 转成万手
        if vol > 150:
            vol_score = 70
        elif vol > 100:
            vol_score = 60
        elif vol > 50:
            vol_score = 50
        else:
            vol_score = 30
    else:
        vol_score = 50
    comps["成交量"] = {"score": round(vol_score, 1), "weight": "30%"}

    # 计算总分
    total = sum(
        v["score"] * int(v["weight"].rstrip("%")) / 100
        for v in comps.values()
    )
    return round(total, 1), comps


def format_report(indices, sector, volume, score, comps):
    lines = []
    lines.append(f"\n{'='*55}")
    lines.append(f"  🌍 宏观环境  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"{'='*55}")

    # 评分
    bar = "█" * max(1, int(score / 10)) + "░" * max(0, 10 - max(1, int(score / 10)))
    lines.append(f"\n  宏观评分: {bar}  {score}/100")
    if score >= 65:
        lines.append(f"  判定: 🟢 宏观环境良好")
    elif score >= 45:
        lines.append(f"  判定: 🟡 宏观中性")
    else:
        lines.append(f"  判定: 🔴 宏观偏弱")

    # 指数
    if indices and not isinstance(indices, dict) and "error" not in indices:
        lines.append(f"\n📈 主要指数")
        for name in ["上证指数", "深证成指", "创业板指", "科创50"]:
            if name in indices:
                d = indices[name]
                arrow = "▲" if d["change_pct"] >= 0 else "▼"
                lines.append(f"  {name:<8s} {d['price']:.0f}  {arrow}{abs(d['change_pct']):.2f}%")

    # 行业广度
    if sector and not sector.get("error"):
        lines.append(f"\n🏢 行业广度")
        lines.append(f"  上涨: {sector.get('up',0)} | 下跌: {sector.get('down',0)} | 平盘: {sector.get('flat',0)}")
        lines.append(f"  涨跌比: {sector.get('up_ratio',0)}%")

    # 分解
    lines.append(f"\n📐 宏观分解")
    for name, comp in comps.items():
        s = comp["score"]
        w = comp["weight"]
        bar2 = "█" * max(1, int(s / 10)) + "░" * max(0, 10 - max(1, int(s / 10)))
        lines.append(f"  {name:<8s} {bar2} {s:.0f}  (权重{w})")

    return "\n".join(lines)


def run(json_output=False):
    indices = fetch_index_data()
    sector = fetch_sector_performance()
    volume = fetch_market_volume()
    score, comps = calc_macro_score(indices, sector, volume)

    if json_output:
        return json.dumps({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "macro_score": score,
            "components": {k: v["score"] for k, v in comps.items()},
            "indices": indices,
            "sector_breadth": sector,
            "volume": volume,
        }, ensure_ascii=False, indent=2, default=str)

    return format_report(indices, sector, volume, score, comps)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="宏观环境监控")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--sentiment-score", action="store_true", help="只输出评分")
    args = parser.parse_args()

    report = run(json_output=args.json or args.sentiment_score)

    if args.sentiment_score:
        # 从JSON中提取评分
        data = json.loads(report)
        print(data["macro_score"])
    else:
        print(report)