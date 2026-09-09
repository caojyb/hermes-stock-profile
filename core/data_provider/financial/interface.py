#!/usr/bin/env python3
"""
Financial provider interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'stock-work'))
from core.data_provider.models import FinancialReport


class FinancialProvider(ABC):
    """Financial data provider interface."""

    @abstractmethod
    def get_financial_report(self, code: str, report_date: str) -> Optional[FinancialReport]:
        """Get financial report for specific date."""
        raise NotImplementedError()

    @abstractmethod
    def get_latest_financial_date(self, code: str) -> Optional[str]:
        """Get latest available financial report date."""
        raise NotImplementedError()
