#!/usr/bin/env python3
"""
strategy_family_expansion.py — Strategy Family Expansion Registry
===================================================================
Registers strategy families, variants, hypotheses, and lineage for
D7-C4-B Price/Volume Strategy Family Expansion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime

from .experiment_governance import ExperimentRegistry, ExperimentRecord, ExperimentFamily
from .experiment_governance import (
    EXPERIMENT_STATUS_REGISTERED,
    EXPERIMENT_STATUS_NO_EVIDENCE,
    SELECTION_EVENT_NONE,
)


# ---------------------------------------------------------------- Family Definitions
FAMILY_TREND = "Trend"
FAMILY_MOMENTUM = "Momentum"
FAMILY_REVERSAL = "Reversal"
FAMILY_BREAKOUT = "Breakout"
FAMILY_VOLATILITY = "Volatility"
FAMILY_PRICE_VOLUME = "PriceVolume"


@dataclass(frozen=True)
class StrategyFamilyDefinition:
    family_id: str
    family_name: str
    hypothesis: str
    economic_rationale: str
    required_features: List[str]
    required_datasets: List[str]
    target_id: str
    target_version: str
    universe_version: str
    fold_policy: str
    evaluation_metrics: List[str]
    status: str = "ACTIVE"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    notes: str = ""


# ---------------------------------------------------------------- Expansion Registry
class StrategyFamilyExpansionRegistry:
    """
    Manages strategy family definitions and variant lineage for C4-B.
    """

    def __init__(self, experiment_registry: Optional[ExperimentRegistry] = None):
        self._families: Dict[str, StrategyFamilyDefinition] = {}
        self._experiment_registry = experiment_registry or ExperimentRegistry()

    def register_family(self, family: StrategyFamilyDefinition) -> None:
        self._families[family.family_id] = family
        exp_family = ExperimentFamily(
            experiment_family_id=family.family_id,
            family_name=family.family_name,
            hypothesis=family.hypothesis,
            strategy_family=family.family_name,
            notes=family.notes,
        )
        self._experiment_registry.register_family(exp_family)

    def get_family(self, family_id: str) -> Optional[StrategyFamilyDefinition]:
        return self._families.get(family_id)

    def list_families(self) -> List[StrategyFamilyDefinition]:
        return list(self._families.values())

    def register_variant_experiment(self, record: ExperimentRecord) -> None:
        self._experiment_registry.register_experiment(record)

    def get_experiment_registry(self) -> ExperimentRegistry:
        return self._experiment_registry

    def summary(self) -> Dict[str, Any]:
        registry_summary = self._experiment_registry.summary()
        return {
            "total_families": len(self._families),
            "family_ids": list(self._families.keys()),
            **registry_summary,
        }


# ---------------------------------------------------------------- Default C4-B Families
DEFAULT_FAMILIES: List[StrategyFamilyDefinition] = [
    StrategyFamilyDefinition(
        family_id="TREND_FAMILY_001",
        family_name=FAMILY_TREND,
        hypothesis="Medium-term price trend predicts future 5D/10D/20D universe-relative excess return.",
        economic_rationale="Trend following captures persistence in cross-sectional returns.",
        required_features=["daily_price"],
        required_datasets=["daily_price"],
        target_id="future_excess_return",
        target_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        fold_policy="anchored_expanding",
        evaluation_metrics=["IC", "RankIC", "MeanExcessReturn", "HitRate"],
        notes="Legacy baseline retained from C1.",
    ),
    StrategyFamilyDefinition(
        family_id="MOMENTUM_FAMILY_001",
        family_name=FAMILY_MOMENTUM,
        hypothesis="Cross-sectional historical return strength predicts future universe-relative excess return.",
        economic_rationale="Momentum captures continuation in relative performance across stocks.",
        required_features=["daily_price"],
        required_datasets=["daily_price"],
        target_id="future_excess_return",
        target_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        fold_policy="anchored_expanding",
        evaluation_metrics=["IC", "RankIC", "MeanExcessReturn", "HitRate"],
        notes="Medium-term and risk-adjusted variants added in C4-B.",
    ),
    StrategyFamilyDefinition(
        family_id="REVERSAL_FAMILY_001",
        family_name=FAMILY_REVERSAL,
        hypothesis="Short-term price reversal predicts future universe-relative excess return.",
        economic_rationale="Reversal captures short-term overreaction / mean reversion.",
        required_features=["daily_price"],
        required_datasets=["daily_price"],
        target_id="future_excess_return",
        target_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        fold_policy="anchored_expanding",
        evaluation_metrics=["IC", "RankIC", "MeanExcessReturn", "HitRate"],
        notes="Legacy baseline retained from C1.",
    ),
    StrategyFamilyDefinition(
        family_id="BREAKOUT_FAMILY_001",
        family_name=FAMILY_BREAKOUT,
        hypothesis="Recent breakout from historical price range predicts future universe-relative excess return.",
        economic_rationale="Breakout reflects supply/demand imbalance and new information assimilation.",
        required_features=["daily_price"],
        required_datasets=["daily_price"],
        target_id="future_excess_return",
        target_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        fold_policy="anchored_expanding",
        evaluation_metrics=["IC", "RankIC", "MeanExcessReturn", "HitRate"],
        notes="Strength and confirmation variants added in C4-B.",
    ),
    StrategyFamilyDefinition(
        family_id="VOLATILITY_FAMILY_001",
        family_name=FAMILY_VOLATILITY,
        hypothesis="Historical volatility and volatility change predict future universe-relative excess return.",
        economic_rationale="Volatility may reflect information uncertainty, risk premium, or investor sentiment.",
        required_features=["daily_price"],
        required_datasets=["daily_price"],
        target_id="future_excess_return",
        target_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        fold_policy="anchored_expanding",
        evaluation_metrics=["IC", "RankIC", "MeanExcessReturn", "HitRate"],
        notes="Does not assume low volatility = better stock; hypothesis is empirical.",
    ),
    StrategyFamilyDefinition(
        family_id="PRICE_VOLUME_FAMILY_001",
        family_name=FAMILY_PRICE_VOLUME,
        hypothesis="Price-volume interaction predicts future universe-relative excess return.",
        economic_rationale="Volume confirms or contradicts price movement; abnormal volume may signal informed trading.",
        required_features=["daily_price", "daily_volume"],
        required_datasets=["daily_price", "daily_volume"],
        target_id="future_excess_return",
        target_version="v1",
        universe_version="RESEARCH_UNIVERSE_V1",
        fold_policy="anchored_expanding",
        evaluation_metrics=["IC", "RankIC", "MeanExcessReturn", "HitRate"],
        notes="Volume trend and volume-price correlation variants added in C4-B.",
    ),
]


def create_default_expansion_registry() -> StrategyFamilyExpansionRegistry:
    registry = StrategyFamilyExpansionRegistry()
    for family in DEFAULT_FAMILIES:
        registry.register_family(family)
    return registry
