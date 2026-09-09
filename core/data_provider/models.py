#!/usr/bin/env python3
"""
Data provider layer models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class QuoteSnapshot:
    """Real-time quote snapshot."""
    code: str
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    amount: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    provider: str = ""
    quality: float = 0.0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class KlineBar:
    """Single K-line bar."""
    code: str
    date: str = ""
    open: float = 0.0
    close: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    amount: float = 0.0
    provider: str = ""
    quality: float = 0.0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class MinuteBar:
    """Minute-level K-line bar."""
    code: str
    ts: str = ""
    date: str = ""
    open: float = 0.0
    close: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    amount: float = 0.0
    provider: str = ""
    quality: float = 0.0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class FinancialReport:
    """Financial report snapshot."""
    code: str = ""
    report_date: str = ""
    revenue: float = 0.0
    profit: float = 0.0
    roe: float = 0.0
    debt_ratio: float = 0.0
    profit_growth: float = 0.0
    revenue_growth: float = 0.0
    provider: str = ""
    quality: float = 0.0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class FundFlow:
    """Fund flow record."""
    code: str = ""
    date: str = ""
    main_fund_flow: float = 0.0
    north_bound_flow: float = 0.0
    retail_fund_flow: float = 0.0
    total_fund_flow: float = 0.0
    provider: str = ""
    quality: float = 0.0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class SectorRank:
    """Sector ranking entry."""
    sector_code: str = ""
    sector_name: str = ""
    date: str = ""
    rank: int = 0
    change_pct: float = 0.0
    total_market_cap: float = 0.0
    leading_stock: str = ""
    provider: str = ""
    quality: float = 0.0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class NewsItem:
    """News item."""
    title: str = ""
    url: str = ""
    source: str = ""
    publish_time: str = ""
    summary: str = ""
    sentiment: str = ""
    confidence: float = 0.0
    provider: str = ""
    quality: float = 0.0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class HoldingsRow:
    """Holdings row."""
    code: str = ""
    name: str = ""
    shares: int = 0
    buy_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    pnl_pct: float = 0.0
    status: str = ""
    source: str = ""
    provider: str = ""
    quality: float = 0.0
    raw: Optional[Dict[str, Any]] = None
