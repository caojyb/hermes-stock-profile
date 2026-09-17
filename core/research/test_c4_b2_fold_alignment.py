#!/usr/bin/env python3
"""
test_c4_b2_fold_alignment.py — M9.1-C4-B2-G regression tests for trading-calendar fold alignment.
"""
from __future__ import annotations

import json, sqlite3, unittest, sys
from pathlib import Path

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'

sys_path = str(BASE)
sys.path.insert(0, sys_path)
from core.research.walk_forward_validation import WalkForwardEngine

def universe_fetcher(decision_date):
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' ORDER BY code LIMIT 200")
    rows = cur.fetchall()
    con.close()
    return [{"code": r[0], "name": r[1]} for r in rows]

def kline_loader(symbol, start_date, end_date):
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    base = symbol.split('.')[0] if '.' in symbol else symbol
    candidates = [symbol, base, base+'.SH', base+'.SZ']
    seen=set(); rows=[]; seen_dates=set()
    for code in candidates:
        if code in seen: continue
        seen.add(code)
        if start_date and end_date:
            cur.execute('SELECT date,open,close,high,low,volume FROM klines WHERE code=? AND date>=? AND date<=? ORDER BY date', (code, start_date, end_date))
        else:
            cur.execute("SELECT date,open,close,high,low,volume FROM klines WHERE code=? ORDER BY date", (code,))
        for r in cur.fetchall():
            if r[0] in seen_dates: continue
            seen_dates.add(r[0])
            rows.append({'date':r[0],'open':r[1],'close':r[2],'high':r[3],'low':r[4],'volume':r[5]})
    con.close()
    return rows

class TestFoldAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = WalkForwardEngine(
            universe_fetcher=universe_fetcher,
            kline_loader=kline_loader,
            db_path=str(DB_PATH),
            dataset_version="v1",
            universe_version="RESEARCH_UNIVERSE_V1",
            target_version="v1",
            pit_policy="PIT_RESEARCH_V1",
            fold_policy="anchored_expanding",
        )
        cls.folds = cls.engine.define_folds_auto(252, 63, 5, 8, 8)

    def test_all_folds_have_trading_day_validation_start(self):
        for f in self.folds:
            klines = kline_loader("000001", f.validation_start, f.validation_start)
            self.assertTrue(
                len(klines) > 0 and klines[0].get("open") is not None,
                f"{f.fold_id} validation_start {f.validation_start} is not a trading day"
            )

    def test_all_folds_have_trading_day_validation_end(self):
        for f in self.folds:
            klines = kline_loader("000001", f.validation_end, f.validation_end)
            self.assertTrue(
                len(klines) > 0 and klines[0].get("open") is not None,
                f"{f.fold_id} validation_end {f.validation_end} is not a trading day"
            )

    def test_alignment_does_not_shift_valid_trading_days(self):
        aligned = json.loads((ARTIFACT_DIR / 'c4_b2_stage2_trend_8fold_aligned.json').read_text())
        expected = {f['fold_id']: f for f in aligned['folds']}
        for f in self.folds:
            exp = expected[f.fold_id]
            self.assertEqual(f.validation_start, exp['validation_start'])
            self.assertEqual(f.validation_end, exp['validation_end'])
            self.assertEqual(f.train_start, exp['train_start'])
            self.assertEqual(f.train_end, exp['train_end'])

    def test_specific_non_trading_days_aligned(self):
        aligned = json.loads((ARTIFACT_DIR / 'c4_b2_stage2_trend_8fold_aligned.json').read_text())
        expected = {
            'fold_003': '2025-07-25',
            'fold_004': '2025-09-30',
            'fold_006': '2026-02-13',
            'fold_007': '2026-04-24',
        }
        for f in self.folds:
            if f.fold_id in expected:
                self.assertEqual(f.validation_start, expected[f.fold_id])

    def test_aligned_manifest_generated(self):
        p = ARTIFACT_DIR / 'c4_b2_fold_boundary_before_after.json'
        self.assertTrue(p.exists(), "before/after manifest must exist")
        obj = json.loads(p.read_text())
        self.assertEqual(obj['summary']['total_folds'], 8)
        self.assertEqual(len(obj['folds']), 8)

    def test_aligned_results_generated(self):
        p = ARTIFACT_DIR / 'c4_b2_stage2_trend_8fold_aligned.json'
        self.assertTrue(p.exists(), "aligned results must exist")
        obj = json.loads(p.read_text())
        self.assertEqual(obj['valid_fold_count'], 8)
        self.assertEqual(obj['low_sample_fold_count'], 0)

    def test_report_generated(self):
        p = BASE / 'docs' / 'M9_1_C4_B2_G_TRADING_CALENDAR_FOLD_ALIGNMENT.md'
        self.assertTrue(p.exists(), "alignment report must exist")

if __name__ == '__main__':
    unittest.main()
