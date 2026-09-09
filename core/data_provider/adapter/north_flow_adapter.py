#!/usr/bin/env python3
"""
North flow shadow adapter for north_flow_monitor.py.

Read-only adapter. Does not modify production writes.
"""
from __future__ import annotations

import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

PROFILE_ROOT = Path('/home/caojy/.hermes/profiles/stock')
sys.path.insert(0, str((PROFILE_ROOT / 'stock-work').resolve()))

from core.data_provider.fund_flow.eastmoney import EastMoneyFundFlowProvider, NorthFlowItem
from core.data_provider.health import ProviderHealth
from core.data_provider.exceptions import DataProviderError


@dataclass
class NorthFlowCompareResult:
    code: str
    name: str
    legacy_net_buy: float
    provider_net_buy: float
    legacy_hold_value: float
    provider_hold_value: float
    net_buy_diff: float
    hold_value_diff: float
    provider_error: Optional[str] = None
    legacy_error: Optional[str] = None


class NorthFlowShadowAdapter:
    """Shadow adapter for north flow comparison."""

    def __init__(self, limit: int = 50) -> None:
        self.limit = limit
        health = ProviderHealth(provider="eastmoney_fund_flow_shadow")
        self.provider = EastMoneyFundFlowProvider(health=health)
        self.results: List[NorthFlowCompareResult] = []

    def _legacy_fetch_north_top(self) -> Tuple[List[dict], List[dict]]:
        buy_top: List[dict] = []
        sell_top: List[dict] = []
        url = "http://push2delay.eastmoney.com/api/qt/clist/get"
        base_params = {
            'pn': 1, 'pz': self.limit, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2,
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f12,f14,f62,f71'
        }

        def parse_response(params):
            try:
                req = urllib.request.Request(
                    url,
                    data=("&".join([f"{k}={v}" for k, v in params.items()])).encode("utf-8"),
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                import json
                payload = json.loads(text)
                items = payload.get("data", {}).get("diff", [])
                result = []
                for item in items:
                    code = item.get("f12", "")
                    name = item.get("f14", "")
                    net_buy = item.get("f62", 0) or 0
                    hold_value = item.get("f71", 0) or 0
                    if code:
                        result.append({
                            'code': code,
                            'name': name,
                            'net_buy': float(net_buy),
                            'hold_value': float(hold_value),
                        })
                return result
            except Exception:
                return []

        buy_params = base_params.copy()
        buy_params['fid'] = 'f62'
        buy_params['po'] = 1
        buy_top = parse_response(buy_params)

        sell_params = base_params.copy()
        sell_params['fid'] = 'f62'
        sell_params['po'] = 0
        sell_top = parse_response(sell_params)

        return buy_top, sell_top

    def compare(self) -> Tuple[List[NorthFlowCompareResult], dict]:
        legacy_start = time.perf_counter()
        legacy_buy, legacy_sell = self._legacy_fetch_north_top()
        legacy_latency = (time.perf_counter() - legacy_start) * 1000

        provider_start = time.perf_counter()
        provider_error = None
        provider_buy: List[NorthFlowItem] = []
        provider_sell: List[NorthFlowItem] = []
        try:
            provider_buy = self.provider.get_northbound_rank(limit=self.limit, descending=True)
            provider_sell = self.provider.get_northbound_rank(limit=self.limit, descending=False)
        except DataProviderError as exc:
            provider_error = str(exc)
        provider_latency = (time.perf_counter() - provider_start) * 1000

        legacy_buy_map = {r['code']: r for r in legacy_buy}
        legacy_sell_map = {r['code']: r for r in legacy_sell}
        provider_buy_map = {r.code: r for r in provider_buy}
        provider_sell_map = {r.code: r for r in provider_sell}

        results: List[NorthFlowCompareResult] = []
        all_codes = sorted(set(legacy_buy_map) | set(legacy_sell_map) | set(provider_buy_map) | set(provider_sell_map))
        for code in all_codes:
            legacy_item = legacy_buy_map.get(code) or legacy_sell_map.get(code)
            provider_item = provider_buy_map.get(code) or provider_sell_map.get(code)
            if legacy_item and provider_item:
                results.append(NorthFlowCompareResult(
                    code=code,
                    name=legacy_item.get('name', provider_item.name),
                    legacy_net_buy=legacy_item.get('net_buy', 0.0),
                    provider_net_buy=provider_item.net_buy,
                    legacy_hold_value=legacy_item.get('hold_value', 0.0),
                    provider_hold_value=provider_item.hold_value,
                    net_buy_diff=abs(provider_item.net_buy - legacy_item.get('net_buy', 0.0)),
                    hold_value_diff=abs(provider_item.hold_value - legacy_item.get('hold_value', 0.0)),
                ))
            elif legacy_item and not provider_item:
                results.append(NorthFlowCompareResult(
                    code=code,
                    name=legacy_item.get('name', ''),
                    legacy_net_buy=legacy_item.get('net_buy', 0.0),
                    provider_net_buy=0.0,
                    legacy_hold_value=legacy_item.get('hold_value', 0.0),
                    provider_hold_value=0.0,
                    net_buy_diff=abs(legacy_item.get('net_buy', 0.0)),
                    hold_value_diff=abs(legacy_item.get('hold_value', 0.0)),
                    provider_error=provider_error or "missing",
                ))
            elif provider_item and not legacy_item:
                results.append(NorthFlowCompareResult(
                    code=code,
                    name=provider_item.name,
                    legacy_net_buy=0.0,
                    provider_net_buy=provider_item.net_buy,
                    legacy_hold_value=0.0,
                    provider_hold_value=provider_item.hold_value,
                    net_buy_diff=abs(provider_item.net_buy),
                    hold_value_diff=abs(provider_item.hold_value),
                    legacy_error="missing",
                ))
        self.results.extend(results)
        summary = {
            "matched": sum(1 for r in results if r.provider_error is None and r.legacy_error is None),
            "provider_buy_count": len(provider_buy),
            "provider_sell_count": len(provider_sell),
            "legacy_buy_count": len(legacy_buy),
            "legacy_sell_count": len(legacy_sell),
            "provider_latency_ms": provider_latency,
            "legacy_latency_ms": legacy_latency,
        }
        return results, summary
