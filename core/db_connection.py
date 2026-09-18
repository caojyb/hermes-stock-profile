#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一 SQLite 连接工厂（2026-09-18 二轮审计 P1-2）
================================================
背景：全库 442 处 sqlite3.connect 裸调用、0 处 busy_timeout、0 处 WAL，
97 个写者并发下锁冲突/半写风险高。本工厂统一注入并发安全参数。

用法（新代码）：
    from core.db_connection import connect_db
    conn = connect_db('/path/to/db.sqlite', writer=True)
    with conn:  # 自动事务
        conn.execute(...)

存量代码迁移策略：不一次性改 442 处；优先接入高频写点
（double_monitor、daily_data_refresh、decision/execution、simulation）。

参数说明：
- WAL: 读写不互斥，写者不再阻塞读者（多写者仍串行）
- busy_timeout=30000: 锁等待 30s 再报错（原来立即抛 database is locked）
- writer=True: 额外 BEGIN IMMEDIATE 语义由调用方事务承担；
  WAL + busy_timeout 已覆盖绝大多数场景
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from core.path_resolver import get_path_resolver

_resolver = get_path_resolver()

DEFAULT_BUSY_TIMEOUT_MS = 30_000


def connect_db(
    db_path: str | Path,
    *,
    writer: bool = False,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    readonly: bool = False,
) -> sqlite3.Connection:
    """创建带并发安全参数的 SQLite 连接。

    Args:
        db_path: 数据库文件路径
        writer: True=写连接（确保 WAL pragma 应用，含建库场景）
        busy_timeout_ms: 锁等待毫秒数
        readonly: True=只读连接（mode=ro，不写 WAL header）
    Returns:
        sqlite3.Connection（row_factory 未设，保持与存量代码一致）
    """
    db_path = str(db_path)
    if readonly:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=busy_timeout_ms / 1000)
        return conn

    conn = sqlite3.connect(db_path, timeout=busy_timeout_ms / 1000)
    # WAL 允许读写并发；对已存在 -wal/-shm 的库幂等
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    # 写连接加同步保护，防止掉电半写
    if writer:
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connect_market_db(*, writer: bool = False, readonly: bool = False) -> sqlite3.Connection:
    """market_cache.db 专用快捷连接（canonical 路径）。"""
    return connect_db(_resolver.market_cache_db, writer=writer, readonly=readonly)


def connect_simulation_db(*, writer: bool = False, readonly: bool = False) -> sqlite3.Connection:
    """simulation.db 专用快捷连接。"""
    return connect_db(_resolver.simulation_db, writer=writer, readonly=readonly)
