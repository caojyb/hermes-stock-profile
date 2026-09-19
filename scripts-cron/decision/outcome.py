#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decision Outcome & Learning Foundation（Phase 6）
=================================================
统一 Outcome Contract：Decision → Execution → Position → Exit → Outcome 数据闭环。

原则（Observe first, learn later）：
- Outcome 只记录事实，不自动修改策略
- planned 与 actual 严格分离（评估 Decision 是否正确 vs Execution 是否偏离）
- 历史数据不足 → UNKNOWN/LEGACY/PARTIAL，不伪造
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from uuid import uuid4
from datetime import datetime, timezone

# ═══ 生命周期状态 ═══
DECIDED = 'DECIDED'        # 已决策（未执行/未知执行）
EXECUTED = 'EXECUTED'      # 已执行（未平仓）
OPEN = 'OPEN'              # 持仓中
CLOSED = 'CLOSED'          # 已平仓
CANCELLED = 'CANCELLED'    # 已取消
UNKNOWN = 'UNKNOWN'        # 状态未知
OUTCOME_STATUS = (DECIDED, EXECUTED, OPEN, CLOSED, CANCELLED, UNKNOWN)

# ═══ 统一 Exit Reason（映射现有退出语义，不修改）═══
STOP_LOSS = 'STOP_LOSS'
TAKE_PROFIT = 'TAKE_PROFIT'
TRAILING_STOP = 'TRAILING_STOP'
MA20_EXIT = 'MA20_EXIT'
PORTFOLIO_RISK = 'PORTFOLIO_RISK'
MANUAL_EXIT = 'MANUAL_EXIT'
FORCED_EXIT = 'FORCED_EXIT'
OTHER = 'OTHER'
EXIT_REASONS = (STOP_LOSS, TAKE_PROFIT, TRAILING_STOP, MA20_EXIT,
                PORTFOLIO_RISK, MANUAL_EXIT, FORCED_EXIT, OTHER, UNKNOWN)

# ═══ Outcome 来源（Integrity：decision_id 关联性）═══
SOURCE_DECISION = 'DECISION'   # 有关联 decision_id
SOURCE_LEGACY = 'LEGACY'       # 无 decision_id（历史交易）
SOURCE_SHADOW = 'SHADOW'       # Shadow 策略（主升浪）
SOURCE_UNKNOWN = 'UNKNOWN'

# ═══ Counterfactual 时间窗口 ═══
CF_WINDOWS = (5, 10, 20, 40, 60)


def gen_outcome_id():
    return f"out_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


@dataclass
class Planned:
    """计划（Decision 层）：系统认为应该怎样。"""
    entry_price: float = 0.0
    target_position: float = 0.0
    position_size: float = 0.0
    stop_loss: float = 0.0
    take_profit: list = field(default_factory=list)
    exit_signal: str = ''

    def __bool__(self):
        return bool(self.entry_price or self.target_position or self.position_size)


@dataclass
class Actual:
    """实际（Execution 层）：真实发生了什么。"""
    entry_price: float = 0.0
    position_size: float = 0.0
    exit_price: float = 0.0
    realized_pnl: float = 0.0
    return_pct: float = 0.0
    # Phase 6.8：Position Quantity / Cost Basis Integrity
    initial_quantity: float = 0.0
    added_quantity: float = 0.0
    total_entry_quantity: float = 0.0
    average_entry_price: float = 0.0
    total_exit_quantity: float = 0.0
    weighted_exit_price: float = 0.0
    final_quantity: float = 0.0


@dataclass
class Excursion:
    """持仓期间波动（MAE/MFE）。数据不足 → UNKNOWN。"""
    mae: float = 0.0     # 最大不利波动（%）<=0
    mfe: float = 0.0     # 最大有利波动（%）>=0
    max_drawdown: float = 0.0
    max_profit: float = 0.0
    status: str = UNKNOWN  # OK / UNKNOWN / PARTIAL


@dataclass
class Counterfactual:
    """NO_TRADE 反事实（最小结构，非真实交易）。"""
    eligible: bool = False
    horizon: int = 0          # 交易日窗口
    hypothetical_entry_price: float = 0.0
    hypothetical_position: float = 0.0
    hypothetical_return: float = 0.0
    hypothetical_mae: float = 0.0
    hypothetical_mfe: float = 0.0
    status: str = UNKNOWN     # COMPUTED / UNKNOWN / NOT_ELIGIBLE


