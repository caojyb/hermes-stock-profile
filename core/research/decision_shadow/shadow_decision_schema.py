#!/usr/bin/env python3
"""
shadow_decision_schema.py — Shadow Decision Intelligence Schema
=================================================================
Defines the frozen contracts for the Shadow Decision Assembly.
All objects are research-only and must not produce BUY/SELL/ADD/REDUCE/EXIT/POSITION_SIZE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


# =====================================================================
# Market Context Snapshot (minimal, for shadow decision)
# =====================================================================
class RegimeSnapshot(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"
    RISK_ON = "RISK_ON"
    NORMAL = "NORMAL"
    RISK_OFF = "RISK_OFF"
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MarketContextSnapshot:
    context_id: str
    decision_time: str
    data_cutoff: str
    structural_state: str
    intermediate_state: str
    tactical_state: str
    risk_state: str
    confidence: str
    context_version: str
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Strategy Eligibility
# =====================================================================
class StrategyEligibilityStatus(str, Enum):
    ACTIVE_FOR_SHADOW = "ACTIVE_FOR_SHADOW"
    INCOMPATIBLE = "INCOMPATIBLE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class StrategyEligibilityAssessment:
    strategy_id: str
    strategy_version: str
    status: str
    qualification_status: str
    research_only: bool
    reason_codes: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Tradability
# =====================================================================
class TradabilityStatus(str, Enum):
    TRADABLE = "TRADABLE"
    UNTRADABLE = "UNTRADABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TradabilityAssessment:
    stock_code: str
    decision_time: str
    tradability: str
    tradability_score: str
    confidence: str
    reason_codes: List[str] = field(default_factory=list)
    checks: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Entry Timing
# =====================================================================
class EntryTimingState(str, Enum):
    NOW = "NOW"
    WAIT = "WAIT"
    STAGED_ENTRY = "STAGED_ENTRY"
    NO_ENTRY = "NO_ENTRY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EntryTimingAssessment:
    stock_code: str
    decision_time: str
    entry_timing_state: str
    timing_score: Optional[float]
    confidence: str
    reason_codes: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Risk Assessment
# =====================================================================
class RiskState(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RiskAssessment:
    stock_code: str
    decision_time: str
    market_risk: str
    stock_risk: str
    sector_risk: str
    volatility_risk: str
    liquidity_risk: str
    event_risk: str
    portfolio_risk: str
    risk_score: Optional[float]
    risk_state: str
    risk_penalty: Optional[float]
    reason_codes: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Portfolio Constraints
# =====================================================================
@dataclass(frozen=True)
class PortfolioConstraints:
    decision_time: str
    max_position: Optional[float]
    max_sector_count: Optional[int]
    current_sector_exposure: Dict[str, int]
    cash_available: Optional[float]
    total_asset: Optional[float]
    current_position_count: int
    current_position_pct: Optional[float]
    drawdown: Optional[float]
    drawdown_status: str
    position_size_status: str
    allowed_position_range: Optional[List[float]]
    reason_codes: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Position Sizing
# =====================================================================
@dataclass(frozen=True)
class PositionSizingAssessment:
    stock_code: str
    decision_time: str
    recommended_position_range: Optional[List[float]]
    allowed_position_range: Optional[List[float]]
    sizing_score: Optional[float]
    confidence: str
    reason_codes: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Exit Assessment
# =====================================================================
class ExitTrigger(str, Enum):
    THESIS_INVALIDATION = "THESIS_INVALIDATION"
    OPPORTUNITY_DETERIORATION = "OPPORTUNITY_DETERIORATION"
    STRATEGY_DETERIORATION = "STRATEGY_DETERIORATION"
    RISK_ESCALATION = "RISK_ESCALATION"
    TRADING_STATUS_PROBLEM = "TRADING_STATUS_PROBLEM"
    PORTFOLIO_CONSTRAINT = "PORTFOLIO_CONSTRAINT"
    HORIZON_EXPIRATION = "HORIZON_EXPIRATION"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExitAssessment:
    stock_code: str
    decision_time: str
    exit_signal: str
    exit_triggers: List[str]
    exit_confidence: str
    invalidation_conditions: List[str]
    reason_codes: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Shadow Decision
# =====================================================================
class ShadowAction(str, Enum):
    BUY = "BUY"
    ADD = "ADD"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class ShadowDecision:
    decision_id: str
    decision_time: str
    stock_code: str
    action: str

    market_context: MarketContextSnapshot
    strategy_assessment: List[StrategyEligibilityAssessment]
    opportunity: Optional[Dict[str, Any]]
    tradability: Optional[TradabilityAssessment]
    entry_timing: Optional[EntryTimingAssessment]
    risk: Optional[RiskAssessment]
    trading_permission: Optional[Dict[str, Any]]
    portfolio_constraints: Optional[PortfolioConstraints]
    position_sizing: Optional[PositionSizingAssessment]
    current_position: Optional[Dict[str, Any]]

    decision_confidence: str
    research_only: bool
    production_eligible: bool
    reason_codes: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)
    explanation: Dict[str, str] = field(default_factory=dict)
    exit_conditions: Optional[ExitAssessment] = None
    provenance: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# Shadow Dataset Record (serializable for research storage)
# =====================================================================
@dataclass(frozen=True)
class ShadowDecisionRecord:
    stock_code: str
    decision_time: str
    action: str
    opportunity_score: Optional[float]
    timing_score: Optional[float]
    risk_score: Optional[float]
    permission: Optional[str]
    tradability: Optional[str]
    position_range: Optional[List[float]]
    research_only: bool
    reason_codes: List[str]
    provenance: Dict[str, Any]


# =====================================================================
# Coverage Matrix
# =====================================================================
@dataclass(frozen=True)
class DecisionCoverageMatrix:
    decision_time: str
    stock_code: str
    market_context_available: bool
    strategy_signal_available: bool
    opportunity_available: bool
    tradability_available: bool
    timing_available: bool
    risk_available: bool
    portfolio_truth_available: bool
    position_sizing_available: bool
    final_action_available: bool
    coverage_pct: float
    missing_components: List[str]
