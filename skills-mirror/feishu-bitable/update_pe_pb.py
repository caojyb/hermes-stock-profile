#!/usr/bin/env python3
"""
update_pe_pb.py — 批量更新PE/PB数据（Phase 2核心）
用法: python3 update_pe_pb.py [batch_size]
"""
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

import sys
import os
sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')

import sqlite3
import time
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

DB_PATH = _STOCK_MARKET_DB
# 2026-06-07 修复: SOCKS5代理对HTTPS握手有兼容问题（requests库读取超时）
# qt.gtimg.cn 直连可用，速率达42只/秒，无需代理
PROXIES = None


def init_pe_pb_table():
    """初始化PE/PB表（增加分位列）"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pe_pb_data (
            code TEXT,
            fetch_date TEXT,
            pe_ttm REAL,
            pb_mrq REAL,
            pe_percentile REAL,
            pb_percentile REAL,
            pe_hist_avg REAL,
            pb_hist_avg REAL,
            source TEXT,
            PRIMARY KEY (code, fetch_date)
        )
    """)
    conn.commit()
    conn.close()


def fetch_pe_pb_tencent(code: str) -> dict:
    """从腾讯财经获取实时PE/PB"""
    try:
        market = 'sh' if code.startswith(('6', '601', '603', '605', '688')) else 'sz'
        full = f"{market}{code}"
        url = f"https://qt.gtimg.cn/q={full}"
        r = requests.get(url, timeout=5, proxies=PROXIES)
        text = r.text
        
        # 腾讯格式: ...="..." 其中包含~分隔的字段
        import re
        match = re.search(r'="([^"]+)"', text)
        if not match:
            return {}
        parts = match.group(1).split('~')
        if len(parts) < 50:
            return {}
        
        pe = parts[39].strip()  # PE
        pb = parts[46].strip()  # PB
        
        result = {}
        if pe and pe not in ('', '-', 'N/A', '0'):
            try:
                result['pe_ttm'] = float(pe)
            except:
                pass
        if pb and pb not in ('', '-', 'N/A', '0'):
            try:
                result['pb_mrq'] = float(pb)
            except:
                pass
        return result
    except:
        return {}


def fetch_pe_pb_eastmoney(code: str) -> dict:
    """从东方财富获取PE/PB（备用）"""
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            'reportName': 'RPT_DMSK_TS_HSASC',
            'columns': 'SECURITY_CODE,PE_TTM,PB_MRQ',
            'filter': f'(SECURITY_CODE="{code}")',
            'pageNumber': 1,
            'pageSize': 1,
            'source': 'HSF10',
            'client': 'HSF10'
        }
        r = requests.get(url, params=params, timeout=8, proxies=PROXIES)
        data = r.json()
        if data.get('result') and data['result'].get('data'):
            row = data['result']['data'][0]
            return {
                'pe_ttm': float(row['PE_TTM']) if row.get('PE_TTM') and row['PE_TTM'] > 0 else None,
                'pb_mrq': float(row['PB_MRQ']) if row.get('PB_MRQ') and row['PB_MRQ'] > 0 else None,
            }
    except:
        pass
    return {}


