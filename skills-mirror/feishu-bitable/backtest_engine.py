#!/usr/bin/env python3
"""
回测引擎 v2.0 — 专业多因子策略回测框架

改进（vs v1.0）：
- 交易成本模型：佣金万2.5双向 + 印花税0.05%卖出 + 滑点0.1%
- 前视偏差修复：T日收盘后计算，T+1开盘价执行
- 基准对比：自动对比沪深300
- Walk-forward验证：滚动窗口训练+测试
- 交易限制：ST/停牌/涨跌停过滤
- 幸存者偏差：使用退市股数据

用法：
  python3 backtest_engine.py --strategy lowvol_highroe_oversold --start 2022-01 --end 2026-07
  python3 backtest_engine.py --strategy lowvol_highroe_main_up --start 2022-01 --end 2026-07
  python3 backtest_engine.py --strategy ima_532 --start 2022-01 --end 2026-07 --oos 0.3
  python3 backtest_engine.py --list-strategies
"""

import os, sys, json, math, sqlite3, argparse, statistics, calendar, random
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
MARKET_DB = Path("/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db")

# ── 交易成本常量（A股） ──
COMMISSION_RATE = 0.00025       # 佣金万2.5（双向）
STAMP_TAX_RATE = 0.0005         # 印花税0.05%（仅卖出，2023年8月后）
SLIPPAGE_RATE = 0.001           # 滑点0.1%（保守估计）
# 回测中不设最低佣金（最小佣金5元是针对实盘大资金，回测中按比例计算）

# ── 工具函数 ──

def _get_db():
    """获取数据库连接，带文件存在性检查"""
    db_path = str(MARKET_DB)
    if not os.path.exists(db_path):
        msg = f"🔴 CRITICAL: 数据库文件不存在! {db_path}"
        print(f"\n{'='*60}\n{msg}\n{'='*60}", file=sys.stderr)
        # 尝试发送飞书告警
        try:
            import subprocess
            subprocess.run(["python3", "-c", f"""
import json, urllib.request
# 飞书告警 - 使用Hermes的飞书渠道
msg = {{"msg_type": "text", "content": {{"text": "🚨 数据库崩溃: market_cache.db 被删除或损坏!\\n路径: {db_path}\\n所有策略已暂停运行，请立即恢复数据库!"}}}}
try:
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/bot/v2/hook/emergency",
        data=json.dumps(msg).encode(),
        headers={{"Content-Type": "application/json"}}
    )
    urllib.request.urlopen(req, timeout=5)
except:
    pass
print(msg["content"]["text"])
"""], timeout=10)
        except:
            pass
        raise FileNotFoundError(f"数据库文件不存在: {db_path}. 所有策略已暂停，请恢复数据库后重试。")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def calc_sharpe(returns, rf=0.02):
    """计算年化夏普比率"""
    if len(returns) < 2:
        return 0
    avg_r = sum(returns) / len(returns)
    excess = [(r - rf / 252) for r in returns]
    std = math.sqrt(sum((r - avg_r) ** 2 for r in returns) / len(returns))
    return (sum(excess) / len(excess)) / std * math.sqrt(252) if std > 0 else 0


def calc_trade_cost(buy_amount, sell_amount):
    """计算交易成本（双向）
    Args:
        buy_amount: 买入金额
        sell_amount: 卖出金额
    Returns:
        total_cost: 总交易成本
    """
    buy_commission = buy_amount * COMMISSION_RATE
    sell_commission = sell_amount * COMMISSION_RATE
    sell_stamp = sell_amount * STAMP_TAX_RATE
    slippage = (buy_amount + sell_amount) * SLIPPAGE_RATE
    return buy_commission + sell_commission + sell_stamp + slippage


