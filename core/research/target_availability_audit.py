#!/usr/bin/env python3
"""
target_availability_audit.py — M9.1-C4-B2 Target Availability Closure Audit
=====================================================================

Read-only audit of canonical target-engine paths and C4-B1 evidence.
No DB writes, no target-engine changes, no DecisionEngine changes.
"""
from __future__ import annotations

import os, sys, sqlite3, json, hashlib
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

C4B1_RESULTS = BASE / 'docs/M9_1_D7_C4_B1_EXPANDED_WALK_FORWARD_RESULTS.md'


@dataclass(frozen=True)
class LayerCounts:
    signal_rows: int = 0
    candidate_rows: int = 0
    universe_rows: int = 0
    entry_price_available: int = 0
    exit_price_available_5d: int = 0
    exit_price_available_10d: int = 0
    exit_price_available_20d: int = 0
    reference_available_5d: int = 0
    reference_available_10d: int = 0
    reference_available_20d: int = 0
    valid_target_count_5d: int = 0
    valid_target_count_10d: int = 0
    valid_target_count_20d: int = 0
    missing_target_count_5d: int = 0
    missing_target_count_10d: int = 0
    missing_target_count_20d: int = 0


@dataclass(frozen=True)
class DateBoundaryResult:
    decision_date: str
    is_trading_day: bool
    kline_count: int
    next_trading_day: str
    next_open_exists: bool


