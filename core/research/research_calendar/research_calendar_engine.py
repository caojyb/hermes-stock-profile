#!/usr/bin/env python3
"""Minimal reusable Research Calendar Engine for alpha source research."""

from __future__ import annotations

from typing import List, Dict, Set, Optional


class ResearchCalendarEngine:
    """Source-independent calendar engine for alpha source research."""

    def __init__(self, global_calendar: List[str]):
        self.global_calendar: Set[str] = set(global_calendar)
        self.source_calendars: Dict[str, Dict] = {}

    def register_source_calendar(self, source_id: str, eligible_dates: List[str],
                                  metadata: Dict) -> None:
        """Register source-specific eligible calendar."""
        self.source_calendars[source_id] = {
            "eligible_dates": set(eligible_dates),
            "metadata": metadata,
        }

    def get_source_eligible_dates(self, source_id: str) -> List[str]:
        """Get eligible dates for a source."""
        if source_id not in self.source_calendars:
            return []
        return sorted(self.source_calendars[source_id]["eligible_dates"])

    def get_intersection_dates(self, source_ids: List[str]) -> List[str]:
        """Get intersection of eligible dates across sources."""
        if not source_ids:
            return sorted(self.global_calendar)

        eligible_sets = []
        for sid in source_ids:
            if sid in self.source_calendars:
                eligible_sets.append(self.source_calendars[sid]["eligible_dates"])
            elif sid == "GLOBAL":
                eligible_sets.append(self.global_calendar)
            else:
                return []

        intersection = set.intersection(*eligible_sets)
        return sorted(intersection)

    def explain_date_exclusion(self, source_id: str, date: str) -> Optional[str]:
        """Explain why a date is excluded for a source."""
        if source_id in self.source_calendars:
            if date in self.source_calendars[source_id]["eligible_dates"]:
                return None
            return f"Date {date} not in {source_id} eligible calendar"
        return f"Source {source_id} not registered"

    def get_global_calendar(self) -> List[str]:
        """Get global market calendar."""
        return sorted(self.global_calendar)
