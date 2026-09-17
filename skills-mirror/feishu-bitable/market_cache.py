#!/usr/bin/env python3
"""
全市场K线缓存系统
每天16:30自动下载全市场A股K线，存入SQLite，供盘中扫描秒出结果

用法:
    python3 market_cache.py refresh       # 全量下载（约3分钟）
    python3 market_cache.py incremental  # 增量更新（盘中用，只更新持仓相关+热门）
    python3 market_cache.py scan         # 扫描全市场，给出建仓推荐
"""
import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])

from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

import sqlite3
import json
import time
import math
import os
# 清除代理环境变量——国内金融API（akshare/腾讯行情/东方财富）直连更快更稳
for _key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
             'all_proxy', 'ALL_PROXY']:
    os.environ.pop(_key, None)
import akshare as ak
import pandas as pd
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from typing import Optional
import gc
from concurrent.futures import ThreadPoolExecutor, as_completed


def is_trading_day():
    """检查今天是否为 A 股交易日，非交易日则直接退出"""
    try:
        df = ak.tool_trade_date_hist_sina()
        trading_dates = set(pd.to_datetime(df['trade_date']).dt.date)
        if date.today() not in trading_dates:
            print(f"今日 ({date.today()}) 非 A 股交易日，跳过执行")
            return False
    except Exception as e:
        print(f"交易日判断异常: {e}，继续执行")
    return True

DB_PATH = os.environ.get(
    "MARKET_CACHE_DB",
    _STOCK_MARKET_DB
)

# 安静模式：no_agent cron 推送到飞书时只输出最终汇总，不打印逐批进度
QUIET = os.environ.get("MARKET_CACHE_QUIET", "0") == "1"


def _qprint(*args, **kwargs):
    """quiet 模式下不打印中间进度，只保留最终汇总。"""
    if not QUIET:
        print(*args, **kwargs)

# ============================================================
# SQLite 表结构
# ============================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,      -- 6位代码，如 '605058'
    name TEXT,
    market TEXT,               -- 'sh' 或 'sz'
    sector TEXT,               -- 所属行业板块
    list_date TEXT,            -- 入库日期
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS klines (
    code TEXT,
    date TEXT,                 -- 'YYYY-MM-DD'
    open REAL,
    close REAL,
    high REAL,
    low REAL,
    volume REAL,
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_klines_code ON klines(code);
CREATE INDEX IF NOT EXISTS idx_klines_date ON klines(date);

CREATE TABLE IF NOT EXISTS indicators (
    code TEXT PRIMARY KEY,
    date TEXT,                 -- 计算日期

    -- 价格信息
    current_price REAL,
    prev_close REAL,
    change_pct REAL,

    -- 技术指标
    rsi_14 REAL,
    macd REAL,
    macd_signal REAL,
    macd_hist REAL,
    boll_middle REAL,
    boll_upper REAL,
    boll_lower REAL,
    boll_position REAL,         -- 布林位 0-100%
    ma5 REAL,
    ma10 REAL,
    ma20 REAL,
    ma60 REAL,
    ma_bullish INTEGER,         -- 1=多头 0=纠缠 -1=空头
    atr_14 REAL,

    -- 评分
    signal_score REAL,          -- 综合信号分 -100~100
    signal_level INTEGER,        -- 0-5
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_indicators_score ON indicators(signal_score DESC);
CREATE INDEX IF NOT EXISTS idx_indicators_rsi ON indicators(rsi_14);
CREATE INDEX IF NOT EXISTS idx_indicators_boll ON indicators(boll_position);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def get_db():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def init_db():
    """初始化数据库"""
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化完成: {DB_PATH}")


# ============================================================
# 股票列表
# ============================================================

def build_stock_list() -> list:
    """
    构建A股全量股票列表（约5000只）
    用 akshare 获取全量，失败时用备用列表
    """
    import requests

    all_stocks = []

    # 备用：常见股票代码池（确保最少有数据）
    backup_list = [
        # 沪市主板
        '600000','600009','600016','600019','600028','600030','600031','600036',
        '600048','600050','600058','600060','600061','600104','600109','600111',
        '600150','600160','600170','600176','600183','600196','600199','600276',
        '600297','600309','600436','600519','600585','600588','600690','600703',
        '600760','600809','600887','600893','600905','600918','600926','600941',
        '601006','601012','601066','601088','601118','601166','601288','601319',
        '601328','601336','601398','601601','601628','601668','601688','601728',
        '601818','601857','601888','601898','601939','601988','601995','603259',
        '603288','603501','603799','603986','605058',
        # 深市主板
        '000001','000002','000063','000100','000333','000338','000425','000538',
        '000568','000651','000661','000708','000725','000768','000858','000876',
        '000895','000938','002001','002027','002032','002044','002049','002142',
        '002153','002236','002252','002304','002311','002352','002371','002415',
        '002460','002466','002475','002493','002594','002601','002607','002714',
        '002736','002812','002841','002920','300003','300015','300033','300059',
        '300122','300124','300142','300274','300347','300364','300408','300474',
        '300529','300750','300760','300896','300982','301056','301399','688041',
        '688111','688126','688187','688223','688256','688363','688499','688502',
        '688599','688981',
    ]

    try:
        # 用 akshare 获取全量A股列表（不经过代理，直连更稳定）
        import akshare as ak
        df = ak.stock_info_a_code_name()

        for _, row in df.iterrows():
            code = str(row["code"]).strip()
            name = str(row["name"]).strip()
            if len(code) == 6 and code.isdigit():
                market = "sh" if code.startswith(("6", "601", "603", "605", "688")) else (
                         "bj" if code.startswith(("4", "8")) else "sz")
                all_stocks.append((code, name, market))

        print(f"  从 akshare 获取 {len(all_stocks)} 只股票")
    except Exception as e:
        print(f"  akshare 获取失败，使用备用列表: {e}")
        for code in backup_list:
            market = "sh" if code.startswith(("6", "601", "603", "605", "688")) else "sz"
            all_stocks.append((code, code, market))

    # 去重
    seen = {}
    for code, name, market in all_stocks:
        if code not in seen:
            seen[code] = (code, name, market)
    return list(seen.values())


# ============================================================
# 技术指标计算
# ============================================================

def calc_rsi(closes: list, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_ema(prices: list, period: int) -> Optional[list]:
    if len(prices) < period:
        return None
    ema = [sum(prices[:period]) / period]
    mult = 2 / (period + 1)
    for p in prices[period:]:
        ema.append((p - ema[-1]) * mult + ema[-1])
    return ema


def calc_macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9):
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None, None, None
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_slow))]
    if len(macd_line) < signal:
        return None, None, None
    sig_line = calc_ema(macd_line, signal)
    if sig_line is None:
        return None, None, None
    return macd_line[-1], sig_line[-1], macd_line[-1] - sig_line[-1]


