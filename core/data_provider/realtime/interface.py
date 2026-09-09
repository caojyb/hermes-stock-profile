#!/usr/bin/env python3
"""
Realtime provider interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional
import sys
from pathlib import Path

# Ensure stock-work is on sys.path for model imports
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'stock-work'))
from core.data_provider.models import QuoteSnapshot, MinuteBar


class RealtimeProvider(ABC):
    """Real-time data provider interface."""

    @abstractmethod
    def get_quote(self, code: str) -> QuoteSnapshot:
        """Get latest quote for single stock."""
        raise NotImplementedError()

    @abstractmethod
    def get_batch_quotes(self, codes: List[str]) -> List[QuoteSnapshot]:
        """Get latest quotes for multiple stocks."""
        raise NotImplementedError()

    @abstractmethod
    def get_minute_kline(self, code: str, trade_date: str) -> List[MinuteBar]:
        """Get minute-level K-line for specific date."""
        raise NotImplementedError()
