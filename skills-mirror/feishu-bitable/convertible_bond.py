#!/usr/bin/env python3
"""
可转债数据模块 v1.0
数据源：东方财富（通过 akshare + 直连 API）
用法：
  python3 convertible_bond.py scan       # 扫描全市场可转债
  python3 convertible_bond.py top --by premium  # 按溢价率排序
  python3 convertible_bond.py top --by yield    # 按到期收益率排序
  python3 convertible_bond.py --json     # JSON输出
"""

import os, sys, json, argparse
from datetime import datetime
from pathlib import Path

# 强制直连
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    os.environ.pop(k, None)

import akshare as ak
import pandas as pd


def fetch_convertible_bonds():
    """获取全市场可转债数据"""
    try:
        df = ak.bond_zh_cov()
        if df.empty:
            return {"error": "无数据"}
        return df
    except Exception as e:
        return {"error": str(e)}


def fetch_live_prices():
    """获取可转债实时行情（通过东方财富 push2 API）"""
    import requests
    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f3", "fs": "m:0+t:6+f:!2,m:0+t:5081+f:!2",
        "fields": "f2,f3,f12,f14,f15,f16,f17,f18,f23,f24,f25,f26,f27,f28,f30,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40,f41,f42,f43,f44,f45,f46,f47,f48,f49,f50,f57,f58,f60,f62,f63,f64,f65,f66,f67,f68,f69,f70,f71,f72,f73,f74,f75,f76,f77,f78,f79,f80,f81,f82,f83,f84,f85,f86,f87,f88,f89,f90,f91,f92,f93,f94,f95,f96,f97,f98,f99,f100,f101,f102,f103,f104,f105,f106,f107,f108,f109,f110,f111,f112,f113,f114,f115,f116,f117,f118,f119,f120,f121,f122,f123,f124,f125,f126,f127,f128,f129,f130,f131,f132,f133,f134,f135,f136,f137,f138,f139,f140,f141,f142,f143,f144,f145,f146,f147,f148,f149,f150,f151,f152,f153,f154,f155,f156,f157,f158,f159,f160,f161,f162,f163,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f184,f185,f186,f187,f188,f189,f190,f191,f192,f193,f194,f195,f196,f197,f198,f199,f200"
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        diff = data.get("data", {}).get("diff", []) or []
        # push2delay 返回的字段是数字，需要转成可读格式
        return diff
    except Exception as e:
        return {"error": str(e)}


def analyze_bonds(df):
    """分析可转债数据"""
    if isinstance(df, dict) and "error" in df:
        return df

    # 计算关键指标
    results = []
    for _, row in df.iterrows():
        try:
            item = {
                "code": str(row.get("债券代码", "")),
                "name": str(row.get("债券简称", "")),
                "stock_code": str(row.get("正股代码", "")),
                "stock_name": str(row.get("正股简称", "")),
                "stock_price": float(row.get("正股价", 0) or 0),
                "convert_price": float(row.get("转股价", 0) or 0),
                "convert_value": float(row.get("转股价值", 0) or 0),
                "bond_price": float(row.get("债现价", 0) or 0),
                "premium": float(row.get("转股溢价率", 0) or 0),
                "issue_size": float(row.get("发行规模", 0) or 0),
                "rating": str(row.get("信用评级", "")),
            }
            # 计算到期收益率近似值
            if item["bond_price"] > 0 and item["convert_value"] > 0:
                item["premium_ratio"] = (item["bond_price"] - item["convert_value"]) / item["convert_value"] * 100
            else:
                item["premium_ratio"] = 0
            results.append(item)
        except (ValueError, TypeError):
            continue

    return results


def format_report(bonds):
    """格式化可转债报告"""
    lines = []
    lines.append(f"\n🏦 可转债市场扫描  {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"{'='*55}")

    if isinstance(bonds, dict) and "error" in bonds:
        lines.append(f"\n⚠️ {bonds['error']}")
        return "\n".join(lines)

    # 按溢价率排序（低溢价 = 股性强）
    sorted_bonds = sorted(bonds, key=lambda x: abs(x.get("premium", 999)))

    lines.append(f"\n共 {len(bonds)} 只可转债")
    lines.append(f"\n📊 低溢价TOP10（股性强）")
    for b in sorted_bonds[:10]:
        lines.append(f"  {b['name']}({b['code']}) 溢价:{b.get('premium',0):.1f}%  债价:{b.get('bond_price',0):.2f}  正股:{b['stock_name']}")

    # 高溢价（债性强）
    reversed_bonds = sorted(bonds, key=lambda x: x.get("premium", 0), reverse=True)
    lines.append(f"\n📊 高溢价TOP5（债性强，到期收益率高）")
    for b in reversed_bonds[:5]:
        lines.append(f"  {b['name']}({b['code']}) 溢价:{b.get('premium',0):.1f}%  债价:{b.get('bond_price',0):.2f}")

    return "\n".join(lines)


def run(mode="scan", json_output=False):
    if mode == "scan":
        df = fetch_convertible_bonds()
        bonds = analyze_bonds(df)
        if json_output:
            return json.dumps(bonds, ensure_ascii=False, indent=2, default=str)
        return format_report(bonds)
    return ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="可转债数据模块")
    parser.add_argument("mode", nargs="?", default="scan", help="扫描模式")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()
    print(run(args.mode, args.json))