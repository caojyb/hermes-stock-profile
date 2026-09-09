#!/usr/bin/env python3
"""
Configuration loader for data providers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import os

_DEFAULT_CONFIG: Dict[str, Any] = {
    "realtime": {
        "quote": {
            "primary": {"provider": "eastmoney", "timeout": 10, "retry": 3},
            "fallback": [
                {"provider": "sina", "timeout": 8, "retry": 2},
            ],
        }
    },
    "historical": {
        "kline": {
            "primary": {"provider": "eastmoney", "timeout": 15, "retry": 3},
            "fallback": [
                {"provider": "akshare", "timeout": 20, "retry": 2},
            ],
        }
    },
    "financial": {
        "reports": {
            "primary": {"provider": "eastmoney", "timeout": 20, "retry": 3},
            "fallback": [
                {"provider": "akshare", "timeout": 30, "retry": 2},
            ],
        }
    },
    "fund_flow": {
        "main_fund": {
            "primary": {"provider": "eastmoney", "timeout": 10, "retry": 3},
            "fallback": [],
        }
    },
}


def _resolve_config_path() -> Path:
    """Resolve config path relative to this file."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "config" / "data_sources.yaml",
        here.parents[1] / "config" / "data_sources.yaml",
        here.parent / "config" / "data_sources.yaml",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load data source configuration.

    If the YAML file does not exist, return the built-in default config.
    """
    config_path = Path(path) if path else _resolve_config_path()
    if not config_path.exists():
        return dict(_DEFAULT_CONFIG)
    try:
        import yaml
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return dict(_DEFAULT_CONFIG)
        return data
    except Exception:
        return dict(_DEFAULT_CONFIG)
