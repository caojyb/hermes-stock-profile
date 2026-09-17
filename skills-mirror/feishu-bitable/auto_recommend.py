#!/usr/bin/env python3
"""
auto_recommend.py — 三档推荐系统 + 自动化买卖建议
==================================================
Phase 1: 三档推荐体系（激进/稳健/价值），输出股票+价格+理由
Phase 2: 基本面过滤（ROE/负债/PE分位），避免基本面差的超跌股
Phase 3: 止损止盈规则 + 仓位管理

用法:
  python3 auto_recommend.py scan          # 全市场扫描，输出推荐
  python3 auto_recommend.py status        # 查看各档当前状态
  python3 auto_recommend.py candidates    # 输出候选股池
"""
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

import sys
import os
sys.path.insert(0, __file__.rsplit('/', 1)[0])

import sqlite3
import json
import time
import requests
import akshare as ak
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

DB_PATH = _STOCK_MARKET_DB

# ============================================================
# 三档推荐体系常量
# ============================================================

# 激进档：超跌反弹
AGGRESSIVE_CONFIG = {
    'name': '激进档-超跌反弹',
    'max_position': 0.05,      # 单只最多5%总仓
    'rsi_max': 25,             # RSI<25
    'boll_pos_max': 20,        # 布林位置<20%
    'stop_loss_pct': 0.07,     # 止损-7%
    'take_profit_targets': [0.10, 0.15],  # 10%/15%止盈分批
    'hold_days_max': 10,       # 最长持有10天
    'required_score': 50,      # 最低信号评分
}

# 稳健档：主升浪顺势
STEADY_CONFIG = {
    'name': '稳健档-主升浪',
    'max_position': 0.10,      # 单只最多10%总仓
    'rsi_min': 40,            # RSI 40-70
    'rsi_max': 70,
    'boll_pos_min': 20,        # 布林位置20-70%
    'boll_pos_max': 70,
    'ma_required': True,       # 需要均线多头排列
    'stop_loss_pct': 0.05,    # 止损-5%
    'take_profit_targets': [0.08, 0.15],  # 8%/15%
    'hold_days_max': 20,       # 最长持有20天
    'required_score': 40,
}

# 价值档：基本面+低估值
VALUE_CONFIG = {
    'name': '价值档-低估值成长',
    'max_position': 0.15,      # 单只最多15%总仓
    'roe_min': 15,             # ROE > 15%
    'profit_growth_min': 10,   # 利润增速 > 10%
    'debt_ratio_max': 60,      # 负债率 < 60%
    'pe_max': 40,              # PE < 40（成长股适当放宽）
    'stop_loss_pct': 0.10,     # 止损-10%（长持可接受更大波动）
    'take_profit_pct': 0.30,   # 目标30%
    'hold_days_min': 30,       # 至少持有30天
    'hold_days_max': 120,      # 最长持有120天
    'required_score': 30,
}


# ============================================================
# 数据类
# ============================================================

@dataclass
class Recommendation:
    """推荐记录"""
    # --- 无默认值（必须指定）---
    code: str
    name: str
    current_price: float
    tier: str                      # '激进档'/'稳健档'/'价值档'
    tier_type: str                 # '超跌反弹'/'主升浪'/'价值投资'
    buy_price: float              # 建议买入价
    buy_range_low: float          # 买入区间下限
    buy_range_high: float         # 买入区间上限
    entry_way: str                # 入场方式说明
    stop_loss: float             # 止损价
    stop_loss_pct: float         # 止损幅度%
    take_profit_1: float         # 第一止盈价
    take_profit_1_pct: float     # 第一止盈幅度%
    take_profit_2: float         # 第二止盈价
    take_profit_2_pct: float     # 第二止盈幅度%
    hold_days_max: int           # 建议最长持有天数
    signal_score: float          # 技术信号分
    fundamental_score: float     # 基本面分（0-100）
    combined_score: float        # 综合分

    # --- 有默认值 ---
    max_position_pct: float = 5.0   # 单只建议仓位上限
    level: int = 0               # 信号等级 0-5
    roe: Optional[float] = None
    profit_growth: Optional[float] = None
    debt_ratio: Optional[float] = None
    pe_ratio: Optional[float] = None
    reasons: str = ''
    risk_warning: str = ''        # 风险提示
    rsi: float = 0
    boll_position: float = 0
    ma_bullish: bool = False
    atr: float = 0
    market_cap: Optional[float] = None  # 市值(亿)
    sector: str = ''
    
    def to_display(self) -> str:
        """格式化输出"""
        lines = [
            f"━━━━━━━━━━━━━━━",
            f"【{self.name}】{self.code} | {self.tier_type} | 建议仓位≤{self.max_position_pct:.0f}%",
            f"现价: {self.current_price:.2f}元",
            f"买入区间: {self.buy_range_low:.2f} ~ {self.buy_range_high:.2f}元",
            f"建议买入价: {self.buy_price:.2f}元 ({self.entry_way})",
            f"",
            f"止损价: {self.stop_loss:.2f}元 ({self.stop_loss_pct:+.1f}%)",
            f"第一止盈: {self.take_profit_1:.2f}元 ({self.take_profit_1_pct:+.1f}%)",
            f"第二止盈: {self.take_profit_2:.2f}元 ({self.take_profit_2_pct:+.1f}%)",
            f"最长持有: {self.hold_days_max}天",
            f"",
            f"技术信号分: {self.signal_score:.0f} | 基本面分: {self.fundamental_score:.0f} | 综合分: {self.combined_score:.0f}",
            f"理由: {self.reasons}",
        ]
        if self.risk_warning:
            lines.append(f"⚠️ {self.risk_warning}")
        if self.pe_ratio:
            lines.append(f"估值: PE={self.pe_ratio:.1f} ROE={self.roe:.1f}% 负债={self.debt_ratio:.1f}%")
        lines.append(f"技术: RSI={self.rsi:.1f} 布林={self.boll_position:.1f}% 多头={'是' if self.ma_bullish else '否'}")
        if self.market_cap:
            lines.append(f"市值: {self.market_cap:.0f}亿 | 板块: {self.sector or '未知'}")
        lines.append(f"━━━━━━━━━━━━━━━")
        return '\n'.join(lines)

    def to_telegram(self) -> str:
        """飞书友好的单条推荐格式"""
        pe_str = f"PE={self.pe_ratio:.1f}" if self.pe_ratio else ""
        roe_str = f"ROE={self.roe:.1f}%" if self.roe else ""
        pg_str = f"增速={self.profit_growth:.0f}%" if self.profit_growth else ""
        dr_str = f"负债={self.debt_ratio:.1f}%" if self.debt_ratio else ""
        fundamentals = " | ".join([x for x in [pe_str, roe_str, pg_str, dr_str] if x])

        lines = [
            f"*{self.name}*({self.code}) {self.tier_type}",
            f"现价: {self.current_price:.2f} | 建议买: {self.buy_price:.2f}元",
            f"买入: {self.buy_range_low:.2f}~{self.buy_range_high:.2f}元 | 仓位≤{self.max_position_pct:.0f}%",
            f"止损: {self.stop_loss:.2f}({self.stop_loss_pct:+.1f}%) | 目标1: {self.take_profit_1:.2f}({self.take_profit_1_pct:+.1f}%) | 目标2: {self.take_profit_2:.2f}({self.take_profit_2_pct:+.1f}%)",
            f"综合分: {self.combined_score:.0f} | {self.reasons}",
        ]
        if fundamentals:
            lines.append(foundamentals)
        if self.risk_warning:
            lines.append(f"⚠️ {self.risk_warning}")
        return '\n'.join(lines)


