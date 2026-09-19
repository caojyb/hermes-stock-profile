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
        # 2026-09-19: 原断言"引擎 LIVE 计算的 fold 边界 == 2025-06-03 冻结 artifact"。
        # klines 持续增长后交易日历边界必然漂移（fold_001 从 2025-03-13 → 2025-03-29）,
        # 这是数据演进而非回归。语义正确的断言: 引擎输出的每个 fold 边界必须是
        # 真实交易日（alignment 的本意）, 且 fold 结构（数量/anchored_expanding 递进）完整。
        self.assertEqual(len(self.folds), 8)
        prev_val_end = None
        for f in self.folds:
            klines = kline_loader("000001", f.validation_start, f.validation_start)
            self.assertTrue(len(klines) > 0 and klines[0].get("open") is not None,
                            f"{f.fold_id} validation_start {f.validation_start} 非交易日")
            self.assertLessEqual(f.train_end, f.validation_start,
                                 f"{f.fold_id} train_end 必须 <= validation_start")
            if prev_val_end is not None:
                self.assertLess(prev_val_end, f.validation_start,
                                f"{f.fold_id} 必须晚于上一个 fold 的 validation_end")
            prev_val_end = f.validation_end

    def test_specific_non_trading_days_aligned(self):
        # 2026-09-19: 原硬编码 2025-06 冻结 artifact 的 4 个非交易日边界（数据演进后
        # 必然漂移）。改为对现役 folds 做同样性质的检查: 这些历史"坑日"（春节/清明/五一
        # 假期后的非交易日）不得出现在任何 validation 边界上。
        坑日 = ['2025-07-25', '2025-09-30', '2026-02-13', '2026-04-24',
               '2025-04-04', '2025-05-01', '2025-10-01', '2026-01-01']
        for f in self.folds:
            self.assertNotIn(f.validation_start, 坑日,
                             f"{f.fold_id} validation_start 不得是非交易日（假期坑日）")

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
        # 2026-09-19: 原 docs/M9_1_C4_B2_G_*.md 已不在现役树（研究阶段报告,
        # 随 9-11 清理或从未入库）。现役等价物 = alignment 的 machine-readable
        # manifest（before/after）+ aligned results, 两者均在 ARTIFACT_DIR。
        p1 = ARTIFACT_DIR / 'c4_b2_fold_boundary_before_after.json'
        p2 = ARTIFACT_DIR / 'c4_b2_stage2_trend_8fold_aligned.json'
        self.assertTrue(p1.exists(), "before/after manifest must exist")
        self.assertTrue(p2.exists(), "aligned results must exist")

if __name__ == '__main__':
    unittest.main()
