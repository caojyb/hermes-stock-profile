#!/usr/bin/env python3
"""
fetch_pe_pb.py — 获取PE/PB历史分位数据
数据来源：东方财富数据中心 PE/PB分位接口

用法:
  python3 fetch_pe_pb.py single 000001    # 单只股票
  python3 fetch_pe_pb.py batch            # 全量批量更新
  python3 fetch_pe_pb.py scan             # 扫描PE/PB分位
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

import sys
import os
sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')

import sqlite3
import json
import time
import requests
import akshare as ak
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List
import re

DB_PATH = _STOCK_MARKET_DB
PROXIES = {"http": "socks5://127.0.0.1:10808", "https": "socks5://127.0.0.1:10808"}


def get_pe_pb_from_eastmoney(code: str) -> Optional[Dict]:
    """从东方财富获取PE/PB分位数据"""
    try:
        # 东方财富PE/PB分位接口（历史估值百分位）
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            'reportName': 'RPT_DMSK_TS_HSASC',
            'columns': 'SECURITY_CODE,TRADE_DATE,PE_TTM,PB_MRQ',
            'filter': f'(SECURITY_CODE="{code}")',
            'pageNumber': 1,
            'pageSize': 500,
            'sortColumns': 'TRADE_DATE',
            'sortTypes': -1,
            'source': 'HSF10',
            'client': 'HSF10'
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://data.eastmoney.com/'
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        
        if not data.get('result') or not data['result'].get('data'):
            return None
        
        records = data['result']['data']
        if not records:
            return None
        
        # 计算历史分位
        pe_list = [float(r['PE_TTM']) for r in records if r.get('PE_TTM') and r['PE_TTM'] > 0]
        pb_list = [float(r['PB_MRQ']) for r in records if r.get('PB_MRQ') and r['PB_MRQ'] > 0]
        
        if not pe_list or not pb_list:
            return None
        
        latest_pe = pe_list[0] if pe_list else None
        latest_pb = pb_list[0] if pb_list else None
        
        # 计算分位：当前值在历史中的位置
        pe_percentile = _calc_percentile(latest_pe, pe_list) if latest_pe else None
        pb_percentile = _calc_percentile(latest_pb, pb_list) if latest_pb else None
        
        return {
            'pe_ttm': latest_pe,
            'pb_mrq': latest_pb,
            'pe_percentile': pe_percentile,   # 0-100，越低越低估
            'pb_percentile': pb_percentile,
            'history_count': len(pe_list),
            'trade_date': records[0].get('TRADE_DATE', '')
        }
    except Exception as e:
        return None


def _calc_percentile(value: float, history: list) -> float:
    """计算value在history中的百分位"""
    if not history or value <= 0:
        return 50.0
    sorted_hist = sorted(history)
    # 找到value在有序数组中的位置
    rank = sum(1 for v in sorted_hist if v < value)
    percentile = rank / len(sorted_hist) * 100
    return min(100, max(0, percentile))


def fetch_akshare_pe_pb(code: str) -> Optional[Dict]:
    """用AKShare获取PE/PB（从stock_individual_info_em获取）"""
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == code]
        if not row.empty:
            pe = row.iloc[0].get('市盈率-动态')
            pb = row.iloc[0].get('市净率')
            return {
                'pe_ttm': float(pe) if pe and str(pe) not in ('N/A', '--', '') else None,
                'pb_mrq': float(pb) if pb and str(pb) not in ('N/A', '--', '') else None,
            }
    except:
        pass
    return None


def fetch_tencent_pe_pb(code: str) -> Optional[Dict]:
    """从腾讯财经获取实时PE/PB"""
    try:
        market = 'sh' if code.startswith(('6', '601', '603', '605', '688')) else 'sz'
        full = f"{market}{code}"
        url = f"https://qt.gtimg.cn/q={full}"
        r = requests.get(url, timeout=5)
        text = r.text
        
        # 腾讯格式：...~值...
        match = re.search(r'="([^"]+)"', text)
        if match:
            parts = match.group(1).split('~')
            if len(parts) > 50:
                pe = parts[39]  # PE
                pb = parts[46]  # PB
                return {
                    'pe_ttm': float(pe) if pe and pe not in ('', '-', 'N/A') else None,
                    'pb_mrq': float(pb) if pb and pb not in ('', '-', 'N/A') else None,
                }
    except:
        pass
    return None


def update_pe_pb_batch(codes: List[str], batch_size: int = 50):
    """批量更新PE/PB数据到数据库（并发获取，提高效率）"""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cur = conn.cursor()
    
    # 创建PE/PB表（如果不存在）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pe_pb_data (
            code TEXT,
            fetch_date TEXT,
            pe_ttm REAL,
            pb_mrq REAL,
            pe_percentile REAL,
            pb_percentile REAL,
            source TEXT,
            PRIMARY KEY (code, fetch_date)
        )
    """)
    conn.commit()
    
    updated = 0
    errors = 0
    now_str = datetime.now().strftime('%Y-%m-%d')
    
    def fetch_one(code: str) -> tuple:
        """获取单只股票PE/PB"""
        try:
            result = fetch_tencent_pe_pb(code)
            if result and result.get('pe_ttm'):
                return (code, now_str, result['pe_ttm'], result.get('pb_mrq'), 'tencent')
        except:
            pass
        return None
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(fetch_one, code): code for code in codes}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            result = future.result()
            if result:
                cur.execute("""
                    INSERT OR REPLACE INTO pe_pb_data
                    (code, fetch_date, pe_ttm, pb_mrq, source)
                    VALUES (?, ?, ?, ?, ?)
                """, result)
                updated += 1
            else:
                errors += 1
            
            if done_count % 500 == 0:
                conn.commit()
                print(f"  更新进度: {done_count}/{len(codes)} (成功{updated}, 失败{errors})")
    
    conn.commit()
    conn.close()
    print(f"PE/PB更新完成: 成功{updated}只, 失败{errors}只")


