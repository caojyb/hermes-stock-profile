#!/usr/bin/env python3
"""
交易管理模块 v1.0 — 仓位管理 + 止损止盈 + 买卖信号

用法：
  python3 trade_manager.py position --code 600519 --price 188.50    # 仓位计算
  python3 trade_manager.py stop-loss --code 600519 --price 188.50   # 止损计算
  python3 trade_manager.py signal --code 600519                     # 买卖信号
  python3 trade_manager.py scan                                     # 持仓扫描
"""
from pathlib import Path
import sys
# Resolve the Hermes stock profile root dynamically so this works
# regardless of how deeply nested the script is under profiles/stock/.
_profile_root = None
for parent in Path(__file__).resolve().parents:
    if parent.name == 'stock' and parent.parent.name == 'profiles':
        _profile_root = parent
        break
if _profile_root is None:
    raise RuntimeError('Cannot locate Hermes stock profile root')
_STOCK_WORK = _profile_root / 'stock-work'
if str(_STOCK_WORK) not in sys.path:
    sys.path.insert(0, str(_STOCK_WORK))
from core.bootstrap import ensure_stock_work_root
ensure_stock_work_root()

from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

import os, sys, json, sqlite3, argparse, math
from datetime import datetime, date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
MARKET_DB = _STOCK_MARKET_DB


def get_db():
    conn = sqlite3.connect(str(MARKET_DB))
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════
# 技术指标（轻量版，不依赖 signal_engine）
# ═══════════════════════════════════════════

