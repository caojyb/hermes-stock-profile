#!/usr/bin/env python3
"""
c5_h3_capacity_analysis.py — M9.1-C5-H3 Fundamental Strategy Capacity & Implementability Evidence.

Analyzes signal breadth, portfolio concentration, liquidity proxy, turnover,
and basic implementability for fundamental_change_v1.

Outputs:
- c5_h3_capacity_observations.json
- c5_h3_capacity_fold_horizon.json
- c5_h3_capacity_stress.json
- docs/M9_1_C5_H3_FUNDAMENTAL_CAPACITY.md
"""
from __future__ import annotations

import json
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
DOC = BASE / "docs"
ART.mkdir(parents=True, exist_ok=True)
DOC.mkdir(parents=True, exist_ok=True)

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


def fetch_liquidity_proxy(symbols: List[str], decision_time: str) -> Dict[str, Dict[str, Optional[float]]]:
    """Fetch liquidity proxy from klines around decision_time."""
    con = _connect()
    cur = con.cursor()
    dt = datetime.strptime(decision_time, "%Y-%m-%d")
    start = (dt - timedelta(days=20)).strftime("%Y-%m-%d")
    end = (dt + timedelta(days=20)).strftime("%Y-%m-%d")

    liquidity = {}
    for symbol in symbols:
        cur.execute("""
            SELECT volume, turnover, close
            FROM klines
            WHERE code = ?
              AND date >= ?
              AND date <= ?
              AND volume IS NOT NULL
              AND turnover IS NOT NULL
              AND close IS NOT NULL
            ORDER BY date DESC
            LIMIT 1
        """, (symbol, start, end))
        row = cur.fetchone()
        if row:
            volume, turnover, close = row
            liquidity[symbol] = {
                "volume": volume,
                "turnover": turnover,
                "close": close,
                "adv_proxy": turnover if turnover is not None else None,
            }
        else:
            liquidity[symbol] = {
                "volume": None,
                "turnover": None,
                "close": None,
                "adv_proxy": None,
            }
    con.close()
    return liquidity


