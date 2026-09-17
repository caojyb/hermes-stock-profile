#!/usr/bin/env python3
"""
A股翻倍潜力股打分系统 v2.0
基于行业、业绩、市值、资金认可、催化剂五个维度评分

数据来源:
  - 行业: market_cache.db stocks.sector
  - 财务: EastMoney DataCenter RPT_LICO_FN_CPD
  - 市值: REG_CAPITAL(万元) × 现价(元) → 亿元
  - 换手率: 腾讯 qt.gtimg.cn → indicators.turnover_rate
  - 催化剂: EastMoney 公告API (np-anotice-stock.eastmoney.com)
  - 研报: EastMoney 研报API (reportapi.eastmoney.com) — 机构关注度代理
  - 机构调研: 暂无API，用研报数量替代

执行方式:
  python3 double_up_screener.py [--min-score 60] [--top 20]
  python3 double_up_screener.py --codes 600519,000001,300750
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

import os
import sys
import json
import time
import sqlite3
import requests
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path
import pandas as pd
import akshare as ak

# IMA 5:3:2 评分模块
try:
    from score_upgrade import score_stock as score_stock_ima
    _IMA_AVAILABLE = True
except ImportError:
    _IMA_AVAILABLE = False

# 基本面预筛选模块（financial_screen.py 的5项本地检查，不含THS API调用）
try:
    from financial_screen import check_roe, check_debt, check_profit_quality, check_revenue_vs_ar, check_governance, get_financial, get_stock_info
    _FINANCIAL_SCREEN_AVAILABLE = True
except ImportError:
    _FINANCIAL_SCREEN_AVAILABLE = False

# V2RayN 代理 — 2026-06-28: 代理不可用导致脚本超时，已注释绕过；需要时取消注释
# os.environ['http_proxy'] = 'socks5://127.0.0.1:10808'
# os.environ['https_proxy'] = 'socks5://127.0.0.1:10808'

# 本地财务数据缓存（周日更新一次，全表加载<0.1秒，供扫描使用）
FIN_DATA_CACHE: dict = {}  # {code: {roe, profit_growth, revenue_growth, gross_margin, net_margin, debt_ratio, ...}}

DB_PATH = _STOCK_MARKET_DB
EM_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'


def load_financial_data_cache() -> int:
    """
    启动时批量加载 financial_data 表到内存（周日更新后全表加载一次，<0.1秒）
    返回加载的股票数量。
    """
    global FIN_DATA_CACHE
    try:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        cur = conn.cursor()
        # 优先取有完整数据（profit_growth + revenue_growth 非NULL）的最近季度
        # Q1 2026 数据部分缺失 profit_growth，会导致业绩分被压至 0-20
        # 改用 COALESCE 策略：优先找最近有完整数据的季度，缺失时降级取最新可用数据
        cur.execute("""
            WITH complete_data AS (
                -- 标记有完整关键数据的记录
                SELECT code, report_date,
                       profit_growth IS NOT NULL AND revenue_growth IS NOT NULL AS has_complete
                FROM financial_data
            ),
            latest_complete AS (
                -- 每个股票最近有完整数据的季度
                SELECT cd.code, fd.report_date,
                       ROW_NUMBER() OVER (PARTITION BY cd.code ORDER BY fd.report_date DESC) AS rn
                FROM complete_data cd
                JOIN financial_data fd ON cd.code = fd.code AND cd.report_date = fd.report_date
                WHERE cd.has_complete = 1
            ),
            latest_any AS (
                -- 兜底：每个股票最新任何数据
                SELECT code, MAX(report_date) AS any_date
                FROM financial_data
                GROUP BY code
            )
            SELECT fd.code,
                   COALESCE(lc.report_date, la.any_date) AS report_date,
                   fd.roe, fd.profit_growth, fd.revenue_growth,
                   fd.gross_margin, fd.net_margin, fd.debt_ratio
            FROM financial_data fd
            LEFT JOIN latest_complete lc ON fd.code = lc.code AND lc.rn = 1
            LEFT JOIN latest_any la ON fd.code = la.code
            WHERE fd.report_date = COALESCE(lc.report_date, la.any_date)
        """)
        loaded = 0
        for row in cur.fetchall():
            code = row[0]
            FIN_DATA_CACHE[code] = {
                'code': code,
                'report_date': row[1],
                'roe': row[2],
                'profit_growth': row[3],
                'revenue_growth': row[4],
                'gross_margin': row[5],
                'net_margin': row[6],
                'debt_ratio': row[7],
            }
            loaded += 1
        conn.close()
        print(f"  [财务数据] 已从本地缓存加载 {loaded} 只股票最新财务数据")
        return loaded
    except Exception as e:
        print(f"  [财务数据] 加载失败: {e}，将使用API按需获取")
        return 0


def financial_pre_screen(candidates_list: list) -> tuple:
    """
    基本面预筛选：对已有财务数据的股票执行5项本地检查。
    数据来源：financial_data 表（DB查询，无外部API调用）

    检查项（5项来自 financial_screen.py，无需THS现金流数据）：
      ① ROE质量（ROE≥15%且非杠杆驱动）
      ② 负债健康度（负债率<70%）
      ③ 盈利质量（毛利率>30%+净利率>10%）
      ④ 收入vs应收（应收增幅≤营收增幅）
      ⑤ 公司治理（非ST/*ST）

    规则：
      - 有财务数据的 → 5项检查全部通过才放行
      - 无财务数据的 → 放行（不阻塞，数据尚未入库）

    Returns: (passed, failed, stats)
      - passed: 通过检查的候选股
      - failed: 未通过检查的候选股（含无数据放行的）
      - stats: 统计信息
    """
    if not _FINANCIAL_SCREEN_AVAILABLE:
        print(f"  [基本面预筛选] financial_screen 模块不可用，跳过")
        return candidates_list, [], {'total': len(candidates_list), 'with_data': 0, 'no_data': len(candidates_list), 'passed': len(candidates_list), 'failed': 0, 'skipped': True}

    passed = []
    failed = []
    stats = {'total': 0, 'with_data': 0, 'no_data': 0, 'passed': 0, 'failed': 0, 'skipped': False}

    for r in candidates_list:
        code = r['code']
        stats['total'] += 1

        # 查 financial_data 表是否有财务数据
        fin_rows = get_financial(code)
        if not fin_rows:
            # 无数据 → 放行
            stats['no_data'] += 1
            r['financial_screen'] = {'pass': True, 'reason': '无财务数据，放行'}
            passed.append(r)
            continue

        stats['with_data'] += 1
        fin = fin_rows[0]
        prev = fin_rows[1] if len(fin_rows) > 1 else None
        stock = get_stock_info(code)

        # 注意：financial_data 表存储的是单季度ROE，需年化后传给 check_roe
        # 年化因子：根据 report_date 判断季度
        report_date = fin.get('report_date', '')
        annual_factor = 4.0  # 默认Q1
        if report_date.endswith('06-30'):
            annual_factor = 2.0
        elif report_date.endswith('09-30'):
            annual_factor = 4.0 / 3.0
        elif report_date.endswith('12-31'):
            annual_factor = 1.0
        fin_annualized = dict(fin)
        if fin_annualized.get('roe') is not None:
            fin_annualized['roe'] = fin_annualized['roe'] * annual_factor

        # 执行5项本地检查（无THS API调用）
        checks = {
            'roe_quality': check_roe(fin_annualized, prev),
            'debt_health': check_debt(fin, prev),
            'profit_quality': check_profit_quality(fin, prev),
            'revenue_vs_ar': check_revenue_vs_ar(fin, prev),
            'governance': check_governance(fin, prev, stock),
        }

        # 只考虑有实际数据的检查项（排除 data_unavailable）
        available_checks = {k: v for k, v in checks.items()
                          if 'data_unavailable' not in v.get('flags', [])}

        # 有可用数据时，全部通过才算通过
        all_pass = all(v['pass'] for v in available_checks.values()) if available_checks else True

        r['financial_screen'] = {
            'pass': all_pass,
            'checks': {k: {'pass': v['pass'], 'score': v['score'], 'detail': v['detail']}
                      for k, v in checks.items()},
            'failed_checks': [k for k, v in available_checks.items() if not v['pass']],
        }

        if all_pass:
            stats['passed'] += 1
            passed.append(r)
        else:
            stats['failed'] += 1
            failed.append(r)

    return passed, failed, stats


EM_REPORT_API = 'https://reportapi.eastmoney.com/report/list'
EM_ANNOUNCE_API = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
TENcent_QT = 'https://qt.gtimg.cn/q={symbols}'

# 催化剂关键词（正向）
CATALYST_KEYWORDS_POSITIVE = [
    '中标', '合同', '订单', '采购', '签约', '大单',  # 重大订单
    '获批', '注册', '通过一致性评价', 'IND', 'NDA', '临床试验',  # 产品获批
    '收购', '并购', '重组', '战略合作', '增资', '入股',  # 收购/合作
    '扩产', '投产', '量产', '下线', '交付', '首台', '突破',  # 产能
    '业绩预增', '业绩预告', '扭亏', '大幅增长', '超预期',  # 业绩催化
    '分红', '回购', '增持', '员工持股',  # 股东利好
    '技术突破', '专利', '新产品', '独家',  # 技术
]

# 催化剂关键词（负向，匹配则扣分）
CATALYST_KEYWORDS_NEGATIVE = [
    '解禁', '上市流通', '限售股', '减持',  # 股份稀释/抛压
    '退市', '风险警示', 'ST', '立案调查',  # 风险
    '业绩预减', '业绩亏损', '大幅下降', '不及预期',  # 业绩下滑
]

# 行业偏好映射
INDUSTRY_PREFER = {
    100: [
        # AI/TMT
        'AI', 'TMT', '人工智能', '算力', '云计算', '网络安全', '软件', '半导体', '芯片', '集成电路',
        '电子', '通信', '计算机', '传媒', '游戏', '元宇宙', 'AIGC', '大模型',
        # 医药
        '医药', '医疗器械', '创新药', '生物医药', '中药', '化学制药', '原料药',
        # 高端制造
        '机器人', '人形机器人', '半导体设备', '新能源', '锂电池', '储能', '光伏', '风电',
        '新能源汽车', '车', '军工', '航空', '航天', '船舶', '高端制造',
        # 新消费
        '白酒', '啤酒', '食品', '饮料', '美容', '化妆品', '医美', '消费电子',
        # 材料
        '新材料', '碳纤维', '稀土', '氟化工', '磷化工',
    ],
    70: ['基础化工', '机械', '通用设备', '专用设备', '电机', '电气', '电力设备', '环保'],
    30: ['地产', '建筑', '纺织', '零售', '银行', '钢铁', '煤炭', '石油', '公路', '铁路', '港口'],
}


def get_industry_score(sector: str) -> int:
    """行业打分"""
    if not sector:
        return 30  # 无行业信息给低分
    for kw in INDUSTRY_PREFER[100]:
        if kw in sector:
            return 100
    for kw in INDUSTRY_PREFER[70]:
        if kw in sector:
            return 70
    for kw in INDUSTRY_PREFER[30]:
        if kw in sector:
            return 30
    return 50  # 默认中等


def fetch_financial_data(code: str) -> dict:
    """
    获取单只股票最新财务数据。
    仅从本地 financial_data 表缓存读取，不调外部API。
    """
    if code in FIN_DATA_CACHE:
        return FIN_DATA_CACHE[code]
    return {}


def fetch_market_cap(code: str) -> float:
    """获取总市值（亿元），优先用 stocks.total_mcap，缺失则回退到 总股本*现价"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur = conn.cursor()
        # 优先用 stocks 表已有的 total_mcap（元）
        cur.execute("SELECT total_mcap FROM stocks WHERE code = ?", (code,))
        row = cur.fetchone()
        conn.close()
        if row and row[0] and float(row[0]) > 0:
            return round(float(row[0]) / 100000000, 2)  # 元 -> 亿元
        # 兜底：总股本(万股) × 现价 / 10000
        cur = conn.cursor()
        cur.execute("SELECT total_shares_real FROM stocks WHERE code = ?", (code,))
        ts_row = cur.fetchone()
        if not ts_row or not ts_row[0]:
            conn.close()
            return 0
        total_shares_wan = float(ts_row[0])
        cur.execute("SELECT close FROM klines WHERE code = ? ORDER BY date DESC LIMIT 1", (code,))
        price_row = cur.fetchone()
        conn.close()
        if not price_row or not price_row[0]:
            return 0
        price = float(price_row[0])
        return round(total_shares_wan * price / 10000, 2)
    except Exception:
        return 0


def score_industry(sector: str) -> int:
    return get_industry_score(sector)


def score_performance(fin: dict) -> tuple:
    """
    业绩打分 (权重30%)
    数据来源：financial_data 表（周日全量更新，load_financial_data_cache 预加载）
    字段：ROE + 净利润增速 + 营收增速 + 毛利率 + 净利率
    返回 (score, detail)
    """
    profit_g = fin.get('profit_growth') or 0
    revenue_g = fin.get('revenue_growth') or 0
    roe = fin.get('roe') or 0
    gm = fin.get('gross_margin') or 0
    nm = fin.get('net_margin') or 0  # 净利率（新增）

    # 基础分（利润增速 × 营收增速）
    if profit_g >= 50 and revenue_g >= 20:
        base = 100
    elif profit_g >= 30 and revenue_g >= 15:
        base = 80
    elif profit_g >= 10 and revenue_g >= 10:
        base = 50
    elif profit_g > 0 or revenue_g > 0:
        base = 20
    else:
        base = 0  # 负增长或无数据

    # 加分项（更多维度的质量验证）
    bonus = 0
    if roe > 15:
        bonus += 10
    if roe > 20:
        bonus += 5  # 优秀ROE额外加分
    if gm > 30:
        bonus += 5
    if gm > 50:
        bonus += 5  # 优秀毛利率额外加分
    if nm > 15:  # 净利率 > 15% 加分
        bonus += 5

    score = min(100, base + bonus)
    detail = f"净利润{profit_g:+.1f}%|营收{revenue_g:+.1f}%|ROE{roe:.1f}%|毛{gm:.1f}%|净{nm:.1f}%"
    return score, detail


def score_market_cap(market_cap_yi: float) -> tuple:
    """
    市值打分 (权重15%)
    返回 (score, detail)
    """
    if market_cap_yi <= 0:
        return 0, "市值未知"
    if market_cap_yi < 30:
        base = 100
    elif market_cap_yi < 60:
        base = 80
    elif market_cap_yi < 100:
        base = 50
    else:
        base = 20
    detail = f"总市值{int(market_cap_yi)}亿元"
    return base, detail


def score_turnover(turnover_rate: float,调研数: int = 0) -> tuple:
    """
    资金认可打分 (权重20%)
    turnover_rate: 日均换手率 %
    """
    if turnover_rate >= 5:
        base = 100
    elif turnover_rate >= 3:
        base = 80
    elif turnover_rate >= 1:
        base = 50
    else:
        base = 0

    bonus = 0
    if 调研数 > 300:
        bonus = 10
    elif 调研数 > 100:
        bonus = 5

    score = min(100, base + bonus)
    detail = f"换手率{turnover_rate:.2f}%|调研{调研数}家"
    return score, detail


def score_catalyst() -> tuple:
    """
    催化剂打分 (权重15%) — 暂无数据，默认0分
    """
    return 0, "无数据"


def fetch_recent_announcements(code: str, days: int = 20) -> dict:
    """
    获取近N日公告，返回 {count, has_catalyst, catalyst_keywords}
    """
    try:
        # 构造 market_code: 6开头=1(沪), 0/3开头=0(深)
        market_code = '1' if code.startswith(('6', '5', '7')) else '0'
        ann_types = 'SHA,SZA' if market_code == '1' else 'SZA,SHA'
        url = f'{EM_ANNOUNCE_API}?sr=-1&page_size=20&page_index=1&ann_type={ann_types}&client_source=web&stock_list={code}'
        r = requests.get(url, timeout=8)
        data = r.json()
        items = data.get('data', {}).get('list', [])
        if not items:
            return {'count': 0, 'has_catalyst': False, 'titles': []}

        # 过滤近days天
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        recent = [it for it in items if it.get('notice_date', '')[:10] >= cutoff]

        # 检查关键词
        matched_pos = []
        matched_neg = []
        for it in recent:
            title = it.get('title_ch', it.get('title', ''))
            for kw in CATALYST_KEYWORDS_POSITIVE:
                if kw in title:
                    matched_pos.append(title)
                    break
            else:  # 没匹配到正向的才检查负向
                for kw in CATALYST_KEYWORDS_NEGATIVE:
                    if kw in title:
                        matched_neg.append(title)
                        break

        return {
            'count': len(recent),
            'has_catalyst': len(matched_pos) > 0,
            'catalyst_count': len(matched_pos),
            'negative_count': len(matched_neg),
            'titles': matched_pos + matched_neg,
        }
    except Exception:
        return {'count': 0, 'has_catalyst': False, 'catalyst_count': 0, 'titles': []}


def fetch_report_count(code: str, days: int = 365) -> int:
    """
    获取近N天研报数量（作为机构关注度代理指标）
    """
    try:
        from datetime import datetime, timedelta
        end = datetime.now().strftime('%Y-%m-%d')
        begin = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        url = f'{EM_REPORT_API}?pageNo=1&pageSize=1&code={code}&type=1&qType=0&beginTime={begin}&endTime={end}'
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            d = r.json()
            return d.get('hits', 0)
    except Exception:
        pass
    return 0


def _fetch_fund_flow_bonus(code: str) -> float:
    """AKShare 实时个股资金流向加成（-5 ~ +10）"""
    try:
        df = ak.stock_individual_fund_flow(code, market='sh' if code.startswith(('6', '5')) else 'sz')
        if df is None or df.empty:
            return 0
        row = df.iloc[0]
        net = float(row.get('主力净流入-净额', 0) or 0)
        amount = float(row.get('成交额', 1) or 1)
        ratio = net / max(amount, 1) * 100
        if ratio > 5:
            return 10
        elif ratio > 2:
            return 5
        elif ratio > 0:
            return 2
        elif ratio > -2:
            return 0
        else:
            return -5
    except Exception:
        return 0


def score_stock_full(code: str, name: str, sector: str, turnover_rate: float, report_count: int, catalyst_info: dict, mode: str = 'basic') -> dict:
    """综合打分（含催化剂数据）"""
    industry_sc = score_industry(sector)
    fin = fetch_financial_data(code)
    perf_sc, perf_dt = score_performance(fin)
    mc = fetch_market_cap(code)
    mc_sc, mc_dt = score_market_cap(mc)
    turn_sc, turn_dt = score_turnover(turnover_rate, report_count)
    cat_sc, cat_dt = score_catalyst_with_data(catalyst_info)

    # ——— deep mode: IMA 5:3:2 评分 ———
    if mode == 'deep' and _IMA_AVAILABLE:
        ima = score_stock_ima(code)
        if ima and ima.get('total_score', 0) > 0:
            ima_pct = ima['score_pct']
            # 行业加成 + 资金流向加成
            fund_bonus = _fetch_fund_flow_bonus(code)
            deep_score = ima_pct * 0.80 + industry_sc * 0.20 + fund_bonus
            deep_score = min(100, max(0, round(deep_score, 1)))
            return {
                'code': code, 'name': name, 'sector': sector,
                'total_score': deep_score,
                'industry_score': industry_sc,
                'perf_score': round(ima_pct, 1),
                'perf_detail': f"IMA5:3:2基{ima_pct}%|{ima.get('fundamental',{}).get('detail','')}",
                'mc_score': 0,
                'mc_detail': '',
                'turn_score': turn_sc,
                'turn_detail': turn_dt,
                'cat_score': cat_sc,
                'cat_detail': cat_dt,
                'catalyst_info': catalyst_info,
                'fund_bonus': fund_bonus,
                '_deep_grade': ima.get('grade', ''),
            }

    # basic 模式：原版加权
    total = (
        industry_sc * 0.20 +
        perf_sc * 0.30 +
        mc_sc * 0.15 +
        turn_sc * 0.20 +
        cat_sc * 0.15
    )

    return {
        'code': code,
        'name': name,
        'sector': sector,
        'total_score': round(total, 1),
        'industry_score': industry_sc,
        'perf_score': perf_sc,
        'perf_detail': perf_dt,
        'mc_score': mc_sc,
        'mc_detail': mc_dt,
        'turn_score': turn_sc,
        'turn_detail': turn_dt,
        'cat_score': cat_sc,
        'cat_detail': cat_dt,
        'catalyst_info': catalyst_info,
    }


def score_catalyst_with_data(catalyst_info: dict) -> tuple:
    """
    催化剂打分 (权重15%)
    catalyst_info: {count, has_catalyst, catalyst_count, negative_count, titles, report_count}
    """
    pos_count = catalyst_info.get('catalyst_count', 0)
    neg_count = catalyst_info.get('negative_count', 0)
    report_count = catalyst_info.get('report_count', 0)

    # 正向基础分
    if pos_count >= 3:
        base = 80
    elif pos_count == 2:
        base = 60
    elif pos_count == 1:
        base = 30
    else:
        base = 0

    # 负向扣分
    penalty = neg_count * 20

    # 研报加分（机构关注度代理）
    bonus = 0
    if report_count >= 20:
        bonus = 15
    elif report_count >= 10:
        bonus = 10
    elif report_count >= 5:
        bonus = 5

    score = max(0, min(100, base - penalty + bonus))
    pos_titles = [t for t in catalyst_info.get('titles', []) if any(kw in t for kw in CATALYST_KEYWORDS_POSITIVE)]
    neg_titles = [t for t in catalyst_info.get('titles', []) if any(kw in t for kw in CATALYST_KEYWORDS_NEGATIVE)]
    pos_str = '|'.join(pos_titles[:2])
    neg_str = f"⚠️{'|'.join(neg_titles[:1])}" if neg_titles else ''
    detail = f"正向{pos_count}条|负向{neg_count}条|研报{report_count}篇|{pos_str}{neg_str}"
    return score, detail


# ============================================================
# 周末市场展望（来自废弃的 weekly_screener.py）
# ============================================================

def _is_trading_day() -> bool:
    """检查今天是否为 A 股交易日"""
    try:
        df = ak.tool_trade_date_hist_sina()
        trading_dates = set(pd.to_datetime(df['trade_date']).dt.date)
        if date.today() not in trading_dates:
            print(f"  [市场展望] 今日 ({date.today()}) 非 A 股交易日")
            return False
    except Exception as e:
        print(f"  [市场展望] 交易日判断异常: {e}，继续执行")
    return True


def _scan_sector_momentum() -> list:
    """扫描行业板块动量（涨停/跌停家数）"""
    recommendations = []
    try:
        from fundamental import FundamentalFetcher
        fetcher = FundamentalFetcher()
        sentiment = fetcher.get_market_sentiment()
        limit_up = sentiment.get("limit_up", 0)
        limit_down = sentiment.get("limit_down", 0)
        if limit_up > limit_down * 2:
            recommendations.append({
                "direction": "做多情绪",
                "signal": "强",
                "logic": f"涨停{limit_up}家 vs 跌停{limit_down}家，市场赚钱效应强"
            })
        elif limit_down > limit_up * 2:
            recommendations.append({
                "direction": "防御为主",
                "signal": "弱",
                "logic": f"跌停{limit_down}家，亏钱效应明显，控制仓位"
            })
    except Exception as e:
        print(f"  [市场展望] 情绪扫描失败: {e}")
    return recommendations


def _scan_technical_patterns() -> list:
    """基于大盘指数技术面的方向判断"""
    recommendations = []
    try:
        from fundamental import FundamentalFetcher
        fetcher = FundamentalFetcher()
        indices = fetcher.get_all_indices()
        bullish_count = 0
        bearish_count = 0
        for code, info in indices.items():
            pct = info.get("change_pct", 0)
            if pct > 0.5:
                bullish_count += 1
            elif pct < -0.5:
                bearish_count += 1
        if bullish_count >= 3:
            recommendations.append({
                "direction": "多头排列",
                "signal": "强",
                "logic": "多个指数上涨，市场趋势向上，波段持仓可继续持有"
            })
        elif bearish_count >= 3:
            recommendations.append({
                "direction": "空头排列",
                "signal": "弱",
                "logic": "多个指数下跌，短线和波段仓建议减仓"
            })
        else:
            recommendations.append({
                "direction": "震荡整理",
                "signal": "中性",
                "logic": "指数涨跌互现，方向不明，中长线底仓不动，波段仓观望"
            })
    except Exception as e:
        print(f"  [市场展望] 技术扫描失败: {e}")
    return recommendations


def _scan_us_china_correlation() -> list:
    """中美关联分析（美股影响A股次日开盘）"""
    recommendations = []
    try:
        from stock_data import get_stock_quote
        ndx = get_stock_quote("US", "NDX")
        spy = get_stock_quote("US", "SPY")
        gxy = get_stock_quote("US", "GXY")
        us_bullish = []
        if ndx.get("change_pct", 0) > 1:
            us_bullish.append("纳斯达克100")
        if spy.get("change_pct", 0) > 0.5:
            us_bullish.append("标普500")
        if gxy.get("change_pct", 0) > 1:
            us_bullish.append("金龙中国")
        if us_bullish:
            recommendations.append({
                "direction": "外围利好",
                "signal": "正面",
                "logic": f"隔夜{'/'.join(us_bullish)}走强，A股次日高开预期，可关注科技/新能源板块"
            })
        else:
            ndx_pct = ndx.get("change_pct", 0)
            if ndx_pct < -1:
                recommendations.append({
                    "direction": "外围压力",
                    "signal": "负面",
                    "logic": f"纳斯达克下跌{ndx_pct:.1f}%，A股次日可能承压，防御板块优先"
                })
    except Exception as e:
        print(f"  [市场展望] 美股关联分析失败: {e}")
    return recommendations


def main():
    import argparse
    parser = argparse.ArgumentParser(description='A股翻倍潜力股打分')
    parser.add_argument('--min-score', type=int, default=60, help='最低入选分数')
    parser.add_argument('--top', type=int, default=20, help='最多输出数量')
    parser.add_argument('--codes', type=str, default='', help='指定股票代码，逗号分隔')
    parser.add_argument('--write-db', action='store_true',
                        help='将结果写入 double_up_scores 表（供 scan4 前置过滤用）')
    parser.add_argument('--write-fast', action='store_true',
                        help='配合--write-db使用，跳过催化剂数据获取（快速写入）')
    parser.add_argument('--market-outlook', action='store_true',
                        help='输出市场展望（板块动量/技术方向/中美关联，来自废弃的 weekly_screener）')
    parser.add_argument('--mode', type=str, default='basic', choices=['basic', 'deep'],
                        help='评分模式: basic(原版), deep(IMA 5:3:2)')
    parser.add_argument('--show-all', action='store_true',
                        help='显示全部(不按min-score过滤)，用于 --codes 模式')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    parser.add_argument('--industry-neutral', action='store_true',
                        help='行业中性化：按行业分组调整评分，消除行业偏差')
    parser.add_argument('--factor-process', action='store_true',
                        help='因子预处理：去极值+Z-score标准化，消除极端值影响')
    args = parser.parse_args()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] A股翻倍潜力股扫描启动...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 获取候选股票池
    if args.codes:
        codes_raw = args.codes.split(',')
        placeholders = ','.join(['?'] * len(codes_raw))
        cur.execute(f"""
            SELECT s.code, s.name, COALESCE(s.sector, '') as sector,
                   CASE WHEN i.turnover_rate > 100 THEN i.turnover_rate / 10000 ELSE i.turnover_rate END as turnover_rate,
                   COALESCE(i.change_pct, 0) as change_pct
            FROM stocks s
            LEFT JOIN indicators i ON s.code = i.code
            WHERE s.code IN ({placeholders})
        """, codes_raw)
    else:
        cur.execute("""
            SELECT s.code, s.name, COALESCE(s.sector, '') as sector,
                   CASE WHEN i.turnover_rate > 100 THEN i.turnover_rate / 10000 ELSE i.turnover_rate END as turnover_rate,
                   COALESCE(i.change_pct, 0) as change_pct
            FROM stocks s
            LEFT JOIN indicators i ON s.code = i.code
            WHERE s.name NOT LIKE '%ST%' AND s.name NOT LIKE '%*ST%'
              AND s.name NOT LIKE '%S%' AND s.name NOT LIKE '%退%'
              AND s.code NOT LIKE '688%' AND s.code NOT LIKE '787%'
              AND i.code IS NOT NULL
        """)

    candidates = cur.fetchall()
    print(f"  候选股票: {len(candidates)} 只")
    conn.close()

    if not candidates:
        print("  无候选股票")
        return

    # ===== 预加载财务数据（从本地SQLite，<0.1秒）=====
    print(f"  [财务数据] 加载本地缓存...")
    load_financial_data_cache()

    # ===== 第一阶段：快速打分（行业+换手率，无API）=====
    print(f"  [第一阶段] 快速打分...")
    results = []

    def quick_score(row):
        code, name, sector, turnover_rate, change_pct = row
        industry_sc = score_industry(sector)
        mc_sc, mc_dt = 50, "待获取"  # 暂不拉市值，节省时间
        turn_sc, turn_dt = score_turnover(turnover_rate or 0, 0)
        # 业绩分先给0，后面再算
        return {
            'code': code, 'name': name, 'sector': sector,
            'turnover_rate': turnover_rate,
            'industry_score': industry_sc,
            'turn_score': turn_sc,
            'turn_detail': turn_dt,
            'perf_score': 0, 'perf_detail': '',
            'mc_score': mc_sc, 'mc_detail': mc_dt,
            'cat_score': 0, 'cat_detail': '',
        }

    # quick_score 补充 deep 模式字段
    for r in results:
        r['fund_bonus'] = r.get('fund_bonus', 0)
        r['_deep_grade'] = r.get('_deep_grade', '')

    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(quick_score, c): c for c in candidates}
        for future in as_completed(futures):
            results.append(future.result())

    # ===== 基本面预筛选（仅 --mode deep 或 --factor-process 触发）=====
    if (args.mode == 'deep' or args.factor_process) and _FINANCIAL_SCREEN_AVAILABLE:
        print(f"  [基本面预筛选] 执行5项本地检查 (ROE/负债率/盈利质量/应收/治理)...")
        passed, failed, fstats = financial_pre_screen(results)
        excluded = [f for f in failed if f.get('financial_screen', {}).get('failed_checks')]
        print(f"    {fstats['with_data']}只有财务数据 | {fstats['no_data']}只无数据放行 | {fstats['failed']}只未通过")
        if excluded:
            for e in excluded[:10]:
                failed_checks = e.get('financial_screen', {}).get('failed_checks', [])
                print(f"    ❌ {e['name']}({e['code']}): {', '.join(failed_checks)}")
        results = passed
        print(f"   候选池更新: {len(results)} 只（过滤掉 {fstats['failed']} 只）")
    elif args.mode == 'deep' or args.factor_process:
        print(f"  [基本面预筛选] financial_screen 模块不可用，跳过")

    # ===== 第二阶段：候选股补充催化剂数据（仅筛选后）=====
    # 先并发拉所有股的财务+市值（已有），再筛选
    print(f"  [第二阶段] 并发拉取财务+市值数据...")
    done = 0

    def enrich(row_result):
        code = row_result['code']
        name = row_result['name']
        sector = row_result['sector']
        turnover_rate = row_result['turnover_rate']

        fin = fetch_financial_data(code)
        perf_sc, perf_dt = score_performance(fin)
        mc = fetch_market_cap(code)
        mc_sc, mc_dt = score_market_cap(mc)
        turn_sc = score_turnover(turnover_rate or 0, 0)[0]

        row_result['perf_score'] = perf_sc
        row_result['perf_detail'] = perf_dt
        row_result['market_cap_yi'] = mc
        row_result['mc_score'] = mc_sc
        row_result['mc_detail'] = mc_dt

        # 快速总分（不含催化剂）
        quick_total = (
            row_result['industry_score'] * 0.20 +
            perf_sc * 0.30 +
            mc_sc * 0.15 +
            turn_sc * 0.20
        )
        row_result['quick_total'] = round(quick_total, 1)
        return row_result

    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(enrich, r): r for r in results}
        for future in as_completed(futures):
            done += 1
            if done % 200 == 0:
                print(f"  进度: {done}/{len(candidates)}")

    # 过滤：只对有潜力的股票爬催化剂
    threshold = max(args.min_score - 10, 40)
    candidates_for_catalyst = [r for r in results if r['quick_total'] >= threshold]
    
    if args.write_fast:
        # 快速模式：跳过催化剂爬取，用基本分直接写入
        for r in results:
            r['catalyst_info'] = {'count': 0, 'has_catalyst': False, 'catalyst_count': 0, 'negative_count': 0, 'titles': [], 'report_count': 0}
            r['cat_score'] = 0
            r['cat_detail'] = '快速模式跳过'
            total = (r['industry_score'] * 0.25 + r['perf_score'] * 0.35 +
                     r['mc_score'] * 0.15 + r['turn_score'] * 0.25)
            r['total_score'] = round(total, 1)
        print(f"  [快速模式] 跳过催化剂爬取，用基本分写入")
        catalyst_map = {}
    else:
        print(f"  候选催化剂爬取: {len(candidates_for_catalyst)} 只（阈值{threshold}分）")
        # 并发爬公告+研报
        def fetch_catalyst(code):
            ann = fetch_recent_announcements(code, days=20)
            rep = fetch_report_count(code, days=365)
            ann['report_count'] = rep
            return code, ann

        catalyst_map = {}
        done = 0
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(fetch_catalyst, r['code']): r for r in candidates_for_catalyst}
            for future in as_completed(futures):
                code, ann = future.result()
                catalyst_map[code] = ann
                done += 1
                if done % 50 == 0:
                    print(f"  催化剂进度: {done}/{len(candidates_for_catalyst)}")

    # ===== 第三阶段：计算最终分数 =====
    # 先跑 basic 总分（快，不调API）
    for r in results:
        cat_info = catalyst_map.get(r['code'], {'count': 0, 'has_catalyst': False, 'catalyst_count': 0, 'negative_count': 0, 'titles': [], 'report_count': 0})
        r['catalyst_info'] = cat_info
        cat_sc, cat_dt = score_catalyst_with_data(cat_info)
        r['cat_score'] = cat_sc
        r['cat_detail'] = cat_dt
        total = (
            r['industry_score'] * 0.20 +
            r['perf_score'] * 0.30 +
            r['mc_score'] * 0.15 +
            r['turn_score'] * 0.20 +
            cat_sc * 0.15
        )
        r['total_score'] = round(total, 1)

    # 过滤 + 排序
    if args.show_all or (args.codes and args.mode == 'deep'):
        scored = list(results)
    else:
        scored = [r for r in results if r['total_score'] >= args.min_score]
    scored.sort(key=lambda x: x['total_score'], reverse=True)
    top = scored[:args.top]

    # deep 模式：对 top 候选股做 IMA 5:3:2 评分 + 资金流向
    deep_targets = top[:]
    if args.mode == 'deep' and _IMA_AVAILABLE and args.codes:
        deep_targets = [r for r in results if r['code'] in args.codes.split(',')]

    if args.mode == 'deep' and _IMA_AVAILABLE and deep_targets:
        print(f"  [deep mode] IMA 5:3:2 评分 + 实时资金流向 ({len(deep_targets)} 只)...")
        deep_count = 0
        for r in deep_targets:
            try:
                ima = score_stock_ima(r['code'])
                if ima and ima.get('total_score', 0) > 0:
                    fund_bonus = _fetch_fund_flow_bonus(r['code'])
                    deep_total = ima['score_pct'] * 0.80 + r['industry_score'] * 0.20 + fund_bonus
                    r['total_score'] = round(min(100, max(0, deep_total)), 1)
                    r['perf_score'] = round(ima['score_pct'], 1)
                    r['perf_detail'] = f"IMA5:3:2基{ima['score_pct']}%|{ima.get('fundamental',{}).get('detail','')}"
                    r['mc_score'] = 0
                    r['fund_bonus'] = fund_bonus
                    r['_deep_grade'] = ima.get('grade', '')
                    deep_count += 1
            except Exception as e:
                print(f"    deep跳过 {r['code']}: {e}")
                continue
        # 重新排序
        top.sort(key=lambda x: x['total_score'], reverse=True)
        scored = top[:]  # deep模式只用 top 池
        print(f"    {deep_count} 只完成 deep 评分")

    # ===== 行业中性化（可选）=====
    if args.industry_neutral:
        from collections import defaultdict
        sector_groups = defaultdict(list)
        for r in results:
            sec = r.get('sector', '') or '未知'
            sector_groups[sec].append(r)
        adjusted = 0
        for sector, group in sector_groups.items():
            scores = [r['total_score'] for r in group]
            if len(scores) < 3:
                continue
            mean = sum(scores) / len(scores)
            var = sum((s - mean) ** 2 for s in scores) / len(scores)
            std = var ** 0.5
            if std < 1:
                std = 1
            for r in group:
                r['total_score'] = round((r['total_score'] - mean) / std * 10 + 50, 1)
                adjusted += 1
        print(f"  [行业中性化] 已调整 {adjusted} 只股票评分（消除行业偏差）")

    # ===== 因子预处理（可选）=====
    if args.factor_process:
        from factor_utils import process_factor_batch
        # 对基本面因子做去极值+Z-score标准化
        factor_keys = [
            ('perf_score', False),  # 业绩总分
            ('mc_score', False),    # 市值分
            ('turn_score', False),  # 换手率分
        ]
        for key, reverse in factor_keys:
            values = [r.get(key, 0) or 0 for r in results]
            from factor_utils import factor_score
            scores = factor_score(values, reverse=reverse)
            for r, s in zip(results, scores):
                if s is not None:
                    r[key] = s
        # 重新计算总分
        for r in results:
            if r.get('cat_score', 0) > 0:
                r['total_score'] = round(
                    r['industry_score'] * 0.20 + r['perf_score'] * 0.30 +
                    r['mc_score'] * 0.15 + r['turn_score'] * 0.20 +
                    r['cat_score'] * 0.15, 1)
            else:
                r['total_score'] = round(
                    r['industry_score'] * 0.25 + r['perf_score'] * 0.35 +
                    r['mc_score'] * 0.15 + r['turn_score'] * 0.25, 1)
        print(f"  [因子预处理] 已完成去极值+Z-score标准化")

    # --write-db: 将所有通过初筛的股票写入 double_up_scores 表
    if args.write_db:
        scan_date = datetime.now().strftime('%Y-%m-%d')
        db_conn = sqlite3.connect(DB_PATH)
        db_cur = db_conn.cursor()
        db_cur.execute('''
            CREATE TABLE IF NOT EXISTS double_up_scores (
                scan_date TEXT,
                code TEXT,
                name TEXT,
                sector TEXT,
                total_score REAL,
                industry_score INTEGER,
                perf_score INTEGER,
                mc_score INTEGER,
                turn_score INTEGER,
                cat_score INTEGER,
                perf_detail TEXT,
                cat_detail TEXT,
                catalyst_json TEXT,
                PRIMARY KEY (scan_date, code)
            )
        ''')
        # 写入所有通过初筛的股票（行业+换手初筛，不是最终60分门槛）
        written = 0
        # 写入top池（用于scan4过滤）
        for s in scored:
            import json as json_mod
            cat_json = json_mod.dumps(s.get('catalyst_info', {}), ensure_ascii=False)
            db_cur.execute('''
                INSERT OR REPLACE INTO double_up_scores
                (scan_date, code, name, sector, total_score,
                 industry_score, perf_score, mc_score, turn_score, cat_score,
                 perf_detail, cat_detail, catalyst_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                scan_date, s['code'], s['name'], s.get('sector', ''),
                s['total_score'], s['industry_score'], s['perf_score'],
                s['mc_score'], s['turn_score'], s['cat_score'],
                s.get('perf_detail', ''), s.get('cat_detail', ''), cat_json
            ))
            written += 1
        db_conn.commit()
        db_conn.close()
        print(f"\n✅ 双五维打分已写入数据库: {written} 只 ({scan_date})")
        print(f"   表: double_up_scores | 筛选阈值: {args.min_score}分")

    # == JSON输出（在显示之前截断）==
    if args.json:
        result = {
            "run_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "mode": args.mode,
            "min_score": args.min_score,
            "total_candidates": len(candidates),
            "qualified": len(scored),
            "top": [{
                "code": s.get("code"),
                "name": s.get("name"),
                "sector": s.get("sector"),
                "total_score": s.get("total_score"),
                "industry_score": s.get("industry_score"),
                "perf_score": s.get("perf_score"),
                "cat_score": s.get("cat_score"),
                "turn_score": s.get("turn_score"),
                "mc_score": s.get("mc_score"),
                "perf_detail": s.get("perf_detail", ""),
                "cat_detail": s.get("cat_detail", ""),
                "turn_detail": s.get("turn_detail", ""),
                "mc_detail": s.get("mc_detail", ""),
            } for s in scored[:args.top]],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 生成报告
    print(f"\n{'='*60}")
    print(f"翻倍潜力股扫描报告 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"候选池: {len(candidates)}只 | 符合条件(≥{args.min_score}分): {len(scored)}只")
    print()

    # 显示逻辑：--codes deep 模式显示全部，否则按分数分池
    if args.show_all or (args.codes and args.mode == 'deep'):
        print(f"【全部deep评分】({len(scored[:args.top])}只)")
        print("-" * 60)
        for i, s in enumerate(scored[:args.top], 1):
            cat_info = s.get('catalyst_info', {})
            titles = cat_info.get('titles', []) if cat_info else []
            print(f"\n{i}. {s['name']}({s['code']})")
            if s.get('_deep_grade'):
                fb = s.get('fund_bonus', 0)
                print(f"   总分: {s['total_score']}分(deep) | IMA基{s['perf_score']} | 行业{s['industry_score']} | 资金流{fb:+.0f} | 催化{s['cat_score']}/15")
            else:
                print(f"   总分: {s['total_score']}分 | 行业{s['industry_score']}/20 | 业绩{s['perf_score']}/30 | 市值{s.get('market_cap_yi', 0):.0f}亿 | 资金{s['turn_score']}/20 | 催化{s['cat_score']}/15")
            print(f"   行业: {s['sector']}")
            print(f"   业绩: {s['perf_detail']}")
            print(f"   市值: {s['mc_detail']}")
            print(f"   资金: {s['turn_detail']}")
            print(f"   催化剂: {s['cat_detail']}")
            if titles:
                print(f"   重大公告: {titles[0][:50]}")
    else:
        core = [x for x in top if x['total_score'] >= 80]
        alt = [x for x in top if 60 <= x['total_score'] < 80]

        print(f"【核心观察池】≥80分 ({len(core)}只)")
        print("-" * 60)
        for i, s in enumerate(core, 1):
            cat_info = s.get('catalyst_info', {})
            titles = cat_info.get('titles', []) if cat_info else []
            print(f"\n{i}. {s['name']}({s['code']})")
            if s.get('_deep_grade'):
                fb = s.get('fund_bonus', 0)
                print(f"   总分: {s['total_score']}分(deep) | IMA基{s['perf_score']} | 行业{s['industry_score']} | 资金流{fb:+.0f} | 催化{s['cat_score']}/15")
            else:
                print(f"   总分: {s['total_score']}分 | 行业{s['industry_score']}/20 | 业绩{s['perf_score']}/30 | 市值{s.get('market_cap_yi', 0):.0f}亿 | 资金{s['turn_score']}/20 | 催化{s['cat_score']}/15")
            print(f"   行业: {s['sector']}")
            print(f"   业绩: {s['perf_detail']}")
            print(f"   市值: {s['mc_detail']}")
            print(f"   资金: {s['turn_detail']}")
            print(f"   催化剂: {s['cat_detail']}")
            if titles:
                print(f"   重大公告: {titles[0][:50]}")

        print(f"\n【备选池】60-79分 ({len(alt)}只)")
        print("-" * 60)
        for s in alt:
            print(f"  {s['name']}({s['code']}) {s['total_score']}分 | 业绩{s['perf_score']} | 市值{s.get('market_cap_yi', 0):.0f}亿 | 催化{s['cat_score']} | {s['sector']}")

    if args.json:
        result = {
            "run_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "mode": args.mode,
            "min_score": args.min_score,
            "total_candidates": len(candidates),
            "qualified": len(scored),
            "top": [{
                "code": s.get("code"),
                "name": s.get("name"),
                "sector": s.get("sector"),
                "total_score": s.get("total_score"),
                "industry_score": s.get("industry_score"),
                "perf_score": s.get("perf_score"),
                "cat_score": s.get("cat_score"),
                "turn_score": s.get("turn_score"),
                "mc_score": s.get("mc_score"),
                "perf_detail": s.get("perf_detail", ""),
                "cat_detail": s.get("cat_detail", ""),
                "turn_detail": s.get("turn_detail", ""),
                "mc_detail": s.get("mc_detail", ""),
            } for s in scored[:args.top]],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"\n{'='*60}")
    print(f"⚠️ 风险提示：高分不等于必涨，需结合大盘环境判断")
    print(f"   催化剂/研报数据来源：东方财富公告API + 研报API")
    print(f"   建议模拟盘验证2周后再考虑实盘")

    # === 周末市场展望（来自废弃的 weekly_screener.py）===
    # 周报任务在周日17:00运行，市场展望拉取的是最新交易日在线数据，
    # 不应被 is_trading_day() 哨兵拦截（否则周日周报永远没有市场展望）。
    if args.market_outlook:
        print(f"\n{'='*60}")
        print(f"【周末市场展望】{datetime.now().strftime('%Y-%m-%d')}")
        print(f"{'='*60}")
        sector_recs = _scan_sector_momentum()
        tech_recs = _scan_technical_patterns()
        us_recs = _scan_us_china_correlation()
        all_recs = sector_recs + tech_recs + us_recs
        if all_recs:
            for rec in all_recs:
                icon = "🟢" if rec["signal"] in ["强", "正面"] else ("🔴" if rec["signal"] in ["弱", "负面"] else "🟡")
                print(f"{icon} [{rec['direction']}] {rec['logic']}")
        else:
            print("本周数据不足以形成明确方向，等待下周数据确认")


if __name__ == '__main__':
    main()