def calc_boll(closes: list, period: int = 20, std_dev: int = 2):
    if len(closes) < period:
        return None, None, None
    recent = closes[-period:]
    ma = sum(recent) / period
    variance = sum((p - ma) ** 2 for p in recent) / period
    std = math.sqrt(variance)
    return ma, ma + std_dev * std, ma - std_dev * std


def calc_ma(prices: list):
    """计算5/10/20/60均线"""
    result = {}
    for period in [5, 10, 20, 60]:
        if len(prices) >= period:
            result[period] = sum(prices[-period:]) / period
        else:
            result[period] = None
    return result


def calc_atr(klines: list, period: int = 14) -> Optional[float]:
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        high = klines[i]['high']
        low = klines[i]['low']
        prev = klines[i-1]['close']
        tr = max(high - low, abs(high - prev), abs(low - prev))
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def calc_signal_score(rsi: float, macd_hist: float, boll_pos: float,
                      ma_bullish: bool, ma_bearish: bool,
                      change_pct: float) -> tuple:
    """
    计算综合信号评分（双模式：超跌反弹 + 主升浪）
    返回 (score: -100~100, level: 0~5)
    """
    score = 0
    reasons = []

    # ===========================================================
    # 模式A：主升浪信号（RSI健康+布林中位+均线多头）
    # ===========================================================
    uptrend_bonus = 0
    uptrend_reasons = []
    
    # RSI健康区间（40-65）：主力拉升期，不过热不过冷
    if 40 <= rsi <= 65:
        uptrend_bonus += 20
        uptrend_reasons.append(f"RSI健康{rsi:.0f}")
    elif 35 <= rsi < 40:
        uptrend_bonus += 10  # 偏弱但有机会
    
    # MACD正向（上升趋势确认）
    if macd_hist > 0:
        uptrend_bonus += 15
        if macd_hist > 0.1:
            uptrend_reasons.append("MACD强势")
    
    # 布林位中位区间（40-70%）：主升浪进行时
    if 40 <= boll_pos <= 70:
        uptrend_bonus += 15; uptrend_reasons.append("布林中位")
    elif 30 <= boll_pos < 40:
        uptrend_bonus += 8
    elif boll_pos > 90:
        uptrend_bonus -= 10; uptrend_reasons.append("布林上轨")  # 贴上轨，过热预警
    elif boll_pos > 80:
        uptrend_bonus += 3  # 偏强但不惩罚
    
    # 均线多头排列
    if ma_bullish:
        uptrend_bonus += 10; uptrend_reasons.append("均线多头")
    
    # 涨幅适中（上涨中继，不追高）
    if 0 <= change_pct <= 5:
        uptrend_bonus += 5

    # ===========================================================
    # 模式B：超跌反弹信号（RSI<35超卖）
    # ===========================================================
    oversold_bonus = 0
    oversold_reasons = []
    
    if rsi < 20:
        oversold_bonus += 35; oversold_reasons.append("严重超卖")
    elif rsi < 30:
        oversold_bonus += 25; oversold_reasons.append("RSI超卖")
    elif rsi < 40:
        oversold_bonus += 15
    
    if macd_hist > 0:
        oversold_bonus += 10  # 超卖+MACD拐点
    
    if boll_pos < 15:
        oversold_bonus += 15; oversold_reasons.append("布林下轨")
    elif boll_pos < 25:
        oversold_bonus += 8
    
    if ma_bearish:
        oversold_bonus -= 5  # 均线空头略微扣分（还不是买点）
    
    if change_pct < -5:
        oversold_bonus += 5  # 大跌超卖确认

    # ===========================================================
    # 取两种模式中的高分者
    # ===========================================================
    if uptrend_bonus > oversold_bonus:
        score = uptrend_bonus
        reasons = uptrend_reasons
    else:
        score = oversold_bonus
        reasons = oversold_reasons

    # 信号等级
    level = 0
    if score >= 60: level = 5
    elif score >= 40: level = 4
    elif score >= 20: level = 3
    elif score >= 0: level = 2
    elif score >= -20: level = 1

    return score, level


# ============================================================
# K线下载
# ============================================================

def _normalize_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y/%m/%d").strftime("%Y-%m-%d")
    except ValueError:
        return date_str


# 数据源降级统计（线程安全聚合，避免逐只刷屏）
import threading as _threading
_source_stats = {"eastmoney": 0, "tencent": 0, "westock": 0, "failed": 0}
_source_stats_lock = _threading.Lock()


