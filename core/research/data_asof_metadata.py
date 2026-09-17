#!/usr/bin/env python3
"""
stock-work/core/research/data_asof_metadata.py

Data availability metadata registry.
Classifies datasets by PIT safety and tracks enforcement mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from core.research.research_time_context import PITStatus


@dataclass
class DataAsofMetadata:
    dataset_id: str
    data_type: str
    table: Optional[str] = None
    record_scope: str = "row"
    observation_time_field: Optional[str] = None
    effective_time_field: Optional[str] = None
    available_time_field: Optional[str] = None
    source: Optional[str] = None
    current_enforcement: str = "NONE"  # CODE_ENFORCED, DOC_ONLY, NONE
    pit_status: str = PITStatus.PIT_UNKNOWN
    version: str = "1.0"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "data_type": self.data_type,
            "table": self.table,
            "record_scope": self.record_scope,
            "observation_time_field": self.observation_time_field,
            "effective_time_field": self.effective_time_field,
            "available_time_field": self.available_time_field,
            "source": self.source,
            "current_enforcement": self.current_enforcement,
            "pit_status": self.pit_status,
            "version": self.version,
            "notes": self.notes,
        }


# Default registry based on D7-A audit findings
DEFAULT_DATASETS = [
    DataAsofMetadata(
        dataset_id="daily_klines",
        data_type="daily_market_data",
        table="klines",
        observation_time_field="date",
        effective_time_field=None,
        available_time_field=None,
        source="EastMoney/eastmoney_api",
        current_enforcement="NONE",
        pit_status=PITStatus.PIT_UNSAFE,
        notes="No available_time; market close assumed but not tagged.",
    ),
    DataAsofMetadata(
        dataset_id="financial_data",
        data_type="financial_data",
        table="financial_data",
        observation_time_field="report_date",
        effective_time_field=None,
        available_time_field="fetched_at",
        source="EastMoney",
        current_enforcement="NONE",
        pit_status=PITStatus.PIT_UNSAFE,
        notes="fetched_at exists but not enforced as data cutoff.",
    ),
    DataAsofMetadata(
        dataset_id="fund_flow",
        data_type="fund_flow",
        table="main_fund_flow",
        observation_time_field="date",
        effective_time_field=None,
        available_time_field=None,
        source="EastMoney",
        current_enforcement="NONE",
        pit_status=PITStatus.PIT_UNSAFE,
        notes="No available_time; recent data only (2026-07+).",
    ),
    DataAsofMetadata(
        dataset_id="sector_industry",
        data_type="sector_industry",
        table=None,
        observation_time_field=None,
        effective_time_field=None,
        available_time_field=None,
        source="Unknown",
        current_enforcement="NONE",
        pit_status=PITStatus.PIT_UNKNOWN,
        notes="No sector/industry as-of metadata found.",
    ),
    DataAsofMetadata(
        dataset_id="news",
        data_type="news",
        table="news_cache",
        observation_time_field="news_time",
        effective_time_field=None,
        available_time_field="fetched_at",
        source="news_sources",
        current_enforcement="NONE",
        pit_status=PITStatus.PIT_UNSAFE,
        notes="fetched_at exists but not enforced; news_cache empty in audit.",
    ),
    DataAsofMetadata(
        dataset_id="policy_event",
        data_type="policy_event",
        table=None,
        observation_time_field=None,
        effective_time_field=None,
        available_time_field=None,
        source="Unknown",
        current_enforcement="NONE",
        pit_status=PITStatus.PIT_UNKNOWN,
        notes="No policy/event store found.",
    ),
    DataAsofMetadata(
        dataset_id="global_market",
        data_type="global_market",
        table=None,
        observation_time_field=None,
        effective_time_field=None,
        available_time_field=None,
        source="Unknown",
        current_enforcement="NONE",
        pit_status=PITStatus.PIT_UNKNOWN,
        notes="No global market data found.",
    ),
    DataAsofMetadata(
        dataset_id="macro",
        data_type="macro",
        table=None,
        observation_time_field=None,
        effective_time_field=None,
        available_time_field=None,
        source="Unknown",
        current_enforcement="NONE",
        pit_status=PITStatus.PIT_UNKNOWN,
        notes="No macro data store found.",
    ),
]
