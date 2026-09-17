#!/usr/bin/env python3
"""
stock-work/core/research/opportunity/opportunity_ranker.py

Ranking and filtering for research opportunities.

This module is intentionally separated from engine to keep ranking logic
independent from score computation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from core.research.opportunity.opportunity_engine import OpportunityEngineConfig
from core.research.opportunity.opportunity_schema import Eligibility, Opportunity


class OpportunityRanker:
    def __init__(self, config: Optional[OpportunityEngineConfig] = None) -> None:
        self.config = config or OpportunityEngineConfig()

    def rank(self, opportunities: List[Opportunity], top_n: Optional[int] = None) -> List[Opportunity]:
        top_n = top_n or self.config.top_n
        eligibility_order = {
            Eligibility.RESEARCH_OPPORTUNITY: 0,
            Eligibility.RESEARCH_CANDIDATE: 1,
            Eligibility.WATCH: 2,
            Eligibility.REJECT: 3,
            Eligibility.UNKNOWN: 4,
        }

        def sort_key(o: Opportunity):
            score = o.opportunity_score if o.opportunity_score is not None else -1.0
            return (
                eligibility_order.get(o.eligibility, 5),
                -score,
                o.stock_code,
            )

        ranked = sorted(opportunities, key=sort_key)[:top_n]
        return ranked

    def filter_by_eligibility(self, opportunities: List[Opportunity], allowed: List[Eligibility]) -> List[Opportunity]:
        return [o for o in opportunities if o.eligibility in allowed]

    def filter_research_only(self, opportunities: List[Opportunity]) -> List[Opportunity]:
        return [o for o in opportunities if o.research_only is True]

    def to_matrix(self, opportunities: List[Opportunity]) -> Dict[str, Dict[str, Optional[float]]]:
        matrix: Dict[str, Dict[str, Optional[float]]] = {}
        for o in opportunities:
            matrix.setdefault(o.stock_code, {})["opportunity_score"] = o.opportunity_score
            matrix[o.stock_code]["eligibility"] = o.eligibility.value
            matrix[o.stock_code]["rank"] = o.rank
        return matrix
