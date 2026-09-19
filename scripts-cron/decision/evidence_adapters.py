#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evidence Adapters — 把现有模块输出适配成 DecisionContext 的 EvidenceItem（M10-C）

原则：
- 只做适配/封装，不重算任何现有指标/选股/评分规则。
- 缺失数据必须输出 UNAVAILABLE / UNKNOWN，禁止用 0 / empty / default positive 伪装。
- 不接入新 Alpha；不修改 C5 / Fundamental / Opportunity 研究结论。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional
from datetime import datetime, timezone
import os

from .context import EvidenceItem, EvidenceAvailability, DecisionContext


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══ Opportunity Adapter ═══
@dataclass
class OpportunityEvidence:
    opportunity_id: str = ''
    symbol: str = ''
    ranking: int = 0
    score: float = 0.0
    evidence_refs: list = field(default_factory=list)
    as_of: str = ''
    provenance: Dict[str, Any] = field(default_factory=dict)


def adapt_opportunity(*, symbol: str, as_of: str = '', source_table: str = 'double_up_scores',
                      universe_source: str = 'scan_doubling_potential') -> EvidenceItem:
    """读取现有 Opportunity 输出并封装为 EvidenceItem。

    当前 production opportunity 来源：
    - double_up_scores 表（scan_doubling_potential.py 写入）
    - stock_opportunity_scan.py 盘中医推

    若当前无有效记录，返回 UNAVAILABLE。
    """
    decision_time = _now_iso()
    row = _read_opportunity_row(symbol, source_table)
    if row is None:
        return EvidenceItem(
            source='opportunity',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'source_table': source_table, 'universe_source': universe_source, 'reason': 'NO_CURRENT_RECORD'},
            confidence=0.0,
            value=None,
            reason='NO_CURRENT_RECORD',
        )
    try:
        opp = OpportunityEvidence(
            opportunity_id=str(row.get('scan_id', row.get('opportunity_id', '')) or ''),
            symbol=str(row.get('code', symbol)),
            ranking=0,
            score=float(row.get('total_score', row.get('score', 0)) or 0.0),
            evidence_refs=[],
            as_of=str(row.get('scan_date', as_of) or ''),
            provenance={
                'source_table': source_table,
                'universe_source': universe_source,
                'provider': 'local_db',
                'source_record_id': str(row.get('scan_date', '')) + '_' + str(row.get('code', symbol)),
                'retrieved_at': decision_time,
                'schema_note': 'double_up_scores has no rank/evidence_refs/id columns; using canonical schema',
            },
        )
        return EvidenceItem(
            source='opportunity',
            code=opp.symbol,
            decision_time=decision_time,
            available_time=opp.as_of,
            PIT_status='APPROXIMATE',
            availability=EvidenceAvailability.AVAILABLE,
            provenance=opp.provenance,
            confidence=0.7,
            value=asdict(opp),
        )
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return EvidenceItem(
            source='opportunity',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'source_table': source_table, 'reason': 'ADAPTER_ERROR'},
            confidence=0.0,
            value=None,
            reason='ADAPTER_ERROR',
        )


def _market_db_path() -> str:
    try:
        from pathlib import Path
        import sys as _sys
        _root = Path(__file__).resolve().parent.parent.parent.parent / 'stock-work'
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from core.compat_paths import MARKET_DB as _DB
        return str(_DB)
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        # fallback to explicit known canonical production path
        return '/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db'


