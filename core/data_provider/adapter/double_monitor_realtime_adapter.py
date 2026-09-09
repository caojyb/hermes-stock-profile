#!/usr/bin/env python3
"""
Realtime read cutover adapter for double_monitor.py.

Switches only the READ PATH for current quote lookup to the Data Provider Layer,
while keeping all write paths and monitoring logic unchanged.
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, Optional

PROFILE_ROOT = Path('/home/caojy/.hermes/profiles/stock')
sys.path.insert(0, str((PROFILE_ROOT / 'stock-work').resolve()))

from core.data_provider.provider_manager import ProviderManager
from core.data_provider.realtime.eastmoney import EastMoneyRealtimeProvider
from core.data_provider.health import ProviderHealth


class DoubleMonitorRealtimeAdapter:
    """Provider-first realtime reader with legacy fallback."""

    def __init__(self) -> None:
        health = ProviderHealth(provider="eastmoney_realtime_double_monitor")
        provider = EastMoneyRealtimeProvider(health=health)
        self.manager = ProviderManager()
        self.manager.register_provider("eastmoney_realtime", provider)
        self.provider = provider
        self.provider_used_count = 0
        self.fallback_count = 0

    def get_current_quote(self, code: str) -> Dict[str, Optional[float]]:
        """Return unified quote dict with provider_used flag."""
        try:
            quote = self.provider.get_quote(code)
            self.provider_used_count += 1
            return {
                "code": code,
                "price": float(quote.price),
                "change_pct": float(quote.change_pct or 0.0),
                "volume": int(quote.volume or 0),
                "amount": float(quote.amount or 0.0),
                "provider_used": True,
                "provider": "eastmoney",
            }
        except Exception:
            self.fallback_count += 1
            legacy = self._legacy_quote(code)
            legacy["provider_used"] = False
            legacy["provider"] = "legacy"
            return legacy

    def _legacy_quote(self, code: str) -> Dict[str, Optional[float]]:
        prefix = "sz" if code.startswith(("0", "3")) else "sh"
        sina_code = f"{prefix}{code}"
        url = f"https://hq.sinajs.cn/list={sina_code}"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("gbk", errors="replace")
        except Exception:
            return {
                "code": code,
                "price": None,
                "change_pct": None,
                "volume": None,
                "amount": None,
            }
        for line in text.strip().split("\n"):
            if "=" not in line:
                continue
            raw_code = line.split("=")[0].split("_")[-1].strip()
            code_only = raw_code[2:] if raw_code.startswith(("sh", "sz")) else raw_code
            if code_only != code:
                continue
            parts = line.split('"')[1].split(",")
            if len(parts) < 10:
                return {
                    "code": code,
                    "price": None,
                    "change_pct": None,
                    "volume": None,
                    "amount": None,
                }
            try:
                price = float(parts[3])
                prev_close = float(parts[2])
                change_pct = 0.0
                if prev_close > 0:
                    change_pct = (price - prev_close) / prev_close * 100
                return {
                    "code": code,
                    "price": price,
                    "change_pct": change_pct,
                    "volume": int(parts[8]) if len(parts) > 8 else None,
                    "amount": float(parts[9]) if len(parts) > 9 else None,
                }
            except (ValueError, IndexError):
                return {
                    "code": code,
                    "price": None,
                    "change_pct": None,
                    "volume": None,
                    "amount": None,
                }
        return {
            "code": code,
            "price": None,
            "change_pct": None,
            "volume": None,
            "amount": None,
        }
