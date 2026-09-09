#!/usr/bin/env python3
"""
Historical provider interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'stock-work'))
from core.data_provider.models import KlineBar


class HistoricalProvider(ABC):
    """Historical data provider interface."""

    @abstractmethod
    def get_daily_kline(self, code: str, start: date, end: date) -> List[KlineBar]:
        """Get daily K-line data."""
        raise NotImplementedError()

    @abstractmethod
    def get_latest_trade_date(self, code: str) -> Optional[str]:
        """Get latest available trade date for stock."""
        raise NotImplementedError()