# ============================================================
# 数据库读取
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def bulk_load_financial_data(conn, codes: List[str]) -> Dict[str, Dict]:
    """批量加载多只股票的财务数据（一次CTE查询，替代4939次单次查询）"""
    if not codes:
        return {}
    placeholders = ','.join('?' * len(codes))
    cur = conn.cursor()
    cur.execute(f"""
        WITH latest AS (
            SELECT code, MAX(report_date) as maxd
            FROM financial_data
            WHERE code IN ({placeholders})
            GROUP BY code
        )
        SELECT fd.code, fd.roe, fd.profit_growth, fd.revenue_growth,
               fd.debt_ratio, fd.gross_margin, fd.net_margin,
               pe.pe_ttm
        FROM financial_data fd
        JOIN latest l ON fd.code = l.code AND fd.report_date = l.maxd
        LEFT JOIN (
            SELECT code, pe_ttm FROM pe_pb_data
            WHERE (code, fetch_date) IN (
                SELECT code, MAX(fetch_date) FROM pe_pb_data
                WHERE code IN ({placeholders}) AND pe_ttm > 0
                GROUP BY code
            )
        ) pe ON fd.code = pe.code
    """, codes + codes)
    result = {}
    for row in cur.fetchall():
        result[row[0]] = {
            'roe': row[1], 'profit_growth': row[2], 'revenue_growth': row[3],
            'debt_ratio': row[4], 'gross_margin': row[5], 'net_margin': row[6],
            'pe_ratio': row[7],
        }
    return result


def bulk_load_market_cap(conn, codes: List[str]) -> Dict[str, Optional[float]]:
    """批量加载市值估算（一次查询替代每股票询）"""
    if not codes:
        return {}
    placeholders = ','.join('?' * len(codes))
    cur = conn.cursor()
    cur.execute(f"""
        SELECT i.code, i.current_price, f.bvps
        FROM indicators i
        LEFT JOIN financial_data f ON f.code = i.code
        WHERE i.date = (SELECT MAX(date) FROM indicators)
          AND i.code IN ({placeholders})
          AND i.current_price IS NOT NULL AND i.current_price > 0
    """, codes)
    result = {}
    for code, price, bvps in cur.fetchall():
        if price and bvps:
            try:
                cap = price * (bvps * 1e8) / 1e8
                result[code] = cap if cap < 5000 else cap
            except:
                result[code] = None
        else:
            result[code] = None
    return result


def bulk_load_double_up_scores(conn, codes: List[str]) -> Dict[str, Dict]:
    """批量加载双五维打分（一次CTE查询，替代每股票询）"""
    if not codes:
        return {}
    placeholders = ','.join('?' * len(codes))
    cur = conn.cursor()
    cur.execute(f"""
        WITH latest AS (
            SELECT code, MAX(scan_date) as maxd
            FROM double_up_scores
            WHERE code IN ({placeholders})
            GROUP BY code
        )
        SELECT d.code, d.total_score, d.industry_score, d.perf_score,
               d.mc_score, d.turn_score, d.cat_score
        FROM double_up_scores d
        JOIN latest l ON d.code = l.code AND d.scan_date = l.maxd
    """, codes)
    result = {}
    for row in cur.fetchall():
        result[row[0]] = {
            'total_score': row[1], 'industry_score': row[2],
            'perf_score': row[3], 'mc_score': row[4],
            'turn_score': row[5], 'cat_score': row[6],
        }
    return result


def get_all_candidates(conn) -> List[Dict]:
    """获取所有候选股（有完整指标的）"""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            i.code, s.name, i.current_price, i.rsi_14, i.boll_position,
            i.ma5, i.ma10, i.ma20, i.ma60, i.ma_bullish, i.atr_14,
            i.signal_score, i.signal_level, i.change_pct,
            s.sector
        FROM indicators i
        JOIN stocks s ON i.code = s.code
        WHERE i.date = (SELECT MAX(date) FROM indicators)
          AND i.current_price IS NOT NULL
          AND i.current_price > 0
    """)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_double_up_score(conn, code: str) -> Optional[Dict]:
    """获取双五维打分（来自周日周更），用于稳健档前置过滤"""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT total_score, industry_score, perf_score,
                   mc_score, turn_score, cat_score
            FROM double_up_scores
            WHERE code = ?
              AND scan_date = (SELECT MAX(scan_date) FROM double_up_scores)
            LIMIT 1
        """, (code,))
    except sqlite3.OperationalError:
        # 表不存在（周日 cron 首次运行前）
        return None
    row = cur.fetchone()
    if not row:
        return None
    return {
        'total_score': row[0],
        'industry_score': row[1],
        'perf_score': row[2],
        'mc_score': row[3],
        'turn_score': row[4],
        'cat_score': row[5],
    }