@dataclass
class Outcome:
    """统一 Outcome 对象（不可变，可追溯）。"""
    # 标识
    outcome_id: str = ''
    decision_id: str = ''          # 空 = LEGACY/UNKNOWN（不伪造）
    symbol: str = ''
    name: str = ''
    action: str = ''               # BUY/ADD/HOLD/REDUCE/SELL/NO_TRADE
    strategy: str = ''
    strategy_version: str = ''
    outcome_source: str = SOURCE_LEGACY  # DECISION/LEGACY/SHADOW/UNKNOWN/TEST/SIMULATION
    execution_source: str = ''     # Phase 7.1: 实际 execution source（SIMULATION/MANUAL_CONFIRMATION/PRODUCTION）
    data_quality: str = ''         # Phase 7.1: VALID/DEGRADED/UNKNOWN/TEST/SIMULATION

    # 时间
    decision_time: str = ''        # Phase 7.1: decision 生成时间
    execution_time: str = ''       # 无真实成交时间 → UNKNOWN（不用 decision 冒充）
    exit_time: str = ''
    as_of_time: str = ''
    holding_period_days: int = 0   # Phase 7.1: 0 = UNKNOWN（不要用 0 伪装有效数据）

    # planned vs actual
    planned: Planned = field(default_factory=Planned)
    actual: Actual = field(default_factory=Actual)

    # lifecycle
    lifecycle_status: str = UNKNOWN   # DECIDED/EXECUTED/OPEN/CLOSED/CANCELLED/UNKNOWN
    exit_reason: str = UNKNOWN
    exit_triggers: list = field(default_factory=list)

    # excursion
    excursion: Excursion = field(default_factory=Excursion)
    # Phase 7.2: MAE/MFE from actual entry→exit K-line excursion
    mae: float = 0.0
    mfe: float = 0.0
    mae_mfe_status: str = UNKNOWN  # COMPUTED / UNKNOWN / PARTIAL

    # market
    entry_regime: str = ''         # Phase 7.1: 决策时的 Regime
    exit_regime: str = ''          # Phase 7.1: 退出时的 Regime

    # portfolio provenance
    portfolio_snapshot_id: str = ''
    position_id: str = ''           # Phase 6.7：对应 entry execution 的 position_id

    # Phase 7.1: Evaluation Metadata（从 Decision 传递）
    candidate_score: float = 0.0   # Phase 7.1: 候选评分（缺失 = 0.0 + MISSING 标记）
    candidate_rank: int = 0        # Phase 7.1: 候选排名
    candidate_reason_codes: list = field(default_factory=list)  # Phase 7.1
    permission_status: str = ''    # Phase 7.1: ALLOW/REDUCE/NO_NEW_ENTRY/EXIT_ONLY
    permission: dict = field(default_factory=dict)  # Phase 7.1
    portfolio_assessment: dict = field(default_factory=dict)  # Phase 7.1
    portfolio_drawdown: float = 0.0  # Phase 7.1
    portfolio_risk_flags: list = field(default_factory=list)  # Phase 7.1
    slippage_price: float = 0.0    # Phase 7.1: 执行滑点
    slippage_quantity: float = 0.0  # Phase 7.1
    execution_delay_seconds: int = 0  # Phase 7.1

    # provenance
    decision_snapshot_id: str = ''
    config_version: str = ''
    code_version: str = ''

    # counterfactual（仅 NO_TRADE）
    counterfactual: Counterfactual = field(default_factory=Counterfactual)

    # quality（Decision vs Execution 分离）
    decision_quality: str = UNKNOWN   # GOOD/BAD/NEUTRAL/UNKNOWN（评估维度见文档）
    execution_quality: str = UNKNOWN  # GOOD/BAD/NEUTRAL/UNKNOWN

    # Baseline Decision Attribution Contract v1（区分经济贡献层）
    attribution: dict = field(default_factory=dict)  # {market, opportunity, evidence, timing, sizing, portfolio, execution}
    attribution_version: str = 'attribution_v1'

    def freeze(self) -> dict:
        return asdict(self)


