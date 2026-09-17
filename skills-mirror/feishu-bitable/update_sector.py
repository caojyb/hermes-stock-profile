#!/usr/bin/env python3
"""补充 stocks 表的 sector 字段（行业分类）"""
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB
import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])

import os
import sqlite3
import time
import sys
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# V2RayN 代理
os.environ['http_proxy'] = 'socks5://127.0.0.1:10808'
os.environ['https_proxy'] = 'socks5://127.0.0.1:10808'

DB_PATH = _STOCK_MARKET_DB
EM_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'


def fetch_sector(code: str) -> tuple:
    """获取单只股票的行业信息（东方财富 DataCenter API）"""
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
        r = requests.get(EM_URL, params=params, timeout=10)
        data = r.json()
        if data.get('result') and data['result'].get('data'):
            item = data['result']['data'][0]
            board = item.get('BOARD_NAME_LEVEL', '')
            if board and '-' in board:
                industry = board.split('-')[-1].strip()
            else:
                industry = board or ''
            return code, industry
        return code, None
    except Exception:
        return code, None


def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始补充行业信息（EastMoney DataCenter API）...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 获取所有 sector 为 NULL 的股票
    cur.execute("SELECT code FROM stocks WHERE sector IS NULL OR sector = ''")
    codes = [r[0] for r in cur.fetchall()]
    print(f"  待补充: {len(codes)} 只")

    if not codes:
        print("  无需补充")
        conn.close()
        return

    # 并发查询（30线程，每只约0.5秒）
    results = {}
    done = 0
    total = len(codes)

    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(fetch_sector, c): c for c in codes}
        for future in as_completed(futures):
            code, industry = future.result()
            if industry:
                results[code] = industry
            done += 1
            if done % 500 == 0 or done == total:
                elapsed = done / 30 * 0.5  # 粗估
                print(f"  进度: {done}/{total} (约{elapsed:.0f}s)")

    # 批量写入
    updated = 0
    for code, industry in results.items():
        cur.execute("UPDATE stocks SET sector = ? WHERE code = ?", (industry, code))
        updated += 1

    conn.commit()

    # 验证
    cur.execute("SELECT COUNT(*) FROM stocks WHERE sector IS NOT NULL AND sector != ''")
    filled = cur.fetchone()[0]
    print(f"✅ 行业补充完成: {updated}只写入成功, 总计 {filled}/{total} 只有行业信息")

    conn.close()


if __name__ == '__main__':
    main()
