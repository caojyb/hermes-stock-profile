#!/usr/bin/env python3
"""
stock-work/core/research/opportunity/opportunity_schema.py

Opportunity Contract schema definitions.

This module defines the typed contract for research-only opportunity objects.
It does not perform data access or DB queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Eligibility(str, Enum):
    RESEARCH_OPPORTUNITY = "RESEARCH_OPPORTUNITY"
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    WATCH = "WATCH"
    REJECT = "REJECT"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OpportunityScoreComponents:
    historical_evidence: Optional[float] = None
    context_compatibility: Optional[float] = None
    signal_strength: Optional[float] = None
    signal_confidence: Optional[float] = None
    risk_penalty: Optional[float] = None
    data_quality: Optional[float] = None
    correlation_penalty: Optional[float] = None
    notes: str = ""


@dataclass(frozen=True)
class StrategySignalSummary:
    strategy_id: str
    strategy_version: str
    family: str
    horizon: int
    raw_score: Optional[float]
    normalized_score: Optional[float]
    confidence: str
    eligibility: str
    reason_code: str
    research_only: bool
    signal_timestamp: str


@dataclass(frozen=True)
class StrategyEvidenceSummary:
    strategy_id: str
    qualification_status: str
    evidence_strength: str
    cross_fold_ic_mean: Optional[float]
    positive_fold_ratio: Optional[float]
    rank_ic_mean: Optional[float]
    mean_excess_return: Optional[float]
    hit_rate: Optional[float]
    sample_count: int
    confidence: str
    notes: str = ""


@dataclass(frozen=True)
class Opportunity:
    """
    Research-only opportunity record.

    Outputs only OPPORTUNITY / CANDIDATE / WATCH / REJECT.
    Never outputs BUY / SELL / ADD / REDUCE / EXIT / POSITION_SIZE.
    """
    stock_code: str
    decision_time: str
    market_context_id: str
    strategy_ids: List[str]
    strategy_versions: Dict[str, str]
    strategy_signal_summary: List[StrategySignalSummary]
    strategy_evidence_summary: List[StrategyEvidenceSummary]
    context_compatibility: str
    signal_strength: Optional[float]
    signal_confidence: str
    risk_penalty: Optional[float]
    data_quality: str
    opportunity_score: Optional[float]
    rank: Optional[int]
    eligibility: Eligibility
    reason_codes: List[str]
    score_components: OpportunityScoreComponents
    provenance: Dict[str, str] = field(default_factory=dict)
    research_only: bool = True
    notes: str = ""


@dataclass(frozen=True)
class OpportunityRun:
    run_id: str
    decision_time: str
    dataset_version: str
    universe_version: str
    context_version: str
    strategy_versions: Dict[str, str]
    normalization_version: str
    opportunity_version: str
    created_at: str
    config: Dict[str, Optional[str]] = field(default_factory=dict)