def get_pe_from_db(conn, code: str) -> Optional[float]:
    """从pe_pb_data获取最新PE"""
    cur = conn.cursor()
    cur.execute("""
        SELECT pe_ttm FROM pe_pb_data
        WHERE code = ? AND pe_ttm IS NOT NULL AND pe_ttm > 0
        ORDER BY fetch_date DESC
        LIMIT 1
    """, (code,))
    row = cur.fetchone()
    return row[0] if row else None


def get_financial_data(conn, code: str) -> Optional[Dict]:
    """获取单只股票最新财务数据（合并PE/PB）"""
    cur = conn.cursor()
    cur.execute("""
        SELECT roe, profit_growth, revenue_growth, debt_ratio,
               gross_margin, net_margin
        FROM financial_data
        WHERE code = ?
        ORDER BY report_date DESC
        LIMIT 1
    """, (code,))
    row = cur.fetchone()
    if not row:
        return None
    
    result = {
        'roe': row[0], 'profit_growth': row[1], 'revenue_growth': row[2],
        'debt_ratio': row[3], 'pe_ratio': None, 'pb_ratio': None,
        'gross_margin': row[4], 'net_margin': row[5]
    }
    
    # 合并PE/PB
    pe = get_pe_from_db(conn, code)
    if pe:
        result['pe_ratio'] = pe
    
    return result


def get_market_cap(conn, code: str) -> Optional[float]:
    """估算市值（亿）"""
    cur = conn.cursor()
    # 从K线取最新收盘价 × 估算股本（从financial_data的bvps估算）
    cur.execute("""
        SELECT i.current_price, f.bvps
        FROM indicators i
        LEFT JOIN financial_data f ON f.code = i.code
        WHERE i.code = ? AND i.date = (SELECT MAX(date) FROM indicators)
        ORDER BY f.report_date DESC
        LIMIT 1
    """, (code,))
    row = cur.fetchone()
    if row and row[0] and row[1]:
        price, bvps = row
        # bvps × 估算股本 = 市值（亿），假设总股本=净资产/每股净资产
        try:
            shares = (bvps * 1e8)  # 简化：bvps单位是元/股，假设1亿股
            cap = price * shares / 1e8  # 亿元
            return cap if cap < 5000 else cap  # 保留原始值
        except:
            pass
    return None