class TargetAvailabilityAudit:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.con.execute("PRAGMA query_only=ON")
        self.cur = self.con.cursor()
        self.report: Dict[str, Any] = {
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'db_path': str(db_path),
            'scope': 'READ_ONLY_AUDIT',
            'code_versions': self._code_versions(),
            'tables': self._tables(),
            'date_boundary_samples': [],
            'layers': {},
            'horizons': {},
            'reference_audit': {},
            'c4b1_evidence': {},
            'conclusion': {},
        }

    def _code_versions(self) -> Dict[str, str]:
        files = [
            BASE / 'core/research/target_engine.py',
            BASE / 'core/research/reference_benchmark.py',
            BASE / 'core/research/walk_forward_validation.py',
            BASE / 'core/research/run_expanded_walk_forward.py',
            BASE / 'core/research/expanded_walk_forward_validation.py',
            BASE / 'docs/M9_1_D7_C4_B1_EXPANDED_WALK_FORWARD_RESULTS.md',
        ]
        out = {}
        for p in files:
            if not p.exists():
                out[str(p.relative_to(BASE))] = 'MISSING'
                continue
            h = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
            s = p.stat().st_size
            out[str(p.relative_to(BASE))] = f'sha1={h};bytes={s}'
        return out

    def _tables(self) -> Dict[str, int]:
        out = {}
        for t in ['klines','indicators','stocks','meta','universe_pit_snapshot']:
            try:
                self.cur.execute(f'SELECT COUNT(*) FROM {t}')
                out[t] = self.cur.fetchone()[0]
            except Exception as e:
                out[t] = f'ERR:{e}'
        try:
            self.cur.execute('SELECT MIN(date), MAX(date) FROM klines')
            out['klines_min_max'] = self.cur.fetchone()
        except Exception:
            out['klines_min_max'] = None
        return out

    @staticmethod
    def _next_calendar_day(date_str: str) -> str:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return (dt + __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d')

    def audit_date_boundary(self, dates: List[str]) -> List[DateBoundaryResult]:
        results = []
        for d in dates:
            self.cur.execute('SELECT COUNT(*) FROM klines WHERE date=?', (d,))
            c = self.cur.fetchone()[0]
            nd = self._next_calendar_day(d)
            self.cur.execute('SELECT COUNT(*) FROM klines WHERE date=?', (nd,))
            nc = self.cur.fetchone()[0]
            results.append(DateBoundaryResult(
                decision_date=d,
                is_trading_day=c > 0,
                kline_count=c,
                next_trading_day=nd,
                next_open_exists=nc > 0,
            ))
        return results

    def audit_price_chain(self, symbol: str, decision_date: str, horizon: int) -> Dict[str, Optional[bool]]:
        self.cur.execute(
            'SELECT date, open, close FROM klines WHERE code=? AND date>=? ORDER BY date LIMIT ?',
            (symbol, decision_date, horizon + 5),
        )
        rows = self.cur.fetchall()
        if not rows:
            return {'decision_in_klines': False, 'entry_exists': False, 'exit_exists': False, 'prices': None}
        dates = [r[0] for r in rows]
        decision_idx = dates.index(decision_date) if decision_date in dates else -1
        if decision_idx < 0:
            return {'decision_in_klines': False, 'entry_exists': False, 'exit_exists': False, 'prices': None}
        entry_idx = decision_idx + 1
        exit_idx = decision_idx + horizon
        return {
            'decision_in_klines': True,
            'entry_exists': entry_idx < len(rows) and rows[entry_idx][1] is not None,
            'exit_exists': exit_idx < len(rows) and rows[exit_idx][2] is not None,
            'prices': {
                'decision_date': decision_date,
                'entry_date': rows[entry_idx][0] if entry_idx < len(rows) else None,
                'exit_date': rows[exit_idx][0] if exit_idx < len(rows) else None,
                'entry_open': rows[entry_idx][1] if entry_idx < len(rows) else None,
                'exit_close': rows[exit_idx][2] if exit_idx < len(rows) else None,
            },
        }

    def layer_funnel(self, universe_size: int = 200) -> LayerCounts:
        # Representative symbol sample from universe, not full 5187.
        self.cur.execute(
            'SELECT code FROM stocks WHERE code NOT LIKE "688%%" AND code NOT LIKE "787%%" ORDER BY code LIMIT ?',
            (universe_size,),
        )
        symbols = [r[0] for r in self.cur.fetchall()]
        lc = LayerCounts(signal_rows=len(symbols), candidate_rows=len(symbols), universe_rows=len(symbols))

        for sym in symbols:
            # entry price
            r = self.audit_price_chain(sym, '2025-06-03', 5)
            if r.get('entry_exists'):
                lc = lc.__class__(**{**lc.__dict__, 'entry_price_available': lc.entry_price_available + 1})
            for h in [5, 10, 20]:
                rr = self.audit_price_chain(sym, '2025-06-03', h)
                if rr.get('exit_exists'):
                    attr = f'exit_price_available_{h}d'
                    lc = lc.__class__(**{**lc.__dict__, attr: getattr(lc, attr) + 1})
        return lc

    def reference_audit(self, decision_date: str = '2025-06-03') -> Dict[str, Any]:
        try:
            from core.research.reference_benchmark import ReferenceBenchmark
            rb = ReferenceBenchmark(None, None)
            out = {}
            for h in [5, 10, 20]:
                res = rb.compute_reference(decision_date, h, 'UNIVERSE_MEDIAN', min_coverage_ratio=0.5)
                out[f'{h}d'] = {
                    'reference_return': res.reference_return,
                    'valid_count': res.reference_valid_count,
                    'total_count': res.reference_total_count,
                    'valid_ratio': res.reference_valid_ratio,
                    'status': 'AVAILABLE' if res.reference_return is not None else 'UNAVAILABLE',
                }
            return out
        except Exception as e:
            return {'error': str(e)}

    def c4b1_evidence(self) -> Dict[str, Any]:
        if not C4B1_RESULTS.exists():
            return {'status': 'MISSING', 'path': str(C4B1_RESULTS)}
        text = C4B1_RESULTS.read_text(encoding='utf-8', errors='replace')
        summary = {
            'status': 'PRESENT',
            'path': str(C4B1_RESULTS),
            'bytes': len(text),
            'low_sample_mentions': text.count('LOW_SAMPLE'),
            'no_evidence_mentions': text.count('NO_EVIDENCE'),
            'valid_fold_count_zero_mentions': text.count('"valid_fold_count": 0'),
            'evidence': text[:6000],
        }
        return summary

    def run(self) -> Dict[str, Any]:
        self.report['date_boundary_samples'] = [
            asdict(x) for x in self.audit_date_boundary([
                '2025-06-01', '2026-01-02', '2026-03-01', '2025-06-03', '2026-01-05', '2026-02-27'
            ])
        ]
        self.report['layers'] = asdict(self.layer_funnel(200))
        self.report['reference_audit'] = self.reference_audit('2025-06-03')
        self.report['c4b1_evidence'] = self.c4b1_evidence()
        self.report['conclusion'] = self._conclude()
        out_path = ARTIFACT_DIR / 'c4_b2_target_availability_audit.json'
        out_path.write_text(json.dumps(self.report, indent=2, ensure_ascii=False), encoding='utf-8')
        return self.report

    def _conclude(self) -> Dict[str, Any]:
        c4 = self.report.get('c4b1_evidence', {})
        layers = self.report.get('layers', {})
        ref = self.report.get('reference_audit', {})
        status = 'PARTIALLY_READY'
        if c4.get('valid_fold_count_zero_mentions', 0) >= 14 and layers.get('valid_target_count_5d', 0) == 0:
            root = 'DATE_ALIGNMENT_PROBLEM / DATA_MISSING'
        elif c4.get('status') == 'PRESENT':
            root = 'C4-B1 evidence available; exact layer drop requires runner execution with instrumented funnel'
        else:
            root = 'C4-B1 evidence unavailable; target engine code appears canonical'
        return {
            'TARGET_AVAILABILITY_STATUS': status,
            'ROOT_CAUSE_CATEGORY': root,
            'PRIOR_BLOCKER': 'valid_target_count=0 across 14 variants x 8 folds x 3 horizons in C4-B1 artifact',
            'NEXT_ACTION': 'Run 1 strategy x 1 fold x 1 horizon with instrumented funnel; do not rerun full matrix yet',
        }


def main():
    audit = TargetAvailabilityAudit(str(DB_PATH))
    report = audit.run()
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