def _src_inc(key):
    with _source_stats_lock:
        _source_stats[key] = _source_stats.get(key, 0) + 1


def get_source_stats(reset: bool = True) -> dict:
    """返回数据源降级统计，默认重置计数器。"""
    global _source_stats
    with _source_stats_lock:
        s = dict(_source_stats)
        if reset:
            _source_stats = {"eastmoney": 0, "tencent": 0, "westock": 0, "failed": 0}
    return s


def download_klines(code: str, market: str, days: int = 2000) -> list:
    """下载单只股票的K线数据（三级降级：东方财富 -> 腾讯 -> westock）

    支持最多2000天（约8年）历史K线，前复权。统一返回 YYYY-MM-DD。
    每个数据源连续失败 3 次后自动切换到下一级。
    成功的数据源计入 _source_stats，不逐只打印，避免 no_agent 推送刷屏。
    """
    max_retries = 3

    # 东方财富 secid: 1=上交所, 0=深交所
    secid = f"1.{code}" if market == "sh" else f"0.{code}"

    for attempt in range(max_retries):
        try:
            r = _download_klines_eastmoney(code, market, secid, days)
            if r:
                _src_inc("eastmoney")
                return r
        except Exception:
            pass

    for attempt in range(max_retries):
        try:
            r = _download_klines_tencent(code, market, days)
            if r:
                _src_inc("tencent")
                return r
        except Exception:
            pass

    for attempt in range(max_retries):
        try:
            r = _download_klines_westock(code, market, days)
            if r:
                _src_inc("westock")
                return r
        except Exception:
            pass

    _src_inc("failed")
    return []


def _download_klines_eastmoney(code: str, market: str, secid: str, days: int) -> list:
    """第一优先：东方财富 push2his（上限2000天）"""
    import requests

    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,  # 日K线
        "fqt": 1,    # 前复权
        "end": "20500101",
        "lmt": min(days, 2000),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://quote.eastmoney.com",
    }

    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    klines = data.get("data", {}).get("klines", []) or []
    if not klines:
        return []

    result = []
    for k in klines:
        parts = k.split(",")
        if len(parts) >= 6:
            try:
                result.append({
                    "date": _normalize_date(parts[0]),
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]) if parts[5] else 0,
                    "turnover": float(parts[6]) if len(parts) > 6 and parts[6] else None,
                })
            except (ValueError, IndexError):
                continue

    # 按日期升序排序
    result.sort(key=lambda k: k["date"])

    # 计算 amplitude
    prev_close = None
    for k in result:
        amplitude = None
        if prev_close is not None and prev_close > 0:
            amplitude = (k["high"] - k["low"]) / prev_close * 100
        k["amplitude"] = amplitude
        prev_close = k["close"]

    return result


def _download_klines_tencent(code: str, market: str, days: int = 2000) -> list:
    """第二优先：腾讯行情API（上限641天）"""
    import requests
    full_code = f"{market}{code}"
    market_id = 1 if market == "sh" else 0
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    params = {
        "apptype": "", "fqt": 1,
        "lmt": min(days, 641), "market": market_id,
        "param": f"{full_code},day,,,{min(days,641)},qfq"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://finance.qq.com"
    }
    resp = requests.get(url, params=params, headers=headers, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        return []
    code_data = data.get("data", {})
    if not isinstance(code_data, dict):
        return []
    code_data = code_data.get(full_code, {})
    if not isinstance(code_data, dict):
        return []
    klines = code_data.get("qfqday") or code_data.get("day") or []
    result = []
    for k in klines:
        if not isinstance(k, list) or len(k) < 9:
            continue
        try:
            result.append({
                "date": _normalize_date(k[0]),
                "open": float(k[1]),
                "close": float(k[2]),
                "high": float(k[3]),
                "low": float(k[4]),
                "volume": float(k[5]) if len(k) > 5 and k[5] else 0,
                "turnover": float(k[8]) * 10000 if len(k) > 8 and k[8] else None,
            })
        except (ValueError, IndexError):
            continue

    # 按日期升序排序
    result.sort(key=lambda k: k["date"])

    # 计算 amplitude
    prev_close = None
    for k in result:
        amplitude = None
        if prev_close is not None and prev_close > 0:
            amplitude = (k["high"] - k["low"]) / prev_close * 100
        k["amplitude"] = amplitude
        prev_close = k["close"]

    return result


def _download_klines_westock(code: str, market: str, days: int = 2000) -> list:
    """第三优先：westock-data kline（本地 CLI，上限约 641 天）"""
    import subprocess
    full_code = f"{market}{code}"
    cmd = (
        "npx -y westock-data-skillhub@1.0.3 "
        f"kline {full_code} --period day --limit {min(days, 641)}"
    )
    raw = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30).stdout
    return _parse_westock_kline(raw)


