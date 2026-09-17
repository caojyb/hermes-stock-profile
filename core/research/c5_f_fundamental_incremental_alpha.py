#!/usr/bin/env python3
"""
c5_f_fundamental_incremental_alpha.py — M9.1-C5-F Fundamental Incremental Alpha Validation.

Validates whether Fundamental provides incremental information beyond Technical Library,
using aligned decision times, common sample, residual analysis, and rank-based metrics.

Outputs:
- c5_f_fundamental_incremental.json
- c5_f_incremental_status.json
- c5_f_fold_horizon_analysis.json
- c5_f_common_sample_analysis.json
- c5_f_fundamental_technical_correlation.json
- docs/M9_1_C5_F_FUNDAMENTAL_INCREMENTAL_ALPHA.md
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.research.base_strategy import BaseStrategy, Signal
from core.research.strategies.fundamental_change_strategy import FundamentalChangeStrategy

BASE = Path(__file__).resolve().parents[2]
DB = BASE / "data/production/market_cache.db"
ART = BASE / "data/research/strategy"
ART.mkdir(parents=True, exist_ok=True)

# Common universe for incremental analysis
UNIVERSE = [
    "000001", "000002", "600519", "000858", "601318",
    "002594", "600036", "000333", "002714", "603288",
    "002415", "000063", "002304", "600276", "000568",
    "002352", "600887",
]

FOLD_HORIZON_DECISION_TIMES = {
    ("fold_001", 5): "2025-03-13",
    ("fold_001", 10): "2025-03-13",
    ("fold_001", 20): "2025-03-13",
    ("fold_002", 5): "2025-05-20",
    ("fold_002", 10): "2025-05-20",
    ("fold_002", 20): "2025-05-20",
    ("fold_003", 5): "2025-07-25",
    ("fold_003", 10): "2025-07-25",
    ("fold_003", 20): "2025-07-25",
    ("fold_004", 5): "2025-09-30",
    ("fold_004", 10): "2025-09-30",
    ("fold_004", 20): "2025-09-30",
    ("fold_005", 5): "2025-12-10",
    ("fold_005", 10): "2025-12-10",
    ("fold_005", 20): "2025-12-10",
    ("fold_006", 5): "2026-02-13",
    ("fold_006", 10): "2026-02-13",
    ("fold_006", 20): "2026-02-13",
    ("fold_007", 5): "2026-04-24",
    ("fold_007", 10): "2026-04-24",
    ("fold_007", 20): "2026-04-24",
    ("fold_008", 5): "2026-07-02",
    ("fold_008", 10): "2026-07-02",
    ("fold_008", 20): "2026-07-02",
}

HORIZONS = [5, 10, 20]


def _connect():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def fetch_fundamental_signal(symbol: str, decision_time: str) -> Optional[Signal]:
    strategy = FundamentalChangeStrategy(db_path=str(DB))
    strategy.horizon = 5
    stock = {"code": symbol, "symbol": symbol}
    return strategy.generate_signal(stock, decision_time)


def fetch_technical_signal(symbol: str, decision_time: str, horizon: int) -> Optional[float]:
    """
    Lightweight technical baseline using price trend over a fixed lookback.
    This does not rely on TrendStrategy/MomentumStrategy dependency injection,
    and is used only for incremental analysis on the common aligned universe.
    """
    con = _connect()
    cur = con.cursor()
    lookback = 60
    end_dt = datetime.strptime(decision_time, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=lookback * 2)
    cur.execute("""
        SELECT date, close
        FROM klines
        WHERE code = ?
          AND date >= ?
          AND date <= ?
          AND close IS NOT NULL
        ORDER BY date ASC
    """, (symbol, start_dt.strftime("%Y-%m-%d"), decision_time))
    rows = cur.fetchall()
    con.close()
    if len(rows) < lookback + 1:
        return None
    recent = rows[-lookback:]
    start_price = recent[0][1]
    end_price = recent[-1][1]
    if not start_price or start_price <= 0 or end_price is None:
        return None
    return end_price / start_price - 1.0


def fetch_forward_returns(symbols: List[str], decision_time: str, horizon: int) -> Dict[str, Optional[float]]:
    con = _connect()
    cur = con.cursor()
    dt = datetime.strptime(decision_time, "%Y-%m-%d")
    end_date = (dt + timedelta(days=horizon * 2)).strftime("%Y-%m-%d")
    returns = {}
    for symbol in symbols:
        cur.execute("""
            SELECT date, close
            FROM klines
            WHERE code = ?
              AND date >= ?
              AND date <= ?
            ORDER BY date ASC
        """, (symbol, decision_time, end_date))
        rows = cur.fetchall()
        if len(rows) < 2:
            returns[symbol] = None
            continue
        start_price = rows[0][1]
        end_price = rows[-1][1]
        if start_price and start_price > 0 and end_price is not None:
            returns[symbol] = (end_price - start_price) / start_price
        else:
            returns[symbol] = None
    con.close()
    return returns


def _to_float(signal: Optional[Signal]) -> Optional[float]:
    if signal is None or not signal.eligibility:
        return None
    v = signal.raw_score
    return float(v) if v is not None else None


def _mean(xs: List[Optional[float]]) -> Optional[float]:
    vals = [x for x in xs if x is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _std(xs: List[Optional[float]]) -> Optional[float]:
    vals = [x for x in xs if x is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))


def _pearson(xs: List[Optional[float]], ys: List[Optional[float]]) -> Optional[float]:
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    xs_np = [p[0] for p in pairs]
    ys_np = [p[1] for p in pairs]
    mx = sum(xs_np) / len(xs_np)
    my = sum(ys_np) / len(ys_np)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs_np) / len(xs_np))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys_np) / len(ys_np))
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs_np, ys_np)) / len(xs_np)
    return cov / (sx * sy)


def _rank(xs: List[Optional[float]]) -> List[Optional[float]]:
    valid = [(i, v) for i, v in enumerate(xs) if v is not None]
    if not valid:
        return [None] * len(xs)
    vals = [v for _, v in valid]
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    for rank, idx in enumerate(order, start=1):
        ranks[idx] = rank
    max_rank = max(ranks)
    if max_rank > 0:
        ranks = [r / max_rank for r in ranks]
    out = [None] * len(xs)
    for (i, _), rank in zip(valid, ranks):
        out[i] = rank
    return out


def _spearman(xs: List[Optional[float]], ys: List[Optional[float]]) -> Optional[float]:
    rx = _rank(xs)
    ry = _rank(ys)
    return _pearson(rx, ry)


def run_aligned_validation() -> Dict[str, Any]:
    fundamental_results = []
    technical_results = []
    combined_results = []
    correlation_results = []
    common_sample_results = []
    fold_horizon_results = []

    for (fold_id, horizon), decision_time in FOLD_HORIZON_DECISION_TIMES.items():
        fundamental_signals = []
        technical_signals = []
        forward_returns = []
        metadata = []

        for symbol in UNIVERSE:
            fund_signal = fetch_fundamental_signal(symbol, decision_time)
            fund_val = _to_float(fund_signal)
            fundamental_signals.append(fund_val)

            tech_val = fetch_technical_signal(symbol, decision_time, horizon)
            technical_signals.append(tech_val)

            fwd = fetch_forward_returns([symbol], decision_time, horizon)[symbol]
            forward_returns.append(fwd)
            metadata.append({
                "symbol": symbol,
                "fundamental_signal": fund_val,
                "fundamental_eligibility": fund_signal.eligibility if fund_signal else False,
                "fundamental_reason": fund_signal.reason_code if fund_signal else None,
                "technical_signal": tech_val,
                "forward_return": fwd,
            })

        valid_fund = [v is not None for v in fundamental_signals]
        valid_tech = [v is not None for v in technical_signals]
        common_valid = [i for i in range(len(UNIVERSE)) if valid_fund[i] and valid_tech[i] and forward_returns[i] is not None]

        common_sample_results.append({
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "universe_size": len(UNIVERSE),
            "fundamental_valid_count": sum(valid_fund),
            "technical_valid_count": sum(valid_tech),
            "common_valid_count": len(common_valid),
            "technical_only_count": sum(valid_fund) - len(common_valid),
            "fundamental_only_count": sum(valid_tech) - len(common_valid),
            "intersection_count": len(common_valid),
        })

        if len(common_valid) < 3:
            fold_horizon_results.append({
                "fold_id": fold_id,
                "horizon": horizon,
                "decision_time": decision_time,
                "status": "INSUFFICIENT_COMMON_SAMPLE",
                "common_valid_count": len(common_valid),
            })
            continue

        cf = [fundamental_signals[i] for i in common_valid]
        ct = [technical_signals[i] for i in common_valid]
        cr = [forward_returns[i] for i in common_valid]

        fund_ic = _pearson(cf, cr)
        fund_rank_ic = _spearman(cf, cr)
        tech_ic = _pearson(ct, cr)
        tech_rank_ic = _spearman(ct, cr)

        fund_ranks = _rank(cf)
        tech_ranks = _rank(ct)
        combined_ranks = []
        for i in range(len(common_valid)):
            if fund_ranks[i] is not None and tech_ranks[i] is not None:
                combined_ranks.append((fund_ranks[i] + tech_ranks[i]) / 2.0)
            elif fund_ranks[i] is not None:
                combined_ranks.append(fund_ranks[i])
            elif tech_ranks[i] is not None:
                combined_ranks.append(tech_ranks[i])
            else:
                combined_ranks.append(None)

        combined_ic = _pearson(combined_ranks, cr)
        combined_rank_ic = _spearman(combined_ranks, cr)

        # Residual alpha: Fundamental orthogonalized to Technical via rank regression
        residual_ic = None
        residual_rank_ic = None
        pairs = [(f, t) for f, t in zip(fund_ranks, tech_ranks) if f is not None and t is not None]
        if len(pairs) >= 3:
            f_vals = [p[0] for p in pairs]
            t_vals = [p[1] for p in pairs]
            n = len(f_vals)
            mx = sum(f_vals) / n
            my = sum(t_vals) / n
            sx = math.sqrt(sum((x - mx) ** 2 for x in f_vals) / n)
            sy = math.sqrt(sum((y - my) ** 2 for y in t_vals) / n)
            if sx > 1e-9 and sy > 1e-9:
                cov = sum((f_vals[i] - mx) * (t_vals[i] - my) for i in range(n)) / n
                beta = cov / (sy * sy)
                residual_fund = [f_vals[i] - beta * (t_vals[i] - my) for i in range(n)]
                residual_ic = _pearson(residual_fund, cr[:len(residual_fund)])
                residual_rank_ic = _spearman(residual_fund, cr[:len(residual_fund)])

        correlations = {
            "technical_baseline": {
                "pearson": _pearson(cf, ct),
                "spearman": _spearman(cf, ct),
            }
        }

        def hit_rate(scores, returns):
            pairs = [(s, r) for s, r in zip(scores, returns) if s is not None and r is not None]
            if not pairs:
                return None
            return sum(1 for s, r in pairs if (s > 0 and r > 0) or (s < 0 and r < 0)) / len(pairs)

        fundamental_results.append({
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "ic": fund_ic,
            "rank_ic": fund_rank_ic,
            "hit_rate": hit_rate(cf, cr),
            "eligible_count": sum(valid_fund),
            "valid_sample_count": len(common_valid),
        })

        technical_results.append({
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "technical_ic": tech_ic,
            "technical_rank_ic": tech_rank_ic,
            "technical_hit_rate": hit_rate(ct, cr),
        })

        combined_results.append({
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "combined_ic": combined_ic,
            "combined_rank_ic": combined_rank_ic,
            "combined_hit_rate": hit_rate(combined_ranks, cr),
            "residual_ic": residual_ic,
            "residual_rank_ic": residual_rank_ic,
        })

        correlation_results.append({
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "correlations": correlations,
        })

        fold_horizon_results.append({
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "status": "VALID",
            "fundamental_ic": fund_ic,
            "technical_ic": tech_ic,
            "combined_ic": combined_ic,
            "residual_ic": residual_ic,
            "fundamental_hit_rate": hit_rate(cf, cr),
            "technical_hit_rate": hit_rate(ct, cr),
            "combined_hit_rate": hit_rate(combined_ranks, cr),
        })

    return {
        "technical_baseline_note": "Technical baseline computed from aligned common-universe kline trend signal; C4-B2 strategy-level evidence not per-symbol aligned.",
        "fundamental_results": fundamental_results,
        "technical_results": technical_results,
        "combined_results": combined_results,
        "correlation_results": correlation_results,
        "common_sample_results": common_sample_results,
        "fold_horizon_results": fold_horizon_results,
    }


def assess_incremental_status(results: Dict[str, Any]) -> Dict[str, Any]:
    fh = results["fold_horizon_results"]
    valid = [r for r in fh if r.get("status") == "VALID"]
    if not valid:
        return {"FUNDAMENTAL_INCREMENTAL_STATUS": "DATA_LIMITED", "reason": "no valid fold/horizon pairs"}

    positive_incremental_folds = 0
    for r in valid:
        tech_ic = r.get("technical_ic")
        combined_ic = r.get("combined_ic")
        if tech_ic is not None and combined_ic is not None and combined_ic > tech_ic:
            positive_incremental_folds += 1

    positive_ratio = positive_incremental_folds / len(valid) if valid else 0

    horizon_counts = {}
    for r in valid:
        h = r["horizon"]
        horizon_counts.setdefault(h, {"count": 0, "positive": 0})
        horizon_counts[h]["count"] += 1
        tech_ic = r.get("technical_ic")
        combined_ic = r.get("combined_ic")
        if tech_ic is not None and combined_ic is not None and combined_ic > tech_ic:
            horizon_counts[h]["positive"] += 1

    multi_horizon = sum(1 for v in horizon_counts.values() if v["positive"] > 0)

    residual_valid = [r for r in valid if r.get("residual_ic") is not None]
    residual_positive = sum(1 for r in residual_valid if r["residual_ic"] > 0)
    residual_ratio = residual_positive / len(residual_valid) if residual_valid else 0

    if positive_ratio >= 0.6 and multi_horizon >= 2 and residual_ratio >= 0.5:
        status = "STRONG_INCREMENTAL"
    elif positive_ratio >= 0.4 and multi_horizon >= 1 and residual_ratio >= 0.3:
        status = "WEAK_INCREMENTAL"
    elif positive_ratio > 0 or residual_ratio > 0:
        status = "INCONCLUSIVE"
    else:
        status = "NO_INCREMENTAL"

    return {
        "FUNDAMENTAL_INCREMENTAL_STATUS": status,
        "valid_fold_horizon_count": len(valid),
        "positive_incremental_folds": positive_incremental_folds,
        "positive_incremental_ratio": positive_ratio,
        "multi_horizon_support": multi_horizon,
        "residual_positive_ratio": residual_ratio,
        "horizon_breakdown": horizon_counts,
    }


def main() -> None:
    results = run_aligned_validation()
    incremental = assess_incremental_status(results)

    (ART / "c5_f_fundamental_incremental.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_f_incremental_status.json").write_text(
        json.dumps(incremental, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    (ART / "c5_f_fold_horizon_analysis.json").write_text(
        json.dumps({"summary": incremental, "by_fold_horizon": results["fold_horizon_results"]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    common_samples = results["common_sample_results"]
    avg_common = sum(r["common_valid_count"] for r in common_samples) / len(common_samples) if common_samples else 0
    sample_selection_risk = "LOW" if all(r["common_valid_count"] >= 10 for r in common_samples) else "HIGH"
    (ART / "c5_f_common_sample_analysis.json").write_text(
        json.dumps({"common_samples": common_samples, "summary": {
            "total_fold_horizon": len(common_samples),
            "avg_common_valid": avg_common,
            "sample_selection_risk": sample_selection_risk,
        }}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    (ART / "c5_f_fundamental_technical_correlation.json").write_text(
        json.dumps({"correlations": results["correlation_results"], "summary": {
            "status": "COMPLETE",
            "note": "Correlation computed per fold/horizon",
        }}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    report_lines = [
        "# M9.1-C5-F Fundamental Incremental Alpha Validation",
        "",
        "## Status",
        f"- FUNDAMENTAL_INCREMENTAL_STATUS: {incremental['FUNDAMENTAL_INCREMENTAL_STATUS']}",
        f"- Valid fold/horizon pairs: {incremental.get('valid_fold_horizon_count', 0)}",
        f"- Positive incremental folds: {incremental.get('positive_incremental_folds', 0)}",
        f"- Positive incremental ratio: {incremental.get('positive_incremental_ratio', 0):.2f}",
        f"- Multi-horizon support: {incremental.get('multi_horizon_support', 0)}",
        f"- Residual positive ratio: {incremental.get('residual_positive_ratio', 0):.2f}",
        "",
        "## Summary",
        "- Technical baseline: aligned common-universe price-trend signal",
        "- Fundamental: aligned 8 folds x 3 horizons",
        "- Combined: rank-based combination",
        "- Residual: Fundamental orthogonalized to Technical",
        "",
        "## Answer to Core Question",
        f"Does Fundamental provide incremental information beyond Technical Library? {incremental['FUNDAMENTAL_INCREMENTAL_STATUS']}",
        "",
        "## Artifacts",
        "- `c5_f_fundamental_incremental.json`",
        "- `c5_f_incremental_status.json`",
        "- `c5_f_fold_horizon_analysis.json`",
        "- `c5_f_common_sample_analysis.json`",
        "- `c5_f_fundamental_technical_correlation.json`",
        "",
        "## Gates",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
    ]
    report = "\n".join(report_lines)
    (BASE / "docs" / "M9_1_C5_F_FUNDAMENTAL_INCREMENTAL_ALPHA.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "incremental_status": incremental,
        "artifacts": [
            "data/research/strategy/c5_f_fundamental_incremental.json",
            "data/research/strategy/c5_f_incremental_status.json",
            "data/research/strategy/c5_f_fold_horizon_analysis.json",
            "data/research/strategy/c5_f_common_sample_analysis.json",
            "data/research/strategy/c5_f_fundamental_technical_correlation.json",
            "docs/M9_1_C5_F_FUNDAMENTAL_INCREMENTAL_ALPHA.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
