#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M10-B P0 regression tests（只读/最小，不改业务逻辑）
"""
from __future__ import annotations

import sys
from pathlib import Path

DECISION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DECISION_DIR))
sys.path.insert(0, str(DECISION_DIR.parent.parent.parent / 'stock-work'))

from decision.outcome_store import build_from_trade, build_open_from_real, compute_mae_mfe
from decision.evidence_framework import (
    build_review_record_from_outcome,
    build_review_record_from_no_trade,
    evaluation_readiness,
    evidence_completeness,
    EvidenceLevel,
)


def test_outcome_store_import():
    assert hasattr(build_from_trade, '__call__')
    assert hasattr(build_open_from_real, '__call__')
    assert hasattr(compute_mae_mfe, '__call__')


def test_outcome_from_trade_legacy():
    trade = {
        'code': '600540', 'name': '-test', 'status': '清仓止盈',
        'buy_date': '2026-08-31', 'sell_date': '2026-09-02',
        'buy_price': 10, 'sell_price': 12,
        'profit_amount': 2000, 'profit_pct': 0.2, 'strategy': 'v1_double',
    }
    o = build_from_trade(trade, regime='STRONG_TREND')
    assert o.decision_id == ''
    assert o.lifecycle_status == 'CLOSED'
    assert o.exit_reason == 'TAKE_PROFIT'
    assert o.symbol == '600540'
    assert o.strategy == 'v1_double'


def test_outcome_open_from_real():
    snap = {'snapshot_id': 'real_20260908_12345678'}
    pos = {'code': '000001', 'name': '平安银行', 'quantity': 100, 'avg_cost': 10, 'current_price': 11, 'buy_date': '2026-08-15'}
    o = build_open_from_real(pos, snap, regime='STRONG_TREND')
    assert o.lifecycle_status == 'OPEN'
    assert o.action == 'HOLD'
    assert o.portfolio_snapshot_id == snap['snapshot_id']


def test_evidence_framework_review_from_outcome():
    from decision.outcome_store import build_from_trade
    o = build_from_trade({
        'code': '600540', 'name': '-test', 'status': '清仓止盈',
        'buy_date': '2026-08-31', 'sell_date': '2026-09-02',
        'buy_price': 10, 'sell_price': 12,
        'profit_amount': 2000, 'profit_pct': 0.2, 'strategy': 'v1_double',
    })
    ex = {
        'decision_id': '', 'symbol': '600540', 'action': 'SELL', 'status': 'CLOSED',
        'execution_id': 'e1', 'position_id': 'p1',
        'planned': {'price': 10, 'quantity': 100, 'position': 0.1},
        'actual': {'price': 12, 'quantity': 100, 'position': 0},
        'entry_regime': 'STRONG_TREND', 'exit_regime': 'STRONG_TREND',
        'candidate_score': 70, 'candidate_rank': 1,
        'permission_status': 'ALLOW', 'portfolio_assessment': {'action': 'OK'},
        'portfolio_drawdown': 0.05, 'portfolio_risk_flags': [],
        'decision_time': '2026-08-31T01:35:56+00:00', 'run_mode': 'SIMULATION', 'environment': '',
    }
    review = build_review_record_from_outcome(o, ex)
    assert review['outcome_id'] == o.outcome_id
    assert review['facts']['decision_quality']['action'] == 'SELL'
    # 2026-09-19: review['evidence_completeness'] 是状态字符串（撞键已修, 完整结构在 review['completeness']）
    ec = review['completeness']
    assert 'missing_sections' in ec
    assert review['evidence_completeness'] in ('EVIDENCE_COMPLETE', 'PRODUCTION_PARTIAL')


def test_evidence_framework_no_trade_review():
    dec = {
        'decision_id': 'd1', 'action': 'NO_TRADE', 'reason_codes': ['DATA_STALE'],
        'market_regime': 'HIGH_VOLATILITY', 'regime_label': '高波动',
        'permission_status': 'NO_NEW_ENTRY', 'candidate_score': None, 'candidate_rank': 0,
    }
    review = build_review_record_from_no_trade(dec)
    assert review['decision_id'] == 'd1'
    assert review['facts']['no_trade_evidence']['reason_codes'] == ['DATA_STALE']


def test_evaluation_readiness_partial():
    from decision.outcome_store import build_from_trade
    o = build_from_trade({
        'code': '600540', 'name': '-test', 'status': '清仓止盈',
        'buy_date': '2026-08-31', 'sell_date': '2026-09-02',
        'buy_price': 10, 'sell_price': 12,
        'profit_amount': 2000, 'profit_pct': 0.2, 'strategy': 'v1_double',
    })
    ex = {
        'decision_id': '', 'symbol': '600540', 'action': 'SELL', 'status': 'CLOSED',
        'execution_id': 'e1', 'position_id': 'p1',
        'planned': {'price': 10, 'quantity': 100, 'position': 0.1},
        'actual': {'price': 12, 'quantity': 100, 'position': 0},
        'strategy': 'v1_double',
    }
    r = evaluation_readiness(o, ex)
    assert 'production_evaluation_ready' in r
    assert 'missing_fields' in r


if __name__ == '__main__':
    test_outcome_store_import()
    test_outcome_from_trade_legacy()
    test_outcome_open_from_real()
    test_evidence_framework_review_from_outcome()
    test_evidence_framework_no_trade_review()
    test_evaluation_readiness_partial()
    print('M10-B P0 regression OK')
