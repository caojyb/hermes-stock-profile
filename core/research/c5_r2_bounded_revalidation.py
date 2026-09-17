#!/usr/bin/env python3
"""
c5_r2_bounded_revalidation.py — M9.1-C5-R2 Bounded Stage 1 + Stage 2 Revalidation.

Runs:
- Stage 1: 1 fold × 8 variants × 3 horizons = 24 experiments
- Stage 2: 1 strategy × 8 folds × 3 horizons = 24 experiments

Requires C5-R2 pre-Stage 1 gates to have passed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Optional

# ---------------------------------------------------------------------------
# Paths / safety
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data" / "research"
DOCS = BASE / "docs"
DB_PATH = BASE / "data" / "production" / "market_cache.db"

for d in (ART, DOCS):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Frozen gates
# ---------------------------------------------------------------------------
FROZEN_GATES = {
    "QUALIFICATION_STATUS": "INSUFFICIENT_EVIDENCE",
    "D8_H_ALLOWED": False,
    "PRODUCTION_PROMOTION": False,
    "FUNDAMENTAL_ROLE": "OPTIONAL_EVIDENCE",
    "OPPORTUNITY_VALIDATION_STATUS": "UNSTABLE",
    "REGIME_AWARE_OPPORTUNITY_STATUS": "NO_IMPROVEMENT",
    "NO_NEXT_ALPHA_SOURCE_READY": True,
    "C5_R_EVIDENCE_STATUS": "INVALID_PENDING_PIPELINE_AUDIT",
}

# ---------------------------------------------------------------------------
# VOLUME variant spec (pre-frozen, same as C5-R)
# ---------------------------------------------------------------------------
VOLUME_SPEC = {
    "spec_version": "c5_r_volume_v1",
    "frozen_at": "2026-09-08T00:00:00",
    "families": {
        "V1_VOLUME_TREND": {
            "V1A": {"lookback": 20, "method": "slope", "normalization": "raw", "direction": "POSITIVE"},
            "V1B": {"lookback": 60, "method": "slope", "normalization": "raw", "direction": "POSITIVE"},
        },
        "V2_RELATIVE_VOLUME": {
            "V2A": {"lookback": 60, "method": "percentile_rank", "normalization": "percentile", "direction": "POSITIVE"},
            "V2B": {"lookback": 20, "method": "percentile_rank", "normalization": "percentile", "direction": "POSITIVE"},
        },
        "V3_VOLUME_MOMENTUM": {
            "V3A": {"lookback": 5, "lookback2": 20, "method": "acceleration", "normalization": "raw", "direction": "POSITIVE"},
            "V3B": {"lookback": 10, "lookback2": 60, "method": "acceleration", "normalization": "raw", "direction": "POSITIVE"},
        },
        "V4_PRICE_VOLUME_CONFIRMATION": {
            "V4A": {"lookback": 20, "method": "correlation", "normalization": "raw", "direction": "POSITIVE"},
            "V4B": {"lookback": 60, "method": "covariance", "normalization": "raw", "direction": "POSITIVE"},
        },
    },
    "horizons": [5, 10, 20],
    "min_universe_size": 100,
    "pit_policy": "EOD_T0_CLOSE",
}

BENCHMARK = "000300"

# ---------------------------------------------------------------------------
# Data access with canonical dedup
# ---------------------------------------------------------------------------
def get_universe_at(date: str) -> List[str]:
    con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute("SELECT DISTINCT code FROM klines WHERE date=?", (date,))
    symbols = [r[0] for r in cur.fetchall()]
    con.close()
    return symbols


def bulk_get_klines(symbols: List[str], start: str, end: str) -> Dict[str, List[Dict]]:
    if not symbols:
        return {}
    con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    cur = con.cursor()
    placeholders = ','.join(['?'] * len(symbols))
    cur.execute(
        f"SELECT code, date, open, close, high, low, volume FROM klines "
        f"WHERE code IN ({placeholders}) AND date>=? AND date<=? ORDER BY code, date",
        symbols + [start, end]
    )
    rows = cur.fetchall()
    con.close()

    result = defaultdict(list)
    seen = set()
    for code, date, open_, close, high, low, volume in rows:
        key = (code, date)
        if key in seen:
            continue
        seen.add(key)
        result[code].append({
            'date': date,
            'open': open_,
            'close': close,
            'high': high,
            'low': low,
            'volume': volume,
        })
    return result


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------
def compute_signal(klines: List[Dict], variant: str, params: dict) -> Optional[float]:
    if len(klines) < 2:
        return None

    lookback = params.get("lookback", 20)
    lookback2 = params.get("lookback2", lookback * 3)
    method = params.get("method", "slope")

    volumes = [k['volume'] for k in klines[-lookback2:]]
    closes = [k['close'] for k in klines[-lookback2:]]

    if not volumes or len(volumes) < lookback:
        return None

    if variant in ["V1A", "V1B"]:
        recent = volumes[-lookback:]
        n = len(recent)
        if n < 2:
            return None
        x_mean = (n - 1) / 2
        y_mean = sum(recent) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(recent))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den == 0:
            return None
        slope = num / den
        return slope / max(1, y_mean)

    elif variant in ["V2A", "V2B"]:
        current = volumes[-1]
        hist = volumes[-lookback2:]
        if not hist:
            return None
        rank = sum(1 for v in hist if v <= current) / len(hist)
        return rank * 100.0

    elif variant in ["V3A", "V3B"]:
        if len(volumes) < lookback2:
            return None
        recent_avg = sum(volumes[-lookback:]) / lookback
        prior_avg = sum(volumes[-lookback2:-lookback]) / (lookback2 - lookback)
        if prior_avg == 0:
            return None
        return (recent_avg - prior_avg) / prior_avg

    elif variant in ["V4A", "V4B"]:
        if len(closes) < lookback or len(volumes) < lookback:
            return None
        price_changes = [(closes[i] - closes[i-1]) / max(1, closes[i-1]) for i in range(1, len(closes))]
        vol_changes = [(volumes[i] - volumes[i-1]) / max(1, volumes[i-1]) for i in range(1, len(volumes))]
        n = min(len(price_changes), len(vol_changes))
        if n < 2:
            return None
        price_changes = price_changes[-n:]
        vol_changes = vol_changes[-n:]

        if method == "correlation":
            mean_p = sum(price_changes) / n
            mean_v = sum(vol_changes) / n
            cov = sum((p - mean_p) * (v - mean_v) for p, v in zip(price_changes, vol_changes)) / n
            std_p = (sum((p - mean_p) ** 2 for p in price_changes) / n) ** 0.5
            std_v = (sum((v - mean_v) ** 2 for v in vol_changes) / n) ** 0.5
            if std_p == 0 or std_v == 0:
                return None
            return cov / (std_p * std_v)
        else:
            mean_p = sum(price_changes) / n
            mean_v = sum(vol_changes) / n
            return sum((p - mean_p) * (v - mean_v) for p, v in zip(price_changes, vol_changes)) / n

    return None


# ---------------------------------------------------------------------------
# Target computation
# ---------------------------------------------------------------------------
def compute_targets_bulk(symbols: List[str], decision_time: str, horizon: int,
                         symbol_klines: Dict[str, List[Dict]], bench_klines: List[Dict]) -> Dict[str, float]:
    if not bench_klines:
        return {}

    targets = {}
    bench_len = len(bench_klines)

    for sym in symbols:
        klines = symbol_klines.get(sym, [])
        if len(klines) < horizon + 1:
            continue

        entry_idx = None
        for i, k in enumerate(klines):
            if k['date'] == decision_time:
                entry_idx = i + 1
                break

        if entry_idx is None or entry_idx >= len(klines):
            continue

        exit_idx = entry_idx + horizon - 1
        if exit_idx >= len(klines):
            continue

        entry_price = klines[entry_idx]['open']
        exit_price = klines[exit_idx]['close']
        if entry_price <= 0 or exit_price <= 0:
            continue
        symbol_return = (exit_price - entry_price) / entry_price

        bench_entry_idx = None
        for i, k in enumerate(bench_klines):
            if k['date'] == decision_time:
                bench_entry_idx = i + 1
                break

        if bench_entry_idx is None or bench_entry_idx >= bench_len:
            continue

        bench_exit_idx = bench_entry_idx + horizon - 1
        if bench_exit_idx >= bench_len:
            continue

        bench_entry = bench_klines[bench_entry_idx]['open']
        bench_exit = bench_klines[bench_exit_idx]['close']
        if bench_entry <= 0 or bench_exit <= 0:
            continue
        bench_return = (bench_exit - bench_entry) / bench_entry

        targets[sym] = symbol_return - bench_return

    return targets


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------
def run_experiments_bulk(fold_id: str, date: str, universe: List[str],
                         variant_ids: List[tuple], horizon: int,
                         symbol_klines: Dict[str, List[Dict]],
                         bench_klines: List[Dict]) -> List[Dict]:
    results = []

    max_lookback = 60 * 2

    variant_signals = {}
    for vid, family_name, params in variant_ids:
        signals = []
        for sym in universe:
            klines = symbol_klines.get(sym, [])
            sig = compute_signal(klines, vid, params)
            if sig is not None:
                signals.append((sym, sig))
        variant_signals[vid] = signals

    targets = compute_targets_bulk(universe, date, horizon, symbol_klines, bench_klines)

    for vid, family_name, params in variant_ids:
        signals = variant_signals.get(vid, [])
        valid = [(sym, sig, targets[sym]) for sym, sig in signals if sym in targets]

        if len(valid) >= 10:
            valid_sorted = sorted(valid, key=lambda x: x[1])
            ranks = list(range(len(valid_sorted)))
            targs = [v[2] for v in valid_sorted]
            n = len(ranks)
            mean_r = sum(ranks) / n
            mean_t = sum(targs) / n
            num = sum((r - mean_r) * (t - mean_t) for r, t in zip(ranks, targs))
            dr = (sum((r - mean_r)**2 for r in ranks))**0.5
            dt = (sum((t - mean_t)**2 for t in targs))**0.5
            ic = num / (dr * dt) if dr > 0 and dt > 0 else 0.0

            top_q = valid_sorted[:max(1, n//5)]
            mean_excess = sum(t for _, _, t in top_q) / len(top_q)
            hit_rate = sum(1 for _, _, t in top_q if t > 0) / len(top_q)

            hhi = sum((1.0/len(top_q))**2 for _ in top_q) if top_q else 0.0
        else:
            ic = 0.0
            mean_excess = 0.0
            hit_rate = 0.0
            hhi = 0.0

        results.append({
            "fold_id": fold_id,
            "horizon": horizon,
            "variant": vid,
            "family": family_name,
            "decision_time": date,
            "n_signals": len(signals),
            "n_valid_targets": len(valid),
            "ic": ic,
            "mean_excess_return": mean_excess,
            "hit_rate": hit_rate,
            "hhi": hhi,
        })

    return results


# ---------------------------------------------------------------------------
# Fold construction
# ---------------------------------------------------------------------------
def build_folds(calendar: List[str], n_folds: int = 8) -> Dict[str, List[str]]:
    folds = {}
    fold_size = len(calendar) // n_folds
    for i in range(n_folds):
        fold_id = f"fold_{i+1:03d}"
        start_idx = i * fold_size
        end_idx = (i + 1) * fold_size if i < n_folds - 1 else len(calendar)
        folds[fold_id] = calendar[start_idx:end_idx]
    return folds


# ---------------------------------------------------------------------------
# Stage 1: 1 fold × 8 variants × 3 horizons = 24 experiments
# ---------------------------------------------------------------------------
def run_stage1(folds: Dict[str, List[str]]) -> List[Dict]:
    results = []
    stage1_fold = "fold_004"
    stage1_dates = folds.get(stage1_fold, [])

    # Use 1 representative date for exactly 24 experiments
    sample_dates = [stage1_dates[len(stage1_dates) // 2]] if stage1_dates else []

    variant_ids = []
    for family_name, family in VOLUME_SPEC["families"].items():
        for vid, params in family.items():
            variant_ids.append((vid, family_name, params))

    for date in sample_dates:
        universe = get_universe_at(date)
        if len(universe) < VOLUME_SPEC["min_universe_size"]:
            continue

        max_lookback = 60 * 2
        start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=max_lookback * 2)
        start = start_dt.strftime("%Y-%m-%d")
        end_dt = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=20*2)
        end = end_dt.strftime("%Y-%m-%d")

        symbol_klines = bulk_get_klines(universe, start, end)
        bench_klines = bulk_get_klines([BENCHMARK], start, end).get(BENCHMARK, [])

        for horizon in VOLUME_SPEC["horizons"]:
            batch = run_experiments_bulk(stage1_fold, date, universe, variant_ids, horizon,
                                         symbol_klines, bench_klines)
            results.extend(batch)

    return results


# ---------------------------------------------------------------------------
# Stage 2: 1 pre-registered strategy × 8 folds × 3 horizons = 24 experiments
# ---------------------------------------------------------------------------
# Pre-registered representative VOLUME strategy: V1A (V1_VOLUME_TREND, lookback=20, slope)
STAGE2_VARIANT = ("V1A", "V1_VOLUME_TREND", {"lookback": 20, "method": "slope", "normalization": "raw", "direction": "POSITIVE"})


def run_stage2(folds: Dict[str, List[str]]) -> List[Dict]:
    results = []
    variant_ids = [STAGE2_VARIANT]

    for fold_id, fold_dates in folds.items():
        # Sample 1 date per fold
        sample_dates = [fold_dates[len(fold_dates) // 2]] if fold_dates else []

        for date in sample_dates:
            universe = get_universe_at(date)
            if len(universe) < VOLUME_SPEC["min_universe_size"]:
                continue

            max_lookback = 60 * 2
            start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=max_lookback * 2)
            start = start_dt.strftime("%Y-%m-%d")
            end_dt = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=20*2)
            end = end_dt.strftime("%Y-%m-%d")

            symbol_klines = bulk_get_klines(universe, start, end)
            bench_klines = bulk_get_klines([BENCHMARK], start, end).get(BENCHMARK, [])

            for horizon in VOLUME_SPEC["horizons"]:
                batch = run_experiments_bulk(fold_id, date, universe, variant_ids, horizon,
                                             symbol_klines, bench_klines)
                results.extend(batch)

    return results


# ---------------------------------------------------------------------------
# Stage 1 hard gate check
# ---------------------------------------------------------------------------
def check_stage1_gate(stage1_results: List[Dict]) -> Dict:
    if not stage1_results:
        return {"stage1_status": "STAGE1_INVALID", "reason": "no_experiments"}

    # Data checks
    zero_target_experiments = [r for r in stage1_results if r["n_valid_targets"] == 0]
    if len(zero_target_experiments) == len(stage1_results):
        return {"stage1_status": "STAGE1_INVALID", "reason": "all_zero_targets"}

    # Signal checks
    nan_explosion = any(r["ic"] != r["ic"] for r in stage1_results)  # NaN check
    inf_signals = any(abs(r["ic"]) == float('inf') for r in stage1_results)
    if nan_explosion or inf_signals:
        return {"stage1_status": "STAGE1_INVALID", "reason": "signal_contamination"}

    # Economic checks
    all_excess = [r["mean_excess_return"] for r in stage1_results if r["n_valid_targets"] > 0]
    if not all_excess:
        return {"stage1_status": "STAGE1_INVALID", "reason": "no_valid_excess"}

    max_abs_excess = max(abs(min(all_excess)), abs(max(all_excess)))
    if max_abs_excess > 5.0:
        return {"stage1_status": "STAGE1_INVALID", "reason": f"extreme_excess_{max_abs_excess}"}

    # Predictive checks
    ics = [r["ic"] for r in stage1_results if r["n_valid_targets"] > 0]
    mean_ic = sum(ics) / len(ics) if ics else 0.0
    median_ic = sorted(ics)[len(ics)//2] if ics else 0.0

    return {
        "stage1_status": "STAGE1_VALIDATED",
        "n_experiments": len(stage1_results),
        "n_valid_experiments": len([r for r in stage1_results if r["n_valid_targets"] > 0]),
        "mean_ic": mean_ic,
        "median_ic": median_ic,
        "max_abs_excess": max_abs_excess,
        "zero_target_count": len(zero_target_experiments),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("M9.1-C5-R2 Bounded Revalidation")
    print("=" * 60)

    # Load calendar
    con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute("SELECT DISTINCT date FROM klines ORDER BY date")
    global_calendar = [r[0] for r in cur.fetchall()]
    con.close()

    print(f"Global calendar: {len(global_calendar)} dates")

    folds = build_folds(global_calendar, n_folds=8)
    print(f"Folds: {len(folds)}")

    # ------------------------------------------------------------------
    # Stage 1
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("STAGE 1: 1 fold × 8 variants × 3 horizons = 24 experiments")
    print("=" * 60)

    stage1_results = run_stage1(folds)
    print(f"Stage 1 completed: {len(stage1_results)} experiments")

    stage1_gate = check_stage1_gate(stage1_results)
    print(f"Stage 1 gate: {stage1_gate['stage1_status']}")
    if "reason" in stage1_gate:
        print(f"  Reason: {stage1_gate['reason']}")

    stage1_summary = {
        "n_experiments": len(stage1_results),
        "gate": stage1_gate,
        "results": stage1_results,
    }

    (ART / "c5_r2_stage1.json").write_text(
        json.dumps(stage1_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {ART / 'c5_r2_stage1.json'}")

    # ------------------------------------------------------------------
    # Stage 2 (only if Stage 1 passed)
    # ------------------------------------------------------------------
    stage2_results = []
    stage2_status = "NOT_EXECUTED"

    if stage1_gate["stage1_status"] == "STAGE1_VALIDATED":
        print("\n" + "=" * 60)
        print("STAGE 2: 1 strategy × 8 folds × 3 horizons = 24 experiments")
        print(f"Pre-registered strategy: {STAGE2_VARIANT[0]} ({STAGE2_VARIANT[1]})")
        print("=" * 60)

        stage2_results = run_stage2(folds)
        print(f"Stage 2 completed: {len(stage2_results)} experiments")

        # Fold-level summary
        fold_summary = defaultdict(list)
        for r in stage2_results:
            fold_summary[r["fold_id"]].append(r)

        fold_metrics = {}
        for fold_id, fold_results in fold_summary.items():
            valid = [r for r in fold_results if r["n_valid_targets"] > 0]
            fold_metrics[fold_id] = {
                "n_experiments": len(fold_results),
                "n_valid": len(valid),
                "mean_ic": sum(r["ic"] for r in valid) / len(valid) if valid else 0.0,
                "median_ic": sorted([r["ic"] for r in valid])[len(valid)//2] if valid else 0.0,
                "mean_excess": sum(r["mean_excess_return"] for r in valid) / len(valid) if valid else 0.0,
                "hit_rate": sum(r["hit_rate"] for r in valid) / len(valid) if valid else 0.0,
            }

        # Determine evidence status
        all_ics = [r["ic"] for r in stage2_results if r["n_valid_targets"] > 0]
        positive_folds = sum(1 for m in fold_metrics.values() if m["mean_ic"] > 0)
        mean_ic_all = sum(all_ics) / len(all_ics) if all_ics else 0.0

        if mean_ic_all > 0.02 and positive_folds >= 6:
            stage2_status = "VOLUME_PRELIMINARY_RESEARCH_CANDIDATE"
        elif mean_ic_all > 0.01 and positive_folds >= 4:
            stage2_status = "VOLUME_PRELIMINARY_RESEARCH_CANDIDATE"
        elif mean_ic_all > 0:
            stage2_status = "VOLUME_INSUFFICIENT_EVIDENCE"
        else:
            stage2_status = "VOLUME_INSUFFICIENT_EVIDENCE"

        stage2_summary = {
            "n_experiments": len(stage2_results),
            "strategy": STAGE2_VARIANT[0],
            "family": STAGE2_VARIANT[1],
            "status": stage2_status,
            "fold_metrics": fold_metrics,
            "results": stage2_results,
        }

        (ART / "c5_r2_stage2.json").write_text(
            json.dumps(stage2_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Stage 2 evidence status: {stage2_status}")
        print(f"Saved: {ART / 'c5_r2_stage2.json'}")
    else:
        print("\nStage 2 NOT executed: Stage 1 failed validation.")
        stage2_status = "NOT_EXECUTED"

    # ------------------------------------------------------------------
    # Final status
    # ------------------------------------------------------------------
    final_status = {
        "c5_r_original_status": "INVALID_EVIDENCE",
        "c5_r2_status": stage1_gate["stage1_status"],
        "volume_evidence_status": stage2_status if stage2_status != "NOT_EXECUTED" else "C5_R_PIPELINE_INVALID",
        "gates": FROZEN_GATES,
        "artifacts": [
            "data/research/c5_r2_kline_integrity.json",
            "data/research/c5_r2_target_reconciliation.json",
            "data/research/c5_r2_economic_sanity.json",
            "data/research/c5_r2_duplicate_audit.json",
            "data/research/c5_r2_bug_fix_audit.json",
            "data/research/c5_r2_stage1_gate.json",
            "data/research/c5_r2_stage1.json",
            "data/research/c5_r2_stage2.json",
            "data/research/c5_r2_final_status.json",
            "docs/M9_1-C5-R2_KLINE_DEDUP_AND_BOUNDED_REVALIDATION.md",
        ],
    }

    (ART / "c5_r2_final_status.json").write_text(
        json.dumps(final_status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("C5-R2 BOUNDED REVALIDATION COMPLETE")
    print("=" * 60)
    print(f"Stage 1: {stage1_gate['stage1_status']}")
    print(f"Stage 2: {stage2_status}")
    print(f"Final volume evidence status: {final_status['volume_evidence_status']}")
    print(f"\nArtifacts in {ART}")
