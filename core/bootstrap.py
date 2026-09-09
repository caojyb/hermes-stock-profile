#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stock-work bootstrap helper

Provides a single idempotent helper to ensure `stock-work/` is on `sys.path`
so that `core.*` imports resolve correctly when scripts are executed directly
under Hermes cron or standalone CLI.

Usage:
    from core.bootstrap import ensure_stock_work_root
    ensure_stock_work_root()
    from core.compat_paths import ...
"""

from pathlib import Path
import sys


def ensure_stock_work_root() -> None:
    """
    Insert the stock-work repository root into sys.path[0] if not already present.

    The root is resolved relative to this file's location, so it does not depend
    on the current working directory or any hardcoded profile path.
    """
    root = Path(__file__).resolve().parent.parent
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