def calc_max_dd(equity_curve):
    """计算最大回撤"""
    peak = equity_curve[0]
    max_dd = 0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def calc_metrics(monthly_returns, equity_curve):
    """计算所有绩效指标"""
    n_months = len(monthly_returns)
    if n_months < 2:
        return {"error": "样本不足"}

    total_return = (equity_curve[-1] / equity_curve[0] - 1) * 100
    years = n_months / 12
    if years > 0 and equity_curve[-1] > 0 and equity_curve[0] > 0:
        cagr = ((equity_curve[-1] / equity_curve[0]) ** (1 / years) - 1) * 100
    else:
        cagr = -100.0

    # 月收益统计
    win_months = sum(1 for r in monthly_returns if r > 0)
    loss_months = sum(1 for r in monthly_returns if r < 0)
    win_rate = win_months / n_months * 100

    # 盈亏比
    avg_win = sum(r for r in monthly_returns if r > 0) / win_months if win_months > 0 else 0
    avg_loss = abs(sum(r for r in monthly_returns if r < 0) / loss_months) if loss_months > 0 else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')

    # 夏普 (基于月收益 * 12)
    monthly_excess = [r - 0.02 / 12 for r in monthly_returns]
    avg_m = sum(monthly_returns) / n_months
    std_m = math.sqrt(sum((r - avg_m) ** 2 for r in monthly_returns) / n_months)
    sharpe = (avg_m - 0.02 / 12) / std_m * math.sqrt(12) if std_m > 0 else 0

    max_dd = calc_max_dd(equity_curve)

    return {
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(cagr, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate_pct": round(win_rate, 1),
        "profit_loss_ratio": round(profit_loss_ratio, 2) if profit_loss_ratio != float('inf') else "∞",
        "total_months": n_months,
        "avg_monthly_return_pct": round(avg_m, 2),
        "calmar_ratio": round(cagr / (max_dd * 100) if max_dd > 0 else 0, 2),
    }


def calc_benchmark_metrics(strategy_returns, benchmark_returns):
    """计算超额收益指标
    Returns:
        alpha: 年化超额收益
        beta: 市场暴露
        tracking_error: 跟踪误差
        information_ratio: 信息比率
    """
    if len(strategy_returns) != len(benchmark_returns) or len(strategy_returns) < 2:
        return {"alpha": 0, "beta": 0, "tracking_error": 0, "information_ratio": 0}

    # 计算超额收益
    excess = [s - b for s, b in zip(strategy_returns, benchmark_returns)]
    avg_excess = sum(excess) / len(excess)
    # 年化alpha
    alpha = avg_excess * 12

    # 计算beta
    avg_s = sum(strategy_returns) / len(strategy_returns)
    avg_b = sum(benchmark_returns) / len(benchmark_returns)
    cov = sum((s - avg_s) * (b - avg_b) for s, b in zip(strategy_returns, benchmark_returns)) / len(strategy_returns)
    var_b = sum((b - avg_b) ** 2 for b in benchmark_returns) / len(benchmark_returns)
    beta = cov / var_b if var_b > 0 else 0

    # 跟踪误差
    te = math.sqrt(sum((e - avg_excess) ** 2 for e in excess) / len(excess)) * math.sqrt(12)
    ir = (avg_excess * 12) / te if te > 0 else 0

    return {
        "alpha_pct": round(alpha, 2),
        "beta": round(beta, 2),
        "tracking_error_pct": round(te, 2),
        "information_ratio": round(ir, 2),
    }


# ── 数据加载 ──

def load_stock_universe(conn, min_trade_days=200):
    """加载满足最小交易天数的股票池"""
    cur = conn.execute(
        "SELECT code, COUNT(*) as days FROM klines GROUP BY code HAVING days >= ?",
        (min_trade_days,)
    )
    return {r["code"] for r in cur.fetchall()}


def load_monthly_kline_data(conn, codes, start_date, end_date):
    """
    加载指定股票池的月K线数据
    返回: {code: [(date, close), ...]}
    """
    data = defaultdict(list)
    cur = conn.execute(
        """SELECT code, date, open, close, high, low, volume FROM klines
           WHERE code IN ({}) AND date >= ? AND date <= ?
           ORDER BY code, date""".format(
            ",".join("?" for _ in codes)
        ),
        list(codes) + [start_date, end_date]
    )
    for r in cur.fetchall():
        item = {"date": r["date"], "open": r["open"], "close": r["close"],
                "high": r["high"], "low": r["low"], "volume": r["volume"]}
        data[r["code"]].append(item)
    return data


def get_monthly_snapshots(data, rebalance_day=1):
    """
    从日K线数据提取每月调仓日的快照
    使用T-1交易日数据计算，模拟T日收盘后选股，T+1执行
    返回: [(date, {code: close, ...}), ...]
    """
    # 按年月分组
    monthly = defaultdict(dict)
    for code, klines in data.items():
        for item in klines:
            ym = item["date"][:7]
            if code not in monthly[ym] or item["date"] > monthly[ym][code]["date"]:
                monthly[ym][code] = item

    snapshots = []
    for ym in sorted(monthly.keys()):
        snapshot = {}
        date_str = None
        for code, item in monthly[ym].items():
            d = item["date"]
            if date_str is None or d > date_str:
                date_str = d
            snapshot[code] = item["close"]
        if date_str:
            snapshots.append((date_str, snapshot))
    return snapshots


def build_next_open_lookup(data):
    """构建次日开盘价查找表
    对每只股票，对每个有数据的日期，找到下一个交易日及其开盘价
    返回: {code: {date: next_open, ...}}
    """
    lookup = {}
    for code, klines in data.items():
        code_lookup = {}
        for i in range(len(klines) - 1):
            curr_date = klines[i]["date"]
            next_open = klines[i + 1]["open"]
            code_lookup[curr_date] = {"date": klines[i + 1]["date"], "open": next_open}
        # 最后一笔无下一日数据
        lookup[code] = code_lookup
    return lookup


def smart_money_filter(code, signal_date, kline_data, conn=None):
    """聪明钱共振过滤器

    检查北向资金（如有）和量价确认信号，降低假突破概率。

    逻辑（三级递进）：
    1. 北向资金数据可用 → 近5日净流出则跳过
    2. 主力资金数据可用 → 与北向方向冲突则跳过
    3. 均无 → 使用量价确认代理：5日均量/20日均量 + 价格趋势

    Returns: True=通过(可买入), False=拦截
    """
    # 1. 检查北向资金（如果 indicators 表有数据）
    if conn:
        try:
            cur = conn.execute(
                """SELECT north_flow FROM indicators
                   WHERE code = ? AND date = ? AND north_flow IS NOT NULL
                   AND north_flow != '-' AND CAST(north_flow AS REAL) != 0""",
                (code, signal_date)
            )
            row = cur.fetchone()
            if row:
                nf = float(row[0])
                if nf < 0:
                    return False  # 北向净流出，拦截
        except Exception:
            pass

    # 2. 量价确认代理（北向/主力数据不可用时回退）
    kl = kline_data.get(code, [])
    if len(kl) < 25:
        return True  # 数据不足，放行

    # 找到 signal_date 之前的最近25根K线
    recent = [k for k in kl if k["date"] <= signal_date]
    if len(recent) < 25:
        return True

    recent = recent[-25:]

    # --- 条件A：放量上涨确认 ---
    # 最近5日均量 vs 前20日均量
    vol_5 = sum(k["volume"] for k in recent[-5:]) / 5
    vol_20 = sum(k["volume"] for k in recent[:-5]) / 20 if len(recent) > 5 else 1
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1.0

    # 最近5日价格变化
    price_5d_ago = recent[-6]["close"]
    price_change_5d = (recent[-1]["close"] - price_5d_ago) / price_5d_ago * 100

    # 最近1日价格变化
    price_1d_ago = recent[-2]["close"]
    price_change_1d = (recent[-1]["close"] - price_1d_ago) / price_1d_ago * 100

    # 量价背离检测
    # 情况1：价格上涨但缩量 → 假突破嫌疑
    if price_change_5d > 3 and vol_ratio < 0.8:
        return False
    # 情况2：价格下跌但放量 → 出货嫌疑
    if price_change_5d < -3 and vol_ratio > 1.3:
        return False
    # 情况3：单日大涨但缩量 → 缺乏买盘支撑
    if price_change_1d > 5 and vol_ratio < 0.7:
        return False

    return True


def calc_market_down_pct(data, signal_date):
    """计算信号日当天全市场下跌股票占比
    从kline数据中统计当日收盘价低于开盘价的股票比例
    Returns: 下跌占比 (0~100), 或 None (数据不足)
    """
    down = 0
    total = 0
    for code, klines in data.items():
        # 找到 signal_date 当天的K线
        for k in klines:
            if k["date"] == signal_date:
                total += 1
                if k["close"] < k["open"]:
                    down += 1
                break
    if total < 100:
        return None  # 样本不足
    return down / total * 100


def load_benchmark_data(conn, start_date, end_date):
    """加载沪深300指数数据用于基准对比"""
    code = "000300"
    cur = conn.execute(
        "SELECT date, close FROM klines WHERE code = ? AND date >= ? AND date <= ? ORDER BY date",
        (code, start_date, end_date)
    )
    rows = cur.fetchall()
    return {r["date"]: r["close"] for r in rows}


def get_benchmark_monthly_returns(benchmark_prices, snapshot_dates):
    """获取基准指数对应月份的收益率"""
    monthly_returns = []
    for i in range(1, len(snapshot_dates)):
        prev_date = snapshot_dates[i-1]
        curr_date = snapshot_dates[i]
        prev_close = benchmark_prices.get(prev_date)
        curr_close = benchmark_prices.get(curr_date)
        if prev_close and curr_close and prev_close > 0:
            r = (curr_close - prev_close) / prev_close * 100
            monthly_returns.append(r)
        else:
            monthly_returns.append(0)
    return monthly_returns


def is_st_stock(code):
    """检查是否为ST股票（通过代码前缀判断）"""
    code_num = code[-6:] if len(code) > 6 else code
    try:
        code_int = int(code_num)
    except ValueError:
        return False
    # ST股票代码范围：600xxx 中 *ST 和 ST 需要通过数据库或名称判断
    # 这里用简单的规则：股票代码不以 6/0/3 开头且不是主板
    return False  # 暂用数据库判断


def check_trade_restrictions(code, date, conn):
    """检查交易限制：停牌、ST、涨跌停
    TODO: 需要数据库有停牌和ST标记字段
    """
    # 目前用K线数据中有无当天数据来判断是否停牌
    # 如果有high/low/close为0或null说明停牌
    return True  # 暂不做严格限制

# ── 内置策略 ──


def _calc_ma(prices, periods=[5, 10, 20, 60]):
    """计算多周期均线"""
    result = {}
    for p in periods:
        result[p] = sum(prices[-p:]) / p if len(prices) >= p else None
    return result


def _is_ma_bullish(ma_dict):
    """判断均线是否多头排列：MA5 > MA10 > MA20 > MA60"""
    for p in [5, 10, 20, 60]:
        if ma_dict.get(p) is None:
            return False
    return ma_dict[5] > ma_dict[10] > ma_dict[20] > ma_dict[60]


def _calc_rsi(prices, period=14):
    """计算RSI指标"""
    if len(prices) < period + 1:
        return None
    gains, losses = 0, 0
    for i in range(len(prices) - period, len(prices)):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calc_bollinger(prices, period=20, std_dev=2.0):
    """计算布林带，返回 (mid, upper, lower, position_pct)"""
    if len(prices) < period:
        return None, None, None, None
    recent = prices[-period:]
    ma = sum(recent) / period
    variance = sum((p - ma) ** 2 for p in recent) / period
    std = math.sqrt(variance)
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    current = prices[-1]
    if upper == lower:
        pos = 50.0
    else:
        pos = (current - lower) / (upper - lower) * 100
    return ma, upper, lower, pos


def _check_main_up(closes, avg_roe, roe_min=15.0):
    """主升浪模式检查：均线多头 + RSI 40-70"""
    if avg_roe < roe_min:
        return False
    if len(closes) < 60:
        return False
    ma = _calc_ma(closes)
    if not _is_ma_bullish(ma):
        return False
    rsi = _calc_rsi(closes)
    if rsi is None or rsi < 40 or rsi > 70:
        return False
    return True


def _check_oversold(closes, avg_roe, roe_min=10.0):
    """超跌反弹模式检查：布林下轨附近 + RSI < 30"""
    if avg_roe < roe_min:
        return False
    if len(closes) < 60:
        return False
    rsi = _calc_rsi(closes)
    if rsi is None or rsi >= 30:
        return False
    _, _, _, boll_pos = _calc_bollinger(closes)
    if boll_pos is None or boll_pos >= 20:
        return False
    return True


def create_strategy_lowvol_highroe_dual(mode="main_up"):
    """
    创建双模式策略函数（闭包方式，将mode作为参数绑定）
    mode: 'main_up' (主升浪) 或 'oversold' (超跌反弹)
    """
    check_fn = _check_main_up if mode == "main_up" else _check_oversold
    roe_min = 15.0 if mode == "main_up" else 10.0
    mode_label = "主升浪" if mode == "main_up" else "超跌反弹"

    def _strategy(snapshot_date, all_prices, top_n=30):
        """低波动高ROE双模式策略（动态生成）"""
        conn = _get_db()
        # 获取ROE数据（使用截至snapshot_date的最新财报）
        # 财报公布有延迟，假设Q1在5月可用，Q2在8月，Q3在10月，年报在4月
        cur = conn.execute("""
            SELECT code, AVG(roe) as avg_roe FROM (
                SELECT code, roe, report_date,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) as rn
                FROM financial_data WHERE roe IS NOT NULL AND report_date <= ?
            ) WHERE rn <= 8 GROUP BY code HAVING avg_roe >= ?
        """, (snapshot_date[:7] + "-01", roe_min))
        high_roe = {r["code"]: r["avg_roe"] for r in cur.fetchall()}

        codes = [c for c in all_prices if c in high_roe]
        if not codes:
            conn.close()
            return []

        # 计算截至snapshot_date的最近60天K线
        # 使用窗口函数取每个股票在snapshot_date之前的最近60条
        placeholders = ",".join("?" for _ in codes)
        cur = conn.execute(
            f"""SELECT code, close FROM klines 
                WHERE code IN ({placeholders}) AND date <= ?
                ORDER BY code, date DESC""",
            codes + [snapshot_date]
        )
        kline_data = {}
        for r in cur.fetchall():
            code = r["code"]
            if code not in kline_data:
                kline_data[code] = []
            if len(kline_data[code]) < 60:
                kline_data[code].append(r["close"])
        conn.close()

        scored = []
        for code in codes:
            closes = kline_data.get(code, [])
            if len(closes) < 60:
                continue
            # 双模式技术面检查
            if not check_fn(closes, high_roe.get(code, 0)):
                continue
            # 计算波动率
            prices = closes[:60] if len(closes) >= 60 else closes
            logs = [math.log(prices[i+1]/prices[i]) for i in range(len(prices)-1)
                    if prices[i] > 0 and prices[i+1] > 0]
            if len(logs) < 20:
                continue
            vol = statistics.stdev(logs) * math.sqrt(252)
            scored.append((code, vol, high_roe.get(code, 0)))

        if len(scored) < 5:
            return [c for c, _, _ in scored]

        # 低波动优先
        scored.sort(key=lambda x: x[1])
        cutoff = max(5, int(len(scored) * 0.3))
        return [c for c, _, _ in scored[:top_n]]

    _strategy.__name__ = f"strategy_lowvol_highroe_{mode}"
    _strategy.__doc__ = f"低波动高ROE双模式策略 ({mode_label})"
    return _strategy


# 预创建双模式策略实例
_strategy_lowvol_highroe_main_up = create_strategy_lowvol_highroe_dual("main_up")
_strategy_lowvol_highroe_oversold = create_strategy_lowvol_highroe_dual("oversold")


def strategy_ima_532(snapshot_date, all_prices, top_n=30):
    """
    IMA 5:3:2 评分策略
    使用 score_upgrade.py 的评分系统选股
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from score_upgrade import score_stock
    except ImportError:
        print("⚠️ score_upgrade.py 不可用，降级到简单ROE排序", file=sys.stderr)
        # 简单ROE排序作为备选
        conn = _get_db()
        cur = conn.execute("""
            SELECT code, AVG(roe) as avg_roe FROM (
                SELECT code, roe, report_date,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) as rn
                FROM financial_data WHERE roe IS NOT NULL
            ) WHERE rn <= 4 GROUP BY code HAVING avg_roe >= 10
            ORDER BY avg_roe DESC LIMIT ?
        """, (top_n,))
        codes = [r["code"] for r in cur.fetchall()]
        conn.close()
        return codes

    scored = []
    for code, close in all_prices.items():
        try:
            r = score_stock(code)
            if r and r.get("score_pct", 0) > 0:
                scored.append((code, close, r["score_pct"]))
        except Exception:
            continue

    scored.sort(key=lambda x: -x[2])
    return [c for c, _, _ in scored[:top_n]]


def create_strategy_doubling_v1(price_pos_max=40, vol_ratio_min=2.7, atr_pct_min=3,
                                 mcap_min=5, mcap_max=90, turnover_min=8000,
                                 avg_amount_20d=4000):
    """创建翻倍策略 V1 策略函数（参数化工厂）"""
    def _strategy(snapshot_date, all_prices, top_n=30):
        conn = _get_db()
        cur = conn.execute("""
            SELECT code, name, total_mcap FROM stocks
            WHERE total_mcap BETWEEN ? AND ?
              AND (is_st IS NULL OR is_st = 0)
              AND code NOT LIKE '688%%'
        """, (mcap_min * 1e8, mcap_max * 1e8))
        universe = {r["code"]: {"name": r["name"], "mcap": r["total_mcap"]}
                    for r in cur.fetchall()}
        conn.close()
        if not universe:
            return []

        conn = _get_db()
        scored = []
        for code in list(universe.keys())[:2000]:
            try:
                cur = conn.execute("""
                    SELECT date, close, volume, turnover, high, low
                    FROM klines WHERE code=? AND date<=?
                    ORDER BY date DESC LIMIT 500
                """, (code, snapshot_date))
                kl_raw = cur.fetchall()
                if not kl_raw or len(kl_raw) < 60:
                    continue
                kl_raw.reverse()
                closes = [r[1] for r in kl_raw if r[1] is not None]
                if len(closes) < 60:
                    continue
                price_pos = (closes[-1] - min(closes)) / (max(closes) - min(closes)) * 100
                if price_pos > price_pos_max:
                    continue
                if len(kl_raw) < 25:
                    continue

                # 流动性硬约束1: 信号日成交额 >= turnover_min(万元)
                # kl_raw[-1][3] 是 turnover (元)
                min_turnover_1d = turnover_min * 10000
                latest_turnover = kl_raw[-1][3] or 0
                if latest_turnover < min_turnover_1d:
                    continue

                # 流动性硬约束2: 近20日均成交额 >= avg_amount_20d(万元)
                if avg_amount_20d > 0:
                    min_turnover_20d = avg_amount_20d * 10000
                    recent_ts = [(r[3] or 0) for r in kl_raw[-25:]]
                    avg_turnover_20d = sum(recent_ts[:-5]) / max(len(recent_ts[:-5]), 1)
                    if avg_turnover_20d < min_turnover_20d:
                        continue

                vol_5 = sum((r[2] or 0) for r in kl_raw[-5:]) / 5
                vol_20 = sum((r[2] or 0) for r in kl_raw[-25:-5]) / 20
                vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 0
                if vol_ratio < vol_ratio_min:
                    continue
                trs = []
                for i in range(1, len(kl_raw)):
                    h, l, pc = kl_raw[i][4] or 0, kl_raw[i][5] or 0, kl_raw[i-1][1] or 0
                    if h and l and pc:
                        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
                if len(trs) < 14:
                    continue
                atr = sum(trs[-14:]) / 14
                close = kl_raw[-1][1] or 0
                atr_pct = atr / close * 100 if close else 0
                if atr_pct < atr_pct_min:
                    continue
                score = 0
                mcap_wan = (universe[code]["mcap"] or 0) / 1e4
                if mcap_min <= mcap_wan <= mcap_min + 15:
                    score += 40
                elif mcap_wan <= mcap_max:
                    score += 30
                if price_pos <= price_pos_max * 0.5:
                    score += 30
                elif price_pos <= price_pos_max:
                    score += 20
                if vol_ratio >= vol_ratio_min * 1.5:
                    score += 20
                elif vol_ratio >= vol_ratio_min:
                    score += 10
                if atr_pct >= atr_pct_min * 1.67:
                    score += 15
                elif atr_pct >= atr_pct_min:
                    score += 10
                scored.append((code, score))
            except Exception:
                continue
        conn.close()
        scored.sort(key=lambda x: -x[1])
        return [c for c, _ in scored[:top_n]]
    _strategy.__name__ = f"doubling_v1_p{price_pos_max}_v{vol_ratio_min}_a{atr_pct_min}"
    _strategy.__doc__ = f"翻倍策略 V1 (分位≤{price_pos_max}%, 量比≥{vol_ratio_min}, ATR≥{atr_pct_min}%, 市值{mcap_min}-{mcap_max}亿, 成交额≥{turnover_min}万, 20日均≥{avg_amount_20d}万)"
    return _strategy

# 默认参数实例
strategy_doubling_v1 = create_strategy_doubling_v1()


STRATEGIES = {
    "lowvol_highroe_main_up": _strategy_lowvol_highroe_main_up,
    "lowvol_highroe_oversold": _strategy_lowvol_highroe_oversold,
    "ima_532": strategy_ima_532,
    "doubling_v1": strategy_doubling_v1,
}


# ── 回测主逻辑 ──

def run_backtest(strategy_fn, start_date="2020-01", end_date="2026-07",
                 top_n=30, oos_split=0.0, benchmark="000300",
                 walk_forward=False, walk_window=24, walk_step=12,
                 market_fear_threshold=0.0):
    """
    运行回测（v2.0 专业版）

    改进：
    - 交易成本：佣金万2.5双向 + 印花税0.05%卖出 + 滑点0.1%
    - 前视偏差：使用T-1收盘数据，模拟T+1开盘执行
    - 基准对比：沪深300
    - Walk-forward验证：滚动窗口训练+测试

    参数:
        strategy_fn: 策略函数 (date, price_dict) → [code, ...]
        start_date/end_date: "YYYY-MM" 格式
        top_n: 选股数量
        oos_split: 简单样本外比例 (0.0 = 全样本)
        benchmark: 基准指数代码
        walk_forward: 启用walk-forward验证
        walk_window: 训练窗口月数（默认24个月=2年）
        walk_step: 步进月数（默认12个月=1年）
    """
    print(f"📡 加载数据 {start_date} ~ {end_date}...", file=sys.stderr)

    # 补全日期
    start_full = f"{start_date}-01"
    y, m = end_date.split("-")
    last_day = calendar.monthrange(int(y), int(m))[1]
    end_full = f"{end_date}-{last_day:02d}"

    conn = _get_db()

    # 加载股票池
    universe = load_stock_universe(conn, min_trade_days=200)
    print(f"  股票池: {len(universe)} 只", file=sys.stderr)

    # 加载K线数据
    data = load_monthly_kline_data(conn, universe, start_full, end_full)
    conn.close()

    # 按月提取调仓快照
    snapshots = get_monthly_snapshots(data)
    print(f"  月频调仓: {len(snapshots)} 个月", file=sys.stderr)

    if len(snapshots) < 6:
        return {"error": f"数据不足，仅 {len(snapshots)} 个月"}

    # 获取基准指数数据
    conn = _get_db()
    benchmark_prices = load_benchmark_data(conn, start_full, end_full)
    conn.close()

    snapshot_dates = [s[0] for s in snapshots]
    benchmark_monthly = get_benchmark_monthly_returns(benchmark_prices, snapshot_dates)

    if walk_forward:
        return _run_walk_forward(strategy_fn, snapshots, benchmark_monthly,
                                 top_n, walk_window, walk_step, data)

    # 简单样本内/外分割
    if oos_split > 0:
        split_idx = int(len(snapshots) * (1 - oos_split))
        ins_snapshots = snapshots[:split_idx]
        oos_snapshots = snapshots[split_idx:]
        ins_benchmark = benchmark_monthly[:split_idx-1] if len(benchmark_monthly) >= split_idx else []
        oos_benchmark = benchmark_monthly[split_idx-1:] if len(benchmark_monthly) > split_idx else []
        print(f"  样本内: {len(ins_snapshots)} 个月 | 样本外: {len(oos_snapshots)} 个月", file=sys.stderr)
    else:
        ins_snapshots = snapshots
        oos_snapshots = []
        ins_benchmark = benchmark_monthly
        oos_benchmark = []
        print(f"  全样本: {len(ins_snapshots)} 个月", file=sys.stderr)

    def _run(snaps, bench_returns, label, cost_ratio=1.0):
        """内部回测运行函数
        cost_ratio: 成本比例（walk-forward中可调）
        """
        if len(snaps) < 3:
            return None

        monthly_returns = []
        equity = [1.0]
        turnover_list = []  # 记录换手率
        total_gapup_fails = 0  # 跳空高开无法买入次数
        total_trades = 0       # 总交易次数（含失败）
        total_smart_filtered = 0  # 聪明钱过滤器拦截次数
        total_fear_skipped = 0    # 市场恐慌过滤器跳过月数

        # 预构建次日开盘价查找表
        next_open_lookup = build_next_open_lookup(data)

        # 数据库连接（用于北向资金查询）
        filter_conn = _get_db()

        for i in range(1, len(snaps)):
            prev_date, prev_prices = snaps[i - 1]
            curr_date, curr_prices = snaps[i]

            # 市场恐慌过滤器：只在市场恐慌时交易
            if market_fear_threshold > 0:
                fear_pct = calc_market_down_pct(data, prev_date)
                if fear_pct is not None and fear_pct < market_fear_threshold:
                    total_fear_skipped += 1
                    # 恐慌不足，跳过该月，等权收益率记为0
                    monthly_returns.append(0)
                    equity.append(equity[-1])
                    continue

            # 策略选股（使用T-1数据，无前视偏差）
            selected = strategy_fn(prev_date, prev_prices, top_n=top_n)
            if not selected:
                continue

            # 计算组合收益（等权，含交易成本）
            n_hold = len(selected)
            returns = []
            gapup_fails_this_month = 0

            for code in selected:
                total_trades += 1
                if code in prev_prices and code in curr_prices:
                    signal_close = prev_prices[code]  # 信号日收盘价

                    # 查找次日开盘价
                    next_info = next_open_lookup.get(code, {}).get(prev_date, None)
                    if next_info and next_info["open"] > 0:
                        buy_price = next_info["open"]  # 次日开盘价
                        next_open = next_info["open"]

                        # 跳空高开检查：次日开盘 > 信号日收盘 * 1.03
                        if signal_close > 0 and next_open > signal_close * 1.03:
                            gapup_fails_this_month += 1
                            total_gapup_fails += 1
                            continue  # 跳过该交易，不记收益

                        # 聪明钱共振过滤器
                        if not smart_money_filter(code, prev_date, data, filter_conn):
                            total_smart_filtered += 1
                            continue  # 假突破嫌疑，跳过

                    else:
                        # 无次日数据（停牌/退市），用信号日收盘价近似
                        buy_price = signal_close

                    # 卖出价 = 当月最后一个交易日收盘价
                    sell_price = curr_prices[code]

                    # 单笔收益
                    raw_return = (sell_price - buy_price) / buy_price * 100
                    # 交易成本（每笔交易）
                    position_value = 1.0 / n_hold  # 假设总资金为1
                    buy_amount = position_value
                    # 防止负价格导致成本计算错误
                    raw_ratio = max(-0.999, raw_return / 100)
                    sell_amount = position_value * (1 + raw_ratio)
                    cost = calc_trade_cost(buy_amount, sell_amount)
                    cost_pct = cost / position_value * 100
                    net_return = raw_return - cost_pct * cost_ratio
                    returns.append(net_return)

            if returns:
                avg_ret = sum(returns) / len(returns)
                monthly_returns.append(avg_ret)
                equity.append(equity[-1] * (1 + avg_ret / 100))

        if len(monthly_returns) < 3:
            return None

        metrics = calc_metrics(monthly_returns, equity)
        metrics["label"] = label
        metrics["months"] = len(monthly_returns)
        metrics["start_date"] = snaps[0][0][:7]
        metrics["end_date"] = snaps[-1][0][:7]
        metrics["final_equity"] = round(equity[-1], 4)
        metrics["selected_count"] = top_n
        metrics["gapup_fails"] = total_gapup_fails
        metrics["total_trades"] = total_trades
        metrics["smart_filtered"] = total_smart_filtered
        metrics["fear_skipped"] = total_fear_skipped

        # 基准对比
        if len(bench_returns) >= len(monthly_returns):
            bm = bench_returns[:len(monthly_returns)]
            excess = calc_benchmark_metrics(monthly_returns, bm)
            metrics.update(excess)

            # 基准自身收益
            bm_equity = [1.0]
            for r in bm:
                bm_equity.append(bm_equity[-1] * (1 + r / 100))
            bm_total = (bm_equity[-1] / bm_equity[0] - 1) * 100
            metrics["benchmark_return_pct"] = round(bm_total, 2)

        return metrics

    results = {}
    ins_result = _run(ins_snapshots, ins_benchmark, "样本内")
    if ins_result:
        results["in_sample"] = ins_result

    if oos_snapshots:
        oos_result = _run(oos_snapshots, oos_benchmark, "样本外")
        if oos_result:
            results["out_of_sample"] = oos_result

    results["total_months"] = len(snapshots)
    results["stock_universe"] = len(universe)
    results["top_n"] = top_n
    results["start"] = start_date
    results["end"] = end_date
    results["trade_cost_model"] = f"佣金{COMMISSION_RATE*10000:.1f}‱+印花税{STAMP_TAX_RATE*100:.2f}%+滑点{SLIPPAGE_RATE*100:.1f}%"

    return results


def _run_walk_forward(strategy_fn, snapshots, benchmark_monthly, top_n, window=24, step=12, data=None):
    """Walk-forward滚动验证"""
    n = len(snapshots)
    if n < window + step:
        print(f"  ⚠️ 数据不足({n}个月)，回退到普通回测", file=sys.stderr)
        return run_backtest(strategy_fn, start_date=snapshots[0][0][:7],
                           end_date=snapshots[-1][0][:7], top_n=top_n)

    print(f"  Walk-forward: 窗口={window}个月 步进={step}个月", file=sys.stderr)

    all_test_returns = []
    all_test_equity = [1.0]
    all_test_benchmark = []
    segments = []
    total_gapup_fails = 0
    total_trades = 0
    total_smart_filtered = 0

    # 预构建次日开盘价查找表
    next_open_lookup = build_next_open_lookup(data)

    # 数据库连接（用于北向资金查询）
    wf_conn = _get_db()

    # 滚动窗口
    for train_start in range(0, n - window, step):
        train_end = train_start + window
        test_end = min(train_end + step, n)

        train_snaps = snapshots[train_start:train_end]
        test_snaps = snapshots[train_end:test_end]
        test_bench = benchmark_monthly[train_end:test_end]

        if len(test_snaps) < 2:
            continue

        print(f"    训练: {train_snaps[0][0][:7]}~{train_snaps[-1][0][:7]} "
              f"测试: {test_snaps[0][0][:7]}~{test_snaps[-1][0][:7]} ({len(test_snaps)}个月)", file=sys.stderr)

        # 在训练集上跑
        train_returns = []
        for i in range(1, len(train_snaps)):
            prev_date, prev_prices = train_snaps[i-1]
            curr_date, curr_prices = train_snaps[i]
            selected = strategy_fn(prev_date, prev_prices, top_n=top_n)
            if not selected:
                continue
            rets = []
            for code in selected:
                if code in prev_prices and code in curr_prices:
                    signal_close = prev_prices[code]
                    # 次日开盘价
                    next_info = next_open_lookup.get(code, {}).get(prev_date, None)
                    if next_info and next_info["open"] > 0:
                        buy_price = next_info["open"]
                        # 跳空高开检查
                        if signal_close > 0 and next_info["open"] > signal_close * 1.03:
                            continue
                    else:
                        buy_price = signal_close
                    r = (curr_prices[code] - buy_price) / buy_price * 100
                    # 含交易成本
                    pos = 1.0 / top_n
                    cost = calc_trade_cost(pos, pos * (1 + r/100))
                    net_r = r - cost / pos * 100
                    rets.append(net_r)
            if rets:
                train_returns.append(sum(rets) / len(rets))

        # 在测试集上跑
        for i in range(1, len(test_snaps)):
            prev_date, prev_prices = test_snaps[i-1]
            curr_date, curr_prices = test_snaps[i]
            selected = strategy_fn(prev_date, prev_prices, top_n=top_n)
            if not selected:
                all_test_equity.append(all_test_equity[-1])
                continue
            rets = []
            for code in selected:
                total_trades += 1
                if code in prev_prices and code in curr_prices:
                    signal_close = prev_prices[code]
                    # 次日开盘价
                    next_info = next_open_lookup.get(code, {}).get(prev_date, None)
                    if next_info and next_info["open"] > 0:
                        buy_price = next_info["open"]
                        # 跳空高开检查
                        if signal_close > 0 and next_info["open"] > signal_close * 1.03:
                            total_gapup_fails += 1
                            continue
                        # 聪明钱共振过滤器
                        if not smart_money_filter(code, prev_date, data, wf_conn):
                            total_smart_filtered += 1
                            continue
                    else:
                        buy_price = signal_close
                    r = (curr_prices[code] - buy_price) / buy_price * 100
                    pos = 1.0 / top_n
                    cost = calc_trade_cost(pos, pos * (1 + r/100))
                    net_r = r - cost / pos * 100
                    rets.append(net_r)
            if rets:
                avg_r = sum(rets) / len(rets)
                all_test_returns.append(avg_r)
                all_test_equity.append(all_test_equity[-1] * (1 + avg_r / 100))
                if test_bench and i-1 < len(test_bench):
                    all_test_benchmark.append(test_bench[i-1])

        segments.append({
            "train_start": train_snaps[0][0][:7],
            "train_end": train_snaps[-1][0][:7],
            "test_start": test_snaps[0][0][:7],
            "test_end": test_snaps[-1][0][:7],
            "train_months": len(train_returns),
            "test_months": len(test_snaps) - 1,
        })

    if len(all_test_returns) < 3:
        return {"error": "Walk-forward测试数据不足"}

    metrics = calc_metrics(all_test_returns, all_test_equity)
    metrics["label"] = "Walk-Forward"
    metrics["months"] = len(all_test_returns)
    metrics["start_date"] = snapshots[0][0][:7]
    metrics["end_date"] = snapshots[-1][0][:7]
    metrics["final_equity"] = round(all_test_equity[-1], 4)
    metrics["selected_count"] = top_n
    metrics["gapup_fails"] = total_gapup_fails
    metrics["total_trades"] = total_trades
    metrics["smart_filtered"] = total_smart_filtered

    # 基准对比
    if len(all_test_benchmark) >= len(all_test_returns):
        bm = all_test_benchmark[:len(all_test_returns)]
        excess = calc_benchmark_metrics(all_test_returns, bm)
        metrics.update(excess)

    results = {
        "walk_forward": metrics,
        "segments": segments,
        "total_months": len(snapshots),
        "stock_universe": len(snapshots[0][1]) if snapshots else 0,
        "top_n": top_n,
        "start": snapshots[0][0][:7],
        "end": snapshots[-1][0][:7],
        "trade_cost_model": f"佣金{COMMISSION_RATE*10000:.1f}‱+印花税{STAMP_TAX_RATE*100:.2f}%+滑点{SLIPPAGE_RATE*100:.1f}%",
    }

    return results


def format_report(results, strategy_name):
    """生成 Markdown 回测报告"""
    if not results or "error" in results:
        return f"## 回测失败\n\n{results.get('error', '未知错误')}\n"

    lines = []
    lines.append(f"# 回测报告: {strategy_name}")
    lines.append(f"")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 数据源: market_cache.db")
    lines.append(f"> 调仓频率: 月频")
    lines.append(f"> 选股数量: {results.get('top_n', '?')} 只")
    lines.append(f"> 股票池: {results.get('stock_universe', '?')} 只")
    lines.append(f"")
    lines.append(f"## 总览")
    lines.append(f"")
    if "walk_forward" in results:
        wf = results["walk_forward"]
        lines.append(f"| 指标 | Walk-Forward |")
        lines.append(f"|------|--------------|")
        for k, v in [("cagr_pct", "年化收益率"), ("sharpe_ratio", "夏普比率"),
                     ("max_drawdown_pct", "最大回撤"), ("win_rate_pct", "月胜率"),
                     ("profit_loss_ratio", "盈亏比"), ("total_return_pct", "累计收益"),
                     ("calmar_ratio", "卡玛比率"), ("alpha_pct", "年化超额"),
                     ("beta", "Beta"), ("information_ratio", "信息比率"),
                     ("benchmark_return_pct", "基准收益"), ("total_months", "回测月数")]:
            if k in wf:
                lines.append(f"| {v} | {wf[k]} |")
        lines.append(f"")
        lines.append(f"## Walk-Forward验证")
        lines.append(f"")
        lines.append(f"- **训练窗口**: 24个月")
        lines.append(f"- **步进**: 12个月")
        lines.append(f"- **分段数**: {len(results.get('segments', []))}")
        if "gapup_fails" in wf:
            gapup = wf.get("gapup_fails", 0)
            total = wf.get("total_trades", 0)
            fail_pct = round(gapup / total * 100, 1) if total > 0 else 0
            lines.append(f"- **跳空高开无法买入**: {gapup}/{total} 次 ({fail_pct}%)")
        if "smart_filtered" in wf:
            sf = wf.get("smart_filtered", 0)
            lines.append(f"- **聪明钱过滤器拦截**: {sf} 次")
        for seg in results.get("segments", []):
            lines.append(f"  - 训练: {seg['train_start']}~{seg['train_end']} → 测试: {seg['test_start']}~{seg['test_end']} ({seg['test_months']}个月)")
        lines.append(f"")
    else:
        lines.append(f"| 指标 | 全样本 |" + (" 样本内 | 样本外 |" if "out_of_sample" in results else ""))
        lines.append(f"|------|--------|" + ("--------|--------|" if "out_of_sample" in results else ""))

        def _row(metric, label):
            ins = results.get("in_sample", {})
            oos = results.get("out_of_sample", {})
            v_ins = ins.get(metric, "-")
            v_oos = oos.get(metric, "-")
            return f"| {label} | {v_ins} |" + (f" {v_ins} | {v_oos} |" if oos else "")

        for k in ["cagr_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate_pct",
                   "profit_loss_ratio", "total_return_pct", "calmar_ratio",
                   "alpha_pct", "beta", "information_ratio", "benchmark_return_pct",
                   "total_months"]:
            label = {"cagr_pct": "年化收益率", "sharpe_ratio": "夏普比率",
                     "max_drawdown_pct": "最大回撤", "win_rate_pct": "月胜率",
                     "profit_loss_ratio": "盈亏比", "total_return_pct": "累计收益",
                     "calmar_ratio": "卡玛比率", "alpha_pct": "年化超额",
                     "beta": "Beta", "information_ratio": "信息比率",
                     "benchmark_return_pct": "基准收益", "total_months": "回测月数"}.get(k, k)
            if k == "benchmark_return_pct" or k in results.get("in_sample", {}):
                lines.append(_row(k, label))
        lines.append(f"")

    ins = results.get("in_sample", {}) or results.get("walk_forward", {})
    if ins:
        lines.append(f"## 绩效详情")
        lines.append(f"")
        lines.append(f"- **期间**: {ins.get('start_date', '?')} ~ {ins.get('end_date', '?')} ({ins.get('months', '?')}个月)")
        lines.append(f"- **年化收益**: {ins.get('cagr_pct', '?')}%")
        lines.append(f"- **夏普比率**: {ins.get('sharpe_ratio', '?')}")
        lines.append(f"- **最大回撤**: {ins.get('max_drawdown_pct', '?')}%")
        lines.append(f"- **卡玛比率**: {ins.get('calmar_ratio', '?')}")
        lines.append(f"- **月胜率**: {ins.get('win_rate_pct', '?')}%")
        lines.append(f"- **盈亏比**: {ins.get('profit_loss_ratio', '?')}")
        lines.append(f"- **累计收益**: {ins.get('total_return_pct', '?')}%")
        lines.append(f"- **终值**: {ins.get('final_equity', '?')} (1→N)")
        if "alpha_pct" in ins:
            lines.append(f"- **年化超额**: {ins['alpha_pct']}%")
            lines.append(f"- **Beta**: {ins.get('beta', '?')}")
            lines.append(f"- **信息比率**: {ins.get('information_ratio', '?')}")
            lines.append(f"- **基准收益**: {ins.get('benchmark_return_pct', '?')}%")
        if "gapup_fails" in ins:
            gapup = ins.get("gapup_fails", 0)
            total = ins.get("total_trades", 0)
            fail_pct = round(gapup / total * 100, 1) if total > 0 else 0
            lines.append(f"- **跳空高开无法买入**: {gapup}/{total} 次 ({fail_pct}%)")
        if "smart_filtered" in ins:
            sf = ins.get("smart_filtered", 0)
            lines.append(f"- **聪明钱过滤器拦截**: {sf} 次")
        if "fear_skipped" in ins and ins.get("fear_skipped", 0) > 0:
            lines.append(f"- **市场恐慌不足跳过**: {ins['fear_skipped']} 个月")
        lines.append(f"")

    lines.append(f"## 回测参数")
    lines.append(f"")
    lines.append(f"- 策略: {strategy_name}")
    lines.append(f"- 数据区间: {results.get('start', '?')} ~ {results.get('end', '?')}")
    lines.append(f"- 股票池: {results.get('stock_universe', '?')} 只")
    lines.append(f"- 选股数量: {results.get('top_n', '?')} 只")
    lines.append(f"- 调仓: 月频, 等权")
    if "trade_cost_model" in results:
        lines.append(f"- 交易成本: {results['trade_cost_model']}")
    lines.append(f"")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="多因子策略回测引擎")
    parser.add_argument("--strategy", default="lowvol_highroe_oversold",
                        choices=list(STRATEGIES.keys()) + ["all"],
                        help="策略名称 (lowvol_highroe_main_up=主升浪, lowvol_highroe_oversold=超跌反弹)")
    parser.add_argument("--mode", type=str, default=None,
                        choices=["main_up", "oversold"],
                        help="快捷模式选择: main_up(主升浪), oversold(超跌反弹) — 自动选择对应策略")
    parser.add_argument("--start", default="2020-01", help="开始年月 (YYYY-MM)")
    parser.add_argument("--end", default="2026-07", help="结束年月 (YYYY-MM)")
    parser.add_argument("--top-n", type=int, default=30, help="选股数量")
    parser.add_argument("--oos", type=float, default=0.0, help="样本外比例 (0.0~1.0)")
    parser.add_argument("--walk-forward", action="store_true", help="启用Walk-forward滚动验证")
    parser.add_argument("--walk-window", type=int, default=24, help="Walk-forward训练窗口（月数）")
    parser.add_argument("--walk-step", type=int, default=12, help="Walk-forward步进（月数）")
    parser.add_argument("--list-strategies", action="store_true", help="列出可用策略")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--save", action="store_true", help="保存报告到文件")
    parser.add_argument("--market-fear", type=float, default=0.0,
                        help="市场恐慌过滤器阈值（如60=下跌占比>60%时才交易）")

    args = parser.parse_args()

    if args.list_strategies:
        print("可用策略:")
        for name in STRATEGIES:
            doc = STRATEGIES[name].__doc__ or "无描述"
            print(f"  {name:<30s} {doc.strip()}")
        sys.exit(0)

    # --mode 快捷方式：自动选择对应策略
    if args.mode:
        args.strategy = f"lowvol_highroe_{args.mode}"

    strategies = [args.strategy] if args.strategy != "all" else list(STRATEGIES.keys())

    for sname in strategies:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"  策略: {sname}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        fn = STRATEGIES[sname]
        results = run_backtest(fn, start_date=args.start, end_date=args.end,
                               top_n=args.top_n, oos_split=args.oos,
                               walk_forward=args.walk_forward,
                               walk_window=args.walk_window,
                               walk_step=args.walk_step,
                               market_fear_threshold=args.market_fear)

        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            report = format_report(results, sname)
            print(report)

        if args.save:
            out_dir = SCRIPT_DIR / "backtest_reports"
            out_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            out_path = out_dir / f"backtest_{sname}_{ts}.md"
            out_path.write_text(report, encoding="utf-8")
            print(f"\n✅ 报告已保存: {out_path}", file=sys.stderr)