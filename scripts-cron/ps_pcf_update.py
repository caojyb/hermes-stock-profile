#!/usr/bin/env python3
"""
PS/PCF 估值数据更新模块
======================
数据源: push2delay.eastmoney.com
- PCF (市现率): 批量接口 f169 字段
- PS (市销率): 接口 f168 字段实测不可用，本版本先只保留 PCF
集成到每周 PE/PB 刷新任务中
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
import os, sys, sqlite3, json, requests
from datetime import date, datetime
from pathlib import Path

MKT_DB = _STOCK_MARKET_DB
HEADERS = {'User-Agent': 'Mozilla/5.0'}

def get_pcf_batch():
    """批量获取全市场 PCF（市现率）"""
    url = 'https://push2delay.eastmoney.com/api/qt/clist/get'
    pcf_data = {}
    for page in range(1, 60):
        params = {
            'pn': page, 'pz': 100, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f12',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f12,f169'
        }
        try:
            r = requests.get(url, params=params, timeout=10, headers=HEADERS)
            items = r.json().get('data', {}).get('diff', [])
            if not items:
                break
            for item in items:
                code = item.get('f12', '')
                pcf = item.get('f169')
                if code and pcf not in (None, '-', 0):
                    pcf_data[code] = pcf
        except Exception as e:
            print(f'  第{page}页获取失败: {e}')
            continue
    return pcf_data

def update_pcf_only(pcf_data):
    conn = sqlite3.connect(MKT_DB, timeout=60)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(indicators)")
    cols = [c[1] for c in cur.fetchall()]
    if 'pcf_ttm' not in cols:
        cur.execute('ALTER TABLE indicators ADD COLUMN pcf_ttm REAL')
    updated = 0
    for code, pcf in pcf_data.items():
        cur.execute('UPDATE indicators SET pcf_ttm=? WHERE code=?', (pcf, code))
        if cur.rowcount > 0:
            updated += 1
    conn.commit()
    conn.close()
    return updated

def run():
    print(f'📊 PCF 估值数据更新 | {date.today().isoformat()}')
    print('='*55)
    print('📥 获取 PCF（市现率）...')
    pcf_data = get_pcf_batch()
    print(f'   获取 {len(pcf_data)} 只 PCF 数据')
    print('💾 更新数据库...')
    n_pcf = update_pcf_only(pcf_data)
    print(f'   更新 PCF: {n_pcf} 只')
    conn = sqlite3.connect(MKT_DB, timeout=60)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM indicators WHERE pcf_ttm IS NOT NULL AND pcf_ttm != 0')
    pcf_count = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM indicators WHERE pcf_ttm > 0')
    pcf_pos = cur.fetchone()[0]
    conn.close()
    print()
    print('📊 更新后统计:')
    print(f'   PCF 有数据: {pcf_count} 只（其中 >0: {pcf_pos} 只）')
    print('='*55)
    print('✅ PCF 更新完成')
    print('='*55)

if __name__ == '__main__':
    run()
