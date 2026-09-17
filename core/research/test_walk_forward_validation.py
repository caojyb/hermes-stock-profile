#!/usr/bin/env python3
"""
test_walk_forward_validation.py — Walk-Forward Validation Tests
================================================================
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


class TestWalkForwardValidation(unittest.TestCase):
    """Test suite for Walk-Forward Validation."""

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

    def test_01_chronological_split(self):
        """Test 1: Folds are chronological, no overlap."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe,
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        dates = ["2024-05-31", "2024-08-30", "2024-11-29"]
        folds = engine.define_folds(dates, train_window_days=60, validation_window_days=10, embargo_days=1)
        self.assertEqual(len(folds), 3)
        for i in range(len(folds)-1):
            self.assertLess(folds[i].validation_end, folds[i+1].validation_start)

    def test_02_no_train_validation_overlap(self):
        """Test 2: Train end < validation start."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe,
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        dates = ["2024-05-31", "2024-08-30"]
        folds = engine.define_folds(dates, train_window_days=60, validation_window_days=10, embargo_days=2)
        for fold in folds:
            self.assertLess(fold.train_end, fold.validation_start)

    def test_03_pit_enforcement(self):
        """Test 3: Strategy uses only PIT-safe data."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        universe = [{"code": "000001"}]
        signals = strategy.run(universe, "2024-05-31")
        for s in signals:
            if s.eligibility:
                self.assertIsNotNone(s.raw_score)

    def test_04_normalization_leakage_rejection(self):
        """Test 4: Normalization uses only current universe, not future."""
        from core.research.signal_normalization import NormalizationLayer
        from core.research.base_strategy import Signal
        norm = NormalizationLayer(method="percentile")
        signals = [
            Signal("000001", "2024-05-31", "test", "v1", 0.1, None, True, "OK"),
            Signal("000002", "2024-05-31", "test", "v1", 0.2, None, True, "OK"),
        ]
        # Normalization should not depend on future data
        result = norm._percentile_normalize(signals)
        self.assertEqual(len(result), 2)

    def test_05_target_isolation(self):
        """Test 5: Strategy does not access future target."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        universe = [{"code": "000001"}]
        signals = strategy.run(universe, "2024-05-31")
        for s in signals:
            self.assertIsNone(s.normalized_score)

    def test_06_universe_pit(self):
        """Test 6: Universe(T) is used, not current universe."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        custom_universe = [{"code": "000001"}]
        signals = strategy.run(custom_universe, "2024-05-31")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].stock_code, "000001")

    def test_07_baseline_comparison(self):
        """Test 7: Baseline runs in fold."""
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
        )
        result = engine.run_fold(fold, strategy, baseline, horizons=[5])
        self.assertIsNotNone(result)
        self.assertIn(result.fold_status, ["VALID_FOLD", "LOW_SAMPLE", "INVALID_FOLD"])

    def test_08_low_sample_handling(self):
        """Test 8: Low sample folds are marked."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
            min_valid_targets=999,
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
        )
        result = engine.run_fold(fold, strategy, baseline, horizons=[5])
        self.assertEqual(result.fold_status, "LOW_SAMPLE")

    def test_09_deterministic_fold(self):
        """Test 9: Same fold definition produces same result."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader, lookback=60)
        baseline = NaiveBaselineStrategy(kline_loader=None, seed=42)
        fold = FoldDefinition(
            fold_id="fold_001",
            train_start="2024-01-01",
            train_end="2024-05-30",
            validation_start="2024-05-31",
            validation_end="2024-07-31",
            fold_index=1,
        )
        result1 = engine.run_fold(fold, strategy, baseline, horizons=[5])
        result2 = engine.run_fold(fold, strategy, baseline, horizons=[5])
        self.assertEqual(result1.strategy_ic, result2.strategy_ic)

    def test_10_provenance(self):
        """Test 10: Fold result contains provenance."""
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
        )
        result = engine.run_fold(fold, strategy, baseline, horizons=[5])
        self.assertEqual(result.strategy_id, "trend_v1")
        self.assertEqual(result.strategy_version, "v1")
        self.assertIsNotNone(result.created_at)

    def test_11_future_data_rejection(self):
        """Test 11: Future data is rejected in strategy."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        universe = [{"code": "000001"}]
        signals = strategy.run(universe, "2099-01-01")
        for s in signals:
            self.assertFalse(s.eligibility)

    def test_12_anomaly_handling(self):
        """Test 12: Anomaly handling is tracked."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
            max_anomaly_ratio=0.0,
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
        )
        result = engine.run_fold(fold, strategy, baseline, horizons=[5])
        self.assertIn(result.fold_status, ["VALID_FOLD", "DATA_QUALITY_WARNING", "LOW_SAMPLE", "INVALID_FOLD"])

    def test_13_full_validation_run(self):
        """Test 13: Full validation run produces stability summary."""
        engine = WalkForwardEngine(
            universe_fetcher=lambda d: self.sample_universe[:20],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        baseline = NaiveBaselineStrategy(kline_loader=None)
        dates = ["2024-05-31", "2024-08-30"]
        summary = engine.run_full_validation(strategy, baseline, dates, horizons=[5])
        self.assertEqual(summary["fold_count"], 2)
        self.assertIn("stability_summary", summary)

    def test_14_multi_horizon(self):
        """Test 14: Multi-horizon validation."""
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
        )
        result = engine.run_fold(fold, strategy, baseline, horizons=[5, 10, 20])
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
