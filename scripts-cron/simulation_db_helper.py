#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一 simulation DB 路径获取。
测试模式 -> simulation_test.db，生产模式 -> canonical runtime simulation.db。
"""
import os
from pathlib import Path

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

from core.compat_paths import SIMULATION_DB as _STOCK_SIMULATION_DB


def get_active_sim_db() -> Path:
    mode = os.environ.get('SIM_MODE', '')
    if mode == 'test':
        return Path('/home/caojy/.hermes/profiles/stock/scripts/cron/simulation_test.db')
    return _STOCK_SIMULATION_DB


__all__ = ['get_active_sim_db']