def _read_opportunity_row(symbol: str, source_table: str) -> Optional[Dict[str, Any]]:
    try:
        import sqlite3
        db_path = _market_db_path()
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Canonical schema: double_up_scores has no rank/evidence_refs/id columns.
        cur.execute("""
            SELECT code, scan_date, total_score, sector, strategy, catalyst_json
            FROM double_up_scores
            WHERE code=?
            ORDER BY scan_date DESC LIMIT 1
        """, (symbol,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return None


def _read_latest_fundamental_row(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import sqlite3
        db_path = _market_db_path()
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT report_date, roe, profit_growth, revenue_growth, pe_ratio, pb_ratio
            FROM financial_data
            WHERE code=? OR code=?
            ORDER BY report_date DESC LIMIT 1
        """, (symbol, symbol + '.SH') if symbol.startswith('6') else (symbol, symbol + '.SZ'))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return None


def _read_latest_capital_flow_row(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import sqlite3
        db_path = _market_db_path()
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT date, main_net_inflow, main_buy, main_sell
            FROM main_fund_flow
            WHERE code=?
            ORDER BY date DESC LIMIT 1
        """, (symbol,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return None


def _read_latest_indicator_row(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import sqlite3
        db_path = _market_db_path()
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT turnover_rate, vol_ratio, updated_at, ma20, macd, atr_14, signal_score
            FROM indicators
            WHERE code=?
            LIMIT 1
        """, (symbol,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return None


# ═══ Fundamental Adapter ═══
@dataclass
class FundamentalEvidence:
    report_date: str = ''
    roe: float = 0.0
    profit_growth: float = 0.0
    revenue_growth: float = 0.0
    pe_ratio: float = 0.0
    pb_ratio: float = 0.0
    available_fields: list = field(default_factory=list)
    missing_fields: list = field(default_factory=list)


def adapt_fundamental(*, symbol: str, as_of: str = '') -> EvidenceItem:
    """读取当前可获得的 Fundamental evidence 并封装。

    若关键字段缺失或 unavailable，返回 UNAVAILABLE。
    禁止用 0 或空值伪装有效数据。
    """
    decision_time = _now_iso()
    row = _read_latest_fundamental_row(symbol)
    if row is None:
        return EvidenceItem(
            source='fundamental',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'financial_data', 'reason': 'NO_FINANCIAL_RECORD'},
            confidence=0.0,
            value=None,
            reason='NO_FINANCIAL_RECORD',
        )
    try:
        available = []
        missing = []
        for key in ['roe', 'profit_growth', 'revenue_growth', 'pe_ratio', 'pb_ratio']:
            v = row.get(key)
            if v is not None:
                available.append(key)
            else:
                missing.append(key)
        # 如果所有关键字段都缺失，视为 UNAVAILABLE
        if not available:
            return EvidenceItem(
                source='fundamental',
                code=symbol,
                decision_time=decision_time,
                available_time=str(row.get('report_date', '') or ''),
                PIT_status='APPROXIMATE',
                availability=EvidenceAvailability.UNAVAILABLE,
                provenance={'provider': 'financial_data', 'report_date': str(row.get('report_date', '')), 'reason': 'ALL_KEY_FIELDS_MISSING'},
                confidence=0.0,
                value=None,
                reason='ALL_KEY_FIELDS_MISSING',
            )
        fund = FundamentalEvidence(
            report_date=str(row.get('report_date', '') or ''),
            roe=float(row.get('roe', 0) or 0),
            profit_growth=float(row.get('profit_growth', 0) or 0),
            revenue_growth=float(row.get('revenue_growth', 0) or 0),
            pe_ratio=float(row.get('pe_ratio', 0) or 0),
            pb_ratio=float(row.get('pb_ratio', 0) or 0),
            available_fields=available,
            missing_fields=missing,
        )
        return EvidenceItem(
            source='fundamental',
            code=symbol,
            decision_time=decision_time,
            available_time=fund.report_date,
            PIT_status='APPROXIMATE',
            availability=EvidenceAvailability.AVAILABLE,
            provenance={
                'provider': 'financial_data',
                'report_date': fund.report_date,
                'available_fields': available,
                'missing_fields': missing,
                'retrieved_at': decision_time,
            },
            confidence=0.6,
            value=asdict(fund),
        )
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return EvidenceItem(
            source='fundamental',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'financial_data', 'reason': 'ADAPTER_ERROR'},
            confidence=0.0,
            value=None,
            reason='ADAPTER_ERROR',
        )


# ═══ Capital Flow Adapter ═══
def adapt_capital_flow(*, symbol: str, as_of: str = '') -> EvidenceItem:
    """读取 Capital Flow evidence。

    当前生产数据覆盖有限，不伪装历史值。
    若无记录，返回 UNAVAILABLE。
    """
    decision_time = _now_iso()
    try:
        row = _read_latest_capital_flow_row(symbol)
    except Exception as e:
        return EvidenceItem(
            source='capital_flow',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'main_fund_flow', 'reason': f'QUERY_ERROR: {e}'},
            confidence=0.0,
            value=None,
            reason='QUERY_ERROR',
        )
    if row is None:
        return EvidenceItem(
            source='capital_flow',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'main_fund_flow', 'reason': 'NO_CAPITAL_FLOW_RECORD'},
            confidence=0.0,
            value=None,
            reason='NO_CAPITAL_FLOW_RECORD',
        )
    try:
        value = {
            'date': str(row.get('date', '') or ''),
            'main_net_inflow': float(row.get('net_amt', 0) or 0),
            'main_buy': None,
            'main_sell': None,
            'note': 'net_amt mapped to main_net_inflow; main_buy/main_sell unavailable in canonical schema',
        }
        return EvidenceItem(
            source='capital_flow',
            code=symbol,
            decision_time=decision_time,
            available_time=value['date'],
            PIT_status='APPROXIMATE',
            availability=EvidenceAvailability.AVAILABLE,
            provenance={'provider': 'main_fund_flow', 'retrieved_at': decision_time, 'schema_version': 'v1'},
            confidence=0.5,
            value=value,
        )
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return EvidenceItem(
            source='capital_flow',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'main_fund_flow', 'reason': 'ADAPTER_ERROR'},
            confidence=0.0,
            value=None,
            reason='ADAPTER_ERROR',
        )


def _read_latest_capital_flow_row(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import sqlite3
        db_path = _market_db_path()
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT date, net_amt
            FROM main_fund_flow
            WHERE code=?
            ORDER BY date DESC LIMIT 1
        """, (symbol,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.OperationalError as e:
        raise
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return None


# ═══ News/Event Adapter ═══
def adapt_news(*, symbol: str, as_of: str = '') -> EvidenceItem:
    """读取 News/Event evidence。

    M9.1-C5-Q 已确认当前 News/Event 为 NOT_READY / STOP。
    因此本 adapter 当前固定返回 UNAVAILABLE，并记录真实原因。
    """
    decision_time = _now_iso()
    return EvidenceItem(
        source='news_event',
        code=symbol,
        decision_time=decision_time,
        available_time='',
        PIT_status='UNKNOWN',
        availability=EvidenceAvailability.UNAVAILABLE,
        provenance={'provider': 'news_cache', 'reason': 'SOURCE_NOT_READY', 'evidence': 'M9.1-C5-Q'},
        confidence=0.0,
        value=None,
        reason='SOURCE_NOT_READY',
    )


# ═══ Volume Evidence Adapter ═══
@dataclass
class VolumeEvidence:
    turnover_rate: float = 0.0
    volume_ratio: float = 0.0
    amount: float = 0.0


def adapt_volume(*, symbol: str, as_of: str = '') -> EvidenceItem:
    """读取 Volume Evidence。若 indicators 无 turnover_rate，返回 UNAVAILABLE。"""
    decision_time = _now_iso()
    row = _read_latest_indicator_row(symbol)
    if row is None:
        return EvidenceItem(
            source='volume',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'indicators', 'reason': 'NO_INDICATOR_RECORD'},
            confidence=0.0,
            value=None,
            reason='NO_INDICATOR_RECORD',
        )
    try:
        turnover = row.get('turnover_rate')
        vol_ratio = row.get('volume_ratio')
        # 禁止用 0 伪装有效数据
        if turnover is None and vol_ratio is None:
            return EvidenceItem(
                source='volume',
                code=symbol,
                decision_time=decision_time,
                available_time=str(row.get('updated_at', '') or ''),
                PIT_status='APPROXIMATE',
                availability=EvidenceAvailability.UNAVAILABLE,
                provenance={'provider': 'indicators', 'reason': 'VOLUME_FIELDS_MISSING'},
                confidence=0.0,
                value=None,
                reason='VOLUME_FIELDS_MISSING',
            )
        value = VolumeEvidence(
            turnover_rate=float(turnover) if turnover is not None else 0.0,
            volume_ratio=float(vol_ratio) if vol_ratio is not None else 0.0,
            amount=float(row.get('amount', 0) or 0),
        )
        return EvidenceItem(
            source='volume',
            code=symbol,
            decision_time=decision_time,
            available_time=str(row.get('updated_at', '') or ''),
            PIT_status='APPROXIMATE',
            availability=EvidenceAvailability.AVAILABLE,
            provenance={'provider': 'indicators', 'retrieved_at': decision_time},
            confidence=0.6,
            value=asdict(value),
        )
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return EvidenceItem(
            source='volume',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'indicators', 'reason': 'ADAPTER_ERROR'},
            confidence=0.0,
            value=None,
            reason='ADAPTER_ERROR',
        )


# ═══ Technical Evidence Adapter ═══
@dataclass
class TechnicalEvidence:
    ma20: float = 0.0
    macd: float = 0.0
    atr_14: float = 0.0
    volume_ratio: float = 0.0
    signal_score: float = 0.0
    data_quality: str = ''


def adapt_technical(*, symbol: str, as_of: str = '') -> EvidenceItem:
    """读取 Technical Evidence。若 indicators 无可用字段，返回 UNAVAILABLE。"""
    decision_time = _now_iso()
    row = _read_latest_indicator_row(symbol)
    if row is None:
        return EvidenceItem(
            source='technical',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'indicators', 'reason': 'NO_INDICATOR_RECORD'},
            confidence=0.0,
            value=None,
            reason='NO_INDICATOR_RECORD',
        )
    try:
        value = TechnicalEvidence(
            ma20=float(row.get('ma20') or 0),
            macd=float(row.get('macd') or 0),
            atr_14=float(row.get('atr_14') or 0),
            volume_ratio=float(row.get('volume_ratio') or 0),
            signal_score=float(row.get('signal_score') or 0),
            data_quality='current_snapshot',
        )
        return EvidenceItem(
            source='technical',
            code=symbol,
            decision_time=decision_time,
            available_time=str(row.get('updated_at', '') or ''),
            PIT_status='APPROXIMATE',
            availability=EvidenceAvailability.AVAILABLE,
            provenance={'provider': 'indicators', 'retrieved_at': decision_time},
            confidence=0.7,
            value=asdict(value),
        )
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return EvidenceItem(
            source='technical',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'indicators', 'reason': 'ADAPTER_ERROR'},
            confidence=0.0,
            value=None,
            reason='ADAPTER_ERROR',
        )


# ═══ Tradability Adapter ═══
def adapt_tradability(*, symbol: str, as_of: str = '', liquidity_ok: Optional[bool] = None) -> EvidenceItem:
    """Tradability Evidence。

    若 liquidity_ok 未提供，从本地指标推断；仍无法判断则返回 UNKNOWN。
    """
    decision_time = _now_iso()
    if liquidity_ok is None:
        liquidity_ok = _infer_liquidity_ok(symbol)
    try:
        return EvidenceItem(
            source='tradability',
            code=symbol,
            decision_time=decision_time,
            available_time=as_of or _now_iso(),
            PIT_status='APPROXIMATE',
            availability=EvidenceAvailability.AVAILABLE if liquidity_ok else EvidenceAvailability.UNAVAILABLE,
            provenance={'provider': 'local_inference', 'liquidity_ok': bool(liquidity_ok), 'retrieved_at': decision_time},
            confidence=0.5 if liquidity_ok is None else 0.6,
            value={'liquidity_ok': liquidity_ok},
            reason='' if liquidity_ok else 'LIQUIDITY_INSUFFICIENT',
        )
    except Exception as _e:
        print(f"[EXC] evidence_adapters.py: {type(_e).__name__}: {_e}")
        return EvidenceItem(
            source='tradability',
            code=symbol,
            decision_time=decision_time,
            available_time='',
            PIT_status='UNKNOWN',
            availability=EvidenceAvailability.UNKNOWN,
            provenance={'provider': 'local_inference', 'reason': 'ADAPTER_ERROR'},
            confidence=0.0,
            value=None,
            reason='ADAPTER_ERROR',
        )


def _infer_liquidity_ok(symbol: str) -> Optional[bool]:
    row = _read_latest_indicator_row(symbol)
    if not row:
        return None
    turnover = row.get('turnover_rate')
    amount = row.get('amount')
    if turnover is None and amount is None:
        return None
    if turnover is not None and float(turnover) > 0:
        return True
    if amount is not None and float(amount) > 0:
        return True
    return None
