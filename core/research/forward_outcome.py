#!/usr/bin/env python3
"""
Compatibility re-export for forward_outcome.

Actual implementation lives at:
  scripts/cron/research/forward_outcome.py

This module re-exports from the canonical research location to maintain
the stock-work/core/research/ namespace.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Resolve actual module path
_ACTUAL_DIR = Path(__file__).resolve().parents[3] / 'scripts' / 'cron' / 'research'
if str(_ACTUAL_DIR) not in sys.path:
    sys.path.insert(0, str(_ACTUAL_DIR))

from forward_outcome import (  # noqa: E402
    HORIZONS,
    UNKNOWN,
    DEFAULT_DB,
    DEFAULT_OUTPUT,
    compute_one,
    compute_outcomes,
    load_candidates,
    write_csv,
    main,
)

__all__ = [
    'HORIZONS',
    'UNKNOWN',
    'DEFAULT_DB',
    'DEFAULT_OUTPUT',
    'compute_one',
    'compute_outcomes',
    'load_candidates',
    'write_csv',
    'main',
]
