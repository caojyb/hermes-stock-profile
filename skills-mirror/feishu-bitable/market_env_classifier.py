#!/usr/bin/env python3
"""市场环境自动分类脚本"""
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB
import sqlite3
import math
from datetime import datetime, timedelta

DB = _STOCK_MARKET_DB
LARGE_INDEX = '000300'
MID_INDEX = '000905'

def get_klines(conn, code, limit=800):
    cur = conn.execute(
        "SELECT date, close, high, low, volume FROM klines WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, limit))
    rows = cur.fetchall()
    rows.reverse()
    return rows

def calc_ma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def calc_atr(klines, period=20):
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i][2] or 0, klines[i][3] or 0, klines[i-1][1] or 0
        if h and l and pc:
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period

def classify_market():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    kl = get_klines(conn, LARGE_INDEX, 500)
    if len(kl) < 120:
        return {"error": f"沪深300数据不足: {len(kl)}"}
    closes = [r['close'] for r in kl]
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    ma120 = calc_ma(closes, 120)
    if None in (ma20, ma60, ma120):
        return {"error": "均线计算失败"}
    if ma20 > ma60 > ma120:
        trend_score = 100; trend_label = "多头排列"
    elif ma20 < ma60 < ma120:
        trend_score = 0; trend_label = "空头排列"
    else:
        trend_score = 50; trend_label = "交织状态"
    if ma20 > ma60 and trend_score == 50:
        trend_score = 65
    elif ma60 > ma20 and trend_score == 50:
        trend_score = 35

    kl_atr = get_klines(conn, LARGE_INDEX, 800)
    if len(kl_atr) < 250:
        return {"error": "波动率数据不足"}
    current_atr = calc_atr(kl_atr, 20)
    current_close = kl_atr[-1][1]
    current_atr_pct = (current_atr / current_close * 100) if current_close and current_atr else 0
    hist_atr_pcts = []
    for i in range(250, len(kl_atr)-20):
        atr = calc_atr(kl_atr[i-20:i+20], 20)
        close = kl_atr[i][1]
        if atr and close:
            hist_atr_pcts.append(atr / close * 100)
    if hist_atr_pcts:
        sorted_hist = sorted(hist_atr_pcts)
        vol_percentile = sum(1 for v in sorted_hist if v < current_atr_pct) / len(sorted_hist) * 100
    else:
        vol_percentile = 50
    vol_score = vol_percentile

    if len(kl) < 125:
        return {"error": "流动性数据不足"}
    vol_20 = sum((r['volume'] or 0) for r in kl[-20:]) / 20
    vol_120 = sum((r['volume'] or 0) for r in kl[-120:]) / 120
    liq_ratio = vol_20 / vol_120 if vol_120 > 0 else 1
    if liq_ratio > 1.2: liq_score = 80; liq_label = "量能放大"
    elif liq_ratio > 0.8: liq_score = 50; liq_label = "量能正常"
    else: liq_score = 20; liq_label = "量能萎缩"
    if liq_ratio > 1.5: liq_score = 100
    elif liq_ratio < 0.5: liq_score = 0

    kl_small = get_klines(conn, MID_INDEX, 50)
    if len(kl_small) < 20 or len(kl) < 20:
        return {"error": "风格数据不足"}
    large_ret = (kl[-1][1] - kl[-21][1]) / kl[-21][1] * 100
    small_ret = (kl_small[-1][1] - kl_small[-21][1]) / kl_small[-21][1] * 100
    style_ratio = large_ret / small_ret if small_ret != 0 else 1
    if style_ratio > 1.1: style_score = 80; style_label = "大盘占优"
    elif style_ratio < 0.9: style_score = 20; style_label = "小盘占优"
    else: style_score = 50; style_label = "风格均衡"

    total = trend_score * 0.30 + vol_score * 0.25 + liq_score * 0.25 + style_score * 0.20
    if total > 70 and vol_percentile < 50:
        env_label = "🟢 强趋势"; env_desc = "适合主升浪策略"
    elif vol_percentile > 70:
        env_label = "🔴 高波动"; env_desc = "适合超跌反弹策略"
    elif liq_score < 30:
        env_label = "⚫ 低量能"; env_desc = "需要极度保守"
    else:
        env_label = "🟡 震荡市"; env_desc = "适合低吸策略"

    similar_months = []
    for i in range(12, len(kl_atr)-250, 20):
        hist_vol = calc_atr(kl_atr[i:i+40], 20)
        hist_close = kl_atr[i+20][1]
        hv_pct = (hist_vol / hist_close * 100) if hist_close and hist_vol else 0
        dist = abs(hv_pct - current_atr_pct) + abs(hist_close/kl_atr[i][1]-1)*10
        similar_months.append((dist, kl_atr[i+20][0]))
    similar_months.sort(key=lambda x: x[0])
    top3 = [(d, dt) for d, dt in similar_months[:3] if d < 5]
    conn.close()
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "environment": {"label": env_label, "description": env_desc, "total_score": round(total, 1)},
        "dimensions": {
            "trend": {"score": trend_score, "label": trend_label, "weight": "30%", "ma20": round(ma20, 2), "ma60": round(ma60, 2), "ma120": round(ma120, 2)},
            "volatility": {"score": round(vol_score, 1), "label": f"分位{round(vol_percentile, 0):.0f}%", "weight": "25%", "atr_pct": round(current_atr_pct, 2)},
            "liquidity": {"score": liq_score, "label": liq_label, "weight": "25%", "ratio": round(liq_ratio, 2)},
            "style": {"score": style_score, "label": style_label, "weight": "20%", "ratio": round(style_ratio, 2)},
        },
        "similar_periods": [dt for _, dt in top3],
    }

if __name__ == "__main__":
    import sys, json
    result = classify_market()
    print(json.dumps(result, ensure_ascii=False, indent=2))
