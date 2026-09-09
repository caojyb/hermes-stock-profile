#!/usr/bin/env python3
"""
Realtime provider adapter for shadow mode.

Provides a side-by-side comparison between legacy fetching and
EastMoneyRealtimeProvider without changing production writes.
"""
from __future__ import annotations

import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROFILE_ROOT = Path('/home/caojy/.hermes/profiles/stock')
sys.path.insert(0, str((PROFILE_ROOT / 'stock-work').resolve()))

from core.data_provider.models import QuoteSnapshot
from core.data_provider.exceptions import DataProviderError
from core.data_provider.health import ProviderHealth
from core.data_provider.provider_manager import ProviderManager
from core.data_provider.realtime.eastmoney import EastMoneyRealtimeProvider


@dataclass
class QuoteResult:
    code: str
    legacy_price: float
    provider_price: float
    legacy_change_pct: float
    provider_change_pct: float
    price_diff: float
    change_pct_diff: float
    legacy_volume: int
    provider_volume: int
    legacy_amount: float
    provider_amount: float
    volume_diff: int
    amount_diff: float
    provider_latency_ms: float
    legacy_latency_ms: float
    provider_error: Optional[str] = None
    legacy_error: Optional[str] = None


class RealtimeShadowAdapter:
    """Shadow adapter for realtime provider comparison."""

    def __init__(self, shadow_mode: bool = True) -> None:
        self.shadow_mode = shadow_mode
        health = ProviderHealth(provider="eastmoney_realtime_shadow")
        self.provider = EastMoneyRealtimeProvider(health=health)
        self.manager = ProviderManager()
        self.manager.register_provider("eastmoney_realtime", self.provider)
        self.results: List[QuoteResult] = []

    def _legacy_batch_quote(self, codes: List[str]) -> Tuple[Dict[str, Dict[str, float]], float]:
        results: Dict[str, Dict[str, float]] = {}
        start = time.perf_counter()
        if not codes:
            return results, (time.perf_counter() - start) * 1000
        sina_codes = ",".join([f"{'sz' if c.startswith(('0','3')) else 'sh'}{c}" for c in codes])
        url = f"https://hq.sinajs.cn/list={sina_codes}"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("gbk", errors="replace")
        except Exception as exc:
            return results, (time.perf_counter() - start) * 1000
        for line in text.strip().split("\n"):
            if "=" not in line:
                continue
            raw_code = line.split("=")[0].split("_")[-1].strip()
            code = raw_code[2:] if raw_code.startswith(("sh", "sz")) else raw_code
            parts = line.split('"')[1].split(",")
            if len(parts) < 10:
                continue
            try:
                price = float(parts[3])
                prev_close = float(parts[2])
                change_pct = 0.0
                if prev_close > 0:
                    change_pct = (price - prev_close) / prev_close * 100
                volume = int(parts[8]) if len(parts) > 8 else 0
                amount = float(parts[9]) if len(parts) > 9 else 0.0
                results[code] = {
                    "price": price,
                    "change_pct": change_pct,
                    "volume": volume,
                    "amount": amount,
                }
            except (ValueError, IndexError):
                continue
        return results, (time.perf_counter() - start) * 1000

    def compare_batch(self, codes: List[str]) -> List[QuoteResult]:
        legacy_data, legacy_latency = self._legacy_batch_quote(codes)
        provider_start = time.perf_counter()
        provider_error = None
        provider_quotes: List[QuoteSnapshot] = []
        try:
            provider_quotes = self.provider.get_batch_quotes(codes)
        except DataProviderError as exc:
            provider_error = str(exc)
        provider_latency = (time.perf_counter() - provider_start) * 1000

        provider_map = {q.code: q for q in provider_quotes}
        results: List[QuoteResult] = []
        for code in codes:
            legacy = legacy_data.get(code)
            provider_quote = provider_map.get(code)
            if legacy and provider_quote:
                results.append(QuoteResult(
                    code=code,
                    legacy_price=legacy["price"],
                    provider_price=provider_quote.price,
                    legacy_change_pct=legacy["change_pct"],
                    provider_change_pct=provider_quote.change_pct,
                    price_diff=abs(provider_quote.price - legacy["price"]),
                    change_pct_diff=abs(provider_quote.change_pct - legacy["change_pct"]),
                    legacy_volume=legacy.get("volume", 0),
                    provider_volume=provider_quote.volume or 0,
                    legacy_amount=legacy.get("amount", 0.0),
                    provider_amount=provider_quote.amount or 0.0,
                    volume_diff=(provider_quote.volume or 0) - legacy.get("volume", 0),
                    amount_diff=(provider_quote.amount or 0.0) - legacy.get("amount", 0.0),
                    provider_latency_ms=provider_latency,
                    legacy_latency_ms=legacy_latency,
                    provider_error=provider_error,
                ))
            elif legacy and not provider_quote:
                results.append(QuoteResult(
                    code=code,
                    legacy_price=legacy["price"],
                    provider_price=0.0,
                    legacy_change_pct=legacy["change_pct"],
                    provider_change_pct=0.0,
                    price_diff=legacy["price"],
                    change_pct_diff=legacy["change_pct"],
                    legacy_volume=legacy.get("volume", 0),
                    provider_volume=0,
                    legacy_amount=legacy.get("amount", 0.0),
                    provider_amount=0.0,
                    volume_diff=-legacy.get("volume", 0),
                    amount_diff=-legacy.get("amount", 0.0),
                    provider_latency_ms=provider_latency,
                    legacy_latency_ms=legacy_latency,
                    provider_error=provider_error or "missing",
                ))
            elif not legacy and provider_quote:
                results.append(QuoteResult(
                    code=code,
                    legacy_price=0.0,
                    provider_price=provider_quote.price,
                    legacy_change_pct=0.0,
                    provider_change_pct=provider_quote.change_pct,
                    price_diff=provider_quote.price,
                    change_pct_diff=provider_quote.change_pct,
                    legacy_volume=0,
                    provider_volume=provider_quote.volume or 0,
                    legacy_amount=0.0,
                    provider_amount=provider_quote.amount or 0.0,
                    volume_diff=provider_quote.volume or 0,
                    amount_diff=provider_quote.amount or 0.0,
                    provider_latency_ms=provider_latency,
                    legacy_latency_ms=legacy_latency,
                    provider_error=None,
                    legacy_error="missing",
                ))
        self.results.extend(results)
        return results

    def summary(self) -> Dict[str, float]:
        if not self.results:
            return {}
        matched = [r for r in self.results if r.provider_error is None and r.legacy_error is None]
        price_diffs = [abs(r.price_diff) for r in matched]
        change_diffs = [abs(r.change_pct_diff) for r in matched]
        provider_latencies = [r.provider_latency_ms for r in matched]
        legacy_latencies = [r.legacy_latency_ms for r in matched]
        return {
            "total": len(self.results),
            "matched": len(matched),
            "provider_success_rate": len([r for r in self.results if r.provider_error is None]) / len(self.results) * 100,
            "legacy_success_rate": len([r for r in self.results if r.legacy_error is None]) / len(self.results) * 100,
            "avg_price_diff": sum(price_diffs) / len(price_diffs) if price_diffs else 0.0,
            "max_price_diff": max(price_diffs) if price_diffs else 0.0,
            "avg_change_pct_diff": sum(change_diffs) / len(change_diffs) if change_diffs else 0.0,
            "avg_provider_latency_ms": sum(provider_latencies) / len(provider_latencies) if provider_latencies else 0.0,
            "avg_legacy_latency_ms": sum(legacy_latencies) / len(legacy_latencies) if legacy_latencies else 0.0,
        }
