#!/usr/bin/env python3
"""
EastMoney realtime provider.

Wraps already-verified system patterns into the unified data provider layer.
"""
from __future__ import annotations

import time
import urllib.request
from typing import List, Optional
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'stock-work'))
from core.data_provider.models import QuoteSnapshot
from core.data_provider.exceptions import DataProviderError, ProviderNetworkError, ProviderParseError, ProviderTimeoutError
from core.data_provider.health import ProviderHealth
from core.data_provider.realtime.interface import RealtimeProvider


class EastMoneyRealtimeProvider(RealtimeProvider):
    """EastMoney realtime quote provider."""

    def __init__(self, health: Optional[ProviderHealth] = None, timeout: int = 10) -> None:
        self.health = health or ProviderHealth(provider="eastmoney_realtime")
        self.timeout = timeout

    def _record_success(self, latency_ms: float) -> None:
        self.health.record_success(latency_ms)

    def _record_failure(self, error: str) -> None:
        self.health.record_failure(error)

    def _parse_sina_style(self, text: str) -> List[QuoteSnapshot]:
        results: List[QuoteSnapshot] = []
        for line in text.strip().split("\n"):
            if "=" not in line:
                continue
            raw_code = line.split("=")[0].split("_")[-1].strip()
            code = raw_code[2:] if raw_code.startswith(("sh", "sz")) else raw_code
            parts = line.split('"')[1].split(",")
            if len(parts) < 10:
                continue
            try:
                name = parts[0]
                price = float(parts[3])
                prev_close = float(parts[2])
                change_pct = 0.0
                if prev_close > 0:
                    change_pct = (price - prev_close) / prev_close * 100
                volume = 0
                amount = 0.0
                if len(parts) > 8:
                    try:
                        volume = int(parts[8])
                    except (ValueError, IndexError):
                        volume = 0
                if len(parts) > 9:
                    try:
                        amount = float(parts[9])
                    except (ValueError, IndexError):
                        amount = 0.0
                results.append(QuoteSnapshot(
                    code=code,
                    name=name,
                    price=price,
                    change_pct=change_pct,
                    volume=volume,
                    amount=amount,
                    provider="eastmoney",
                    quality=1.0,
                    raw={"parts": parts},
                ))
            except (ValueError, IndexError):
                continue
        return results

    def get_quote(self, code: str) -> QuoteSnapshot:
        start = time.perf_counter()
        try:
            quotes = self.get_batch_quotes([code])
            latency_ms = (time.perf_counter() - start) * 1000
            if not quotes:
                raise ProviderParseError("empty quote", provider="eastmoney_realtime")
            self._record_success(latency_ms)
            return quotes[0]
        except DataProviderError:
            raise
        except Exception as exc:
            self._record_failure(str(exc))
            raise ProviderNetworkError(str(exc), provider="eastmoney_realtime") from exc

    def get_batch_quotes(self, codes: List[str]) -> List[QuoteSnapshot]:
        start = time.perf_counter()
        if not codes:
            return []
        sina_codes = ",".join([f"{'sz' if c.startswith(('0','3')) else 'sh'}{c}" for c in codes])
        url = f"https://hq.sinajs.cn/list={sina_codes}"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("gbk", errors="replace")
        except urllib.error.URLError as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderNetworkError(str(exc), provider="eastmoney_realtime") from exc
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderTimeoutError(str(exc), provider="eastmoney_realtime") from exc
        try:
            results = self._parse_sina_style(text)
            latency_ms = (time.perf_counter() - start) * 1000
            if not results:
                self._record_failure("empty batch result")
                return []
            self._record_success(latency_ms)
            return results
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderParseError(str(exc), provider="eastmoney_realtime") from exc

    def get_minute_kline(self, code: str, trade_date: str) -> List[dict]:
        start = time.perf_counter()
        try:
            prefix = "sz" if code.startswith(("0", "3")) else "sh"
            secid = f"1.{code}" if prefix == "sh" else f"0.{code}"
            url = f"http://push2delay.eastmoney.com/api/qt/stock/trends2/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13,f14,f15,f16,f17,f18&fields2=f51,f52,f53,f54,f55,f56,f57,f58&ndays=1&lmt=500"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            trends = data.get("data", {}).get("trends", [])
            latency_ms = (time.perf_counter() - start) * 1000
            if not trends:
                self._record_failure("empty trends")
                return []
            bars = []
            for t in trends:
                parts = t.split(",")
                if len(parts) < 7:
                    continue
                bars.append({
                    "ts": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": int(parts[5]),
                    "amount": float(parts[6]),
                })
            self._record_success(latency_ms)
            return bars
        except DataProviderError:
            raise
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._record_failure(str(exc))
            raise ProviderNetworkError(str(exc), provider="eastmoney_realtime") from exc