def update_all_pe_pb(batch_size: int = 100):
    """批量更新所有股票PE/PB"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 获取所有股票代码
    cur.execute("SELECT code FROM stocks")
    codes = [r[0] for r in cur.fetchall()]
    
    init_pe_pb_table()
    now_str = datetime.now().strftime('%Y-%m-%d')
    
    updated = 0
    errors = 0
    
    print(f"开始更新 {len(codes)} 只股票的PE/PB...")
    start = time.time()
    
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        
        # 并发获取（每批最多20个线程）
        def fetch_one(code):
            result = fetch_pe_pb_tencent(code)
            if not result:
                result = fetch_pe_pb_eastmoney(code)
            return code, result
        
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = [ex.submit(fetch_one, c) for c in batch]
            for future in as_completed(futures):
                code, result = future.result()
                if result and (result.get('pe_ttm') or result.get('pb_mrq')):
                    # 计算历史分位：从 pe_pb_data 表中读取该股票的历史 PE/PB 值
                    pe_pct = None
                    pb_pct = None
                    if result.get('pe_ttm'):
                        cur.execute(
                            "SELECT pe_ttm FROM pe_pb_data WHERE code=? AND pe_ttm IS NOT NULL AND pe_ttm > 0 "
                            "ORDER BY fetch_date DESC", (code,))
                        hist_pe = [r[0] for r in cur.fetchall() if r[0]]
                        if hist_pe:
                            sorted_pe = sorted(hist_pe)
                            rank = sum(1 for v in sorted_pe if v < result['pe_ttm'])
                            pe_pct = min(100, max(0, rank / len(sorted_pe) * 100))
                    if result.get('pb_mrq'):
                        cur.execute(
                            "SELECT pb_mrq FROM pe_pb_data WHERE code=? AND pb_mrq IS NOT NULL AND pb_mrq > 0 "
                            "ORDER BY fetch_date DESC", (code,))
                        hist_pb = [r[0] for r in cur.fetchall() if r[0]]
                        if hist_pb:
                            sorted_pb = sorted(hist_pb)
                            rank = sum(1 for v in sorted_pb if v < result['pb_mrq'])
                            pb_pct = min(100, max(0, rank / len(sorted_pb) * 100))
                    cur.execute("""
                        INSERT OR REPLACE INTO pe_pb_data
                        (code, fetch_date, pe_ttm, pb_mrq, pe_percentile, pb_percentile, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (code, now_str, result.get('pe_ttm'), result.get('pb_mrq'),
                          pe_pct, pb_pct, 'tencent/em'))
                    updated += 1
                else:
                    errors += 1
        
        conn.commit()
        elapsed = time.time() - start
        speed = (i + batch_size) / elapsed if elapsed > 0 else 0
        remaining = (len(codes) - i - batch_size) / speed if speed > 0 else 0
        print(f"  进度: {min(i+batch_size, len(codes))}/{len(codes)} "
              f"({speed:.0f}只/秒, 剩余约{remaining:.0f}秒)")
    
    conn.close()
    print(f"完成: 成功{updated}只, 失败{errors}只, 耗时{time.time()-start:.1f}秒")
    return {'updated': updated, 'errors': errors}


def scan_pe_distribution():
    """扫描市场PE分布"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM pe_pb_data
    """)
    total = cur.fetchone()[0]
    print(f"PE/PB数据记录数: {total}")
    
    # 统计有PE数据的股票
    cur.execute("""
        SELECT COUNT(*) FROM pe_pb_data WHERE pe_ttm IS NOT NULL AND pe_ttm > 0
    """)
    with_pe = cur.fetchone()[0]
    print(f"有PE数据的股票: {with_pe}")
    
    # PE分布统计
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            AVG(pe_ttm) as avg_pe,
            MIN(pe_ttm) as min_pe,
            MAX(pe_ttm) as max_pe,
            SUM(CASE WHEN pe_ttm < 20 THEN 1 ELSE 0 END) as low_pe,
            SUM(CASE WHEN pe_ttm > 50 THEN 1 ELSE 0 END) as high_pe
        FROM pe_pb_data
        WHERE pe_ttm IS NOT NULL AND pe_ttm > 0
    """)
    row = cur.fetchone()
    print(f"PE统计: 总数={row[0]}, 均值={row[1]:.1f}, 最小={row[2]:.1f}, 最大={row[3]:.1f}")
    print(f"  低估值(PE<20): {row[4]}只, 高估值(PE>50): {row[5]}只")
    
    conn.close()


if __name__ == '__main__':
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    
    import re
    from typing import Optional, List, Dict, Any
    
    init_pe_pb_table()
    
    # 更新PE/PB数据
    result = update_all_pe_pb(batch_size)
    
    # 扫描分布
    scan_pe_distribution()