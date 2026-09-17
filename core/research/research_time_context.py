#!/usr/bin/env python3
"""
stock-work/core/research/research_time_context.py

Unified research temporal context. All research/backtest data access must go through
this context to enforce available_time <= decision_time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ResearchTimeContext:
    """Temporal boundary for a research run."""
    decision_time: str  # ISO date 'YYYY-MM-DD'
    data_cutoff: str    # max available_time allowed
    universe_snapshot_id: Optional[str] = None
    allowed_information_time: Optional[str] = None
    dataset_version: Optional[str] = None
    feature_version: Optional[str] = None
    run_id: Optional[str] = None

    def validate_available_time(self, available_time: Optional[str]) -> bool:
        if available_time is None:
            raise PITViolationError(
                f"PIT_UNKNOWN: available_time not provided; decision_time={self.decision_time}"
            )
        if available_time > self.decision_time:
            raise PITViolationError(
                f"PIT_UNSAFE: available_time {available_time} > decision_time {self.decision_time}"
            )
        return True

    def is_data_allowed(self, available_time: Optional[str]) -> bool:
        try:
            self.validate_available_time(available_time)
            return True
        except PITViolationError:
            return False


class PITViolationError(Exception):
    """Raised when data violates PIT constraints."""
    pass


class PITStatus(str):
    PIT_SAFE = "PIT_SAFE"
    PIT_CONDITIONAL = "PIT_CONDITIONAL"
    PIT_UNSAFE = "PIT_UNSAFE"
    PIT_UNKNOWN = "PIT_UNKNOWN"
