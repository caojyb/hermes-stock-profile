#!/usr/bin/env python3
"""
Backfill T+5 and T+20 outcomes for all recommendations.

Run daily after market close:
    python3 scripts/cron/track_outcomes.py --all

Or backfill specific horizons:
    python3 scripts/cron/track_outcomes.py --all --horizons t5,t20

Skips already filled horizons.
"""

import sqlite3
import sys
import time
from datetime import datetime
from heartbeat import write
from pathlib import Path

# Paths
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'stock-work'))
from core.compat_paths import MARKET_DB as _MARKET_DB
from core.compat_paths import RECOMMENDATION_POOL_DB as _RECOMMENDATION_POOL_DB
from core.compat_paths import RECOMMENDATION_OUTCOMES_DB as _RECOMMENDATION_OUTCOMES_DB
MARKET_DB = Path(_MARKET_DB)
RECOMMENDATION_DB = Path(_RECOMMENDATION_POOL_DB)
OUTCOME_DB = Path(_RECOMMENDATION_OUTCOMES_DB)


def get_trade_dates_after(ref_date: str, n: int) -> list[str]:
    """Get next N trading dates after ref_date from CSI 300."""
    conn = sqlite3.connect(MARKET_DB, timeout=30)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT date FROM klines
        WHERE code = '000300' AND date > ?
        ORDER BY date ASC
        LIMIT ?
    """, (ref_date, n))
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_close_on_date(code: str, trade_date: str) -> float | None:
    """Get close price for a stock on a specific date."""
    conn = sqlite3.connect(MARKET_DB, timeout=30)
    cur = conn.cursor()
    cur.execute("""
        SELECT close FROM klines
        WHERE code = ? AND date = ?
        LIMIT 1
    """, (code, trade_date))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _fill_horizon(out_cur, rec_id, code, entry_date, rec_price, horizon: str):
    """
    Fill one horizon (t5 or t20) for a recommendation.
    Returns dict of fields to upsert, or None if skip.
    """
    n = 5 if horizon == "t5" else 20
    n_dates = get_trade_dates_after(entry_date, n)
    if len(n_dates) < n:
        return None

    n_date = n_dates[n - 1]
    n_close = get_close_on_date(code, n_date)

    if n_close is None:
        return {
            f"{horizon}_date": n_date,
            f"{horizon}_close": None,
            f"{horizon}_return": None,
            f"{horizon}_skip_reason": "no_data",
            f"{horizon}_filled": 0,
        }

    rec_close = get_close_on_date(code, entry_date)
    if rec_close is None or rec_close <= 0:
        rec_close = rec_price
    n_return = (n_close - rec_close) / rec_close * 100

    bench_n_close = get_close_on_date("000300", n_date)
    bench_rec_close = get_close_on_date("000300", entry_date)
    bench_n_return = None
    if bench_n_close and bench_rec_close and bench_rec_close > 0:
        bench_n_return = (bench_n_close - bench_rec_close) / bench_rec_close * 100

    excess_n = None
    if n_return is not None and bench_n_return is not None:
        excess_n = n_return - bench_n_return

    return {
        f"{horizon}_date": n_date,
        f"{horizon}_close": n_close,
        f"{horizon}_return": n_return,
        f"{horizon}_skip_reason": None,
        f"{horizon}_filled": 1,
        f"bench_{horizon}_return": bench_n_return,
        f"excess_{horizon}": excess_n,
    }


def _determine_status(out_cur, rec_id: str) -> str:
    """Determine overall status based on filled/skipped horizons."""
    row = out_cur.execute(
        "SELECT t1_filled, t1_skip_reason, t5_filled, t5_skip_reason, t20_filled, t20_skip_reason FROM recommendation_outcomes WHERE rec_id = ?",
        (rec_id,)
    ).fetchone()
    if not row:
        return "pending"

    t1_filled, t1_skip, t5_filled, t5_skip, t20_filled, t20_skip = row

    # Count processed horizons (filled or skipped)
    processed = 0
    if t1_filled == 1 or t1_skip is not None:
        processed += 1
    if t5_filled == 1 or t5_skip is not None:
        processed += 1
    if t20_filled == 1 or t20_skip is not None:
        processed += 1

    if processed == 3:
        return "complete"
    elif processed > 0:
        return "partial"
    else:
        return "pending"


def _upsert_horizon(out_cur, rec_id: str, fields: dict):
    """Upsert specific horizon fields into recommendation_outcomes."""
    now = datetime.now().isoformat()
    existing = out_cur.execute(
        "SELECT id FROM recommendation_outcomes WHERE rec_id = ?", (rec_id,)
    ).fetchone()

    if existing:
        # UPDATE only provided fields + updated_at
        set_clauses = []
        values = []
        for key, value in fields.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)
        set_clauses.append("updated_at = ?")
        values.append(now)
        values.append(rec_id)
        sql = f"UPDATE recommendation_outcomes SET {', '.join(set_clauses)} WHERE rec_id = ?"
        out_cur.execute(sql, values)
    else:
        # INSERT with base fields + provided horizon fields
        columns = ["rec_id", "rec_date", "code", "tier", "tier_type", "rec_price", "rec_close"]
        placeholders = ["?", "?", "?", "?", "?", "?", "?"]
        values = [rec_id, None, None, None, None, None, None]  # Will be filled by caller if needed

        for key, value in fields.items():
            columns.append(key)
            placeholders.append("?")
            values.append(value)

        columns.append("updated_at")
        placeholders.append("?")
        values.append(now)

        sql = f"INSERT INTO recommendation_outcomes ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        out_cur.execute(sql, values)


def backfill_horizons(horizons: list[str] = None):
    """Backfill T+N outcomes for all recommendations."""
    if horizons is None:
        horizons = ["t5", "t20"]

    # Read all recommendations
    rec_conn = sqlite3.connect(RECOMMENDATION_DB, timeout=30)
    rec_cur = rec_conn.cursor()
    rec_cur.execute("""
        SELECT id, code, entry_date, entry_price, status
        FROM recommendations
    """)
    recs = rec_cur.fetchall()
    if not recs:
        print("No recommendations to backfill.")
        rec_conn.close()
        rec_conn.close()
        out_conn.close()
        return 0

    _t0 = time.time()
    out_conn = sqlite3.connect(OUTCOME_DB, timeout=30)
    out_cur = out_conn.cursor()
    updated = 0

    try:
        for rec_id, code, entry_date, rec_price, rec_status in recs:
            # Ensure base row exists
            existing = out_cur.execute(
                "SELECT id FROM recommendation_outcomes WHERE rec_id = ?", (rec_id,)
            ).fetchone()
            if not existing:
                # Insert base row
                rec_row = rec_cur.execute(
                    "SELECT tier, tier_type FROM recommendations WHERE id = ?", (rec_id,)
                ).fetchone()
                tier = rec_row[0] if rec_row else None
                tier_type = rec_row[1] if rec_row else None
                out_cur.execute("""
                    INSERT INTO recommendation_outcomes (rec_id, rec_date, code, tier, tier_type, rec_price, rec_close, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (rec_id, entry_date, code, tier, tier_type, rec_price, rec_price, "pending", datetime.now().isoformat()))

            today = datetime.now().strftime('%Y-%m-%d')
            
            # Coverage logic (4 rules):
            # 1. tN_skip_reason IS NULL → calculate
            # 2. tN_skip_reason = 'future' AND today >= tN_date → recalculate (future → filled/no_data)
            # 3. tN_skip_reason = 'no_data' → keep (data missing, don't overwrite)
            # 4. tN_filled = 1 → skip (already calculated)
            
            # Check existing outcome status for this rec
            existing_outcome = out_cur.execute(
                "SELECT t1_filled, t1_skip_reason, t1_date, t5_filled, t5_skip_reason, t5_date, t20_filled, t20_skip_reason, t20_date FROM recommendation_outcomes WHERE rec_id = ?",
                (rec_id,)
            ).fetchone()
            
            def should_calculate(horizon, existing):
                if not existing:
                    return True
                idx = {'t1': 0, 't5': 3, 't20': 6}[horizon]
                filled = existing[idx]
                skip_reason = existing[idx + 1]
                n_date = existing[idx + 2]
                
                if filled == 1:
                    return False  # Rule 4
                if skip_reason == 'no_data':
                    return False  # Rule 3
                if skip_reason == 'future':
                    if n_date is None:
                        return True  # 之前算不出日期，现在重算
                    if today >= n_date:
                        return True  # 日期已到
                    return False
                if skip_reason is None:
                    return True  # Rule 1
                return True
            
            # Fill each horizon
            for horizon in horizons:
                if not should_calculate(horizon, existing_outcome):
                    continue
                    
                n = 1 if horizon == "t1" else (5 if horizon == "t5" else 20)
                n_dates = get_trade_dates_after(entry_date, n)
                if len(n_dates) < n:
                    # T+N 日期不足（未来）
                    fields = {
                        f"{horizon}_date": None,
                        f"{horizon}_close": None,
                        f"{horizon}_return": None,
                        f"{horizon}_skip_reason": "future",
                        f"{horizon}_filled": 0,
                    }
                else:
                    n_date = n_dates[n - 1]
                    n_close = get_close_on_date(code, n_date)

                    if n_close is None:
                        # 日期已到但无数据
                        fields = {
                            f"{horizon}_date": n_date,
                            f"{horizon}_close": None,
                            f"{horizon}_return": None,
                            f"{horizon}_skip_reason": "no_data",
                            f"{horizon}_filled": 0,
                        }
                    else:
                        # 有数据，计算收益
                        rec_close = get_close_on_date(code, entry_date)
                        if rec_close is None or rec_close <= 0:
                            rec_close = rec_price
                        n_return = (n_close - rec_close) / rec_close * 100

                        bench_n_close = get_close_on_date("000300", n_date)
                        bench_rec_close = get_close_on_date("000300", entry_date)
                        bench_n_return = None
                        if bench_n_close and bench_rec_close and bench_rec_close > 0:
                            bench_n_return = (bench_n_close - bench_rec_close) / bench_rec_close * 100

                        excess_n = None
                        if n_return is not None and bench_n_return is not None:
                            excess_n = n_return - bench_n_return

                        fields = {
                            f"{horizon}_date": n_date,
                            f"{horizon}_close": n_close,
                            f"{horizon}_return": n_return,
                            f"{horizon}_skip_reason": None,
                            f"{horizon}_filled": 1,
                            f"bench_{horizon}_return": bench_n_return,
                            f"excess_{horizon}": excess_n,
                        }

                _upsert_horizon(out_cur, rec_id, fields)

            # Update status
            status = _determine_status(out_cur, rec_id)
            out_cur.execute(
                "UPDATE recommendation_outcomes SET status = ?, updated_at = ? WHERE rec_id = ?",
                (status, datetime.now().isoformat(), rec_id)
            )

            updated += 1

        out_conn.commit()
        cost_ms = int((time.time() - _t0) * 1000)
        write('track-outcomes-daily', 'ok', detail=f'processed={updated}', cost_ms=cost_ms, expected_interval_seconds=86400)
        print(f"Backfilled {', '.join(horizons)} for {updated} recommendations.")
        return 0  # 0 = success
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1
    finally:
        out_conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Backfill all recommendations")
    parser.add_argument("--horizons", type=str, default="t5,t20", help="Comma-separated horizons to backfill (t5,t20)")
    args = parser.parse_args()

    if args.all or True:  # Always backfill all
        horizons = [h.strip() for h in args.horizons.split(",")]
        rc = backfill_horizons(horizons)
        if rc == 0:
            from aggregate_performance import aggregate
            aggregate()
        sys.exit(rc)
