#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线入库校验层（2026-09-18 二轮审计 P1-5）
========================================
此前 K 线入库零校验：价格 <=0、成交量为负、日期倒挂的坏数据会静默入库，
直接污染技术指标计算和选股信号。

用法（market_cache.py 等入库前调用）：
    from data_validation import validate_kline
    ok, reason = validate_kline(code, date, open_, close, high, low, volume)
    if ok:
        conn.execute("INSERT ...")

校验规则（ERROR 级 → 拒绝入库；WARNING 级 → 放行但打印标记）：
- ERROR: close/open/high/low 为 None/负/0（A股价格恒>0）；high < max(open,close)；
  low > min(open,close)；volume < 0；日期格式非法或晚于今天
- WARNING: 成交量为 0（停牌可能）；涨跌幅 |change_pct| > 22（超涨跌停边界，可能除权）
"""
from __future__ import annotations

from datetime import date as _date


def validate_kline(code: str, kdate: str, open_: float, close: float,
                   high: float, low: float, volume: float,
                   change_pct: float | None = None) -> tuple[bool, str]:
    """校验单条 K 线。返回 (ok, reason)。ok=False 时调用方必须跳过入库。"""
    try:
        d = _date.fromisoformat(str(kdate)[:10])
    except (ValueError, TypeError):
        return False, f'非法日期格式: {kdate!r}'
    if d > _date.today():
        return False, f'未来日期: {kdate}'

    vals = {'open': open_, 'close': close, 'high': high, 'low': low}
    for name, v in vals.items():
        if v is None:
            return False, f'{name} 为 None'
        try:
            fv = float(v)
        except (ValueError, TypeError):
            return False, f'{name} 非数值: {v!r}'
        if fv <= 0:
            return False, f'{name}={fv} 非正数（A股价格恒>0）'

    o, c, h, l = float(open_), float(close), float(high), float(low)
    if h < max(o, c):
        return False, f'high({h}) < max(open,close)({max(o, c)}) 日期倒挂'
    if l > min(o, c):
        return False, f'low({l}) > min(open,close)({min(o, c)}) 日期倒挂'
    if h < l:
        return False, f'high({h}) < low({l})'

    try:
        v = float(volume)
        if v < 0:
            return False, f'volume={v} 为负'
        if v == 0:
            print(f'[DATAVAL-WARN] {code} {kdate}: volume=0（可能停牌），放行入库')
    except (ValueError, TypeError):
        return False, f'volume 非数值: {volume!r}'

    if change_pct is not None:
        try:
            cp = abs(float(change_pct))
            if cp > 22:
                print(f'[DATAVAL-WARN] {code} {kdate}: |change_pct|={cp}% 超涨跌停边界（可能除权未复权），放行入库')
        except (ValueError, TypeError):
            pass
    return True, 'OK'


def validate_kline_row(code: str, k: dict) -> tuple[bool, str]:
    """便捷入口：直接传市场缓存 API 返回的 k dict（含 date/open/close/high/low/volume）。"""
    return validate_kline(
        code, k.get('date', ''), k.get('open'), k.get('close'),
        k.get('high'), k.get('low'), k.get('volume', 0), k.get('change_pct'))


if __name__ == '__main__':
    # 自检
    assert validate_kline('600540', '2026-09-18', 4.0, 4.05, 4.1, 3.98, 100000)[0]
    assert not validate_kline('600540', '2026-09-18', 4.0, 0.0, 4.1, 3.98, 100)[0], 'close=0 应拒绝'
    assert not validate_kline('600540', '2026-09-18', 4.0, 4.05, 3.9, 3.98, 100)[0], 'high<open 应拒绝'
    assert not validate_kline('600540', '2099-01-01', 4.0, 4.05, 4.1, 3.98, 100)[0], '未来日期应拒绝'
    ok, _ = validate_kline('600540', '2026-09-18', 4.0, 4.05, 4.1, 3.98, 0)
    assert ok, 'volume=0 仅警告放行'
    print('DATA_VALIDATION_SELFTEST_OK')