def get_kline(code, days=60):
    """获取最近N天K线。若K线停更(>3交易日)打印醒目告警并尝试飞书推送。"""
    conn = get_db()
    cur = conn.execute(
        "SELECT date, open, close, high, low, volume FROM klines "
        "WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, days)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    rows.reverse()

    # ── M1: K线新鲜度告警（deep-position-review 等用旧K线无感知） ──
    if rows:
        try:
            latest_str = rows[-1]["date"]
            latest_dt = datetime.strptime(latest_str, '%Y-%m-%d').date()
            data_lag = (date.today() - latest_dt).days
            if data_lag > 3:
                print(f"[WARN] ⚠️ {code} K线停更 {data_lag} 天(最新{latest_str})，以下分析基于过期行情", file=sys.stderr)
                _feishu_alert_stale(code, latest_str, data_lag)
        except (ValueError, TypeError, KeyError):
            pass

    return rows


def _feishu_alert_stale(code, latest_date, lag):
    """K线停更时推送飞书告警（静默失败不影响主流程，避免重复刷屏）。"""
    global _STALE_ALERTED
    if _STALE_ALERTED.get(code):
        return
    try:
        import urllib.request
        token = os.environ.get("FEISHU_WEBHOOK_TOKEN", "")
        if token:
            payload = json.dumps({"msg_type": "text", "content": {"text":
                f"⚠️ [trade_manager] K线停更告警\n{code} 最新 {latest_date}，停更 {lag} 天\n持仓诊断/止损/信号基于过期行情，请检查数据源"}}).encode("utf-8")
            req = urllib.request.Request("https://open.feishu.cn/open-apis/bot/v2/hook/" + token,
                                         data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        _STALE_ALERTED[code] = True
    except Exception:
        pass

_STALE_ALERTED: dict = {}


def calc_atr(klines, period=14):
    """计算 ATR(14)"""
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        high = klines[i]["high"]
        low = klines[i]["low"]
        prev_close = klines[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period


def calc_sma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


# ═══════════════════════════════════════════
# 仓位管理
# ═══════════════════════════════════════════

def calc_position_size(price, total_capital, risk_per_trade=0.02,
                       stop_loss_pct=0.05, method="kelly",
                       win_rate=0.4, reward_risk_ratio=2.0):
    """
    计算仓位大小

    参数:
        price: 当前股价
        total_capital: 总资金
        risk_per_trade: 单笔风险比例 (默认2%)
        stop_loss_pct: 止损比例 (默认5%)
        method: 计算方法
            'fixed' - 固定金额
            'risk_parity' - 风险平价
            'kelly' - 凯利公式
        win_rate: 胜率 (仅kelly)
        reward_risk_ratio: 盈亏比 (仅kelly)

    返回:
        {shares, amount, capital_pct, risk_amount, method}
    """
    result = {"price": price, "total_capital": total_capital, "method": method}

    if method == "fixed":
        # 固定金额: 每只股票投入总资金的5-10%
        alloc_pct = 0.08
        amount = total_capital * alloc_pct
        shares = max(1, int(amount / price / 100) * 100)  # 100股整数倍
        actual_amount = shares * price
        result.update({
            "shares": shares,
            "amount": round(actual_amount, 2),
            "capital_pct": round(actual_amount / total_capital * 100, 1),
            "risk_amount": round(actual_amount * stop_loss_pct, 2),
            "stop_loss_price": round(price * (1 - stop_loss_pct), 2),
        })

    elif method == "risk_parity":
        # 风险平价: 每笔风险金额固定
        risk_amount = total_capital * risk_per_trade
        # 从ATR或止损%计算仓位
        stop_amount = price * stop_loss_pct
        amount = risk_amount / stop_amount * price if stop_amount > 0 else 0
        shares = max(1, int(amount / price / 100) * 100)
        actual_amount = shares * price
        result.update({
            "shares": shares,
            "amount": round(actual_amount, 2),
            "capital_pct": round(actual_amount / total_capital * 100, 1),
            "risk_amount": round(risk_amount, 2),
            "stop_loss_price": round(price * (1 - stop_loss_pct), 2),
        })

    elif method == "kelly":
        # 凯利公式: f = (bp - q) / b
        # b = 盈亏比, p = 胜率, q = 1-p
        b = reward_risk_ratio
        p = win_rate
        q = 1 - p
        kelly_pct = (b * p - q) / b if b > 0 else 0
        kelly_pct = max(0, min(kelly_pct, 0.25))  # 限制上限25%

        amount = total_capital * kelly_pct
        shares = max(1, int(amount / price / 100) * 100)
        actual_amount = shares * price
        result.update({
            "shares": shares,
            "amount": round(actual_amount, 2),
            "capital_pct": round(kelly_pct * 100, 1),
            "kelly_pct": round(kelly_pct * 100, 1),
            "win_rate": win_rate,
            "reward_risk_ratio": reward_risk_ratio,
            "risk_amount": round(actual_amount * stop_loss_pct, 2),
            "stop_loss_price": round(price * (1 - stop_loss_pct), 2),
        })

    return result


# ═══════════════════════════════════════════
# 止损止盈
# ═══════════════════════════════════════════

def calc_stop_loss(code, entry_price, method="atr"):
    """
    计算止损价

    方法:
        'atr' - ATR跟踪止损 (2倍ATR)
        'fixed' - 固定比例 (默认-5%)
        'support' - 最近支撑位 (前低)
        'ma' - 均线止损 (MA20/MA60)
    """
    klines = get_kline(code, 60)
    if not klines:
        return {"entry_price": entry_price, "stop_loss": round(entry_price * 0.95, 2),
                "method": "fixed(5%)", "stop_pct": -5.0}

    closes = [k["close"] for k in klines]
    current_price = closes[-1] if closes else entry_price

    if method == "atr":
        atr = calc_atr(klines)
        if atr and atr > 0:
            sl = current_price - 2 * atr
            return {
                "entry_price": entry_price,
                "current_price": current_price,
                "stop_loss": round(sl, 2),
                "atr": round(atr, 2),
                "method": "ATR(2倍)",
                "stop_pct": round((sl - current_price) / current_price * 100, 1),
            }

    # 固定比例止损
    sl = entry_price * 0.95
    return {
        "entry_price": entry_price,
        "current_price": current_price,
        "stop_loss": round(sl, 2),
        "method": "fixed(5%)",
        "stop_pct": -5.0,
    }


def calc_take_profit(code, entry_price, method="atr"):
    """
    计算止盈价

    方法:
        'atr' - ATR跟踪止盈 (3倍ATR)
        'fixed' - 固定比例 (+15%/+30%分批)
        'resistance' - 最近阻力位
    """
    klines = get_kline(code, 60)
    if not klines:
        return {"entry_price": entry_price, "take_profit_1": round(entry_price * 1.15, 2),
                "take_profit_2": round(entry_price * 1.30, 2), "method": "fixed(15%/30%)"}

    closes = [k["close"] for k in klines]
    current_price = closes[-1] if closes else entry_price

    if method == "atr":
        atr = calc_atr(klines)
        if atr and atr > 0:
            tp1 = entry_price + atr      # 1倍ATR
            tp2 = entry_price + 2 * atr  # 2倍ATR
            tp3 = entry_price + 3 * atr  # 3倍ATR
            return {
                "entry_price": entry_price,
                "current_price": current_price,
                "take_profit_1": round(tp1, 2),
                "take_profit_2": round(tp2, 2),
                "take_profit_3": round(tp3, 2),
                "atr": round(atr, 2),
                "method": "ATR(1/2/3倍)",
                "tp1_pct": round((tp1 - entry_price) / entry_price * 100, 1),
                "tp2_pct": round((tp2 - entry_price) / entry_price * 100, 1),
                "tp3_pct": round((tp3 - entry_price) / entry_price * 100, 1),
            }

    # 固定比例分批止盈
    tp1 = entry_price * 1.15
    tp2 = entry_price * 1.30
    return {
        "entry_price": entry_price,
        "current_price": current_price,
        "take_profit_1": round(tp1, 2),
        "take_profit_2": round(tp2, 2),
        "method": "fixed(15%/30%)",
        "tp1_pct": 15.0,
        "tp2_pct": 30.0,
    }


# ═══════════════════════════════════════════
# 买卖信号
# ═══════════════════════════════════════════

def calc_signal(code):
    """
    综合买卖信号

    信号等级:
        5 - 强烈买入
        4 - 买入
        3 - 关注
        2 - 观望
        1 - 减仓
        0 - 清仓/回避
    """
    klines = get_kline(code, 60)
    if not klines or len(klines) < 30:
        return {"code": code, "signal": 0, "level": "数据不足", "score": 0}

    closes = [k["close"] for k in klines]
    current = closes[-1]

    # RSI
    def rsi(prices, period=14):
        if len(prices) < period + 1:
            return None
        gains = [max(0, prices[i] - prices[i-1]) for i in range(-period, 0)]
        losses = [max(0, prices[i-1] - prices[i]) for i in range(-period, 0)]
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        if avg_l == 0:
            return 100.0
        return 100 - 100 / (1 + avg_g / avg_l)

    rsi_val = rsi(closes)

    # MACD
    def macd(prices):
        if len(prices) < 35:
            return None, None, None
        ema_fast = [sum(prices[:12]) / 12]
        ema_slow = [sum(prices[:26]) / 26]
        kf, ks = 2 / 13, 2 / 27
        for p in prices[12:]:
            ema_fast.append((p - ema_fast[-1]) * kf + ema_fast[-1])
        for p in prices[26:]:
            ema_slow.append((p - ema_slow[-1]) * ks + ema_slow[-1])
        dif = ema_fast[-1] - ema_slow[-1]
        # 信号线 EMA9
        macd_vals = [ema_fast[i] - ema_slow[i] for i in range(len(ema_slow))]
        sig = [sum(macd_vals[:9]) / 9]
        ksig = 2 / 10
        for m in macd_vals[9:]:
            sig.append((m - sig[-1]) * ksig + sig[-1])
        return dif, sig[-1], dif - sig[-1]

    _, _, macd_hist = macd(closes)

    # 均线
    ma5 = calc_sma(closes, 5)
    ma20 = calc_sma(closes, 20)
    ma60 = calc_sma(closes, 60) if len(closes) >= 60 else None

    # 打分
    score = 50  # 中性
    reasons = []

    # RSI评分
    if rsi_val is not None:
        if rsi_val < 25:
            score += 25
            reasons.append(f"RSI={rsi_val:.0f} 严重超卖")
        elif rsi_val < 35:
            score += 15
            reasons.append(f"RSI={rsi_val:.0f} 超卖")
        elif rsi_val > 75:
            score -= 20
            reasons.append(f"RSI={rsi_val:.0f} 超买")
        elif rsi_val > 65:
            score -= 10
            reasons.append(f"RSI={rsi_val:.0f} 偏高")
        else:
            score += 5
            reasons.append(f"RSI={rsi_val:.0f} 中性")

    # MACD评分
    if macd_hist is not None:
        if macd_hist > 0:
            score += 10
            reasons.append("MACD红柱")
        else:
            score -= 5
            reasons.append("MACD绿柱")

    # 均线评分
    if ma5 and ma20:
        if ma5 > ma20:
            score += 10
            reasons.append("均线多头")
        else:
            score -= 8
            reasons.append("均线空头")

    # 趋势强度
    if ma60 and current > ma60:
        score += 8
        reasons.append("站上MA60")
    elif ma60 and current < ma60:
        score -= 5
        reasons.append("跌破MA60")

    score = max(0, min(100, score))

    # 信号等级
    if score >= 80:
        signal = 5
        level = "🔥 强烈买入"
    elif score >= 65:
        signal = 4
        level = "✅ 买入"
    elif score >= 50:
        signal = 3
        level = "👀 关注"
    elif score >= 35:
        signal = 2
        level = "⏳ 观望"
    elif score >= 20:
        signal = 1
        level = "⚠️ 减仓"
    else:
        signal = 0
        level = "❌ 清仓"

    return {
        "code": code,
        "current_price": current,
        "signal": signal,
        "level": level,
        "score": score,
        "rsi": round(rsi_val, 1) if rsi_val is not None else None,
        "macd_hist": round(macd_hist, 4) if macd_hist is not None else None,
        "ma5_ma20": "多头" if (ma5 and ma20 and ma5 > ma20) else "空头",
        "reasons": reasons,
    }


# ═══════════════════════════════════════════
# 输出格式化
# ═══════════════════════════════════════════

def format_position_report(pos):
    lines = []
    lines.append(f"\n{'='*55}")
    lines.append(f"  仓位管理  |  {pos.get('method','').upper()}")
    lines.append(f"{'='*55}")
    lines.append(f"  股价: {pos['price']:.2f}  总资金: {pos['total_capital']:.0f}")
    lines.append(f"  买入: {pos['shares']}股 = {pos['amount']:.2f} ({pos['capital_pct']}%仓位)")
    lines.append(f"  止损: {pos['stop_loss_price']} (-{pos.get('stop_loss_price', 0) / pos['price'] * 100 - 100:.1f}%)")
    lines.append(f"  风险金额: {pos['risk_amount']:.2f}")
    if "kelly_pct" in pos:
        lines.append(f"  凯利比例: {pos['kelly_pct']}% (胜率{pos['win_rate']*100:.0f}% 盈亏比{pos['reward_risk_ratio']:.1f})")
    return "\n".join(lines)


def format_signal_report(sig):
    lines = []
    lines.append(f"\n{'='*55}")
    lines.append(f"  {sig['level']}  {sig['code']}")
    lines.append(f"{'='*55}")
    lines.append(f"  价格: {sig['current_price']:.2f}  评分: {sig['score']}/100")
    lines.append(f"  RSI: {sig.get('rsi', '?')}  MACD: {sig.get('macd_hist', '?')}  均线: {sig.get('ma5_ma20', '?')}")
    if sig.get("reasons"):
        lines.append(f"  理由: {' | '.join(sig['reasons'][:3])}")
    return "\n".join(lines)


def format_stop_loss_report(sl):
    lines = []
    lines.append(f"\n{'='*55}")
    lines.append(f"  止损止盈  |  {sl.get('method','')}")
    lines.append(f"{'='*55}")
    lines.append(f"  入场价: {sl['entry_price']:.2f}  现价: {sl.get('current_price', sl['entry_price']):.2f}")
    lines.append(f"  止损: {sl['stop_loss']} ({sl.get('stop_pct', 0):+.1f}%)")
    if 'take_profit_1' in sl:
        lines.append(f"  止盈1: {sl['take_profit_1']} ({sl.get('tp1_pct', 0):+.1f}%) 卖1/3")
    if 'take_profit_2' in sl:
        lines.append(f"  止盈2: {sl['take_profit_2']} ({sl.get('tp2_pct', 0):+.1f}%) 卖1/3")
    if 'take_profit_3' in sl:
        lines.append(f"  止盈3: {sl['take_profit_3']} ({sl.get('tp3_pct', 0):+.1f}%) 趋势持有")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="交易管理模块")
    sub = parser.add_subparsers(dest="cmd")

    # position
    p = sub.add_parser("position", help="仓位计算")
    p.add_argument("--code", required=True)
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--capital", type=float, default=1000000, help="总资金(默认100万)")
    p.add_argument("--method", choices=["fixed", "risk_parity", "kelly"], default="kelly")
    p.add_argument("--win-rate", type=float, default=0.4)
    p.add_argument("--rr", type=float, default=2.0)
    p.add_argument("--json", action="store_true")

    # stop-loss
    p = sub.add_parser("stop-loss", help="止损止盈计算")
    p.add_argument("--code", required=True)
    p.add_argument("--price", type=float, required=True, help="入场价")
    p.add_argument("--method", choices=["atr", "fixed"], default="atr")
    p.add_argument("--json", action="store_true")

    # signal
    p = sub.add_parser("signal", help="买卖信号")
    p.add_argument("--code", required=True)
    p.add_argument("--json", action="store_true")

    # scan
    p = sub.add_parser("scan", help="持仓扫描")
    p.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.cmd == "position":
        pos = calc_position_size(args.price, args.capital, method=args.method,
                                  win_rate=args.win_rate, reward_risk_ratio=args.rr)
        if args.json:
            print(json.dumps(pos, ensure_ascii=False, indent=2))
        else:
            print(format_position_report(pos))

    elif args.cmd == "stop-loss":
        sl = calc_stop_loss(args.code, args.price, method=args.method)
        tp = calc_take_profit(args.code, args.price, method=args.method)
        result = {**sl, **{k: v for k, v in tp.items() if k not in sl}}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print(format_stop_loss_report(result))

    elif args.cmd == "signal":
        sig = calc_signal(args.code)
        if args.json:
            print(json.dumps(sig, ensure_ascii=False, indent=2, default=str))
        else:
            print(format_signal_report(sig))

    elif args.cmd == "scan":
        # 扫描Bitable持仓
        try:
            from bitable_reader import BitableReader
            reader = BitableReader()
            positions = reader.get_hold_positions()
        except ImportError:
            print("⚠️ 无法读取Bitable持仓")
            sys.exit(1)

        results = []
        for p in positions[:20]:  # 限20只
            code = p.stock_code
            price = p.current_price or 0
            sig = calc_signal(code)
            sl = calc_stop_loss(code, price)
            results.append({"code": code, "signal": sig, "stop_loss": sl})
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        else:
            for r in results:
                print(format_signal_report(r["signal"]))
                print(f"  止损: {r['stop_loss']['stop_loss']} | 方法: {r['stop_loss']['method']}")
            print(f"\n共扫描: {len(results)} 只持仓")

    else:
        parser.print_help()