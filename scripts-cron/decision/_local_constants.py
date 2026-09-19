#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地运行常量（不进入 Git）。

此文件被 .gitignore 排除，用于存放真实环境标识：
- FEISHU_CHAT_ID
- BITABLE_BASE_TOKEN / TABLE_ID
- REAL_HOLDINGS_BASE

仓库内代码统一从此模块导入，避免硬编码进入版本控制。
本地首次运行时请按实际值填充。
"""
from __future__ import annotations

import os
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────
# Feishu
# ─────────────────────────────────────────────────────────────────────────
FEISHU_CHAT_ID: str = os.environ.get('FEISHU_CHAT_ID', '')

# ─────────────────────────────────────────────────────────────────────────
# Bitable
# ─────────────────────────────────────────────────────────────────────────
BITABLE_BASE_TOKEN: str = os.environ.get('BITABLE_APP_TOKEN', '')
BITABLE_TABLE_ID: str = os.environ.get('BITABLE_TABLE_ID', '')
REAL_HOLDINGS_BASE: str = os.environ.get('REAL_HOLDINGS_BASE', '')

# ─────────────────────────────────────────────────────────────────────────
# 兜底：若环境变量为空，允许本地从固定文件读取（该文件也不进 Git）
# ─────────────────────────────────────────────────────────────────────────
_LOCAL_SECRETS_PATH = Path(__file__).with_name('_local_constants.override.json')
if _LOCAL_SECRETS_PATH.exists() and not (FEISHU_CHAT_ID and BITABLE_BASE_TOKEN and BITABLE_TABLE_ID):
    try:
        import json
        _secrets = json.loads(_LOCAL_SECRETS_PATH.read_text(encoding='utf-8'))
        FEISHU_CHAT_ID = FEISHU_CHAT_ID or _secrets.get('FEISHU_CHAT_ID', '')
        BITABLE_BASE_TOKEN = BITABLE_BASE_TOKEN or _secrets.get('BITABLE_BASE_TOKEN', '')
        BITABLE_TABLE_ID = BITABLE_TABLE_ID or _secrets.get('BITABLE_TABLE_ID', '')
        REAL_HOLDINGS_BASE = REAL_HOLDINGS_BASE or _secrets.get('REAL_HOLDINGS_BASE', '')
    except Exception as _e:
        print(f"[EXC] _local_constants.py: {type(_e).__name__}: {_e}")
        pass