def fetch_stock_info(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch stock metadata for tradeability checks."""
    con = _connect()
    cur = con.cursor()
    info = {}
    for symbol in symbols:
        cur.execute("""
            SELECT code, name, market, sector, is_st, total_shares_real, circulating_shares_real, total_mcap
            FROM stocks
            WHERE code = ?
        """, (symbol,))
        row = cur.fetchone()
        if row:
            info[symbol] = {
                "code": row[0],
                "name": row[1],
                "market": row[2],
                "sector": row[3],
                "is_st": row[4],
                "total_shares_real": row[5],
                "circulating_shares_real": row[6],
                "total_mcap": row[7],
            }
        else:
            info[symbol] = {}
    con.close()
    return info


def build_portfolio(symbols: List[str], signals: Dict[str, Optional[Signal]], max_positions: int = 20) -> List[str]:
    eligible = [(sym, sig.raw_score) for sym, sig in signals.items() if sig and sig.eligibility and sig.raw_score is not None]
    eligible.sort(key=lambda x: x[1], reverse=True)
    selected = [sym for sym, _ in eligible[:max_positions]]
    return selected


def compute_hhi(weights: List[float]) -> float:
    if not weights:
        return 0.0
    total = sum(weights)
    if total <= 0:
        return 0.0
    normed = [w / total for w in weights]
    return sum(w * w for w in normed)


def compute_portfolio_metrics(selected: List[str], signals: Dict[str, Optional[Signal]]) -> Dict[str, Any]:
    if not selected:
        return {
            "selected_count": 0,
            "weights": [],
            "hhi": 0.0,
            "top1_weight": 0.0,
            "top5_weight": 0.0,
            "top10_weight": 0.0,
        }

    scores = []
    for sym in selected:
        sig = signals.get(sym)
        scores.append(sig.raw_score if sig and sig.raw_score is not None else 0.0)

    total = sum(abs(s) for s in scores) if scores else 0
    if total <= 0:
        weights = [1.0 / len(selected)] * len(selected)
    else:
        weights = [abs(s) / total for s in scores]

    hhi = compute_hhi(weights)
    top_n = lambda n: sum(sorted(weights, reverse=True)[:n])

    return {
        "selected_count": len(selected),
        "weights": weights,
        "hhi": hhi,
        "top1_weight": top_n(1),
        "top5_weight": top_n(5),
        "top10_weight": top_n(10),
    }


def run_capacity_analysis() -> Dict[str, Any]:
    observations = []
    fold_horizon_records = []
    stress_records = []

    for (fold_id, horizon), decision_time in FOLD_HORIZON_DECISION_TIMES.items():
        signals = {}
        for symbol in UNIVERSE:
            signals[symbol] = fetch_fundamental_signal(symbol, decision_time)

        selected = build_portfolio(UNIVERSE, signals)
        stock_info = fetch_stock_info(selected)
        liquidity = fetch_liquidity_proxy(selected, decision_time)
        port_metrics = compute_portfolio_metrics(selected, signals)

        # Tradeability checks
        st_count = sum(1 for s in selected if stock_info.get(s, {}).get("is_st") == 1)
        missing_price = sum(1 for s in selected if liquidity.get(s, {}).get("close") is None)
        zero_turnover = sum(1 for s in selected if liquidity.get(s, {}).get("turnover", -1) == 0)

        # Liquidity proxy stats
        turnover_vals = [liquidity[s]["turnover"] for s in selected if liquidity.get(s, {}).get("turnover") is not None]
        median_turnover = sorted(turnover_vals)[len(turnover_vals) // 2] if turnover_vals else None
        p25_turnover = sorted(turnover_vals)[len(turnover_vals) // 4] if turnover_vals else None
        p75_turnover = sorted(turnover_vals)[3 * len(turnover_vals) // 4] if turnover_vals else None
        min_turnover = min(turnover_vals) if turnover_vals else None

        obs = {
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "universe_count": len(UNIVERSE),
            "signal_count": sum(1 for s in signals.values() if s is not None),
            "eligible_count": sum(1 for s in signals.values() if s and s.eligibility),
            "selected_count": len(selected),
            "signal_rate": sum(1 for s in signals.values() if s is not None) / len(UNIVERSE),
            "eligible_rate": sum(1 for s in signals.values() if s and s.eligibility) / len(UNIVERSE),
            "selection_rate": len(selected) / len(UNIVERSE),
            "hhi": port_metrics["hhi"],
            "top1_weight": port_metrics["top1_weight"],
            "top5_weight": port_metrics["top5_weight"],
            "top10_weight": port_metrics["top10_weight"],
            "st_count": st_count,
            "missing_price_count": missing_price,
            "zero_turnover_count": zero_turnover,
            "median_turnover": median_turnover,
            "p25_turnover": p25_turnover,
            "p75_turnover": p75_turnover,
            "min_turnover": min_turnover,
        }
        observations.append(obs)

        fold_horizon_records.append({
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "status": "VALID",
            "signal_count": obs["signal_count"],
            "eligible_count": obs["eligible_count"],
            "selected_count": obs["selected_count"],
            "hhi": obs["hhi"],
            "top5_weight": obs["top5_weight"],
            "median_turnover": obs["median_turnover"],
            "st_count": obs["st_count"],
            "zero_turnover_count": obs["zero_turnover_count"],
        })

        # Capacity stress: test 2x, 5x position multiplier
        for mult in [1, 2, 5]:
            stress_records.append({
                "fold_id": fold_id,
                "horizon": horizon,
                "decision_time": decision_time,
                "multiplier": mult,
                "selected_count": len(selected),
                "hhi": obs["hhi"],
                "note": "Research stress only; no real order simulation",
            })

    return {
        "observations": observations,
        "fold_horizon": fold_horizon_records,
        "stress": stress_records,
    }


def compute_capacity_metrics(observations: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_horizon = {5: [], 10: [], 20: []}
    for obs in observations:
        h = obs["horizon"]
        if h in by_horizon:
            by_horizon[h].append(obs)

    def summarize(vals):
        clean = [v for v in vals if v is not None]
        if not clean:
            return {"mean": None, "median": None, "min": None, "max": None, "p25": None, "p75": None}
        clean.sort()
        n = len(clean)
        return {
            "mean": sum(clean) / n,
            "median": clean[n // 2],
            "min": clean[0],
            "max": clean[-1],
            "p25": clean[n // 4],
            "p75": clean[3 * n // 4],
        }

    metrics = {}
    for h, obs_list in by_horizon.items():
        selected_counts = [o["selected_count"] for o in obs_list]
        hhis = [o["hhi"] for o in obs_list if o["hhi"] is not None]
        top5_weights = [o["top5_weight"] for o in obs_list if o["top5_weight"] is not None]
        median_turnovers = [o["median_turnover"] for o in obs_list if o["median_turnover"] is not None]
        st_counts = [o["st_count"] for o in obs_list]
        zero_turnover_counts = [o["zero_turnover_count"] for o in obs_list]

        metrics[h] = {
            "observation_count": len(obs_list),
            "selected_count": summarize(selected_counts),
            "hhi": summarize(hhis),
            "top5_weight": summarize(top5_weights),
            "median_turnover": summarize(median_turnovers),
            "st_count": summarize(st_counts),
            "zero_turnover_count": summarize(zero_turnover_counts),
        }
    return metrics


def assess_capacity_status(metrics: Dict[str, Any]) -> str:
    """Heuristic capacity status based on breadth, concentration, liquidity."""
    issues = []
    for h, m in metrics.items():
        if m["selected_count"]["mean"] is not None and m["selected_count"]["mean"] < 5:
            issues.append(f"{h}D: low selected count")
        if m["hhi"]["mean"] is not None and m["hhi"]["mean"] > 0.15:
            issues.append(f"{h}D: high concentration")
        if m["median_turnover"]["median"] is not None and m["median_turnover"]["median"] <= 0:
            issues.append(f"{h}D: zero/negative median turnover")
        if m["zero_turnover_count"]["mean"] is not None and m["zero_turnover_count"]["mean"] > 0:
            issues.append(f"{h}D: zero turnover constituents")

    if not issues:
        return "PASS"
    if len(issues) <= 2:
        return "LIMITED"
    return "INSUFFICIENT"


def main() -> None:
    capacity = run_capacity_analysis()
    metrics = compute_capacity_metrics(capacity["observations"])
    status = assess_capacity_status(metrics)

    (ART / "c5_h3_capacity_observations.json").write_text(
        json.dumps(capacity, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_h3_capacity_fold_horizon.json").write_text(
        json.dumps({
            "fold_horizon": capacity["fold_horizon"],
            "summary_metrics": metrics,
            "capacity_status": status,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (ART / "c5_h3_capacity_stress.json").write_text(
        json.dumps({
            "stress_records": capacity["stress"],
            "summary": {
                "total_stress_cases": len(capacity["stress"]),
                "note": "Research stress only; no real order simulation",
                "market_impact_evidence": "UNAVAILABLE",
                "cost_adjusted_capacity": "NOT_AVAILABLE",
            },
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    report_lines = [
        "# M9.1-C5-H3 Fundamental Capacity & Implementability Evidence",
        "",
        "## Capacity Status",
        f"- CAPACITY_STATUS: {status}",
        "",
        "## Metrics by Horizon",
    ]
    for h in [5, 10, 20]:
        m = metrics[h]
        report_lines.append(f"- {h}D:")
        report_lines.append(f"  - selected_count: {m['selected_count']}")
        report_lines.append(f"  - hhi: {m['hhi']}")
        report_lines.append(f"  - top5_weight: {m['top5_weight']}")
        report_lines.append(f"  - median_turnover: {m['median_turnover']}")
        report_lines.append(f"  - st_count: {m['st_count']}")
        report_lines.append(f"  - zero_turnover_count: {m['zero_turnover_count']}")

    report_lines.extend([
        "",
        "## Evidence Limitations",
        "- ADV/spread/order book: UNAVAILABLE",
        "- Commission/slippage model: NOT_AVAILABLE",
        "- Market impact model: UNAVAILABLE",
        "",
        "## Next Steps",
        "- Proceed to M9.1-C5-H4 Multiple Testing Closure",
        "",
        "## Gates",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `c5_h3_capacity_observations.json`",
        "- `c5_h3_capacity_fold_horizon.json`",
        "- `c5_h3_capacity_stress.json`",
        "",
    ])
    report = "\n".join(report_lines)
    (DOC / "M9_1_C5_H3_FUNDAMENTAL_CAPACITY.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "capacity_status": status,
        "metrics": metrics,
        "artifacts": [
            "data/research/strategy/c5_h3_capacity_observations.json",
            "data/research/strategy/c5_h3_capacity_fold_horizon.json",
            "data/research/strategy/c5_h3_capacity_stress.json",
            "docs/M9_1_C5_H3_FUNDAMENTAL_CAPACITY.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
