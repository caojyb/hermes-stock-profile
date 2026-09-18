#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_lockup.py — 限售解禁周刷（六轮 P1: 深析关解禁 veto 空转修复）
====================================================================
数据源: 东财 datacenter RPT_LIFT_STAGE（未来 60 天全市场解禁）
写入: market_cache.lockup_release（深析关 deep_screen_gate 的 veto 数据源）

深析关读 release_shares（股），接口给 CURRENT_FREE_SHARES（万股）→ ×1e4。
每周日 18:30 跑；跑完写心跳。
"""
import sqlite3
import sys
import time
import requests
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'stock-work'))

MARKET_DB = None


def _db():
    global MARKET_DB
    if MARKET_DB is None:
        from core.compat_paths import MARKET_DB as _M
        MARKET_DB = str(_M)
    return MARKET_DB


def fetch_lockup(days=60):
    """拉未来 N 天解禁，返回 [(code, date, shares_股, type)]"""
    rows = []
    page = 1
    today = date.today()
    until = (today + timedelta(days=days)).isoformat()
    while page <= 40:  # 上限保护
        r = requests.get(
            'https://datacenter-web.eastmoney.com/api/data/v1/get',
            params={'reportName': 'RPT_LIFT_STAGE',
                    'columns': 'SECURITY_CODE,SECURITY_NAME_ABBR,FREE_DATE,CURRENT_FREE_SHARES,LIFT_MARKET_CAP,FREE_SHARES_TYPE',
                    'pageSize': 500, 'pageNumber': page,
                    'sortColumns': 'FREE_DATE', 'sortTypes': 1,
                    'filter': f"(FREE_DATE>='{today}')(FREE_DATE<='{until}')",
                    'source': 'WEB', 'client': 'WEB'},
            timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        d = r.json()
        if not d.get('success') or not d.get('result'):
            break
        data = d['result'].get('data') or []
        if not data:
            break
        for it in data:
            code = str(it.get('SECURITY_CODE') or '')
            fd = (it.get('FREE_DATE') or '')[:10]
            shares_wan = it.get('CURRENT_FREE_SHARES')  # 万股
            if not code or not fd:
                continue
            try:
                shares = float(shares_wan or 0) * 1e4  # 万股 → 股
            except (TypeError, ValueError):
                shares = 0.0
            rows.append((code, fd, shares, str(it.get('FREE_SHARES_TYPE') or '')))
        total_pages = d['result'].get('pages', 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.5)
    return rows


def main():
    t0 = time.time()
    rows = fetch_lockup(60)
    if not rows:
        print("[EXC] refresh_lockup.py: 解禁接口 0 行——数据源可能变更，保持旧数据不覆盖")
        sys.exit(1)
    conn = sqlite3.connect(_db(), timeout=60)
    cur = conn.cursor()
    # 全量替换: 先清未来日期的旧数据（历史解禁记录保留），再插入
    cur.execute("DELETE FROM lockup_release WHERE release_date >= ?", (date.today().isoformat(),))
    cur.executemany(
        "INSERT OR REPLACE INTO lockup_release (code, release_date, release_shares, release_type) VALUES (?,?,?,?)",
        rows)
    conn.commit()
    n_codes = conn.execute("SELECT COUNT(DISTINCT code) FROM lockup_release WHERE release_date >= ?",
                           (date.today().isoformat(),)).fetchone()[0]
    near30 = conn.execute(
        "SELECT COUNT(*) FROM lockup_release WHERE release_date BETWEEN ? AND ? AND release_shares >= 1e8",
        (date.today().isoformat(), (date.today() + timedelta(days=30)).isoformat())).fetchone()[0]
    conn.close()
    try:
        from heartbeat import write
        write('lockup-refresh-weekly', {'ts': time.strftime('%F %T'), 'rows': len(rows)},
              expected_interval_seconds=7 * 86400)
    except Exception as e:
        print(f"[EXC] refresh_lockup.py 心跳: {type(e).__name__}: {e}")
    print(f"✅ 解禁表刷新: {len(rows)} 条（未来60天, 覆盖 {n_codes} 只）; 30天内≥1亿股 {near30} 条; 耗时 {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