def get_pe_pb_for_code(conn, code: str) -> Optional[Dict]:
    """从数据库获取PE/PB数据"""
    cur = conn.cursor()
    cur.execute("""
        SELECT pe_ttm, pb_mrq, pe_percentile, pb_percentile, fetch_date
        FROM pe_pb_data
        WHERE code = ?
        ORDER BY fetch_date DESC
        LIMIT 1
    """, (code,))
    row = cur.fetchone()
    if row:
        return {
            'pe_ttm': row[0], 'pb_mrq': row[1],
            'pe_percentile': row[2], 'pb_percentile': row[3],
            'fetch_date': row[4]
        }
    return None


def scan_market_pe_pb() -> Dict:
    """扫描全市场PE/PB分布"""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cur = conn.cursor()
    
    cur.execute("""
        SELECT i.code, s.name, i.current_price, i.rsi_14, i.boll_position,
               i.signal_score, p.pe_ttm, p.pb_mrq
        FROM indicators i
        JOIN stocks s ON i.code = s.code
        LEFT JOIN pe_pb_data p ON p.code = i.code
        WHERE i.date = (SELECT MAX(date) FROM indicators)
          AND i.current_price IS NOT NULL
          AND i.current_price > 0
    """)
    
    results = []
    for row in cur.fetchall():
        code, name, price, rsi, boll, score, pe, pb = row
        results.append({
            'code': code, 'name': name, 'price': price,
            'rsi': rsi, 'boll': boll, 'score': score,
            'pe': pe, 'pb': pb
        })
    
    conn.close()
    
    # 按PE统计分布
    pe_valid = [r['pe'] for r in results if r['pe'] and r['pe'] > 0]
    pb_valid = [r['pb'] for r in results if r['pb'] and r['pb'] > 0]
    
    stats = {
        'total': len(results),
        'with_pe': len(pe_valid),
        'with_pb': len(pb_valid),
        'pe_median': sum(pe_valid) / len(pe_valid) if pe_valid else None,
        'pb_median': sum(pb_valid) / len(pb_valid) if pb_valid else None,
    }
    
    # 低估值候选（PE<20 且 PE>0）
    low_pe = [r for r in results if r['pe'] and 0 < r['pe'] < 20]
    print(f"低估值(PE<20): {len(low_pe)}只")
    for r in sorted(low_pe, key=lambda x: x['pe'])[:5]:
        pb_str = f"{r['pb']:.1f}" if r['pb'] else 'N/A'
        print(f"  {r['name']}({r['code']}): PE={r['pe']:.1f} PB={pb_str}")
    
    return {'stats': stats, 'candidates': results}


if __name__ == '__main__':
    import re
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    batch_size = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 50
    
    if cmd == 'single':
        code = sys.argv[2] if len(sys.argv) > 2 else '000001'
        result = fetch_tencent_pe_pb(code)
        print(f"PE/PB: {result}")
    
    elif cmd in ('batch', '100') or cmd.isdigit():
        # 获取所有股票代码
        conn = sqlite3.connect(DB_PATH, timeout=60)
        cur = conn.cursor()
        cur.execute("SELECT code FROM stocks")
        codes = [r[0] for r in cur.fetchall()]
        conn.close()
        
        bs = int(cmd) if cmd.isdigit() else batch_size
        print(f"开始批量更新 {len(codes)} 只股票的PE/PB (batch_size={bs})...")
        update_pe_pb_batch(codes, batch_size=bs)
    
    elif cmd == 'scan':
        result = scan_market_pe_pb()
        print(f"\n市场PE/PB统计: {result['stats']}")
