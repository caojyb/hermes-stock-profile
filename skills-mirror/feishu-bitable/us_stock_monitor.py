#!/usr/bin/env python3
"""
美股持仓周更脚本 v2.1
调度时间：每周六 10:30（美股收盘后）
功能：Finnhub 实时报价 + 基本面 + 新闻周报
支持股票：动态配置
"""

import sys, os, json, urllib.request, math, signal
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from datetime import datetime, timedelta, timezone

# 强制直连
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    os.environ.pop(k, None)

FINNHUB_TOKEN = os.environ.get("FINNHUB_TOKEN", "d70e8g1r01qtb4raecmgd70e8g1r01qtb4raecn0")
FINNHUB_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# 持仓列表（默认值，当未传入 --config 时使用）
POSITIONS = [
    {"symbol": "AAPL", "name": "苹果"},
    {"symbol": "NVDA", "name": "英伟达"},
]


def _get_json(url, params=None, timeout=15):
    if params:
        url = url + "&" + "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v is not None)
    req = urllib.request.Request(url, headers=FINNHUB_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


import urllib.parse


def finnhub_quote(symbol):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_TOKEN}"
    return _get_json(url)


def finnhub_profile(symbol):
    url = f"https://finnhub.io/api/v1/company-profile-2?symbol={symbol}&token={FINNHUB_TOKEN}"
    try:
        return _get_json(url)
    except Exception as e:
        print(f"  Finnhub profile 不可用: {symbol} {type(e).__name__}: {e}")
        return {}


def finnhub_metric(symbol):
    url = f"https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={FINNHUB_TOKEN}"
    return _get_json(url)


def finnhub_news(symbol, days=7):
    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=days)
    url = (
        f"https://finnhub.io/api/v1/company-news"
        f"?symbol={symbol}&from={from_dt.strftime('%Y-%m-%d')}&to={to_dt.strftime('%Y-%m-%d')}&token={FINNHUB_TOKEN}"
    )
    return _get_json(url)


