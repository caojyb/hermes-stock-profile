#!/usr/bin/env python3
"""
Fund flow provider interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'stock-work'))
from core.data_provider.models import FundFlow


class FundFlowProvider(ABC):
    """Fund flow provider interface."""

    @abstractmethod
    def get_main_fund_flow(self, code: str, trade_date: str) -> Optional[FundFlow]:
        """Get main fund flow for specific date."""
        raise NotImplementedError()

    @abstractmethod
    def get_north_bound_flow(self, code: str, trade_date: str) -> Optional[FundFlow]:
        """Get north-bound fund flow."""
        raise NotImplementedError()