def _parse_westock_kline(text: str) -> list:
    """解析 westock kline 的 Markdown 表格输出"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = []
    in_table = False
    for line in lines:
        if line.startswith("| date |"):
            in_table = True
            continue
        if in_table:
            if line.startswith("| ---"):
                continue
            if not line.startswith("|"):
                break
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 8:
                try:
                    result.append({
                        "date": _normalize_date(cells[0]),
                        "open": float(cells[1]),
                        "close": float(cells[2]),
                        "high": float(cells[3]),
                        "low": float(cells[4]),
                        "volume": float(cells[5]) if cells[5] else 0,
                        "turnover": float(cells[6]) if cells[6] else None,
                    })
                except (ValueError, IndexError):
                    continue

    # 按日期升序排序
    result.sort(key=lambda k: k["date"])

    # 计算 amplitude
    prev_close = None
    for k in result:
        amplitude = None
        if prev_close is not None and prev_close > 0:
            amplitude = (k["high"] - k["low"]) / prev_close * 100
        k["amplitude"] = amplitude
        prev_close = k["close"]

    return result


# ============================================================
# 全量刷新
# ============================================================

def fetch_sector(code: str) -> str:
    """获取单只股票的行业（东方财富 DataCenter API）"""
    import requests
    params = {
        'reportName': 'RPT_F10_BASIC_ORGINFO',
        'columns': 'SECURITY_CODE,BOARD_NAME_LEVEL',
        'filter': f'(SECURITY_CODE="{code}")',
        'pageNumber': 1,
        'pageSize': 1,
        'source': 'HSF10',
        'client': 'HSF10'
    }
    try:
        r = requests.get(
            'https://datacenter-web.eastmoney.com/api/data/v1/get',
            params=params, timeout=10
        )
        data = r.json()
        if data.get('result') and data['result'].get('data'):
            board = data['result']['data'][0].get('BOARD_NAME_LEVEL', '')
            if board and '-' in board:
                return board.split('-')[-1].strip()
            return board or ''
    except Exception:
        pass
    return ''


def _normalize_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y/%m/%d").strftime("%Y-%m-%d")
    except ValueError:
        return date_str


ALERT_LOG_PATH = os.environ.get(
    "KLINE_ALERT_LOG",
    os.path.join(os.path.dirname(DB_PATH), "data_alert.log")
)


def _alert(msg: str):
    """Write a simple alert line to a local log file."""
    try:
        os.makedirs(os.path.dirname(ALERT_LOG_PATH), exist_ok=True)
        with open(ALERT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception as e:
        print(f"alert log write failed: {e}")


def validate_klines_refresh(conn) -> bool:
    """Return True if latest klines date is fresh and coverage is sufficient."""
    cur = conn.cursor()
    cur.execute("SELECT MAX(date) FROM klines")
    max_date = cur.fetchone()[0]
    if not max_date:
        _alert("K线刷新校验失败：klines 表为空")
        print("[FAIL] klines table is empty")
        return False

    cur.execute(
        "SELECT COUNT(DISTINCT code) FROM klines WHERE date = (SELECT MAX(date) FROM klines)",
    )
    latest_count = cur.fetchone()[0]

    scan_date = datetime.now().date()
    trading = set()
    try:
        df = ak.tool_trade_date_hist_sina()
        trading = set(pd.to_datetime(df["trade_date"]).dt.date)
    except Exception as e:
        print(f"交易日校验异常: {e}")

    latest_dt = None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            latest_dt = datetime.strptime(max_date, fmt).date()
            break
        except ValueError:
            continue

    stale = False
    if latest_dt is None:
        stale = True
    elif scan_date in trading or latest_dt != scan_date:
        prev = scan_date - timedelta(days=1)
        prev2 = scan_date - timedelta(days=2)
        if latest_dt not in {scan_date, prev, prev2}:
            stale = True

    failed = False
    if stale or latest_count < 4900:
        msg = (
            f"[FAIL] K线刷新不完整，最新日期: {max_date}，覆盖: {latest_count} 只"
        )
        _alert(msg)
        print(msg)
        failed = True
    else:
        print(f"[OK] K线刷新完成，日期: {max_date}，覆盖: {latest_count} 只")

    return not failed


def backfill_missing_dates(conn, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Backfill missing trading-day K-line snapshots between two dates (inclusive)."""
    scan_end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else datetime.now().date()
    scan_start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else scan_end - timedelta(days=7)

    trading = set()
    try:
        df = ak.tool_trade_date_hist_sina()
        trading = set(pd.to_datetime(df["trade_date"]).dt.date)
    except Exception as e:
        print(f"交易日列表获取失败: {e}")

    dates = sorted(d for d in (scan_start + timedelta(days=n) for n in range((scan_end - scan_start).days + 1)) if d in trading)
    if not dates:
        print("[backfill] no trading dates in range")
        return

    cur = conn.cursor()
    cur.execute("SELECT MAX(date) FROM klines")
    current_max = cur.fetchone()[0] or scan_start.strftime("%Y-%m-%d")

    missing = [d for d in dates if d.strftime("%Y-%m-%d") > current_max]
    if not missing:
        print(f"[backfill] no missing dates after {current_max}")
        return

    print(f"[backfill] missing dates: {len(missing)} -> {missing[:5]}{'...' if len(missing) > 5 else ''}")
    for target in missing:
        target_str = target.strftime("%Y-%m-%d")
        print(f"[backfill] backfill {target_str} ...")
        _backfill_single_date(conn, target_str)


def _backfill_single_date(conn, target_date: str):
    """Download one trading day's klines for the full market and write into klines."""
    stocks = build_stock_list()
    total = len(stocks)
    if not total:
        return

    def fetch_one(args):
        code, name, market = args
        klines = download_klines(code, market, 2000)
        return code, name, market, klines

    written = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one, s): s for s in stocks}
        done = 0
        for future in as_completed(futures):
            code, name, market, klines = future.result()
            done += 1
            if done % 500 == 0:
                gc.collect()
            matched = [k for k in (klines or []) if _normalize_date(k.get("date", "")) == target_date]
            if not matched:
                continue
            k = matched[0]
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO klines (code, date, open, close, high, low, volume, turnover, amplitude, change_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        target_date,
                        k.get("open"),
                        k.get("close"),
                        k.get("high"),
                        k.get("low"),
                        k.get("volume"),
                        k.get("turnover"),
                        k.get("amplitude"),
                        change_pct,
                    )
                )
                written += 1
            except Exception as e:
                print(f"  backfill write failed {code} {target_date}: {e}")

            if done % 500 == 0 or done == total:
                print(f"  backfill progress: {done}/{total}, written={written}")

    conn.commit()
    print(f"[backfill] {target_date} written={written}")
    if written < 5000:
        _alert(f"[FAIL] backfill coverage low on {target_date}: {written}")


