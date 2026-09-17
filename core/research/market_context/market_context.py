#!/usr/bin/env python3
"""
stock-work/core/research/market_context/market_context.py

Market Context object with validation, audit, and PIT enforcement.

This module is intentionally data-source agnostic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, Optional

from .context_schema import (
    BreadthState,
    ConfidenceLevel,
    LiquidityState,
    MacroState,
    MarketContext as MarketContextModel,
    RiskState,
    SentimentState,
    StructuralState,
    TacticalState,
    TrendState,
    VolatilityState,
)


@dataclass
class MarketContext:
    """
    Runtime wrapper around the typed MarketContext contract.

    Responsibilities:
    - enforce decision_time <= data_cutoff <= now semantics at object level
    - maintain audit provenance
    - expose stable serialization for downstream research consumers
    """

    model: MarketContextModel
    audit_trace: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._enforce_time_order()

    def _enforce_time_order(self) -> None:
        if self.model.decision_time > self.model.data_cutoff:
            raise ValueError(
                f"PIT_UNSAFE: decision_time {self.model.decision_time} > data_cutoff {self.model.data_cutoff}"
            )

    def mark_future_data(self, source: str, field_name: str) -> None:
        """
        Mark a field as future-data tainted.

        This should be called by builders when they detect that a required
        input's available_time is after the decision_time.
        """
        self.audit_trace[f"{field_name}:future_data_source"] = source
        if self.model.confidence != ConfidenceLevel.UNKNOWN:
            self.model.confidence = ConfidenceLevel.LOW

    def mark_missing(self, field_name: str, reason: str) -> None:
        self.audit_trace[f"{field_name}:missing_reason"] = reason
        # Missing required context should not silently keep an old value.
        # Here we do not silently mutate the enum to avoid accidental leakage;
        # builders should explicitly set UNKNOWN before finalizing.

    def provenance_fingerprint(self) -> str:
        payload = (
            f"{self.model.context_id}|{self.model.decision_time}|"
            f"{self.model.data_cutoff}|{self.model.confidence.value}|"
            f"{self.model.structural_state.value}|{self.model.intermediate_state.value}|"
            f"{self.model.tactical_state.value}|{self.model.risk_state.value}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        data = self.model.to_dict()
        data["audit_trace"] = dict(sorted(self.audit_trace.items()))
        data["provenance_fingerprint"] = self.provenance_fingerprint()
        return data

    def is_research_only(self) -> bool:
        return True

    def action_safe(self) -> bool:
        """
        Market Context must never carry trading actions.

        Returning False here is a guardrail: if downstream code accidentally
        treats context as actionable, this flag forces an explicit research-only
        path.
        """
        return False
