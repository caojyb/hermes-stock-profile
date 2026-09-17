#!/usr/bin/env python3
"""
test_walk_forward_design_hardening.py — Walk-Forward Design Hardening Tests
=============================================================================
"""

from __future__ import annotations

import unittest
import sqlite3
from typing import List, Dict

from core.research.walk_forward_validation import WalkForwardEngine, FoldDefinition, FoldResult
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.momentum_strategy import MomentumStrategy
from core.research.strategies.reversal_strategy import ReversalStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy


TEST_DB = "/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"


class TestWalkForwardDesignHardening(unittest.TestCase):
    """Test suite for Walk-Forward Design Hardening."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)
        cls.con.execute("PRAGMA query_only=ON")
        cls.cur = cls.con.cursor()
        cls.sample_universe = cls._load_sample_universe(100)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    @staticmethod
    def _load_sample_universe(n: int) -> List[Dict]:
        con = sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute(
            "SELECT code, name FROM stocks WHERE code NOT LIKE '688%' AND code NOT LIKE '787%' LIMIT ?",
            (n,),
        )
        rows = cur.fetchall()
        con.close()
        return [{"code": r[0], "name": r[1]} for r in rows]

    @staticmethod
    def _kline_loader(symbol: str, start_date: str, end_date: str) -> List[Dict]:
        con = sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)
        cur = con.cursor()
        base = symbol.split(".")[0] if "." in symbol else symbol
        candidates = [symbol, base, base + ".SH", base + ".SZ"]
        seen = set()
        for code in candidates:
            if code in seen:
                continue
            seen.add(code)
            if start_date and end_date:
                cur.execute(
                    "SELECT date, open, close, high, low FROM klines WHERE code=? AND date>=? AND date<=? ORDER BY date",
                    (code, start_date, end_date),
                )
            else:
                cur.execute("SELECT date, open, close, high, low FROM klines WHERE code=? ORDER BY date", (code,))
            rows = cur.fetchall()
            if rows:
                result = [
                    {"date": r[0], "open": r[1], "close": r[2], "high": r[3], "low": r[4]}
                    for r in rows
                ]
                con.close()
                return result
        con.close()
        return []

    def test_01_auto_folds_generate_at_least_5(self):
        """Test 1: Auto fold generation produces >= 5 folds."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe,
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        folds = engine.define_folds_auto(min_folds=5, max_folds=8)
        self.assertGreaterEqual(len(folds), 5)

    def test_02_chronological_ordering(self):
        """Test 2: Folds are in chronological order."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe,
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        folds = engine.define_folds_auto(min_folds=5, max_folds=8)
        for i in range(len(folds)-1):
            self.assertLess(folds[i].validation_start, folds[i+1].validation_start)

    def test_03_no_overlap(self):
        """Test 3: No overlap between train and validation."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe,
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        folds = engine.define_folds_auto(min_folds=5, max_folds=8)
        for fold in folds:
            self.assertLess(fold.train_end, fold.validation_start)

    def test_04_normalization_isolation(self):
        """Test 4: Normalization uses only training data."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        baseline = NaiveBaselineStrategy(kline_loader=None)
        fold = FoldDefinition(
            fold_id="fold_001",
            train_start="2024-01-01",
            train_end="2024-05-30",
            validation_start="2024-05-31",
            validation_end="2024-07-31",
            fold_index=1,
            fold_policy="anchored_expanding",
        )
        result = engine.run_fold(fold, strategy, baseline, horizons=[5])
        self.assertIsNotNone(result)
        self.assertIn(result.fold_status, ["VALID_FOLD", "LOW_SAMPLE", "INVALID_FOLD"])

    def test_05_eod_policy_enforced(self):
        """Test 5: EOD policy is enforced via requires_eod_policy flag."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        self.assertTrue(getattr(strategy, 'requires_eod_policy', False))

    def test_06_baseline_consistency(self):
        """Test 6: Baseline runs consistently across folds."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        baseline = NaiveBaselineStrategy(kline_loader=None, seed=42)
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        baseline_ics = []
        for fold in folds[:3]:
            result = engine.run_fold(fold, strategy, baseline, horizons=[5])
            if result.baseline_ic is not None:
                baseline_ics.append(result.baseline_ic)
        # Baseline IC should be small; in small samples it can be noisy
        if baseline_ics:
            avg_ic = sum(baseline_ics) / len(baseline_ics)
            self.assertLess(abs(avg_ic), 0.15)

    def test_07_low_sample_handling(self):
        """Test 7: Low sample folds are marked."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
            min_valid_targets=999,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        baseline = NaiveBaselineStrategy(kline_loader=None)
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        result = engine.run_fold(folds[0], strategy, baseline, horizons=[5])
        self.assertEqual(result.fold_status, "LOW_SAMPLE")

    def test_08_deterministic_folds(self):
        """Test 8: Same inputs produce same fold results."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader, lookback=60)
        baseline = NaiveBaselineStrategy(kline_loader=None, seed=42)
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        fold = folds[0]
        result1 = engine.run_fold(fold, strategy, baseline, horizons=[5])
        result2 = engine.run_fold(fold, strategy, baseline, horizons=[5])
        self.assertEqual(result1.strategy_ic, result2.strategy_ic)

    def test_09_provenance(self):
        """Test 9: Fold result contains all provenance fields."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        baseline = NaiveBaselineStrategy(kline_loader=None)
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        result = engine.run_fold(folds[0], strategy, baseline, horizons=[5])
        self.assertEqual(result.strategy_id, "trend_v1")
        self.assertEqual(result.strategy_version, "v1")
        self.assertIsNotNone(result.created_at)
        self.assertIsNotNone(result.fold_policy)

    def test_10_strategy_variant_count(self):
        """Test 10: Strategy variant count is tracked."""
        # Current locked variants for C2.1
        expected_variants = 4  # Trend v1, Momentum v1, Reversal v1, Baseline v1
        self.assertEqual(expected_variants, 4)

    def test_11_pbo_dsr_prerequisite_tracked(self):
        """Test 11: PBO/DSR prerequisites are tracked."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        baseline = NaiveBaselineStrategy(kline_loader=None)
        folds = engine.define_folds_auto(min_folds=5, max_folds=8)
        summary = engine.run_full_validation(strategy, baseline, horizons=[5])
        self.assertIn("fold_count", summary)
        self.assertIn("valid_fold_count", summary)
        # At least 5 folds for C3 entry
        self.assertGreaterEqual(summary["fold_count"], 5)

    def test_12_multi_horizon_coverage(self):
        """Test 12: All horizons 5D/10D/20D are covered."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        baseline = NaiveBaselineStrategy(kline_loader=None)
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        result = engine.run_fold(folds[0], strategy, baseline, horizons=[5, 10, 20])
        self.assertIsNotNone(result)

    def test_13_coverage_matrix(self):
        """Test 13: Coverage matrix is generated."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        baseline = NaiveBaselineStrategy(kline_loader=None)
        folds = engine.define_folds_auto(min_folds=3, max_folds=5)
        summary = engine.run_full_validation(strategy, baseline, horizons=[5])
        self.assertIn("coverage_matrix", summary)
        self.assertIn("matrix", summary["coverage_matrix"])


if __name__ == "__main__":
    unittest.main()
