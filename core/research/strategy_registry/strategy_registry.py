#!/usr/bin/env python3
"""
stock-work/core/research/strategy_registry/strategy_registry.py

Strategy metadata registry for research-only compatibility analysis.

Important:
- This registry does not change strategy behavior.
- It does not change strategy parameters.
- It does not enable automatic switching or weighting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional

from core.research.market_context.context_schema import (
    IntermediateState,
    LiquidityState,
    MacroState,
    RiskState,
    StructuralState,
    TacticalState,
    VolatilityState,
)


@dataclass(frozen=True)
class StrategyProfile:
    strategy_id: str
    family: str
    required_features: FrozenSet[str]
    preferred_regime: Dict[str, str]
    forbidden_regime: Dict[str, str]
    risk_profile: str
    capacity_profile: str
    evidence_status: str
    description: str = ""


class StrategyRegistry:
    """
    Read-only registry for research strategy context analysis.

    The registry describes expected regime fit, not live performance.
    """

    def __init__(self) -> None:
        self._profiles: Dict[str, StrategyProfile] = {}

    def register(self, profile: StrategyProfile) -> None:
        self._profiles[profile.strategy_id] = profile

    def get(self, strategy_id: str) -> Optional[StrategyProfile]:
        return self._profiles.get(strategy_id)

    def all_profiles(self) -> List[StrategyProfile]:
        return list(self._profiles.values())


def build_default_registry() -> StrategyRegistry:
    registry = StrategyRegistry()

    registry.register(
        StrategyProfile(
            strategy_id="trend_v1",
            family="Trend",
            required_features=frozenset({"daily_price"}),
            preferred_regime={
                "structural": StructuralState.BULL.value,
                "intermediate": IntermediateState.RISK_ON.value,
            },
            forbidden_regime={
                "risk_state": RiskState.HIGH.value,
            },
            risk_profile="MEDIUM",
            capacity_profile="HIGH",
            evidence_status="PRELIMINARY_PATTERN",
            description="Trend-following baseline using moving-average relationship.",
        )
    )

    registry.register(
        StrategyProfile(
            strategy_id="momentum_v1",
            family="Momentum",
            required_features=frozenset({"daily_price"}),
            preferred_regime={
                "structural": StructuralState.BULL.value,
                "intermediate": IntermediateState.RISK_ON.value,
                "tactical": TacticalState.MOMENTUM.value,
            },
            forbidden_regime={
                "risk_state": RiskState.HIGH.value,
            },
            risk_profile="MEDIUM",
            capacity_profile="MEDIUM",
            evidence_status="PRELIMINARY_PATTERN",
            description="Simple momentum baseline over fixed lookback.",
        )
    )

    registry.register(
        StrategyProfile(
            strategy_id="reversal_v1",
            family="Reversal",
            required_features=frozenset({"daily_price"}),
            preferred_regime={
                "intermediate": IntermediateState.NORMAL.value,
                "tactical": TacticalState.MEAN_REVERSION.value,
            },
            forbidden_regime={
                "structural": StructuralState.BEAR.value,
                "risk_state": RiskState.HIGH.value,
            },
            risk_profile="MEDIUM",
            capacity_profile="MEDIUM",
            evidence_status="PRELIMINARY_PATTERN",
            description="Mean-reversion baseline.",
        )
    )

    registry.register(
        StrategyProfile(
            strategy_id="breakout_v1",
            family="Breakout",
            required_features=frozenset({"daily_price", "high/low_series"}),
            preferred_regime={
                "structural": StructuralState.BULL.value,
                "intermediate": IntermediateState.RISK_ON.value,
                "tactical": TacticalState.MOMENTUM.value,
            },
            forbidden_regime={
                "liquidity_state": LiquidityState.TIGHT.value,
                "risk_state": RiskState.HIGH.value,
            },
            risk_profile="HIGH",
            capacity_profile="LOW",
            evidence_status="PRELIMINARY_PATTERN",
            description="Breakout strategy dependent on liquidity and volatility expansion.",
        )
    )

    registry.register(
        StrategyProfile(
            strategy_id="volatility_v1",
            family="Volatility",
            required_features=frozenset({"daily_price", "realized_volatility"}),
            preferred_regime={
                "volatility_state": VolatilityState.HIGH.value,
                "risk_state": RiskState.HIGH.value,
            },
            forbidden_regime={
                "liquidity_state": LiquidityState.TIGHT.value,
            },
            risk_profile="HIGH",
            capacity_profile="MEDIUM",
            evidence_status="PRELIMINARY_PATTERN",
            description="Volatility-oriented strategy; best under high-vol but not illiquid regimes.",
        )
    )

    registry.register(
        StrategyProfile(
            strategy_id="pricevolume_v1",
            family="PriceVolume",
            required_features=frozenset({"daily_price", "volume"}),
            preferred_regime={
                "intermediate": IntermediateState.NORMAL.value,
                "tactical": TacticalState.MOMENTUM.value,
                "liquidity_state": LiquidityState.AMPLE.value,
            },
            forbidden_regime={
                "liquidity_state": LiquidityState.TIGHT.value,
                "risk_state": RiskState.HIGH.value,
            },
            risk_profile="MEDIUM",
            capacity_profile="HIGH",
            evidence_status="PRELIMINARY_PATTERN",
            description="Price-volume confirmation strategy.",
        )
    )

    return registry
