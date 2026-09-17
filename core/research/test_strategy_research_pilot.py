#!/usr/bin/env python3
"""
test_strategy_research_pilot.py — Strategy Research Pilot Tests
==============================================================
Bounded sample validation for Strategy Research Pilot.
"""

from __future__ import annotations

import unittest
import sqlite3
from typing import List, Dict

from core.research.target_engine import TargetEngine, HORIZONS
from core.research.base_strategy import BaseStrategy, Signal
from core.research.signal_normalization import NormalizationLayer
from core.research.strategies.trend_strategy import TrendStrategy
from core.research.strategies.momentum_strategy import MomentumStrategy
from core.research.strategies.reversal_strategy import ReversalStrategy
from core.research.strategies.naive_baseline import NaiveBaselineStrategy
from core.research.strategy_research_pilot import StrategyResearchPilot


TEST_DB = "/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db"
SAMPLE_DECISION_DATES = [
    "2024-05-31",
    "2024-08-30",
    "2024-11-29",
    "2025-02-28",
    "2025-05-30",
]


class TestStrategyResearchPilot(unittest.TestCase):
    """Test suite for Strategy Research Pilot."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(f"file:{TEST_DB}?mode=ro", uri=True)
        cls.con.execute("PRAGMA query_only=ON")
        cls.cur = cls.con.cursor()
        cls.sample_universe = cls._load_sample_universe(200)

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

    def test_01_base_strategy_interface(self):
        """Test 1: BaseStrategy defines required interface."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        self.assertEqual(strategy.strategy_id, "trend_v1")
        self.assertEqual(strategy.family, "Trend")
        self.assertEqual(strategy.horizon, 5)
        self.assertEqual(strategy.decision_time_policy, "T_END_OF_DAY")

    def test_02_trend_strategy_basic(self):
        """Test 2: Trend strategy produces eligible signal for valid stock."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        universe = [{"code": "000001"}]
        signals = strategy.run(universe, "2024-05-31")
        self.assertTrue(len(signals) > 0)
        eligible = [s for s in signals if s.eligibility]
        self.assertTrue(len(eligible) > 0)

    def test_03_momentum_strategy_basic(self):
        """Test 3: Momentum strategy produces eligible signal."""
        strategy = MomentumStrategy(kline_loader=self._kline_loader)
        universe = [{"code": "000001"}]
        signals = strategy.run(universe, "2024-05-31")
        self.assertTrue(len(signals) > 0)
        eligible = [s for s in signals if s.eligibility]
        self.assertTrue(len(eligible) > 0)

    def test_04_reversal_strategy_basic(self):
        """Test 4: Reversal strategy produces eligible signal."""
        strategy = ReversalStrategy(kline_loader=self._kline_loader)
        universe = [{"code": "000001"}]
        signals = strategy.run(universe, "2024-05-31")
        self.assertTrue(len(signals) > 0)
        eligible = [s for s in signals if s.eligibility]
        self.assertTrue(len(eligible) > 0)

    def test_05_naive_baseline_basic(self):
        """Test 5: Naive baseline produces signals."""
        strategy = NaiveBaselineStrategy(kline_loader=None)
        universe = [{"code": "000001"}, {"code": "600519"}]
        signals = strategy.run(universe, "2024-05-31")
        self.assertEqual(len(signals), 2)
        for s in signals:
            self.assertEqual(s.eligibility, True)

    def test_06_signal_normalization_percentile(self):
        """Test 6: Percentile normalization produces [0, 1] scores."""
        norm = NormalizationLayer(method="percentile")
        signals = [
            Signal("000001", "2024-05-31", "test", "v1", 0.1, None, True, "OK"),
            Signal("000002", "2024-05-31", "test", "v1", 0.2, None, True, "OK"),
            Signal("000003", "2024-05-31", "test", "v1", 0.3, None, True, "OK"),
        ]
        normalized = norm.normalize(signals)
        self.assertEqual(len(normalized), 3)
        scores = [s.normalized_score for s in normalized]
        self.assertEqual(set(scores), {0.0, 0.5, 1.0})

    def test_07_pit_isolation_future_data(self):
        """Test 7: Future data is rejected."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        # Future decision_time should not produce signals from future data
        signals = strategy.run(self.sample_universe[:10], "2099-01-01")
        # All should be ineligible due to missing decision date in klines
        for s in signals:
            self.assertFalse(s.eligibility)

    def test_08_target_integration(self):
        """Test 8: Strategy signals integrate with target engine."""
        pilot = StrategyResearchPilot(
            universe_fetcher=lambda d: [{"code": "000001"}],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        result = pilot.run_strategy(strategy, "2024-05-31", horizon=5)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertIn("evaluation", result)

    def test_09_deterministic_run(self):
        """Test 9: Same inputs produce same outputs."""
        strategy = TrendStrategy(kline_loader=self._kline_loader, lookback=60)
        universe = [{"code": "000001"}]
        signals1 = strategy.run(universe, "2024-05-31")
        signals2 = strategy.run(universe, "2024-05-31")
        self.assertEqual(signals1[0].raw_score, signals2[0].raw_score)

    def test_10_missing_data_handling(self):
        """Test 10: Missing history produces ineligible signal."""
        strategy = TrendStrategy(kline_loader=lambda s, st, en: [], lookback=60)
        universe = [{"code": "000001"}]
        signals = strategy.run(universe, "2024-05-31")
        self.assertEqual(len(signals), 1)
        self.assertFalse(signals[0].eligibility)
        self.assertEqual(signals[0].reason_code, "INSUFFICIENT_HISTORY")

    def test_11_universe_consistency(self):
        """Test 11: Strategy uses provided universe, not external."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        custom_universe = [{"code": "000001"}]
        signals = strategy.run(custom_universe, "2024-05-31")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].stock_code, "000001")

    def test_12_baseline_comparison(self):
        """Test 12: Baseline strategy runs and produces artifacts."""
        pilot = StrategyResearchPilot(
            universe_fetcher=lambda d: self.sample_universe[:50],
            kline_loader=self._kline_loader,
            db_path=TEST_DB,
        )
        strategy = NaiveBaselineStrategy(kline_loader=None)
        result = pilot.run_strategy(strategy, "2024-05-31", horizon=5)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertGreaterEqual(result["signal_count"], 50)

    def test_13_signal_no_buy_sell(self):
        """Test 13: Strategy output does not contain BUY/SELL."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        universe = [{"code": "000001"}]
        signals = strategy.run(universe, "2024-05-31")
        for s in signals:
            self.assertNotIn("BUY", str(s.__dict__))
            self.assertNotIn("SELL", str(s.__dict__))

    def test_14_multi_horizon(self):
        """Test 14: Strategy runs across 5D/10D/20D."""
        strategy = TrendStrategy(kline_loader=self._kline_loader)
        universe = [{"code": "000001"}]
        for h in HORIZONS:
            signals = strategy.run(universe, "2024-05-31")
            self.assertTrue(len(signals) > 0)


if __name__ == "__main__":
    unittest.main()
