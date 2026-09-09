#!/usr/bin/env python3
"""
Provider health tracking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class ProviderHealth:
    """Provider health state."""
    provider: str
    success_count: int = 0
    failure_count: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_error: str = ""
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0

    def record_success(self, latency_ms: float = 0.0) -> None:
        """Record successful call."""
        self.success_count += 1
        self.last_success = datetime.now()
        self.consecutive_failures = 0
        if latency_ms > 0:
            self.avg_latency_ms = (self.avg_latency_ms + latency_ms) / 2

    def record_failure(self, error: str = "") -> None:
        """Record failed call."""
        self.failure_count += 1
        self.last_failure = datetime.now()
        self.last_error = error or ""
        self.consecutive_failures += 1

    @property
    def is_healthy(self) -> bool:
        """Check if provider is currently healthy."""
        if self.consecutive_failures >= 3:
            return False
        if self.last_failure and datetime.now() - self.last_failure < timedelta(minutes=5):
            return False
        return True

    @property
    def total_calls(self) -> int:
        """Total call count."""
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """Success rate."""
        if self.total_calls == 0:
            return 0.0
        return self.success_count / self.total_calls