def _yfinance_history(symbol, range_="6mo"):
    """通过系统代理获取 Yahoo Finance 历史 K 线，用于补充技术指标。"""
    proxy_host = os.environ.get("YFINANCE_PROXY_HOST") or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "127.0.0.1:7892"
    proxy_handler = urllib.request.ProxyHandler({"http": f"http://{proxy_host}", "https": f"http://{proxy_host}"})
    opener = urllib.request.build_opener(proxy_handler)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(req, timeout=20) as resp:
        data = json.loads(resp.read())
    r = data["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    closes = [c for c in q["close"] if c is not None]
    highs = [h for h in q["high"] if h is not None]
    lows = [l for l in q["low"] if l is not None]
    volumes = [v for v in q["volume"] if v is not None]
    return closes, highs, lows, volumes


def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else None
    if rs is None:
        return None
    return 100 - 100 / (1 + rs)


def calc_ma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def calc_macd(prices):
    if len(prices) < 26:
        return None, None, None
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    dif = ema12 - ema26
    dea = calc_ema([dif] * 9, 9) if len(prices) >= 34 else 0
    macd = 2 * (dif - dea)
    return dif, dea, macd


def calc_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_bollinger(prices, period=20, std_dev=2):
    if len(prices) < period:
        return None, None, None
    ma = sum(prices[-period:]) / period
    variance = sum((p - ma) ** 2 for p in prices[-period:]) / period
    std = math.sqrt(variance)
    return ma + std_dev * std, ma, ma - std_dev * std


def enrich_technicals(symbol):
    try:
        closes, highs, lows, volumes = _yfinance_history(symbol)
    except Exception as e:
        print(f"  Yahoo via proxy 不可用: {symbol} {type(e).__name__}: {e}")
        return {}

    if not closes:
        return {}

    rsi = calc_rsi(closes)
    ma20 = calc_ma(closes, 20)
    ma50 = calc_ma(closes, 50)
    upper, mid, lower = calc_bollinger(closes)
    dif, dea, macd_val = calc_macd(closes)

    volume_ratio = None
    if len(volumes) >= 5:
        volume_ratio = round(volumes[-1] / (sum(volumes[-5:]) / 5), 2)

    return {
        "rsi_14": round(rsi, 1) if rsi is not None else None,
        "ma20": round(ma20, 2) if ma20 is not None else None,
        "ma50": round(ma50, 2) if ma50 is not None else None,
        "bollinger_upper": round(upper, 2) if upper is not None else None,
        "bollinger_mid": round(mid, 2) if mid is not None else None,
        "bollinger_lower": round(lower, 2) if lower is not None else None,
        "macd_dif": round(dif, 2) if dif is not None else None,
        "macd_dea": round(dea, 2) if dea is not None else None,
        "macd": round(macd_val, 2) if macd_val is not None else None,
        "volume_ratio": volume_ratio,
    }


def fmt_num(v, digits=2, suffix=""):
    if v is None:
        return None
    try:
        return f"{float(v):.{digits}f}{suffix}"
    except Exception:
        return None


def analyze_stock(symbol, name):
    quote = finnhub_quote(symbol)
    profile = finnhub_profile(symbol)
    metric = finnhub_metric(symbol)
    news = finnhub_news(symbol)

    if not quote or quote.get("c") is None:
        return {"symbol": symbol, "name": name, "error": "Finnhub 实时报价为空"}

    m = metric.get("metric", {}) if metric else {}
    profile_name = ((profile or {}).get("name") or name).strip()
    price = quote.get("c")
    prev_close = quote.get("pc")
    change_pct = quote.get("dp")
    high = quote.get("h")
    low = quote.get("l")
    volume = quote.get("v")
    if isinstance(volume, (int, float)) and volume > 1_000_000:
        volume_text = f"{volume/1_000_000:.2f}M"
    elif isinstance(volume, (int, float)) and volume > 1_000:
        volume_text = f"{volume/1_000:.2f}K"
    else:
        volume_text = str(volume)

    result = {
        "symbol": symbol,
        "name": profile_name,
        "price": round(price, 2) if isinstance(price, (int, float)) else price,
        "change_pct": round(change_pct, 2) if isinstance(change_pct, (int, float)) else change_pct,
        "high": round(high, 2) if isinstance(high, (int, float)) else high,
        "low": round(low, 2) if isinstance(low, (int, float)) else low,
        "prev_close": round(prev_close, 2) if isinstance(prev_close, (int, float)) else prev_close,
        "volume": volume_text,
        "market_cap": m.get("marketCapitalization"),
        "pe_ttm": m.get("peTTM"),
        "forward_pe": m.get("forwardPE"),
        "peg_ttm": m.get("pegTTM"),
        "ps_ttm": m.get("psTTM"),
        "pb": m.get("pb"),
        "pcf_ttm": m.get("pcfShareTTM"),
        "roe_ttm": m.get("roeTTM"),
        "roa_ttm": m.get("roaTTM"),
        "net_margin_ttm": m.get("netProfitMarginTTM"),
        "beta": m.get("beta"),
        "dividend_yield": m.get("currentDividendYieldTTM"),
        "52w_high": m.get("52WeekHigh"),
        "52w_low": m.get("52WeekLow"),
        "ytd_return": m.get("yearToDatePriceReturnDaily"),
        "4w_return": m.get("priceRelativeToS&P5004Week"),
        "13w_return": m.get("priceRelativeToS&P50013Week"),
        "26w_return": m.get("priceRelativeToS&P50026Week"),
        "52w_return": m.get("priceRelativeToS&P50052Week"),
        "10d_avg_volume": m.get("10DayAverageTradingVolume"),
        "3m_avg_volume": m.get("3MonthAverageTradingVolume"),
    }

    news_items = []
    if isinstance(news, list):
        news_items = [n for n in news if isinstance(n, dict) and n.get("headline")]
        news_items = sorted(news_items, key=lambda x: x.get("datetime", 0), reverse=True)[:5]

    result["news"] = news_items

    tech = enrich_technicals(symbol)
    if tech:
        result.update(tech)

    return result


def format_report(stocks):
    lines = []
    lines.append(f"\n📈 美股持仓周报  {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"{'='*55}")

    for s in stocks:
        if "error" in s:
            lines.append(f"\n  {s.get('name', s.get('symbol'))}({s['symbol']})  数据异常：{s['error']}")
            continue

        lines.append(f"\n  {s['name']}({s['symbol']})  ${s['price']}")
        arrow = "▲" if s.get("change_pct", 0) >= 0 else "▼"
        lines.append(f"  涨跌: {arrow}{abs(s.get('change_pct', 0)):.2f}%  昨收: {s.get('prev_close')}  最高/最低: {s.get('high')}/{s.get('low')}")

        lines.append("  ── 技术面 ──")
        if s.get("rsi_14") is not None:
            lines.append(f"  RSI(14): {s['rsi_14']:.1f}  {'超买' if s['rsi_14'] > 70 else '超卖' if s['rsi_14'] < 30 else '正常'}")
        if s.get("ma20") and s.get("ma50"):
            trend = "多头" if s["ma20"] > s["ma50"] else "空头"
            lines.append(f"  MA20: {s['ma20']}  MA50: {s['ma50']}  [{trend}趋势]")
        if s.get("bollinger_upper") and s.get("bollinger_lower"):
            lines.append(f"  布林带: {s['bollinger_upper']} / {s['bollinger_mid']} / {s['bollinger_lower']}")
        if s.get("macd") is not None and s.get("macd_dif") is not None:
            macd_signal = "金叉" if s["macd"] > 0 else "死叉"
            lines.append(f"  MACD: {s['macd']}  DIF: {s['macd_dif']}  [{macd_signal}]")
        if s.get("volume_ratio") is not None:
            lines.append(f"  量比: {s['volume_ratio']:.2f}")

        lines.append("  ── 估值/质量 ──")
        if s.get("pe_ttm") is not None:
            lines.append(f"  PE(TTM): {s['pe_ttm']:.2f}  Forward PE: {fmt_num(s.get('forward_pe'), 2, '') or 'N/A'}")
        if s.get("peg_ttm") is not None:
            lines.append(f"  PEG(TTM): {s['peg_ttm']:.2f}")
        if s.get("ps_ttm") is not None:
            lines.append(f"  PS(TTM): {s['ps_ttm']:.2f}")
        if s.get("pb") is not None:
            lines.append(f"  PB: {s['pb']:.2f}")
        if s.get("pcf_ttm") is not None:
            lines.append(f"  PCF(TTM): {s['pcf_ttm']:.2f}")
        if s.get("roe_ttm") is not None:
            lines.append(f"  ROE(TTM): {s['roe_ttm']*100:.2f}%")
        if s.get("net_margin_ttm") is not None:
            lines.append(f"  净利率(TTM): {s['net_margin_ttm']*100:.2f}%")
        if s.get("beta") is not None:
            lines.append(f"  Beta: {s['beta']:.2f}")
        if s.get("dividend_yield") is not None:
            lines.append(f"  股息率: {s['dividend_yield']:.2f}%")

        lines.append("  ── 区间表现 ──")
        if s.get("52w_high") and s.get("52w_low") and s.get("price"):
            pos = (s["price"] - s["52w_low"]) / (s["52w_high"] - s["52w_low"]) * 100
            lines.append(f"  52周: ${s['52w_low']} ~ ${s['52w_high']}  当前分位 {pos:.0f}%")
        if s.get("ytd_return") is not None:
            lines.append(f"  年初至今: {s['ytd_return']:.2f}%")
        if s.get("13w_return") is not None:
            lines.append(f"  13周相对标普: {s['13w_return']:.2f}%")
        if s.get("26w_return") is not None:
            lines.append(f"  26周相对标普: {s['26w_return']:.2f}%")
        if s.get("52w_return") is not None:
            lines.append(f"  52周相对标普: {s['52w_return']:.2f}%")

        if s.get("market_cap"):
            lines.append(f"  市值: {s['market_cap']/1000:.2f}B")

        if s.get("news"):
            lines.append("  ── 近期要闻 ──")
            for n in s["news"][:3]:
                dt = datetime.fromtimestamp(n.get("datetime", 0)).strftime("%m-%d %H:%M")
                lines.append(f"  [{dt}] {n.get('headline')}")

    return "\n".join(lines)


def run(symbols=None):
    if symbols is None:
        symbols = POSITIONS
    results = []
    for p in symbols:
        try:
            r = analyze_stock(p["symbol"], p.get("name", p["symbol"]))
            results.append(r)
        except Exception as e:
            results.append({"symbol": p["symbol"], "name": p.get("name", p["symbol"]), "error": str(e)})
    return format_report(results)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="JSON 配置文件路径，内容为 [{\"symbol\":\"AAPL\",\"name\":\"苹果\"}]")
    args = parser.parse_args()

    symbols = None
    if args.config:
        try:
            with open(args.config, "r", encoding="utf-8") as f:
                symbols = json.load(f)
        except Exception as e:
            print(f"配置读取失败: {e}")

    signal.signal(signal.SIGALRM, lambda *_: sys.exit(1))
    signal.alarm(60)
    print(run(symbols=symbols))