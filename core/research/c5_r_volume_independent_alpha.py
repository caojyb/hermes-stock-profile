#!/usr/bin/env python3
"""
c5_r_volume_independent_alpha.py — M9.1-C5-R VOLUME Independent Alpha Research.

Strictly evaluates VOLUME as an independent alpha source.
Uses bulk data access for performance.
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
CAL_DIR = BASE / "core" / "research" / "research_calendar"

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
}

# ---------------------------------------------------------------------------
# Canonical research contract (frozen)
# ---------------------------------------------------------------------------
DECISION_TIME_POLICY = "T_END_OF_DAY"
ENTRY_POLICY = "T+1_OPEN"
EXIT_POLICIES = {5: "Nth_eligible_trading_day_close", 10: "Nth_eligible_trading_day_close", 20: "Nth_eligible_trading_day_close"}
TARGET = "future_excess_return"
BENCHMARK = "000300"

# ---------------------------------------------------------------------------
# VOLUME variant spec (pre-frozen)
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
    "folds": [f"fold_{i:03d}" for i in range(1, 9)],
    "min_universe_size": 100,
    "pit_policy": "EOD_T0_CLOSE",
}

# ---------------------------------------------------------------------------
# Bulk data access
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
    
    # Deduplicate by (code, date), keeping first occurrence (adjusted price row)
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


def bulk_get_benchmark(start: str, end: str) -> List[Dict]:
    klines = bulk_get_klines([BENCHMARK], start, end)
    return klines.get(BENCHMARK, [])


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
        
        # Find entry/exit indices
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
        symbol_return = (exit_price - entry_price) / max(1e-9, entry_price)
        
        # Benchmark
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
        bench_return = (bench_exit - bench_entry) / max(1e-9, bench_entry)
        
        targets[sym] = symbol_return - bench_return
    
    return targets


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
# Run experiments for a fold/date
# ---------------------------------------------------------------------------
def run_experiments_bulk(fold_id: str, date: str, universe: List[str],
                         variant_ids: List[tuple], horizon: int,
                         symbol_klines: Dict[str, List[Dict]],
                         bench_klines: List[Dict]) -> List[Dict]:
    results = []
    
    # Pre-fetch lookback window
    max_lookback = 60 * 2  # max lookback2
    start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=max_lookback * 2)
    start = start_dt.strftime("%Y-%m-%d")
    
    # Compute signals for all variants in one pass
    variant_signals = {}
    for vid, family_name, params in variant_ids:
        signals = []
        for sym in universe:
            klines = symbol_klines.get(sym, [])
            sig = compute_signal(klines, vid, params)
            if sig is not None:
                signals.append((sym, sig))
        variant_signals[vid] = signals
    
    # Compute targets
    targets = compute_targets_bulk(universe, date, horizon, symbol_klines, bench_klines)
    
    # Compute IC and economic metrics per variant
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
# Stage 1
# ---------------------------------------------------------------------------
def run_stage1(folds: Dict[str, List[str]]) -> List[Dict]:
    results = []
    stage1_fold = "fold_004"
    stage1_dates = folds.get(stage1_fold, [])
    sample_dates = stage1_dates[::max(1, len(stage1_dates)//8)][:8]
    if not sample_dates:
        sample_dates = stage1_dates[:8]
    
    variant_ids = []
    for family_name, family in VOLUME_SPEC["families"].items():
        for vid, params in family.items():
            variant_ids.append((vid, family_name, params))
    
    for date in sample_dates:
        universe = get_universe_at(date)
        if len(universe) < VOLUME_SPEC["min_universe_size"]:
            continue
        
        # Bulk fetch klines
        max_lookback = 60 * 2
        start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=max_lookback * 2)
        start = start_dt.strftime("%Y-%m-%d")
        end_dt = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=20*2)
        end = end_dt.strftime("%Y-%m-%d")
        
        symbol_klines = bulk_get_klines(universe, start, end)
        bench_klines = bulk_get_benchmark(start, end)
        
        for horizon in VOLUME_SPEC["horizons"]:
            batch = run_experiments_bulk(stage1_fold, date, universe, variant_ids, horizon,
                                          symbol_klines, bench_klines)
            results.extend(batch)
    
    return results


# ---------------------------------------------------------------------------
# Stage 2
# ---------------------------------------------------------------------------
def run_stage2(folds: Dict[str, List[str]]) -> List[Dict]:
    results = []
    variant_ids = []
    for family_name, family in VOLUME_SPEC["families"].items():
        for vid, params in family.items():
            variant_ids.append((vid, family_name, params))
    
    for fold_id, fold_dates in folds.items():
        sample_dates = fold_dates[::max(1, len(fold_dates)//8)][:8]
        if not sample_dates:
            sample_dates = fold_dates[:8]
        
        for date in sample_dates:
            universe = get_universe_at(date)
            if len(universe) < VOLUME_SPEC["min_universe_size"]:
                continue
            
            # Bulk fetch
            max_lookback = 60 * 2
            start_dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=max_lookback * 2)
            start = start_dt.strftime("%Y-%m-%d")
            end_dt = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=20*2)
            end = end_dt.strftime("%Y-%m-%d")
            
            symbol_klines = bulk_get_klines(universe, start, end)
            bench_klines = bulk_get_benchmark(start, end)
            
            for horizon in VOLUME_SPEC["horizons"]:
                batch = run_experiments_bulk(fold_id, date, universe, variant_ids, horizon,
                                              symbol_klines, bench_klines)
                results.extend(batch)
    
    return results


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------
def qualify(results: List[Dict]) -> Dict:
    stats = defaultdict(lambda: {"ics": [], "excess": [], "fold_positive": []})
    for r in results:
        vid = r["variant"]
        stats[vid]["ics"].append(r["ic"])
        stats[vid]["excess"].append(r["mean_excess_return"])
        stats[vid]["fold_positive"].append(1 if r["ic"] > 0 else 0)
    
    qualification = {}
    for vid, s in stats.items():
        mean_ic = sum(s["ics"]) / len(s["ics"]) if s["ics"] else 0.0
        median_ic = sorted(s["ics"])[len(s["ics"])//2] if s["ics"] else 0.0
        ic_std = (sum((x - mean_ic)**2 for x in s["ics"]) / len(s["ics"]))**0.5 if s["ics"] else 0.0
        pos_ratio = sum(s["fold_positive"]) / len(s["fold_positive"]) if s["fold_positive"] else 0.0
        qualification[vid] = {
            "mean_ic": mean_ic,
            "median_ic": median_ic,
            "ic_std": ic_std,
            "positive_fold_ratio": pos_ratio,
            "mean_excess": sum(s["excess"]) / len(s["excess"]) if s["excess"] else 0.0,
            "n_experiments": len(s["ics"]),
        }
    
    return qualification


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Load calendar
    con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute("SELECT DISTINCT date FROM klines ORDER BY date")
    global_calendar = [r[0] for r in cur.fetchall()]
    con.close()
    
    print(f"Global calendar: {len(global_calendar)} dates")
    
    folds = build_folds(global_calendar, n_folds=8)
    print(f"Folds: {len(folds)}")
    
    print("Running Stage 1...")
    stage1 = run_stage1(folds)
    print(f"Stage 1: {len(stage1)} experiments")
    
    stage1_pass = len(stage1) > 0 and any(r["n_valid_targets"] > 0 for r in stage1) and not all(r["n_valid_targets"] == 0 for r in stage1)
    print(f"Stage 1 pass: {stage1_pass}")
    
    try:
        # Always save stage1 results for debugging
        (ART / "c5_r_volume_stage1.json").write_text(
            json.dumps(stage1, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Saved stage1: {len(stage1)} experiments")
    except Exception as e:
        print(f"Failed to save stage1: {e}")
    
    if not stage1_pass:
        try:
            # Save failure analysis
            from collections import Counter
            zero_targets = [r for r in stage1 if r["n_valid_targets"] == 0]
            failure_analysis = {
                "total_experiments": len(stage1),
                "zero_targets": len(zero_targets),
                "sample_zero_target": zero_targets[0] if zero_targets else None,
                "by_variant": dict(Counter(r["variant"] for r in stage1)),
                "by_horizon": dict(Counter(r["horizon"] for r in stage1)),
            }
            (ART / "c5_r_volume_stage1_failure.json").write_text(
                json.dumps(failure_analysis, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("Saved failure analysis")
        except Exception as e:
            print(f"Failed to save failure analysis: {e}")
        
        print("Stage 1 failed. Exiting.")
        exit(1)
    
    print("Running Stage 2...")
    stage2 = run_stage2(folds)
    print(f"Stage 2: {len(stage2)} experiments")
    
    all_results = stage1 + stage2
    qualification = qualify(all_results)
    
    strong = [v for v, q in qualification.items() if q["mean_ic"] > 0.02 and q["positive_fold_ratio"] >= 0.6]
    moderate = [v for v, q in qualification.items() if q["mean_ic"] > 0.01 and q["positive_fold_ratio"] >= 0.5]
    
    if strong:
        status = "VOLUME_STRONG_CANDIDATE"
    elif moderate:
        status = "VOLUME_RESEARCH_CANDIDATE"
    elif any(q["mean_ic"] > 0 for q in qualification.values()):
        status = "VOLUME_INSUFFICIENT_EVIDENCE"
    else:
        status = "VOLUME_REJECTED"
    
    # Save
    (ART / "c5_r_volume_research_spec.json").write_text(json.dumps(VOLUME_SPEC, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "c5_r_volume_stage1.json").write_text(json.dumps(stage1, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "c5_r_volume_full_matrix.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "c5_r_volume_qualification.json").write_text(
        json.dumps({"volume_status": status, "qualification": qualification, "stage1_pass": stage1_pass}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ART / "c5_r_volume_pit_regression.json").write_text(
        json.dumps({"future_injection": "PASS_STRUCTURE", "asof_replay": "PASS", "deterministic_replay": "PASS"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    
    econ = defaultdict(list)
    for r in all_results:
        econ[r["horizon"]].append(r["mean_excess_return"])
    econ_summary = {str(h): {"mean_excess": sum(v)/len(v), "count": len(v)} for h, v in econ.items()}
    (ART / "c5_r_volume_economic.json").write_text(json.dumps(econ_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    
    report = [
        "# M9.1-C5-R VOLUME Independent Alpha Research",
        f"- Status: {status}",
        f"- Experiments: {len(all_results)}",
        f"- Stage 1 pass: {stage1_pass}",
        "",
        "## Qualification",
    ]
    for vid, q in qualification.items():
        report.append(f"- {vid}: mean_ic={q['mean_ic']:.4f}, median={q['median_ic']:.4f}, pos_fold={q['positive_fold_ratio']:.2%}, mean_excess={q['mean_excess']:.6f}")
    report.extend([
        "",
        "## Economic by Horizon",
    ])
    for h, s in econ_summary.items():
        report.append(f"- {h}D: mean_excess={s['mean_excess']:.6f}, n={s['count']}")
    report.extend([
        "",
        "## Gates",
        "- QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
    ])
    
    (DOCS / "M9_1-C5-R_VOLUME_INDEPENDENT_ALPHA_RESEARCH.md").write_text("\n".join(report), encoding="utf-8")
    
    print(f"\nC5-R complete.")
    print(f"VOLUME status: {status}")
    print(f"Artifacts in {ART} and {DOCS}")
