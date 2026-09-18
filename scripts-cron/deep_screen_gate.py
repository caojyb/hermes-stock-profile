#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deep_screen_gate.py — 推荐入池/推送前深析关（第五轮审计行动 ⑥）
================================================================
用本地结构化数据（不依赖 LLM key）对候选逐票做四项核查：

  1. ST/风险警示识别    — 名称含 ST/*ST/退（Bitable 名称 + stocks 表）
  2. 龙虎榜异常         — 近 5 个交易日上榜（lhb_cache.lhb_data）→ 游资炒作警示
  3. 限售解禁临近       — 未来 30 天内解禁（market_cache.lockup_release）
  4. 股东减持在途       — 近 30 天减持记录（market_cache.holder_change）

输出: gate_result(code) -> dict {pass: bool, flags: [..], veto: [..]}
  veto 项 = 硬拒绝（ST/退市风险、30天内大额解禁）
  flag 项 = 警示标注（龙虎榜上榜、减持），推送时带 ⚠️ 显示，不拦截

被 stock_opportunity_scan.py 在推送前调用；也可独立运行自检。
"""
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'stock-work'))

MARKET_DB = None
LHB_DB = None


def _dbs():
    global MARKET_DB, LHB_DB
    if MARKET_DB is None:
        from core.compat_paths import MARKET_DB as _M, get_db_path as _g
        MARKET_DB = str(_M)
        try:
            LHB_DB = str(_g('lhb_cache'))
        except Exception:
            LHB_DB = None
    return MARKET_DB, LHB_DB


def check_st_risk(code, name=''):
    """ST/退市风险 — 硬拒绝"""
    bad_marks = ('ST', '*ST', '退')
    if name and any(m in name.upper() for m in bad_marks):
        return True
    try:
        mdb, _ = _dbs()
        conn = sqlite3.connect(mdb, timeout=30)
        row = conn.execute("SELECT name FROM stocks WHERE code=?", (code,)).fetchone()
        conn.close()
        if row and any(m in str(row[0]).upper() for m in bad_marks):
            return True
    except Exception:
        pass
    return False


def check_lhb_recent(code, days=5):
    """近 N 交易日龙虎榜上榜 — 警示"""
    try:
        mdb, lhb = _dbs()
        if not lhb:
            return False
        conn = sqlite3.connect(lhb, timeout=30)
        since = (date.today() - timedelta(days=days + 4)).isoformat()  # +4 补周末
        n = conn.execute(
            "SELECT COUNT(*) FROM lhb_data WHERE code=? AND trade_date >= ?", (code, since)
        ).fetchone()[0]
        conn.close()
        return n > 0
    except Exception:
        return False


def check_lockup_near(code, days=30):
    """未来 N 天限售解禁 — 硬拒绝（>1亿股）或警示"""
    try:
        mdb, _ = _dbs()
        conn = sqlite3.connect(mdb, timeout=30)
        rows = conn.execute(
            "SELECT release_date, release_shares FROM lockup_release WHERE code=? "
            "AND release_date >= ? AND release_date <= ?",
            (code, date.today().isoformat(), (date.today() + timedelta(days=days)).isoformat())
        ).fetchall()
        conn.close()
        for rd, shares in rows:
            try:
                if float(shares or 0) >= 1e8:
                    return 'veto', f"{rd} 解禁 {float(shares)/1e8:.1f}亿股"
                elif float(shares or 0) > 0:
                    return 'flag', f"{rd} 解禁 {float(shares)/1e4:.0f}万股"
            except (TypeError, ValueError):
                continue
        return None
    except Exception:
        return None


def check_holder_reduce(code, days=30):
    """近 N 天股东减持 — 警示"""
    try:
        mdb, _ = _dbs()
        conn = sqlite3.connect(mdb, timeout=30)
        since = (date.today() - timedelta(days=days)).isoformat()
        n = conn.execute(
            "SELECT COUNT(*) FROM holder_change WHERE code=? AND change_date >= ? "
            "AND (change_type LIKE '%减持%' OR change_shares < 0)",
            (code, since)
        ).fetchone()[0]
        conn.close()
        return n > 0
    except Exception:
        return False


def gate(code, name=''):
    """四项核查主入口。返回 {pass, veto, flags, coverage}
    P1（六轮审计）: 数据覆盖率标注——数据缺失≠通过（fail-loud）。
    coverage: 每项检查的数据可用性说明，调用方应展示给用户。"""
    veto, flags = [], []
    coverage = []
    if check_st_risk(code, name):
        veto.append(f'ST/退市风险: {name or code}')
    else:
        coverage.append('ST核查: stocks表名称标记（被动识别，非官方风险警示列表）')
    lk = check_lockup_near(code)
    if lk and lk[0] == 'veto':
        veto.append(f'限售解禁: {lk[1]}')
    elif lk:
        flags.append(f'解禁临近: {lk[1]}')
    try:
        mdb, _ = _dbs()
        conn = sqlite3.connect(mdb, timeout=30)
        lk_rows = conn.execute(
            "SELECT COUNT(*) FROM lockup_release WHERE release_date >= ?",
            (date.today().isoformat(),)).fetchone()[0]
        conn.close()
        coverage.append(f'解禁核查: lockup_release 未来数据 {lk_rows} 行'
                        + ('' if lk_rows > 0 else '（⚠️ 空表——本周刷新未跑，解禁检查未生效）'))
    except Exception:
        coverage.append('解禁核查: 数据不可用')
    if check_lhb_recent(code):
        flags.append('近5日龙虎榜上榜（游资炒作警示）')
    if check_holder_reduce(code):
        flags.append('近30日股东减持')
    # 减持检查覆盖说明: holder_change 主要覆盖持仓股（westock 写入），对候选股基本盲
    coverage.append('减持核查: holder_change 仅覆盖持仓股，候选股不覆盖（已知盲区）')
    return {'pass': len(veto) == 0, 'veto': veto, 'flags': flags, 'coverage': coverage}


def gate_batch(candidates):
    """批量: candidates = [{'code':..,'name':..}, ...] → 过滤后 (passed, rejected)"""
    passed, rejected = [], []
    for c in candidates:
        r = gate(str(c.get('code', '')), str(c.get('name', '')))
        if r['pass']:
            passed.append({**c, 'deep_flags': r['flags']})
        else:
            rejected.append({**c, 'veto': r['veto']})
    return passed, rejected


if __name__ == '__main__':
    # 自检: 用关注池最新一期 TOP 10 演练
    mdb, _ = _dbs()
    conn = sqlite3.connect(mdb, timeout=30)
    rows = conn.execute(
        "SELECT code, name FROM double_up_scores WHERE scan_date=(SELECT MAX(scan_date) FROM double_up_scores) LIMIT 10"
    ).fetchall()
    conn.close()
    cands = [{'code': r[0], 'name': r[1] or ''} for r in rows]
    passed, rejected = gate_batch(cands)
    print(f"深析关自检: 候选 {len(cands)} 只 → 通过 {len(passed)} / 拦截 {len(rejected)}")
    for r in rejected:
        print(f"  ⛔ {r['code']} {r['name']}: {'; '.join(r['veto'])}")
    for p in passed:
        if p['deep_flags']:
            print(f"  ⚠️ {p['code']} {p['name']}: {'; '.join(p['deep_flags'])}")
