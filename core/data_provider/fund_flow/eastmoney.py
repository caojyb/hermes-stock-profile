#!/usr/bin/env python3
"""
EastMoney fund flow provider.

Implements north-bound fund flow retrieval for the unified data provider layer.
"""
from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import sys

PROFILE_ROOT = Path('/home/caojy/.hermes/profiles/stock')
sys.path.insert(0, str((PROFILE_ROOT / 'stock-work').resolve()))

from core.data_provider.models import FundFlow
from core.data_provider.exceptions import DataProviderError, ProviderNetworkError, ProviderParseError, ProviderTimeoutError
from core.data_provider.health import ProviderHealth
from core.data_provider.provider_manager import ProviderManager
from core.data_provider.fund_flow.interface import FundFlowProvider


@dataclass
class NorthFlowItem:
    """North-bound fund flow item."""
    code: str = ""
    name: str = ""
    net_buy: float = 0.0
    hold_value: float = 0.0
    provider: str = "eastmoney"
    quality: float = 1.0
    raw: Optional[dict] = None


class EastMoneyFundFlowProvider(FundFlowProvider):
    """EastMoney fund flow provider."""

    def __init__(self, health: Optional[ProviderHealth] = None, timeout: int = 10) -> None:
        self.health = health or ProviderHealth(provider="eastmoney_fund_flow")
        self.timeout = timeout
        self._manager: Optional[ProviderManager] = None

    def set_manager(self, manager: ProviderManager) -> None:
        self._manager = manager

    def _record_success(self, latency_ms: float) -> None:
        self.health.record_success(latency_ms)

    def _record_failure(self, error: str) -> None:
        self.health.record_failure(error)

    def get_northbound_flow(self, codes: List[str], trade_date: Optional[str] = None) -> List[NorthFlowItem]:
        """Get north-bound fund flow for a list of codes."""
        start = time.perf_counter()
        if not codes:
            return []
        secids = []
        for c in codes:
            if c.startswith(("60", "688", "689")):
                secids.append(f"1.{c}")
            else:
                secids.append(f"0.{c}")
        url = "http://push2delay.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1,
            "pz": len(codes),
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f62",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f62,f71",
        }
        req = urllib.request.Request(
            url,
            data=("&".join([f"{k}={v}" for k, v in params.items()])).encode("utf-8"),
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.eastmoney.com"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderNetworkError(str(exc), provider="eastmoney_fund_flow") from exc
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderTimeoutError(str(exc), provider="eastmoney_fund_flow") from exc
        try:
            import json as _json
            payload = _json.loads(text)
            items = payload.get("data", {}).get("diff", [])
            results = []
            for item in items:
                code = item.get("f12", "")
                name = item.get("f14", "")
                net_buy = item.get("f62", 0) or 0
                hold_value = item.get("f71", 0) or 0
                if code:
                    results.append(NorthFlowItem(
                        code=code,
                        name=name,
                        net_buy=float(net_buy),
                        hold_value=float(hold_value),
                        provider="eastmoney",
                        quality=1.0,
                        raw=item,
                    ))
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_success(latency_ms)
            return results
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderParseError(str(exc), provider="eastmoney_fund_flow") from exc

    def get_northbound_rank(self, limit: int = 50, descending: bool = True) -> List[NorthFlowItem]:
        """Get ranked north-bound fund flow list."""
        start = time.perf_counter()
        url = "http://push2delay.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1,
            "pz": limit,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f62",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "po": 1 if descending else 0,
            "fields": "f12,f14,f62,f71",
        }
        req = urllib.request.Request(
            url,
            data=("&".join([f"{k}={v}" for k, v in params.items()])).encode("utf-8"),
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.eastmoney.com"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderNetworkError(str(exc), provider="eastmoney_fund_flow") from exc
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderTimeoutError(str(exc), provider="eastmoney_fund_flow") from exc
        try:
            import json as _json
            payload = _json.loads(text)
            items = payload.get("data", {}).get("diff", [])
            results = []
            for item in items:
                code = item.get("f12", "")
                name = item.get("f14", "")
                net_buy = item.get("f62", 0) or 0
                hold_value = item.get("f71", 0) or 0
                if code:
                    results.append(NorthFlowItem(
                        code=code,
                        name=name,
                        net_buy=float(net_buy),
                        hold_value=float(hold_value),
                        provider="eastmoney",
                        quality=1.0,
                        raw=item,
                    ))
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_success(latency_ms)
            return results
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderParseError(str(exc), provider="eastmoney_fund_flow") from exc

    def get_main_fund_flow(self, code: str, trade_date: str) -> Optional[FundFlow]:
        raise NotImplementedError("use get_northbound_flow or get_northbound_rank")

    def get_north_bound_flow(self, code: str, trade_date: str) -> Optional[FundFlow]:
        raise NotImplementedError("use get_northbound_flow or get_northbound_rank")
