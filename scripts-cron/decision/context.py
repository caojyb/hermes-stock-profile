#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evidence Integration Contract（M10-C）
======================================
统一 Evidence 输入边界：所有进入 DecisionEngine 的 Evidence 必须通过
DecisionContext / EvidenceItem，支持 AVAILABLE / UNAVAILABLE / UNKNOWN / STALE。

原则：
- 不新增 Alpha / Strategy / weighting
- 不修改 DecisionEngine 核心语义
- 不重写现有 evidence framework
- 仅建立最小 integration boundary
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# ═══ Availability 枚举（只允许这四个值）═══
class EvidenceAvailability(str, Enum):
    AVAILABLE = 'AVAILABLE'
    UNAVAILABLE = 'UNAVAILABLE'
    UNKNOWN = 'UNKNOWN'
    STALE = 'STALE'


# ═══ EvidenceItem：单条 Evidence 的统一载体 ═══
@dataclass
class EvidenceItem:
    """进入 DecisionContext 的最小 Evidence 单元。"""
    source: str = ''               # 来源名称，如 'opportunity', 'fundamental', 'capital_flow'
    code: str = ''                 # 标的代码
    decision_time: str = ''        # 决策生成时刻
    available_time: str = ''       # 数据可用时刻
    PIT_status: str = ''           # PIT 状态，如 SAFE / APPROXIMATE / BLOCKED / UNKNOWN
    availability: str = EvidenceAvailability.UNKNOWN  # AVAILABLE / UNAVAILABLE / UNKNOWN / STALE
    provenance: Dict[str, Any] = field(default_factory=dict)  # 来源/provider/record_id
    confidence: float = 0.0        # 置信度 [0,1]
    value: Any = None              # 实际值；UNAVAILABLE 时必须为 None
    reason: str = ''               # UNAVAILABLE / UNKNOWN 时的原因

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def is_available(self) -> bool:
        return self.availability == EvidenceAvailability.AVAILABLE


# ═══ DecisionContext：DecisionEngine 的统一输入视图 ═══
@dataclass
class DecisionContext:
    """DecisionEngine 可读取的 Evidence 集合。"""
    decision_time: str = ''
    symbol: str = ''
    name: str = ''
    mode: str = 'entry'            # entry / position
    has_position: bool = False

    # 现有 Assessment（保留原样，不重新发明）
    market_context: Dict[str, Any] = field(default_factory=dict)
    trading_permission: Dict[str, Any] = field(default_factory=dict)
    risk: Dict[str, Any] = field(default_factory=dict)
    portfolio_truth: Dict[str, Any] = field(default_factory=dict)

    # Evidence 层（新增统一边界）
    opportunity: Optional[EvidenceItem] = None
    technical_evidence: Optional[EvidenceItem] = None
    fundamental_evidence: Optional[EvidenceItem] = None
    volume_evidence: Optional[EvidenceItem] = None
    capital_flow_evidence: Optional[EvidenceItem] = None
    news_evidence: Optional[EvidenceItem] = None
    tradability: Optional[EvidenceItem] = None

    # 元数据
    as_of_time: str = ''
    strategy: str = 'v1_double'
    strategy_version: str = ''
    config_version: str = ''
    code_version: str = ''

    def to_engine_ctx(self) -> Dict[str, Any]:
        """转换为 DecisionEngine.decide(ctx) 可接受的 flat dict。"""
        ctx: Dict[str, Any] = {
            'symbol': self.symbol,
            'name': self.name,
            'mode': self.mode,
            'has_position': self.has_position,
            'as_of_time': self.as_of_time,
            'strategy': self.strategy,
            'strategy_version': self.strategy_version,
            'config_version': self.config_version,
            'code_version': self.code_version,
            # market / permission / risk / portfolio
            'regime_label': (self.market_context or {}).get('regime_label', ''),
            'regime_score': (self.market_context or {}).get('regime_score', 0.0),
            'regime_version': (self.market_context or {}).get('regime_version', ''),
            'permission_status': (self.trading_permission or {}).get('status', ''),
            'permission': (self.trading_permission or {}).get('permission', {}),
            'data_health': (self.trading_permission or {}).get('data_health', ''),
            'portfolio_risk': (self.risk or {}).get('status', ''),
            'portfolio_assessment': (self.risk or {}).get('assessment', self.risk or {}),
            'drawdown': (self.portfolio_truth or {}).get('drawdown', 0.0),
            'drawdown_limit': (self.portfolio_truth or {}).get('drawdown_limit', 0.15),
            'position_count': (self.portfolio_truth or {}).get('position_count', 0),
            'current_exposure': (self.portfolio_truth or {}).get('exposure', 0.0),
            'portfolio_snapshot_id': (self.portfolio_truth or {}).get('snapshot_id', ''),
            'portfolio_source': (self.portfolio_truth or {}).get('source', ''),
            'portfolio_as_of_time': (self.portfolio_truth or {}).get('as_of_time', ''),
        }

        # tradability -> data_health 补充（若 permission 未提供）
        if self.tradability and self.tradability.is_available():
            ctx.setdefault('tradability_available', True)
            ctx['tradability'] = self.tradability.to_dict()
        elif self.tradability and not self.tradability.is_available():
            ctx.setdefault('tradability_available', False)
            ctx['tradability'] = self.tradability.to_dict()

        # evidence provenance 挂载，供 Auditor 读取
        ctx['evidence_provenance'] = {
            'opportunity': self.opportunity.to_dict() if self.opportunity else None,
            'technical_evidence': self.technical_evidence.to_dict() if self.technical_evidence else None,
            'fundamental_evidence': self.fundamental_evidence.to_dict() if self.fundamental_evidence else None,
            'volume_evidence': self.volume_evidence.to_dict() if self.volume_evidence else None,
            'capital_flow_evidence': self.capital_flow_evidence.to_dict() if self.capital_flow_evidence else None,
            'news_evidence': self.news_evidence.to_dict() if self.news_evidence else None,
            'tradability': self.tradability.to_dict() if self.tradability else None,
        }
        return ctx