def calc_margin_factor(code, conn):
    """计算融资融券因子评分
    从 westock 或本地数据获取个股近5日融资净买入额
    条件：
    - 融资净买入为正 + 融资余额占流通市值比3%-15% → +15%加权分
    - 融资净买入为负 + 融资余额占流通市值比>10% → -10%降权分
    返回: (bonus_pct, detail_str)
    """
    try:
        # 从westock获取融资融券数据
        import subprocess
        result = subprocess.run(
            ["npx", "-y", "westock-data-skillhub@1.0.3", "margintrade", code],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout.strip()
        if not output or len(output) < 50:
            return 0, "无融资数据"

        # 解析westock输出（pipe-delimited CSV）
        lines = [l for l in output.split('\n') if l.strip() and '---' not in l]
        if len(lines) < 2:
            return 0, "无融资数据"

        # 解析表头和数据行
        header = [h.strip() for h in lines[0].split('|') if h.strip()]
        data = [v.strip() for v in lines[-1].split('|') if v.strip()]

        # 找到关键字段
        finance_value = None  # 融资余额（元）
        finance_change = None  # 融资余额变化
        market_cap = None  # 流通市值

        for i, h in enumerate(header):
            if i < len(data):
                try:
                    v = float(data[i]) if data[i] else 0
                    if 'FinanceValue' in h or 'margin_balance' in h.lower():
                        finance_value = v
                    elif 'rz' in h.lower() and ('change' in h.lower() or 'net' in h.lower()):
                        finance_change = v
                    elif 'market_cap' in h.lower() or '流通市值' in h:
                        market_cap = v
                except:
                    pass

        if finance_value is None or finance_value <= 0:
            return 0, "无融资余额"

        # 融资余额单位：westock 返回的是元，需转为亿元
        finance_value_yi = finance_value / 1e8

        # 估算流通市值（从market_cache.db获取）
        mkt_conn = sqlite3.connect(str(DB_PATH))
        cur = mkt_conn.execute(
            "SELECT total_shares_real FROM stocks WHERE code=?", [code]
        )
        row = cur.fetchone()
        mkt_conn.close()

        if row and row[0]:
            # 需要当前价格
            mkt_conn2 = sqlite3.connect(str(DB_PATH))
            cur2 = mkt_conn2.execute(
                "SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", [code]
            )
            price_row = cur2.fetchone()
            mkt_conn2.close()
            if price_row:
                market_cap_yi = row[0] * price_row[0] / 1e8
                margin_ratio = finance_value_yi / market_cap_yi * 100 if market_cap_yi > 0 else 0

                # 判断条件
                if finance_change and finance_change > 0 and 3 <= margin_ratio <= 15:
                    return 15, f"融资净买入+{finance_change:.0f}元, 占比{margin_ratio:.1f}%"
                elif finance_change and finance_change < 0 and margin_ratio > 10:
                    return -10, f"融资净卖出{abs(finance_change):.0f}元, 占比{margin_ratio:.1f}%"

        return 0, f"融资余额{finance_value_yi:.2f}亿"

    except Exception as e:
        return 0, f"融资数据获取失败: {str(e)[:30]}"


# ============================================================
# Phase 1: 三档筛选引擎
# ============================================================

def calc_fundamental_score(fin: Optional[Dict]) -> float:
    """基本面评分 0-100"""
    if not fin:
        return 30  # 无数据给低分
    score = 0
    # ROE (30分)
    if fin.get('roe'):
        if fin['roe'] > 20: score += 30
        elif fin['roe'] > 15: score += 25
        elif fin['roe'] > 10: score += 15
        elif fin['roe'] > 5: score += 10
        elif fin['roe'] > 0: score += 5
        else: score += 0
    # 利润增速 (30分)
    pg = fin.get('profit_growth')
    if pg and pg > 0:
        if pg > 30: score += 30
        elif pg > 20: score += 25
        elif pg > 10: score += 20
        elif pg > 5: score += 15
        else: score += 10
    elif pg and pg < 0:
        score += max(0, 10 + pg)  # 亏损视情况扣分
    # 负债率 (20分)
    dr = fin.get('debt_ratio')
    if dr:
        if dr < 40: score += 20
        elif dr < 60: score += 15
        elif dr < 80: score += 8
        else: score += 0
    # 毛利率 (20分)
    gm = fin.get('gross_margin')
    if gm:
        if gm > 50: score += 20
        elif gm > 30: score += 15
        elif gm > 20: score += 10
        elif gm > 10: score += 5
    return min(100, max(0, score))


def screen_aggressive(candidates: List[Dict], fin_map: Dict, mc_map: Dict[str, Optional[float]]) -> List[Recommendation]:
    """激进档：超跌反弹筛选"""
    cfg = AGGRESSIVE_CONFIG
    results = []
    
    for c in candidates:
        rsi = c.get('rsi_14') or 50
        boll = c.get('boll_position') or 50
        score = c.get('signal_score') or 0
        
        # 基础条件
        if rsi >= cfg['rsi_max']: continue
        if boll >= cfg['boll_pos_max']: continue
        if score < cfg['required_score']: continue
        
        fin = fin_map.get(c['code'])
        f_score = calc_fundamental_score(fin)
        
        # 基本面太差的不推荐（负债>80%不推荐超跌反弹）
        if fin and fin.get('debt_ratio', 0) > 80:
            continue
        
        price = c['current_price']
        atr = c.get('atr_14') or price * 0.02
        name = c['name']
        
        # 过滤ST股
        if any(name.startswith(p) for p in ('ST', '*ST', 'S')):
            continue
        
        # 买入区间：现价±3%
        buy_low = price * 0.97
        buy_high = price * 1.00  # 激进档：现价即可买入
        
        rec = Recommendation(
            code=c['code'], name=name,
            current_price=price,
            tier='激进档', tier_type='超跌反弹',
            max_position_pct=AGGRESSIVE_CONFIG['max_position'] * 100,
            buy_price=price,
            buy_range_low=buy_low, buy_range_high=buy_high,
            entry_way='现价买入或-3%区间分批建仓',
            stop_loss=price * (1 - cfg['stop_loss_pct']),
            stop_loss_pct=-cfg['stop_loss_pct'] * 100,
            take_profit_1=price * (1 + cfg['take_profit_targets'][0]),
            take_profit_1_pct=cfg['take_profit_targets'][0] * 100,
            take_profit_2=price * (1 + cfg['take_profit_targets'][1]),
            take_profit_2_pct=cfg['take_profit_targets'][1] * 100,
            hold_days_max=cfg['hold_days_max'],
            signal_score=score,
            fundamental_score=f_score,
            combined_score=score * 0.6 + f_score * 0.4,
            level=c.get('signal_level') or 0,
            roe=fin.get('roe') if fin else None,
            profit_growth=fin.get('profit_growth') if fin else None,
            debt_ratio=fin.get('debt_ratio') if fin else None,
            pe_ratio=fin.get('pe_ratio') if fin else None,
            rsi=rsi, boll_position=boll,
            ma_bullish=bool(c.get('ma_bullish')),
            atr=atr,
            market_cap=mc_map.get(c['code']),
            sector=c.get('sector') or '',
            reasons=_build_aggressive_reason(rsi, boll, c, fin),
            risk_warning=_build_risk_warning(fin, 'aggressive'),
        )
        results.append(rec)
    
    # 按综合分排序
    results.sort(key=lambda x: x.combined_score, reverse=True)
    return results


def screen_steady(candidates: List[Dict], fin_map: Dict, mc_map: Dict[str, Optional[float]], du_map: Dict) -> List[Recommendation]:
    """稳健档：主升浪顺势"""
    cfg = STEADY_CONFIG
    results = []
    
    for c in candidates:
        rsi = c.get('rsi_14') or 50
        boll = c.get('boll_position') or 50
        ma_bullish = bool(c.get('ma_bullish'))
        score = c.get('signal_score') or 0
        
        # 基础条件
        if not (cfg['rsi_min'] <= rsi <= cfg['rsi_max']): continue
        if not (cfg['boll_pos_min'] <= boll <= cfg['boll_pos_max']): continue
        if cfg['ma_required'] and not ma_bullish: continue
        if score < cfg['required_score']: continue

        # 双五维前置过滤：稳健档只推周六打分60分以上的（批量加载，线程安全）
        du = du_map.get(c['code'])
        if du is not None and du['total_score'] < 60:
            continue

        fin = fin_map.get(c['code'])
        f_score = calc_fundamental_score(fin)
        
        # 融资融券因子（翻倍策略试行）
        margin_bonus, margin_detail = calc_margin_factor(c['code'], None)
        
        # 基本面太差不推荐
        if fin and fin.get('debt_ratio', 0) > 80:
            continue
        
        price = c['current_price']
        atr = c.get('atr_14') or price * 0.02
        name = c['name']
        
        if any(name.startswith(p) for p in ('ST', '*ST', 'S')):
            continue
        
        # 稳健档：回调至MA5/MA10买入
        ma5 = c.get('ma5') or price
        ma10 = c.get('ma10') or price
        buy_target = min(ma5, ma10, price)
        buy_low = buy_target * 0.98
        buy_high = buy_target * 1.02
        
        rec = Recommendation(
            code=c['code'], name=name,
            current_price=price,
            tier='稳健档', tier_type='主升浪顺势',
            max_position_pct=STEADY_CONFIG['max_position'] * 100,
            buy_price=buy_target,
            buy_range_low=buy_low, buy_range_high=buy_high,
            entry_way=f'回调至MA5({ma5:.2f})或MA10({ma10:.2f})附近买入',
            stop_loss=min(ma5, ma10) * 0.95,
            stop_loss_pct=-cfg['stop_loss_pct'] * 100,
            take_profit_1=price * (1 + cfg['take_profit_targets'][0]),
            take_profit_1_pct=cfg['take_profit_targets'][0] * 100,
            take_profit_2=price * (1 + cfg['take_profit_targets'][1]),
            take_profit_2_pct=cfg['take_profit_targets'][1] * 100,
            hold_days_max=cfg['hold_days_max'],
            signal_score=score,
            fundamental_score=f_score,
            combined_score=score * 0.5 + f_score * 0.5 + margin_bonus,
            level=c.get('signal_level') or 0,
            roe=fin.get('roe') if fin else None,
            profit_growth=fin.get('profit_growth') if fin else None,
            debt_ratio=fin.get('debt_ratio') if fin else None,
            pe_ratio=fin.get('pe_ratio') if fin else None,
            rsi=rsi, boll_position=boll,
            ma_bullish=ma_bullish,
            atr=atr,
            market_cap=mc_map.get(c['code']),
            sector=c.get('sector') or '',
            reasons=_build_steady_reason(rsi, boll, c, fin) + (f" | 融资{margin_detail}" if margin_bonus != 0 else ""),
            risk_warning=_build_risk_warning(fin, 'steady'),
        )
        results.append(rec)
    
    results.sort(key=lambda x: x.combined_score, reverse=True)
    return results


def screen_value(candidates: List[Dict], fin_map: Dict, mc_map: Dict[str, Optional[float]]) -> List[Recommendation]:
    """价值档：基本面+低估值"""
    cfg = VALUE_CONFIG
    results = []
    
    for c in candidates:
        fin = fin_map.get(c['code'])
        f_score = calc_fundamental_score(fin)
        
        # 基本面条件
        if not fin: continue  # 无财务数据跳过
        roe_val = fin.get('roe') or 0
        pg_val = fin.get('profit_growth')
        dr_val = fin.get('debt_ratio') or 999
        pe_val = fin.get('pe_ratio')
        if roe_val < cfg['roe_min']: continue
        if pg_val is None or pg_val < cfg['profit_growth_min']: continue
        if dr_val > cfg['debt_ratio_max']: continue
        if pe_val is not None and pe_val > cfg['pe_max']: continue
        
        score = c.get('signal_score') or 0
        rsi = c.get('rsi_14') or 50
        boll = c.get('boll_position') or 50
        
        # 价值投资也看技术位，不要买在历史高位
        if boll > 90: continue
        
        price = c['current_price']
        atr = c.get('atr_14') or price * 0.02
        name = c['name']
        
        if any(name.startswith(p) for p in ('ST', '*ST', 'S')):
            continue
        
        # 价值档：PE低位买入
        pe = fin.get('pe_ratio') or 0
        ma20 = c.get('ma20') or price
        
        # 买入区间：现价附近或回调至MA20
        buy_target = min(price, ma20 * 1.02)
        buy_low = buy_target * 0.98
        buy_high = price * 1.03
        
        rec = Recommendation(
            code=c['code'], name=name,
            current_price=price,
            tier='价值档', tier_type='低估值成长',
            max_position_pct=VALUE_CONFIG['max_position'] * 100,
            buy_price=buy_target,
            buy_range_low=buy_low, buy_range_high=buy_high,
            entry_way=f'低估值区间分批建仓，PE={pe:.1f}历史偏低',
            stop_loss=price * (1 - cfg['stop_loss_pct']),
            stop_loss_pct=-cfg['stop_loss_pct'] * 100,
            take_profit_1=price * (1 + cfg['take_profit_pct']),
            take_profit_1_pct=cfg['take_profit_pct'] * 100,
            take_profit_2=price * (1 + cfg['take_profit_pct'] * 1.5),
            take_profit_2_pct=cfg['take_profit_pct'] * 150,
            hold_days_max=cfg['hold_days_max'],
            signal_score=score,
            fundamental_score=f_score,
            combined_score=f_score * 0.7 + score * 0.3,
            level=c.get('signal_level') or 0,
            roe=fin.get('roe'),
            profit_growth=fin.get('profit_growth'),
            debt_ratio=fin.get('debt_ratio'),
            pe_ratio=pe or None,
            rsi=rsi, boll_position=boll,
            ma_bullish=bool(c.get('ma_bullish')),
            atr=atr,
            market_cap=mc_map.get(c['code']),
            sector=c.get('sector') or '',
            reasons=_build_value_reason(c, fin),
            risk_warning=_build_risk_warning(fin, 'value'),
        )
        results.append(rec)
    
    results.sort(key=lambda x: x.combined_score, reverse=True)
    return results


# ============================================================
# 理由构建
# ============================================================

def _build_aggressive_reason(rsi, boll, c, fin):
    """激进档推荐理由 + 投资框架分析"""
    edge_map = {
        (True, True): "RSI严重超卖+布林下轨 → 极端超跌反弹机会",
        (True, False): "RSI超卖 → 技术面极端背离，反弹概率高",
        (False, True): "布林低位 → 价格触及极端支撑带",
        (False, False): "技术超卖 → 乖离率偏离均值过大",
    }
    rsi_extreme = rsi < 20
    boll_extreme = boll < 10
    edge_desc = edge_map.get((rsi_extreme, boll_extreme), "技术超跌反弹")

    # 场景分析
    bull = "反弹至买入区间上方10%（强阻力位）" if rsi < 15 else "反弹5-8%后震荡"
    bear = "继续下探，跌破布林下轨3%+"
    scenario = f"📊 情景：反弹概率60%（目标{bull}）/ 继续筑底30%（横盘）/ 破位10%（止损离场）"

    # 失效条件
    inv = "RSI未再创新低但股价持续新低（底背离失效）"
    return f"Edge: {edge_desc} | Thesis: 超跌反弹均值回归 | {scenario} | 失效: {inv}"


def _build_steady_reason(rsi, boll, c, fin):
    """稳健档推荐理由 + 投资框架分析"""
    edge_map = {
        (True, True): "均线多头+RSI健康+布林中上轨 → 主升浪健康",
        (True, False): "均线多头+RSI健康 → 趋势延续概率高",
        (False, True): "RSI区间健康+布林开口扩张 → 动能加速",
        (False, False): "技术面健康 → 顺势而为",
    }
    ma_ok = c.get('ma_bullish', False)
    rsi_mid = 40 <= rsi <= 60
    boll_ok = 30 <= boll <= 70
    edge_desc = edge_map.get((ma_ok, rsi_mid), "主升浪顺势")

    # 场景分析
    bull = "沿均线稳步上涨15-20%（趋势加速）"
    bear = "跌破20日线且RSI失守50"
    scenario = f"📊 情景：趋势延续55%（目标{bull}）/ 震荡整理25%（高抛低吸）/ 回撤20%（止损离场）"

    # 失效条件
    inv = "收盘跌破20日线或RSI快速跌破50（趋势破坏）"
    return f"Edge: {edge_desc} | Thesis: 趋势延续顺势交易 | {scenario} | 失效: {inv}"


def _build_value_reason(c, fin):
    """价值档推荐理由 + 投资框架分析"""
    if not fin:
        return "Edge: 低估值 | Thesis: 价值回归 | 失效: 基本面恶化"

    roe = fin.get('roe', 0) or 0
    pg = fin.get('profit_growth', 0) or 0
    pe = fin.get('pe_ratio', 0) or 0

    if roe >= 20 and pg >= 15 and pe <= 20:
        quality = "优质成长：ROE高+增速快+估值低 → 戴维斯双击潜力"
    elif roe >= 15 and pg >= 10:
        quality = "稳健成长：ROE达标+持续盈利 → 估值修复机会"
    elif pe <= 15 and roe >= 10:
        quality = "深度价值：PE极低+ROE尚可 → 价值陷阱风险低"
    else:
        quality = f"ROE={roe:.0f}% PE={pe:.0f} → 性价比尚可"

    # 场景分析
    bull = "业绩超预期+估值重估 → 目标价30%+"
    bear = "业绩不及预期或宏观拖累 → 估值进一步压缩"
    scenario = f"📊 情景：业绩兑现40%（目标{bull}）/ 估值修复35%（10-15%）/ 业绩下调25%（持有或止损）"

    # 失效条件
    inv = f"PE杀到{pe*1.3:.0f}倍以上或净利润增速转负"

    return f"Edge: {quality} | Thesis: 价值回归+成长验证 | {scenario} | 失效: {inv}"


def _build_risk_warning(fin, tier):
    if not fin:
        return '⚠️ 无基本面数据，谨慎参与'
    warnings = []
    dr = fin.get('debt_ratio')
    if dr and dr > 70:
        warnings.append(f"负债率{dr:.0f}%偏高")
    pg = fin.get('profit_growth')
    if pg is not None and pg < 0:
        warnings.append(f"利润下滑{pg:.1f}%")
    roe_val = fin.get('roe')
    if roe_val is not None and roe_val < 5:
        warnings.append('ROE偏低')
    if tier == 'aggressive' and dr and dr > 75:
        warnings.append('超跌反弹不宜重仓负债股')
    if warnings:
        return ' '.join(warnings)
    return ''


# ============================================================
# Phase 2: 获取PE/PB历史分位（AKShare）
# ============================================================

def get_pe_pb_percentile(code: str) -> Optional[Dict]:
    """获取PE/PB历史分位数（AKShare）"""
    try:
        # 使用AKShare获取PE/PB分位
        import os as _os
        _os.environ['http_proxy'] = 'socks5://127.0.0.1:10808'
        _os.environ['https_proxy'] = 'socks5://127.0.0.1:10808'
        
        df = ak.stock_a_indicator_lg(symbol=code, period='近3年')
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            return {
                'pe_percentile': float(latest.get('pe Tencent', latest.get('pe', 50))),
                'pb_percentile': float(latest.get('pb', 50)),
            }
    except Exception as e:
        pass
    return None


# ============================================================
# Phase 3: 风控引擎
# ============================================================

def calc_risk_metrics(rec: Recommendation, position_size_pct: float) -> Dict:
    """计算风控指标"""
    return {
        'max_loss_pct': rec.stop_loss_pct,
        'max_loss_amount': position_size_pct * abs(rec.stop_loss_pct) / 100,
        'target_profit_pct': rec.take_profit_2_pct,
        'risk_reward_ratio': abs(rec.take_profit_2_pct) / abs(rec.stop_loss_pct) if rec.stop_loss_pct else 0,
        'position_recommendation': f"{int(rec.tier_max_position() * 100)}%总仓",
    }


def rank_and_filter(all_recs: List[Recommendation], top_n: int = 5) -> List[Recommendation]:
    """对所有推荐排序，输出TopN，避免推太多"""
    # 先按档位去重（每档最多取top3）
    by_tier = {'激进档': [], '稳健档': [], '价值档': []}
    for rec in all_recs:
        by_tier[rec.tier].append(rec)
    
    result = []
    for tier_recs in by_tier.values():
        tier_recs.sort(key=lambda x: x.combined_score, reverse=True)
        result.extend(tier_recs[:3])  # 每档最多3只
    
    # 全局排序
    result.sort(key=lambda x: x.combined_score, reverse=True)
    return result[:top_n]


# ============================================================
# 主扫描函数
# ============================================================

def full_scan(top_n: int = 5, min_score: float = 50) -> Dict[str, Any]:
    """
    全市场扫描，返回三档推荐
    返回: {
        'aggressive': [Recommendation],
        'steady': [Recommendation],
        'value': [Recommendation],
        'summary': {...}
    }
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始全市场扫描...")
    scan_start = time.time()
    
    conn = get_db()
    
    # 获取候选股
    candidates = get_all_candidates(conn)
    print(f"  候选股: {len(candidates)} 只")
    
    print(f"  加载财务数据...")
    fin_start = time.time()
    codes = [c['code'] for c in candidates]
    fin_map = bulk_load_financial_data(conn, codes)
    mc_map = bulk_load_market_cap(conn, codes)
    du_map = bulk_load_double_up_scores(conn, codes)
    print(f"  财务数据: {len(fin_map)}/{len(candidates)}只有效, 市值:{len(mc_map)}只, 五维:{len(du_map)}只, 耗时{time.time()-fin_start:.1f}s")
    
    # 三档筛选（并行：ThreadPoolExecutor绕开SQLite线程限制）
    print(f"  三档并行筛选...")
    screen_start = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_agg = ex.submit(screen_aggressive, candidates, fin_map, mc_map)
        f_std = ex.submit(screen_steady, candidates, fin_map, mc_map, du_map)
        f_val = ex.submit(screen_value, candidates, fin_map, mc_map)
        agg_recs = f_agg.result()
        std_recs = f_std.result()
        val_recs = f_val.result()
    print(f"    激进档→{len(agg_recs)}只, 稳健档→{len(std_recs)}只, 价值档→{len(val_recs)}只, 耗时{time.time()-screen_start:.1f}s")
    
    # 取TopN
    all_recs = agg_recs + std_recs + val_recs
    top_recs = rank_and_filter(all_recs, top_n=top_n)
    
    conn.close()
    
    elapsed = time.time() - scan_start
    print(f"  扫描完成，耗时 {elapsed:.1f}s")
    
    return {
        'aggressive': agg_recs[:5],
        'steady': std_recs[:5],
        'value': val_recs[:5],
        'all_count': {
            'aggressive': len(agg_recs),
            'steady': len(std_recs),
            'value': len(val_recs),
        },
        'top_recommendations': top_recs,
        'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'elapsed_seconds': elapsed,
    }


def format_scan_report(result: Dict) -> str:
    """格式化扫描报告"""
    lines = [
        "📊 **全市场智能选股报告**",
        f"🕐 扫描时间: {result['scan_time']}",
        f"⏱ 耗时: {result['elapsed_seconds']:.1f}秒",
        "",
    ]
    
    # 统计
    lines.append("**【市场概览】**")
    lines.append(f"  超跌反弹候选: {result['all_count']['aggressive']} 只")
    lines.append(f"  主升浪候选: {result['all_count']['steady']} 只")
    lines.append(f"  低估值候选: {result['all_count']['value']} 只")
    lines.append("")
    
    # 三档汇总
    for tier_key, tier_name, recs in [
        ('aggressive', '🔥 激进档-超跌反弹', result['aggressive']),
        ('steady', '📈 稳健档-主升浪', result['steady']),
        ('value', '💎 价值档-低估值', result['value']),
    ]:
        if recs:
            lines.append(f"**【{tier_name}】**")
            for rec in recs[:3]:
                lines.append(f"  {rec.name}({rec.code}) {rec.current_price:.2f}元 | "
                           f"买{rec.buy_range_low:.2f}-{rec.buy_range_high:.2f} | "
                           f"综合分{rec.combined_score:.0f}")
                if rec.pe_ratio:
                    lines.append(f"    估值:PE={rec.pe_ratio:.1f} ROE={rec.roe:.1f}% 负债={rec.debt_ratio:.1f}%")
                lines.append(f"    {rec.reasons[:60]}")
            lines.append("")
    
    # Top5重点推荐
    if result['top_recommendations']:
        lines.append("**★ 重点推荐 TOP5 ★**")
        for i, rec in enumerate(result['top_recommendations'], 1):
            lines.append(f"")
            lines.append(f"**{i}. {rec.name}({rec.code})** {rec.tier_type}")
            lines.append(f"   现价: {rec.current_price:.2f} | 建议买入: {rec.buy_price:.2f}元 ({rec.entry_way})")
            lines.append(f"   止损: {rec.stop_loss:.2f} ({rec.stop_loss_pct:+.1f}%) | "
                         f"目标1: {rec.take_profit_1:.2f} ({rec.take_profit_1_pct:+.1f}%) | "
                         f"目标2: {rec.take_profit_2:.2f} ({rec.take_profit_2_pct:+.1f}%)")
            lines.append(f"   综合分: {rec.combined_score:.0f} (技术{rec.signal_score:.0f}+基本面{rec.fundamental_score:.0f})")
            if rec.pe_ratio:
                lines.append(f"   基本面: PE={rec.pe_ratio:.1f} | ROE={rec.roe:.1f}% | "
                           f"利润增速={rec.profit_growth:.1f}% | 负债={rec.debt_ratio:.1f}%")
            if rec.risk_warning:
                lines.append(f"   ⚠️ {rec.risk_warning}")
    
    return '\n'.join(lines)


# ============================================================
# 回测模式集成
# ============================================================

def run_backtest_mode(mode: str = "run"):
    """回测→实盘闭环模式"""
    from pathlib import Path
    import subprocess, os
    btl_script = Path(__file__).parent.resolve() / "backtest_to_live.py"
    if not btl_script.exists():
        print(f"❌ backtest_to_live.py 不存在: {btl_script}")
        return
    
    if mode == "run":
        print("📊 运行回测→实盘闭环...")
        cmd = [sys.executable, str(btl_script), "--apply"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        if proc.returncode == 0:
            print("\n✅ 回测→实盘闭环完成")
            print("💡 建议: 使用 python3 auto_recommend.py --backtest-mode show 查看结果")
        else:
            print(f"\n❌ 回测失败 (exit={proc.returncode})")
    
    elif mode == "apply":
        print("⚙️ 应用已保存的回测映射到实盘参数...")
        mapping_file = Path.home() / ".hermes" / "cron" / "output" / "backtest_to_live_mapping.json"
        if not mapping_file.exists():
            print(f"❌ 映射文件不存在: {mapping_file}")
            print("💡 请先运行: python3 auto_recommend.py --backtest-mode run")
            return
        
        mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
        best = mapping.get("best_strategy", {})
        if not best:
            print("❌ 映射文件中无有效策略数据")
            return
        
        print(f"★ 最佳策略: {best.get('name', '?')}")
        kelly = best.get("kelly_params", {})
        print(f"📐 凯利参数: 胜率={kelly.get('win_rate', '?')}, 盈亏比={kelly.get('reward_risk_ratio', '?')}")
        adj = best.get("config_adjustments", {})
        print(f"⚙️ 配置调整: 止损={adj.get('stop_loss_pct', '?')}, 仓位={adj.get('max_position_pct', '?')}")
        
        applied = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "best_strategy": best.get("name", "?"),
            "kelly_params": kelly,
            "config_adjustments": adj,
            "source": "auto_recommend.py --backtest-mode apply",
        }
        applied_path = Path.home() / ".hermes" / "cron" / "output" / "backtest_live_applied.json"
        os.makedirs(os.path.dirname(str(applied_path)), exist_ok=True)
        applied_path.write_text(
            json.dumps(applied, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8"
        )
        print(f"✅ 已应用映射到 {applied_path}")
        
        # 输出建议的配置变更
        print("\n📋 建议配置变更:")
        tier = adj.get("tier", "稳健档")
        if tier == "激进档":
            print(f"  AGGRESSIVE_CONFIG['stop_loss_pct'] = {adj.get('stop_loss_pct', 0.07)}")
            print(f"  AGGRESSIVE_CONFIG['max_position'] = {adj.get('max_position_pct', 0.05)}")
        elif tier == "价值档":
            print(f"  VALUE_CONFIG['stop_loss_pct'] = {adj.get('stop_loss_pct', 0.10)}")
            print(f"  VALUE_CONFIG['max_position'] = {adj.get('max_position_pct', 0.15)}")
        else:
            print(f"  STEADY_CONFIG['stop_loss_pct'] = {adj.get('stop_loss_pct', 0.05)}")
            print(f"  STEADY_CONFIG['max_position'] = {adj.get('max_position_pct', 0.10)}")
        print(f"  trade_manager.py 凯利默认: win_rate={kelly.get('win_rate', 0.4)}, rr={kelly.get('reward_risk_ratio', 2.0)}")
    
    elif mode == "show":
        print("📊 显示当前回测映射...")
        cmd = [sys.executable, str(btl_script), "--show-mapping"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)


# ============================================================
# 命令行入口
# ============================================================

if __name__ == '__main__':
    # 解析 --backtest-mode 参数（在 subcmd 之前提取）
    if '--backtest-mode' in sys.argv:
        idx = sys.argv.index('--backtest-mode')
        if idx + 1 < len(sys.argv):
            btmode = sys.argv[idx + 1]
            run_backtest_mode(btmode)
            sys.exit(0)
        else:
            run_backtest_mode("run")
            sys.exit(0)
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    
    if cmd == 'scan':
        result = full_scan(top_n=5)
        report = format_scan_report(result)
        print('\n' + report)
        
        # 保存结果到JSON
        out_path = '/home/caojy/.hermes/profiles/stock/cron/output/auto_recommend_latest.json'
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        
        # 序列化（排除不可json序列化的字段）
        serializable = {}
        for k, v in result.items():
            if k == 'top_recommendations':
                serializable[k] = [r.__dict__ for r in v]
            elif k in ('aggressive', 'steady', 'value'):
                serializable[k] = [r.__dict__ for r in v[:5]]
            else:
                serializable[k] = v
        
        with open(out_path, 'w') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)
        print(f'\n结果已保存: {out_path}')
        
    elif cmd == 'candidates':
        result = full_scan(top_n=20)
        for tier, name in [('aggressive', '激进档'), ('steady', '稳健档'), ('value', '价值档')]:
            recs = result[tier]
            print(f'\n=== {name} ({len(recs)}只) ===')
            for rec in recs[:10]:
                print(rec.to_display())
                print()
    
    elif cmd == 'status':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM indicators")
        latest_date = cur.fetchone()[0]
        
        # 各档统计
        cur.execute("SELECT COUNT(*) FROM indicators WHERE date=? AND rsi_14 < 25 AND boll_position < 20", (latest_date,))
        agg_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM indicators WHERE date=? AND rsi_14 BETWEEN 40 AND 70 AND boll_position BETWEEN 20 AND 70 AND ma_bullish = 1", (latest_date,))
        std_count = cur.fetchone()[0]
        
        print(f'指标日期: {latest_date}')
        print(f'激进档候选(RSI<25且布林<20%): {agg_count} 只')
        print(f'稳健档候选(RSI 40-70且布林20-70%且多头): {std_count} 只')
        
        # 价值档（从financial_data）
        cur.execute("SELECT COUNT(*) FROM financial_data WHERE roe > 15 AND profit_growth > 10 AND debt_ratio < 60 AND pe_ratio < 40")
        val_count = cur.fetchone()[0]
        print(f'价值档候选(ROE>15%且利润增速>10%且负债<60%且PE<40): {val_count} 只')
        
        conn.close()