def full_refresh():
    """全量下载：并发下载所有股票K线，然后计算指标写入DB"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始全量刷新（并发模式）...")
    conn = get_db()
    init_db()

    backfill_missing_dates(conn)
    validate_klines_refresh(conn)

    # 获取股票列表
    stocks = build_stock_list()
    total = len(stocks)
    print(f"  股票总数: {total}")

    # ---- Phase 0: 补充行业信息（针对新上市/缺失的股票）----
    print(f"  [Phase 0/3] 补充行业信息...")
    sector_start = time.time()
    cur = conn.cursor()
    cur.execute("SELECT code FROM stocks WHERE sector IS NULL OR sector = ''")
    missing = [r[0] for r in cur.fetchall()]
    if missing:
        def fetch_sector_thread(c):
            return c, fetch_sector(c)
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(fetch_sector_thread, c) for c in missing]
            for future in as_completed(futures):
                c, sector = future.result()
                if sector:
                    conn.execute("UPDATE stocks SET sector = ? WHERE code = ?", (sector, c))
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM stocks WHERE sector IS NOT NULL AND sector != ''")
        filled = cur.fetchone()[0]
        print(f"  行业补充完成（{len(missing)}只缺失，现{filled}只有行业），耗时 {time.time()-sector_start:.0f}s")
    else:
        print(f"  行业信息已完整，耗时 {time.time()-sector_start:.0f}s")

    # ---- Phase 1: 并发下载所有K线 ----
    print(f"  [Phase 1/2] 并发下载K线（50线程）...")
    download_start = time.time()
    results = []  # (code, name, market, klines)

    def fetch_one(args):
        code, name, market = args
        klines = download_klines(code, market, 2000)
        return code, name, market, klines

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one, s): s for s in stocks}
        done = 0
        for future in as_completed(futures):
            code, name, market, klines = future.result()
            results.append((code, name, market, klines))
            done += 1
            if done % 500 == 0 or done == total:
                gc.collect()
                elapsed = time.time() - download_start
                print(f"  下载进度: {done}/{total} ({done/elapsed:.0f}只/秒)")

    download_time = time.time() - download_start
    print(f"  下载完成: {len(results)}只, 耗时 {download_time:.1f}s")

    # ---- Phase 2: 计算指标 + 写入DB ----
    print(f"  [Phase 2/2] 计算指标并写入DB...")
    write_start = time.time()
    updated = 0
    errors = 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for idx, (code, name, market, klines) in enumerate(results):
        if not klines:
            errors += 1
            continue

        # 跳过 ST/*ST/S* 股票
        if any(name.startswith(prefix) for prefix in ('ST', '*ST', 'S')):
            continue

        # 写入klines表
        for i, k in enumerate(klines):
            # 计算涨跌幅
            if i > 0:
                prev_close = klines[i-1]['close']
                change_pct = (k['close'] - prev_close) / prev_close * 100 if prev_close else 0
            else:
                change_pct = 0
            
            conn.execute("""
                INSERT OR REPLACE INTO klines (code, date, open, close, high, low, volume, turnover, amplitude, change_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (code, k['date'], k['open'], k['close'], k['high'], k['low'], k['volume'], k.get('turnover'), k.get('amplitude'), change_pct))

        # 计算指标
        closes = [k['close'] for k in klines]
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        current = closes[-1]
        prev_close = closes[-2] if len(closes) > 1 else current
        change_pct = (current - prev_close) / prev_close * 100 if prev_close else 0

        rsi = calc_rsi(closes, 14)
        if rsi is not None and (rsi < 0 or rsi > 100):
            print(f"  ⚠️ RSI异常 {code} {name}: rsi={rsi}，强制置50")
            rsi = 50.0
        macd, macd_sig, macd_hist = calc_macd(closes)
        boll_m, boll_u, boll_l = calc_boll(closes)
        ma_vals = calc_ma(closes)
        atr = calc_atr([{"high": h, "low": l, "close": c}
                        for h, l, c in zip(highs, lows, closes)], 14)

        boll_pos = 50.0
        if boll_u and boll_l and boll_u != boll_l:
            boll_pos = (current - boll_l) / (boll_u - boll_l) * 100
        boll_pos = max(0.0, min(100.0, boll_pos))  # P0 clamp

        ma_bullish = (ma_vals.get(5, 0) > ma_vals.get(10, 0) > ma_vals.get(20, 0)
                      if all(ma_vals.get(p) for p in [5, 10, 20]) else False)
        ma_bearish = (ma_vals.get(5, 0) < ma_vals.get(10, 0) < ma_vals.get(20, 0)
                      if all(ma_vals.get(p) for p in [5, 10, 20]) else False)

        score, level = calc_signal_score(
            rsi or 50, macd_hist or 0, boll_pos,
            ma_bullish, ma_bearish, change_pct
        )

        # 更新stocks表（保留已有 sector/total_shares_real/circulating_shares_real/total_mcap，
        # 避免每次 refresh 清空历史字段）
        conn.execute("""
            INSERT OR REPLACE INTO stocks (code, name, market, sector, updated_at,
                                           total_shares_real, circulating_shares_real, total_mcap)
            VALUES (?, ?, ?, COALESCE((SELECT sector FROM stocks WHERE code = ?), ''),
                    ?,
                    COALESCE((SELECT total_shares_real FROM stocks WHERE code = ?), NULL),
                    COALESCE((SELECT circulating_shares_real FROM stocks WHERE code = ?), NULL),
                    COALESCE((SELECT total_mcap FROM stocks WHERE code = ?), NULL))
        """, (code, name, market, code, now_str, code, code, code))

        # 更新indicators表
        conn.execute("""
            INSERT OR REPLACE INTO indicators (
                code, date, current_price, prev_close, change_pct,
                rsi_14, macd, macd_signal, macd_hist,
                boll_middle, boll_upper, boll_lower, boll_position,
                ma5, ma10, ma20, ma60,
                ma_bullish, atr_14,
                signal_score, signal_level, updated_at,
                turnover_rate,
                signal_a, signal_b, signal_c, signal_d
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      COALESCE((SELECT signal_a FROM indicators WHERE code = ?), 0),
                      COALESCE((SELECT signal_b FROM indicators WHERE code = ?), 0),
                      COALESCE((SELECT signal_c FROM indicators WHERE code = ?), 0),
                      COALESCE((SELECT signal_d FROM indicators WHERE code = ?), 0))
        """, (
            code,
            klines[-1]['date'],
            current, prev_close, change_pct,
            rsi, macd, macd_sig, macd_hist,
            boll_m, boll_u, boll_l, boll_pos,
            ma_vals.get(5), ma_vals.get(10), ma_vals.get(20), ma_vals.get(60),
            1 if ma_bullish else (-1 if ma_bearish else 0), atr,
            score, level, now_str,
            klines[-1].get('turnover'),
            code, code, code, code
        ))

        updated += 1

        # 每500只提交一次
        if (idx + 1) % 500 == 0:
            conn.commit()
            print(f"  写入进度: {idx+1}/{total}")

    conn.commit()
    write_time = time.time() - write_start

    # 更新meta
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                 ("last_full_refresh", datetime.now().isoformat()))
    conn.commit()
    conn.close()

    total_time = download_time + write_time
    print(f"✅ 全量刷新完成: {updated}只成功, {errors}失败, 总耗时 {total_time:.1f}s")
    print(f"   下载: {download_time:.1f}s | 计算+写入: {write_time:.1f}s")


