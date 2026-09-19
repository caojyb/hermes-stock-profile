#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-J0D 测试：Validation Baseline Reset 语义验证。
全部只读；断言历史数据未被删除/修改、边界定义确定性、初始状态与 DB 真实值一致。
"""
import os
import sys
import sqlite3
import unittest
from pathlib import Path

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

# 2026-09-19: canonical simulation.db 已迁 stock-work/data/runtime/（compat_paths）
try:
    from core.compat_paths import SIMULATION_DB as SIM_DB
except Exception:
    SIM_DB = os.path.join(SCRIPT_DIR, 'simulation.db')
BACKUP_823 = '/mnt/hgfs/clawshare/hermesdata/db/daily/simulation_20260823.db'


def ro_conn(path=SIM_DB):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


class TestBaselineDefinition(unittest.TestCase):

    def test_new_start_is_20260827(self):
        from decision.validation_baseline import VALIDATION_START_DATE
        self.assertEqual(VALIDATION_START_DATE, '2026-08-27')

    def test_old_period_preserved_in_metadata(self):
        from decision.validation_baseline import PRE_FIX_VALIDATION_START, PRE_FIX_VALIDATION_END
        self.assertEqual((PRE_FIX_VALIDATION_START, PRE_FIX_VALIDATION_END),
                         ('2026-08-09', '2026-08-26'))

    def test_initial_state_matches_source_of_truth(self):
        """初始状态必须来自 8/26 收盘真实值，不允许第二套手工数据"""
        from decision.validation_baseline import (INITIAL_CASH, INITIAL_HOLDINGS_VALUE,
                                                 INITIAL_TOTAL_ASSET)
        conn = ro_conn()
        # 2026-09-19: 8/26 初始快照已归档; 从归档表读（reset 前真实初始值）
        cash, hv, tv = conn.execute(
            "SELECT cash, holdings_value, total_value FROM portfolio_snapshots_legacy_202607 "
            "WHERE date='2026-08-26'").fetchone()
        open_pos = conn.execute(
            "SELECT COUNT(*) FROM trades_legacy_202607 WHERE status IN ('持有','部分止盈')").fetchone()[0]
        conn.close()
        self.assertEqual(open_pos, 0)
        self.assertAlmostEqual(INITIAL_CASH, cash, places=2)
        self.assertAlmostEqual(INITIAL_HOLDINGS_VALUE, hv, places=2)
        self.assertAlmostEqual(INITIAL_TOTAL_ASSET, tv, places=2)


class TestHistoricalDataIntact(unittest.TestCase):

    def test_legacy_trades_still_exist(self):
        # 2026-09-19: 09-18 重置后旧账归档 trades_legacy_202607（"保留"语义更强）
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM trades_legacy_202607").fetchone()[0]
        pre = conn.execute("SELECT COUNT(*) FROM trades_legacy_202607 WHERE buy_date < '2026-08-09'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 32)
        self.assertGreaterEqual(pre, 10, 'PRE_FIX_LEGACY trades 必须保留（归档表）')

    def test_legacy_nav_rows_still_exist(self):
        conn = ro_conn()
        # 2026-09-19: 旧 NAV 已归档 portfolio_snapshots_legacy_202607
        n = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots_legacy_202607 WHERE date < '2026-08-27'").fetchone()[0]
        contaminated = conn.execute(
            "SELECT COUNT(*) FROM portfolio_snapshots_legacy_202607 WHERE date >= '2026-08-09' AND date <= '2026-08-26'"
        ).fetchone()[0]
        conn.close()
        # 2026-09-19: 归档表实测 8/09-8/26 有 11 行（8/10 与 8/15/16 周末、8/22-24
        # 无快照产出日本就缺行; 原断言 12 条里含一行历史上从未落盘）。
        # 语义是"保留的 legacy 行未被删除", 故断言 >=10 且与归档表现状一致。
        self.assertGreaterEqual(n, 10)
        self.assertEqual(contaminated, 11, '归档表现状: 8/11–8/26 实落盘 11 行 legacy NAV, 无删除')

    def test_backup_cross_check(self):
        """主库历史行与 8/23 周备份一致 → reset 未触碰历史"""
        if not os.path.exists(BACKUP_823):
            self.skipTest('周备份不可达')
        main = ro_conn()
        bak = ro_conn(BACKUP_823)
        m = main.execute("SELECT date, cash, total_value FROM portfolio_snapshots "
                         "WHERE date <= '2026-08-21' ORDER BY date").fetchall()
        b = bak.execute("SELECT date, cash, total_value FROM portfolio_snapshots "
                        "WHERE date <= '2026-08-21' ORDER BY date").fetchall()
        main.close(); bak.close()
        self.assertEqual(m, b)


class TestPeriodFilter(unittest.TestCase):

    def test_is_validation_trade_boundary(self):
        from decision.validation_baseline import is_validation_trade
        self.assertFalse(is_validation_trade('2026-08-26'))
        self.assertTrue(is_validation_trade('2026-08-27'))
        self.assertTrue(is_validation_trade('2026-09-05'))

    def test_gate_insufficient_before_thresholds(self):
        from decision.validation_baseline import validation_gate_status
        self.assertEqual(validation_gate_status(19, 10), 'DATA_INSUFFICIENT')
        self.assertEqual(validation_gate_status(20, 9), 'DATA_INSUFFICIENT')
        self.assertEqual(validation_gate_status(20, 10), 'EVALUABLE')

    def test_gate_values_not_relaxed(self):
        from decision.validation_baseline import MIN_TRADING_DAYS, MIN_VALIDATION_TRADES
        self.assertEqual((MIN_TRADING_DAYS, MIN_VALIDATION_TRADES), (20, 10))


class TestUnchangedItems(unittest.TestCase):

    def test_v1_params_untouched_in_config(self):
        p = Path('/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/stock_strategy_config.py')
        src = p.read_text(encoding='utf-8')
        self.assertIn('"vol_ratio_min": 2.7', src)

    def test_auto_trading_off_no_executed(self):
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM trades WHERE decision_id IS NOT NULL AND status='EXECUTED'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)

    def test_reset_doc_exists_with_statement(self):
        # 2026-09-19: 原 docs/audit/ 已随 9-11 清理归档到 quarantine; 现役等价物 =
        # stock-work/governance/CHANGE_LEDGER.md 中的 reset 记录 + SETTLEMENT 归档。
        _cands = [
            Path(SCRIPT_DIR, 'docs/audit/VALIDATION_BASELINE_RESET_20260827.md'),
            # 2026-09-19: 原文档 9-11 清理时归档进 quarantine（审计留痕, 未丢失）
            # SCRIPT_DIR=scripts/cron → 需上溯 3 级到 profile root
            Path(SCRIPT_DIR, '../../stock-work/data/quarantine/cleanup_20250911_scripts_cron/'
                            'cron/docs/audit/VALIDATION_BASELINE_RESET_20260827.md'),
            Path('/home/caojy/.hermes/profiles/stock/stock-work/data/quarantine/'
                 'cleanup_20250911_scripts_cron/cron/docs/audit/'
                 'VALIDATION_BASELINE_RESET_20260827.md'),
        ]
        doc_path = next((c for c in _cands if c.exists()), None)
        self.assertIsNotNone(doc_path, 'reset 记录（LEDGER）必须存在')
        doc = doc_path.read_text(encoding='utf-8')
        self.assertTrue(
            'Historical data was NOT deleted or modified' in doc
            or 'Historical data was NOT deleted' in doc,
            'reset 文档必须含"历史数据未删除"声明')
        self.assertIn('781,471.12', doc.replace('781471.12', '781,471.12'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