def map_exit_reason(triggers):
    """把现有退出语义（STOP_LOSS/TRAILING_STOP/MA20_BREAK...及 legacy 中文 status）映射到统一 Exit Reason。
    不修改任何退出参数/语义。"""
    t = [str(x).upper() for x in (triggers or [])]
    joined = ' '.join(t)
    if not t:
        return UNKNOWN
    # legacy 中文 status 映射
    if '止损' in joined or 'STOP_LOSS' in t:
        return STOP_LOSS
    if '止盈' in joined or 'TAKE_PROFIT' in t or '部分止盈' in joined:
        return TAKE_PROFIT
    if 'TRAILING_STOP' in t or '移动止盈' in joined:
        return TRAILING_STOP
    if 'MA20_BREAK' in t or 'MA20_EXIT' in t or 'MA20' in joined:
        return MA20_EXIT
    if 'PORTFOLIO_RISK' in t or 'DRAWDOWN' in t or 'PORTFOLIO' in joined:
        return PORTFOLIO_RISK
    if 'FORCED' in t:
        return FORCED_EXIT
    if 'MANUAL' in t or '人工' in joined:
        return MANUAL_EXIT
    return OTHER


def build_attribution(decision: dict, execution: dict, outcome: dict) -> dict:
    """Baseline Decision Attribution Contract v1：区分经济贡献层（不重算，只归因）。"""
    entry_regime = (decision.get('market_regime') or decision.get('regime_label') or '').upper()
    exit_regime = ''
    if outcome:
        exit_regime = (outcome.get('exit_regime') or '').upper()
    if not exit_regime:
        exit_regime = entry_regime
    candidate_score = float(decision.get('candidate_score') or 0)
    candidate_rank = int(decision.get('candidate_rank') or 0)
    perm = decision.get('permission') or {}
    perm_status = (decision.get('permission_status') or '').upper()
    portfolio_assessment = decision.get('portfolio_assessment') or {}
    pa_action = (portfolio_assessment.get('action') or '').upper()
    risk_flags = [str(x).upper() for x in (decision.get('risk_flags') or [])]
    actual = (execution.get('actual') or {}) if execution else {}
    planned = (execution.get('planned') or {}) if execution else {}
    actual_price = float(actual.get('price') or 0)
    planned_price = float(planned.get('price') or 0)
    slippage_price = round(actual_price - planned_price, 4) if actual_price and planned_price else 0.0
    ret = 0.0
    if outcome and outcome.get('actual', {}).get('return_pct'):
        ret = float(outcome['actual']['return_pct'])
    attribution = {
        'market': {
            'entry_regime': entry_regime,
            'exit_regime': exit_regime,
            'regime_changed': entry_regime != exit_regime,
        },
        'opportunity': {
            'candidate_score': candidate_score,
            'candidate_rank': candidate_rank,
            'qualified': bool(decision.get('candidate_qualified')),
        },
        'evidence': {
            'has_evidence': bool(decision.get('evidence_refs') or decision.get('reason_codes')),
            'reason_codes_count': len(decision.get('reason_codes') or []),
        },
        'timing': {
            'entry_signal': decision.get('entry_signal') or '',
            'entry_signals': list(decision.get('entry_signals') or []),
        },
        'sizing': {
            'target_position': float(decision.get('target_position') or 0),
            'reference_price': planned_price,
            'actual_price': actual_price,
            'slippage_price': slippage_price,
        },
        'portfolio': {
            'action': pa_action,
            'drawdown': float(decision.get('portfolio_drawdown') or 0),
            'risk_flags': risk_flags,
            'permission_status': perm_status,
            'new_entry': (perm.get('new_entry') or '').upper(),
        },
        'execution': {
            'status': (execution.get('status') or '') if execution else '',
            'source': (execution.get('source') or '') if execution else '',
            'run_mode': (execution.get('run_mode') or '') if execution else '',
            'linkage': (execution.get('linkage') or '') if execution else '',
        },
        'outcome': {
            'return_pct': ret,
            'exit_reason': outcome.get('exit_reason') if outcome else '',
            'holding_period_days': int(outcome.get('holding_period_days') or 0) if outcome else 0,
        },
        'version': 'attribution_v1',
    }
    return attribution