# ============================================================
# 增量更新（只更新持仓相关+热门）
# ============================================================

def _send_feishu(msg: str):
    try:
        from feishu_sender import feishu_send_message
        feishu_send_message(msg)
    except Exception as e:
        print(f"[WARN] 飞书发送失败: {e}")


def incremental_update(focus_codes: list = None, dry_run: bool = False):
    """
    增量更新：并发下载 + 批量写入
    focus_codes: 重点关注列表（如持仓股+候选股）
    dry_run: 为 True 时只计算不写入
    """
    _qprint(f"[{datetime.now().strftime('%H:%M:%S')}] 开始增量更新（并发模式）...")
    if dry_run:
        _qprint("[DRY-RUN] 本次不会写入数据库")
    conn = get_db()

    if focus_codes:
        stocks = [(c, c,
                   "bj" if c.startswith(("4", "8")) else
                   ("sh" if c.startswith(("6", "601", "603", "605", "688")) else "sz"))
                  for c in focus_codes]
    else:
        rows = conn.execute("""
            SELECT i.code, s.name, s.market
            FROM indicators i
            JOIN stocks s ON s.code = i.code
            WHERE DATE(i.updated_at) < DATE('now')
               OR i.updated_at IS NULL
        """).fetchall()
        stocks = rows if rows else []
        today_count = conn.execute(
            "SELECT COUNT(*) FROM indicators WHERE DATE(updated_at) = DATE('now')"
        ).fetchone()[0]
        total_count = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        _qprint(f"  今日已更新: {today_count}/{total_count}，待更新: {len(stocks)} 只")

    if not stocks:
        print("[WARN] stocks 列表为空，触发全量初始化")
        try:
            fallback = build_stock_list()
        except Exception as e:
            _send_feishu(f"🚨 market_cache_refresh: 全量初始化失败 {e}")
            return 1
        stocks = [(c, c, m) for c, _, m in fallback]
        if not stocks:
            _send_feishu("🚨 market_cache_refresh: 全量初始化返回空")
            return 1
        _send_feishu(f"⚠️ 空 stocks，已触发全量初始化: {len(stocks)} 只")

    if len(stocks) < 100:
        _send_feishu(f"⚠️ market_cache_refresh: stocks 列表只有 {len(stocks)} 只")

    print(f"[INFO] incremental_update 待更新 stocks={len(stocks)}")
    BATCH_SIZE = 200
    total_stocks = len(stocks)
    total_updated = 0
    total_errors = 0
    total_skipped = 0
    total_download_time = 0
    total_write_time = 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_one(args):
        code, name, market = args
        klines = download_klines(code, market, 2000)
        return code, name, market, klines

    for batch_start in range(0, total_stocks, BATCH_SIZE):
        batch = stocks[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (total_stocks + BATCH_SIZE - 1) // BATCH_SIZE
        _qprint(f"\n  [批次 {batch_num}/{total_batches}] {len(batch)} 只...")

        # Phase 1: 并发下载本批
        download_start = time.time()
        batch_results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_one, s): s for s in batch}
            done = 0
            for future in as_completed(futures):
                batch_results.append(future.result())
                done += 1
        batch_dl_time = time.time() - download_start
        total_download_time += batch_dl_time
        _qprint(f"    下载完成: {len(batch_results)}只, 耗时 {batch_dl_time:.1f}s")

        # Phase 2: 计算指标 + 写入DB
        write_start = time.time()
        batch_updated = 0
        batch_errors = 0
        batch_skipped = 0
        for idx, (code, name, market, klines) in enumerate(batch_results):
            if not klines:
                batch_errors += 1
                continue
            if any(name.startswith(prefix) for prefix in ('ST', '*ST', 'S')):
                batch_skipped += 1
                _qprint(f"    skip {code}: ST/{name}")
                continue

            latest_kline_date = klines[-1].get('date')
            if not latest_kline_date:
                batch_errors += 1
                _qprint(f"    skip {code}: no latest_kline_date")
                continue

            current_indicator = conn.execute(
                "SELECT date FROM indicators WHERE code=?", (code,)
            ).fetchone()
            current_date = current_indicator[0] if current_indicator else None

            if current_date and latest_kline_date <= current_date:
                batch_skipped += 1
                _qprint(f"    skip {code}: monotonic latest={latest_kline_date} <= current={current_date}")
                continue

            if latest_kline_date < (date.today() - timedelta(days=14)).isoformat():
                batch_skipped += 1
                _qprint(f"    skip {code}: old latest={latest_kline_date} < {(date.today() - timedelta(days=14)).isoformat()}")
                continue

            if dry_run:
                batch_updated += 1
                continue

            for i, k in enumerate(klines):
                if i > 0:
                    prev_close = klines[i-1]['close']
                    change_pct = (k['close'] - prev_close) / prev_close * 100 if prev_close else 0
                else:
                    change_pct = 0
                conn.execute("""
                    INSERT OR REPLACE INTO klines (code, date, open, close, high, low, volume, turnover, amplitude, change_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (code, k['date'], k['open'], k['close'], k['high'], k['low'], k['volume'], k.get('turnover'), k.get('amplitude'), change_pct))

            closes = [k['close'] for k in klines]
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]
            current = closes[-1]
            prev_close = closes[-2] if len(closes) > 1 else current
            change_pct = (current - prev_close) / prev_close * 100 if prev_close else 0

            rsi = calc_rsi(closes, 14)
            if rsi is not None and (rsi < 0 or rsi > 100):
                _qprint(f"  ⚠️ RSI异常 {code}: rsi={rsi}，强制置50")
                rsi = 50.0
            macd, macd_sig, macd_hist = calc_macd(closes)
            boll_m, boll_u, boll_l = calc_boll(closes)
            ma_vals = calc_ma(closes)
            atr = calc_atr([{"high": h, "low": l, "close": c}
                            for h, l, c in zip(highs, lows, closes)], 14)

            boll_pos = 50.0
            if boll_u and boll_l and boll_u != boll_l:
                boll_pos = (current - boll_l) / (boll_u - boll_l) * 100
            boll_pos = max(0.0, min(100.0, boll_pos))

            ma_bullish = (ma_vals.get(5, 0) > ma_vals.get(10, 0) > ma_vals.get(20, 0)
                          if all(ma_vals.get(p) for p in [5, 10, 20]) else False)
            ma_bearish = (ma_vals.get(5, 0) < ma_vals.get(10, 0) < ma_vals.get(20, 0)
                          if all(ma_vals.get(p) for p in [5, 10, 20]) else False)

            score, level = calc_signal_score(
                rsi or 50, macd_hist or 0, boll_pos,
                ma_bullish, ma_bearish, change_pct
            )

            conn.execute("""
                INSERT OR REPLACE INTO stocks (code, name, market, sector, updated_at,
                                               total_shares_real, circulating_shares_real, total_mcap)
                VALUES (?, ?, ?, COALESCE((SELECT sector FROM stocks WHERE code = ?), ''),
                        ?,
                        COALESCE((SELECT total_shares_real FROM stocks WHERE code = ?), NULL),
                        COALESCE((SELECT circulating_shares_real FROM stocks WHERE code = ?), NULL),
                        COALESCE((SELECT total_mcap FROM stocks WHERE code = ?), NULL))
            """, (code, name, market, code, now_str, code, code, code))

            conn.execute("""
                INSERT OR REPLACE INTO indicators (
                    code, date, current_price, prev_close, change_pct,
                    rsi_14, macd, macd_signal, macd_hist,
                    boll_middle, boll_upper, boll_lower, boll_position,
                    ma5, ma10, ma20, ma60, ma_bullish, atr_14,
                    signal_score, signal_level, updated_at,
                    turnover_rate,
                    signal_a, signal_b, signal_c, signal_d
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          COALESCE((SELECT signal_a FROM indicators WHERE code = ?), 0),
                          COALESCE((SELECT signal_b FROM indicators WHERE code = ?), 0),
                          COALESCE((SELECT signal_c FROM indicators WHERE code = ?), 0),
                          COALESCE((SELECT signal_d FROM indicators WHERE code = ?), 0))
            """, (
                code, klines[-1]['date'], current, prev_close, change_pct,
                rsi, macd, macd_sig, macd_hist,
                boll_m, boll_u, boll_l, boll_pos,
                ma_vals.get(5), ma_vals.get(10), ma_vals.get(20), ma_vals.get(60),
                1 if ma_bullish else (-1 if ma_bearish else 0), atr,
                score, level, now_str,
                klines[-1].get('turnover'),
                code, code, code, code
            ))
            batch_updated += 1

        conn.commit()
        batch_write_time = time.time() - write_start
        total_write_time += batch_write_time
        total_updated += batch_updated
        total_errors += batch_errors
        total_skipped += batch_skipped
        _qprint(f"    写入完成: {batch_updated}只成功, {batch_errors}失败, {batch_skipped}跳过, 耗时 {batch_write_time:.1f}s")
        print(f"[INFO] 批次完成: batch={batch_num}, updated={batch_updated}, errors={batch_errors}, skipped={batch_skipped}")

        # 释放本批内存
        del batch_results
        gc.collect()

    if not dry_run:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                     ("last_incremental_update", datetime.now().isoformat()))
        conn.commit()
    conn.close()

    total_time = total_download_time + total_write_time
    print(f"\n✅ 增量更新完成: {total_updated}只成功, {total_errors}失败, {total_skipped}跳过, 总耗时 {total_time:.1f}s")
    if dry_run:
        print("[DRY-RUN] 未写入数据库")
    print(f"   下载: {total_download_time:.1f}s | 计算+写入: {total_write_time:.1f}s")
    stats = get_source_stats()
    print(f"   数据源: 东财 {stats['eastmoney']} | 腾讯 {stats['tencent']} | westock {stats['westock']} | 全失败 {stats['failed']}")


# ============================================================
# 全市场扫描
# ============================================================

def scan_market(limit: int = 20) -> list:
    """
    扫描全市场，返回信号评分最高的个股
    优先: RSI低位 + 布林低位 + MACD拐头
    """
    conn = get_db()

    rows = conn.execute("""
        SELECT
            i.code, s.name,
            i.current_price, i.change_pct,
            i.rsi_14, i.macd_hist, i.boll_position,
            i.ma_bullish, i.signal_score, i.signal_level
        FROM indicators i
        JOIN stocks s ON s.code = i.code
        WHERE i.current_price > 0
          AND i.signal_score > 0
          AND i.rsi_14 IS NOT NULL
        ORDER BY i.signal_score DESC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()
    return rows


def scan_by_sector() -> dict:
    """按板块汇总市场信号"""
    conn = get_db()

    # 按行业板块分组算平均RSI和信号
    rows = conn.execute("""
        SELECT
            s.sector,
            COUNT(*) as stock_count,
            AVG(i.rsi_14) as avg_rsi,
            AVG(i.boll_position) as avg_boll,
            AVG(i.signal_score) as avg_score,
            SUM(CASE WHEN i.signal_score > 30 THEN 1 ELSE 0 END) as strong_count
        FROM indicators i
        JOIN stocks s ON s.code = i.code
        WHERE i.current_price > 0
        GROUP BY s.sector
        HAVING stock_count >= 3
        ORDER BY avg_score DESC
    """).fetchall()

    conn.close()
    return rows


def print_scan_report():
    """打印扫描报告"""
    conn = get_db()
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    conn.close()

    print()
    print(f"📊 全市场扫描报告  ({meta.get('last_full_refresh', '未同步')})")
    print()

    # 大盘参考
    try:
        from fundamental import FundamentalFetcher
        fetcher = FundamentalFetcher()
        sentiment = fetcher.get_market_sentiment()
        indices = sentiment.get('indices', {})
        print("【大盘】")
        for n in ['上证指数', '深证成指', '创业板指', '沪深300']:
            if n in indices:
                info = indices[n]
                print(f"  {n}: {info.get('price','?')} {info.get('change_pct',0):+.2f}%")
        print(f"  涨停:{sentiment.get('limit_up',0)} 跌停:{sentiment.get('limit_down',0)}")
    except:
        pass

    print()
    print("【全市场个股推荐 TOP15】(信号评分>0, RSI偏低优先)")
    print(f"  {'代码':<6} {'名称':<8} {'现价':>7} {'涨跌':>6} {'RSI':>5} {'布林位':>6} {'信号分':>6} {'信号'}")
    print("  " + "-" * 65)

    rows = scan_market(15)
    for r in rows:
        code, name, price, chg, rsi, macd_h, boll_p, ma_b, score, level = r
        chg_str = f"{chg:+.2f}%" if chg else "N/A"
        rsi_str = f"{rsi:.1f}" if rsi else "N/A"
        boll_str = f"{boll_p:.0f}%" if boll_p else "N/A"
        name = name[:8] if name else code
        level_map = {5:"🚀建仓", 4:"⚡重点", 3:"📈观察", 2:"🔎跟踪", 1:"⚠️谨慎"}
        signal_str = level_map.get(level, str(level))
        print(f"  {code:<6} {name:<8} {price:>7.2f} {chg_str:>6} {rsi_str:>5} {boll_str:>6} {score:>6.0f} {signal_str}")

    print()
    print("【建仓逻辑说明】")
    print("  信号评分 = RSI评分(30%) + MACD评分(25%) + 布林位评分(20%) + 均线评分(15%) + 涨跌幅(10%)")
    print("  RSI<35 超卖区域 | 布林位<30% 价格靠近下轨 | MACD柱翻正是拐点信号")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "refresh":
        if not is_trading_day():
            sys.exit(0)
        full_refresh()
    elif cmd == "incremental":
        dry_run = "--dry-run" in sys.argv[2:] or os.environ.get("INCREMENTAL_DRY_RUN") == "1"
        focus = [a for a in sys.argv[2:] if a != "--dry-run" and not a.startswith("-")]
        focus = focus if focus else None
        incremental_update(focus, dry_run=dry_run)
    elif cmd == "scan":
        print_scan_report()
    elif cmd == "init":
        init_db()
        print("✅ 初始化完成")
    else:
        print(f"用法: python3 market_cache.py [refresh|incremental|scan|init]")
