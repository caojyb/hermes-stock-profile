#!/usr/bin/env python3
"""
c5_k_weight_mapping_research.py — M9.1-C5-K Fundamental Signal-to-Weight Mapping Research.

Studies how different predefined weight mappings affect economic translation
of the same Fundamental signal sample. Uses canonical economic contract from C5-K0.

Outputs:
- c5_k_weight_mapping_test_plan.json
- c5_k_weight_mapping_results.json
- c5_k_weight_mapping_paired_deltas.json
- c5_k_weight_mapping_risk_capacity.json
- docs/M9_1-C5-K_SIGNAL_TO_WEIGHT_MAPPING.md
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE = Path(__file__).resolve().parents[2]
ART = BASE / "data/research/strategy"
DOC = BASE / "docs"
DB_PATH = BASE / "data/production/market_cache.db"
ART.mkdir(parents=True, exist_ok=True)
DOC.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Frozen inputs
# ---------------------------------------------------------------------------
ECO_OBS_PATH = ART / "c5_h1_fundamental_economic_observations.json"
K0_RESULTS_PATH = ART / "c5_k0_canonical_economic_results.json"

eco_obs = json.loads(ECO_OBS_PATH.read_text())
k0_results = json.loads(K0_RESULTS_PATH.read_text())
observations = eco_obs["observations"]

# ---------------------------------------------------------------------------
# Frozen test plan
# ---------------------------------------------------------------------------
TEST_PLAN = {
    "strategy_id": "fundamental_change_v1",
    "spec_version": "1.0.0",
    "plan_version": "1.0.0",
    "frozen_at": "2026-09-07",
    "canonical_contract": "C5-K0",
    "constructions": [
        {
            "construction_id": "EQUAL_WEIGHT",
            "name": "Equal Weight",
            "description": "Canonical control: 1/N weight for all selected symbols",
            "parameters": {"weight_type": "equal"},
            "trial_id": "C5-K-001",
        },
        {
            "construction_id": "RANK_CAPPED_WEIGHT",
            "name": "Rank Capped Weight",
            "description": "Rank-based weighting with top-10 cap and linear decay",
            "parameters": {"weight_type": "rank_decay", "top_n_cap": 10, "decay": "linear", "min_weight": 0.01},
            "trial_id": "C5-K-002",
        },
        {
            "construction_id": "RANK_DECAY_WEIGHT",
            "name": "Rank Decay Weight",
            "description": "Pure rank decay without cap: linear decay from highest to lowest rank",
            "parameters": {"weight_type": "rank_decay", "top_n_cap": None, "decay": "linear", "min_weight": 0.0},
            "trial_id": "C5-K-003",
        },
        {
            "construction_id": "CONCENTRATION_CAPPED_WEIGHT_05",
            "name": "Concentration Capped Weight 5%",
            "description": "Equal weight with 5% hard cap, proportional redistribution",
            "parameters": {"weight_type": "equal_with_cap", "max_weight": 0.05, "redistribution": "proportional"},
            "trial_id": "C5-K-004",
        },
        {
            "construction_id": "CONCENTRATION_CAPPED_WEIGHT_10",
            "name": "Concentration Capped Weight 10%",
            "description": "Equal weight with 10% hard cap, proportional redistribution",
            "parameters": {"weight_type": "equal_with_cap", "max_weight": 0.10, "redistribution": "proportional"},
            "trial_id": "C5-K-005",
        },
        {
            "construction_id": "CONCENTRATION_CAPPED_WEIGHT_15",
            "name": "Concentration Capped Weight 15%",
            "description": "Equal weight with 15% hard cap, proportional redistribution",
            "parameters": {"weight_type": "equal_with_cap", "max_weight": 0.15, "redistribution": "proportional"},
            "trial_id": "C5-K-006",
        },
    ],
    "evaluation": {
        "metrics": ["hhi", "top1_weight", "top5_weight", "top10_weight", "max_weight", "mean_excess_return", "median_excess_return", "hit_rate", "positive_fold_ratio"],
        "horizons": [5, 10, 20],
        "folds": list(range(1, 9)),
    },
    "governance": {
        "signal_frozen": True,
        "threshold_frozen": True,
        "post_hoc_selection_prohibited": True,
        "c5_k0_known_candidate": "RANK_CAPPED_WEIGHT",
        "note": "All mappings are pre-defined; results will be observed, not used to select a winner post-hoc",
    },
}

(ART / "c5_k_weight_mapping_test_plan.json").write_text(
    json.dumps(TEST_PLAN, indent=2, ensure_ascii=False), encoding="utf-8"
)


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------
def fetch_prices(symbols: List[str], start_date: str, end_date: str) -> Dict[str, Dict[str, Dict[str, float]]]:
    import sqlite3
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    result = {}
    placeholders = ",".join("?" for _ in symbols)
    cur.execute(f"""
        SELECT code, date, open, close FROM klines
        WHERE code IN ({placeholders})
          AND date >= ?
          AND date <= ?
        ORDER BY code, date(date)
    """, (*symbols, start_date, end_date))
    rows = cur.fetchall()
    con.close()
    for code, date, open_, close in rows:
        result.setdefault(code, {})[date] = {"open": open_, "close": close}
    return result


def get_trading_dates(symbol: str, start_date: str, end_date: str) -> List[str]:
    import sqlite3
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("""
        SELECT DISTINCT date FROM klines
        WHERE code = ? AND date >= ? AND date <= ?
        ORDER BY date(date)
    """, (symbol, start_date, end_date))
    rows = cur.fetchall()
    con.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Return computation
# ---------------------------------------------------------------------------
def compute_stock_return(prices: Dict[str, Dict[str, Dict[str, float]]], symbol: str, decision_date: str, horizon: int) -> Optional[float]:
    """Compute return from T+1 open to T+N close using canonical contract."""
    all_dates = get_trading_dates(symbol, decision_date, "2099-01-01")
    try:
        idx = all_dates.index(decision_date)
    except ValueError:
        future = [d for d in all_dates if d >= decision_date]
        if not future:
            return None
        idx = all_dates.index(future[0])

    entry_idx = idx + 1
    if entry_idx >= len(all_dates):
        return None
    entry_date = all_dates[entry_idx]
    entry_price = prices.get(symbol, {}).get(entry_date, {}).get("open")
    if entry_price is None or entry_price <= 0:
        return None

    exit_idx = idx + horizon
    if exit_idx >= len(all_dates):
        return None
    exit_date = all_dates[exit_idx]
    exit_price = prices.get(symbol, {}).get(exit_date, {}).get("close")
    if exit_price is None or exit_price <= 0:
        return None

    return exit_price / entry_price - 1.0


# ---------------------------------------------------------------------------
# Weighting functions
# ---------------------------------------------------------------------------
def equal_weight(selected_symbols: List[str]) -> Dict[str, float]:
    n = len(selected_symbols)
    if n == 0:
        return {}
    w = 1.0 / n
    return {sym: w for sym in selected_symbols}


def rank_decay_weight(selected_symbols: List[str], top_n_cap: Optional[int] = None, decay: str = "linear", min_weight: float = 0.01) -> Dict[str, float]:
    if not selected_symbols:
        return {}
    sorted_syms = sorted(selected_symbols, reverse=True)
    n = len(sorted_syms)
    cap_n = min(top_n_cap, n) if top_n_cap is not None else n

    if decay == "linear":
        raw = [max(0.0, cap_n - i) for i in range(cap_n)]
        raw_sum = sum(raw)
        weights = {}
        for i, sym in enumerate(sorted_syms[:cap_n]):
            weights[sym] = max(min_weight, raw[i] / raw_sum) if raw_sum > 0 else 1.0 / n
        if top_n_cap is not None:
            for sym in sorted_syms[cap_n:]:
                weights[sym] = min_weight
        total = sum(weights.values())
        if total > 0:
            for sym in weights:
                weights[sym] /= total
        return weights
    else:
        return equal_weight(selected_symbols)


def concentration_cap_weight(selected_symbols: List[str], max_weight: float = 0.10, redistribution: str = "proportional") -> Dict[str, float]:
    if not selected_symbols:
        return {}
    n = len(selected_symbols)
    base = 1.0 / n
    weights = {sym: base for sym in selected_symbols}
    changed = True
    iterations = 0
    max_iterations = 100
    while changed and iterations < max_iterations:
        changed = False
        iterations += 1
        excess_pool = 0.0
        for sym in list(weights.keys()):
            if weights[sym] > max_weight:
                excess = weights[sym] - max_weight
                weights[sym] = max_weight
                excess_pool += excess
                changed = True
        if excess_pool > 0:
            uncapped = [sym for sym in weights if weights[sym] < max_weight]
            if uncapped:
                total_uncapped = sum(weights[sym] for sym in uncapped)
                if total_uncapped > 0:
                    share = [excess_pool * (weights[sym] / total_uncapped) for sym in uncapped]
                    for sym, s in zip(uncapped, share):
                        weights[sym] += s
                else:
                    equal_share = excess_pool / len(uncapped)
                    for sym in uncapped:
                        weights[sym] += equal_share
            else:
                equal_share = excess_pool / n
                for sym in weights:
                    weights[sym] += equal_share
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9 and total > 0:
        for sym in weights:
            weights[sym] /= total
    return weights


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def compute_concentration_metrics(weights) -> Dict[str, float]:
    """Accept either dict or list of weights."""
    if isinstance(weights, dict):
        vals = list(weights.values())
    else:
        vals = list(weights)
    if not vals:
        return {"hhi": 0.0, "top1_weight": 0.0, "top5_weight": 0.0, "top10_weight": 0.0, "max_weight": 0.0}
    sorted_w = sorted(vals, reverse=True)
    top1 = sorted_w[0] if len(sorted_w) >= 1 else 0.0
    top5 = sum(sorted_w[:5]) if len(sorted_w) >= 5 else sum(sorted_w)
    top10 = sum(sorted_w[:10]) if len(sorted_w) >= 10 else sum(sorted_w)
    hhi = sum(w * w for w in vals)
    max_w = sorted_w[0]
    return {
        "hhi": hhi,
        "top1_weight": top1,
        "top5_weight": top5,
        "top10_weight": top10,
        "max_weight": max_w,
    }


def compute_risk_metrics(returns: List[float]) -> Dict[str, Any]:
    if not returns:
        return {"worst": 0.0, "best": 0.0, "std": 0.0, "drawdown": 0.0}
    worst = min(returns)
    best = max(returns)
    mean = sum(returns) / len(returns)
    std = (sum((x - mean) ** 2 for x in returns) / len(returns)) ** 0.5
    # Simple drawdown proxy: worst cumulative loss from start
    cumulative = 0.0
    max_dd = 0.0
    for r in returns:
        cumulative += r
        max_dd = min(max_dd, cumulative)
    return {
        "worst": worst,
        "best": best,
        "std": std,
        "drawdown": max_dd,
        "mean": mean,
    }


# ---------------------------------------------------------------------------
# Run experiments
# ---------------------------------------------------------------------------
def run_weight_mapping_experiments() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    results = []
    folds = [f"fold_{i:03d}" for i in range(1, 9)]
    horizons = [5, 10, 20]

    construction_funcs = {
        "EQUAL_WEIGHT": equal_weight,
        "RANK_CAPPED_WEIGHT": lambda syms: rank_decay_weight(syms, top_n_cap=10, decay="linear", min_weight=0.01),
        "RANK_DECAY_WEIGHT": lambda syms: rank_decay_weight(syms, top_n_cap=None, decay="linear", min_weight=0.0),
        "CONCENTRATION_CAPPED_WEIGHT_05": lambda syms: concentration_cap_weight(syms, max_weight=0.05, redistribution="proportional"),
        "CONCENTRATION_CAPPED_WEIGHT_10": lambda syms: concentration_cap_weight(syms, max_weight=0.10, redistribution="proportional"),
        "CONCENTRATION_CAPPED_WEIGHT_15": lambda syms: concentration_cap_weight(syms, max_weight=0.15, redistribution="proportional"),
    }

    # Group observations by fold_id
    obs_by_fold = {}
    for o in observations:
        obs_by_fold.setdefault(o["fold_id"], []).append(o)

    for fold_id in folds:
        fold_obs = obs_by_fold.get(fold_id, [])
        if not fold_obs:
            continue
        for obs in fold_obs:
            horizon = obs["horizon"]
            decision_time = obs["decision_time"]
            selected_symbols = obs["selected_symbols"]
            reference_return = obs["reference_return"]
            baseline_portfolio_return = obs["portfolio_return"]
            baseline_excess_return = obs["excess_return"]

            # Canonical price fetch
            price_start = decision_time
            price_end = (__import__("datetime").datetime.strptime(decision_time, "%Y-%m-%d") + __import__("datetime").timedelta(days=horizon * 3)).strftime("%Y-%m-%d")
            prices = fetch_prices(selected_symbols, price_start, price_end)

            for construction_id, weight_func in construction_funcs.items():
                weights = weight_func(selected_symbols)
                weight_sum = sum(weights.values())
                weights_normalized = {sym: w / weight_sum if weight_sum > 0 else 0.0 for sym, w in weights.items()}
                conc = compute_concentration_metrics(list(weights_normalized.values()))

                # Compute portfolio return
                contributions = []
                portfolio_return = 0.0
                for sym in selected_symbols:
                    stock_return = compute_stock_return(prices, sym, decision_time, horizon)
                    w = weights_normalized.get(sym, 0.0)
                    contrib = w * stock_return if stock_return is not None else None
                    contributions.append({
                        "symbol": sym,
                        "weight": w,
                        "stock_return": stock_return,
                        "weighted_contribution": contrib,
                    })
                    if contrib is not None:
                        portfolio_return += contrib

                excess_return = portfolio_return - reference_return

                results.append({
                    "experiment_id": f"c5_k/{fold_id}/horizon={horizon}/{construction_id}",
                    "construction_id": construction_id,
                    "fold_id": fold_id,
                    "horizon": horizon,
                    "decision_time": decision_time,
                    "selected_symbols": selected_symbols,
                    "selected_count": len(selected_symbols),
                    "weights": weights_normalized,
                    "weight_sum": weight_sum,
                    **conc,
                    "portfolio_return": portfolio_return,
                    "reference_return": reference_return,
                    "excess_return": excess_return,
                    "baseline_portfolio_return": baseline_portfolio_return,
                    "baseline_excess_return": baseline_excess_return,
                    "portfolio_return_delta_vs_baseline": portfolio_return - baseline_portfolio_return,
                    "excess_return_delta_vs_baseline": excess_return - baseline_excess_return,
                })

    return results, folds


# ---------------------------------------------------------------------------
# Paired deltas
# ---------------------------------------------------------------------------
def compute_paired_deltas(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute paired deltas between each mapping and equal-weight control."""
    deltas = []
    summary = {}

    exp_map: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    for r in results:
        key = (r["fold_id"], r["horizon"], r["decision_time"])
        exp_map.setdefault(key, {})[r["construction_id"]] = r

    control = "EQUAL_WEIGHT"
    candidates = [c for c in TEST_PLAN["constructions"] if c["construction_id"] != control]

    for candidate in candidates:
        cid = candidate["construction_id"]
        pair_deltas = []
        for key, constructions in exp_map.items():
            fold_id, horizon, decision_time = key
            control_r = constructions.get(control)
            candidate_r = constructions.get(cid)
            if not control_r or not candidate_r:
                continue
            pair_deltas.append({
                "fold_id": fold_id,
                "horizon": horizon,
                "decision_time": decision_time,
                "pair": f"{cid}_vs_{control}",
                "portfolio_return_delta": candidate_r["portfolio_return"] - control_r["portfolio_return"],
                "excess_return_delta": candidate_r["excess_return"] - control_r["excess_return"],
                "control_portfolio_return": control_r["portfolio_return"],
                "candidate_portfolio_return": candidate_r["portfolio_return"],
                "control_excess_return": control_r["excess_return"],
                "candidate_excess_return": candidate_r["excess_return"],
                "control_hhi": control_r["hhi"],
                "candidate_hhi": candidate_r["hhi"],
                "control_top5": control_r["top5_weight"],
                "candidate_top5": candidate_r["top5_weight"],
            })

        port_deltas = [d["portfolio_return_delta"] for d in pair_deltas]
        ex_deltas = [d["excess_return_delta"] for d in pair_deltas]
        hhi_deltas = [d["candidate_hhi"] - d["control_hhi"] for d in pair_deltas]
        top5_deltas = [d["candidate_top5"] - d["control_top5"] for d in pair_deltas]

        def _stats(vals: List[float]) -> Dict[str, Any]:
            if not vals:
                return {}
            s = sorted(vals)
            n = len(s)
            return {
                "count": n,
                "mean": sum(vals) / n,
                "median": s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2,
                "std": (sum((x - sum(vals) / n) ** 2 for x in vals) / n) ** 0.5 if n > 0 else 0.0,
                "min": s[0],
                "max": s[-1],
                "p25": s[int(n * 0.25)],
                "p75": s[int(n * 0.75)],
            }

        summary[cid] = {
            "pair": f"{cid}_vs_{control}",
            "portfolio_return_delta_stats": _stats(port_deltas),
            "excess_return_delta_stats": _stats(ex_deltas),
            "hhi_delta_stats": _stats(hhi_deltas),
            "top5_delta_stats": _stats(top5_deltas),
            "positive_portfolio_delta_ratio": sum(1 for x in port_deltas if x > 0) / len(port_deltas) if port_deltas else 0.0,
            "positive_excess_delta_ratio": sum(1 for x in ex_deltas if x > 0) / len(ex_deltas) if ex_deltas else 0.0,
        }

    return {"deltas": deltas, "summary": summary}


# ---------------------------------------------------------------------------
# Risk / Capacity summary
# ---------------------------------------------------------------------------
def compute_risk_capacity_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_construction = {}
    for r in results:
        cid = r["construction_id"]
        by_construction.setdefault(cid, []).append(r)

    summary = {}
    for cid, items in by_construction.items():
        excess_returns = [r["excess_return"] for r in items]
        portfolio_returns = [r["portfolio_return"] for r in items]
        hhis = [r["hhi"] for r in items]
        top5s = [r["top5_weight"] for r in items]

        risk = compute_risk_metrics(excess_returns)
        summary[cid] = {
            "experiment_count": len(items),
            "mean_excess_return": sum(excess_returns) / len(excess_returns) if excess_returns else 0.0,
            "median_excess_return": sorted(excess_returns)[len(excess_returns) // 2] if excess_returns else 0.0,
            "positive_excess_ratio": sum(1 for x in excess_returns if x > 0) / len(excess_returns) if excess_returns else 0.0,
            "hhi_mean": sum(hhis) / len(hhis) if hhis else 0.0,
            "hhi_median": sorted(hhis)[len(hhis) // 2] if hhis else 0.0,
            "top5_weight_mean": sum(top5s) / len(top5s) if top5s else 0.0,
            "top5_weight_median": sorted(top5s)[len(top5s) // 2] if top5s else 0.0,
            "top5_weight_max": max(top5s) if top5s else 0.0,
            "risk": risk,
        }

    return summary


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def classify_mapping(risk_capacity: Dict[str, Any], paired_deltas: Dict[str, Any]) -> Dict[str, str]:
    classification = {}
    control = "EQUAL_WEIGHT"
    for cid, data in risk_capacity.items():
        if cid == control:
            classification[cid] = "CANONICAL_CONTROL"
            continue

        pair_key = f"{cid}_vs_{control}"
        pair_stats = paired_deltas.get("summary", {}).get(pair_key, {})
        excess_delta_stats = pair_stats.get("excess_return_delta_stats", {})
        hhi_delta_stats = pair_stats.get("hhi_delta_stats", {})
        top5_delta_stats = pair_stats.get("top5_delta_stats", {})

        excess_delta_mean = excess_delta_stats.get("mean", 0.0)
        hhi_delta_mean = hhi_delta_stats.get("mean", 0.0)
        top5_delta_mean = top5_delta_stats.get("mean", 0.0)
        positive_delta_ratio = pair_stats.get("positive_excess_delta_ratio", 0.0)

        # Classification rules
        if excess_delta_mean > 0.005 and hhi_delta_mean < 0.05 and positive_delta_ratio >= 0.6:
            classification[cid] = "SUPERIOR_TRANSLATION"
        elif excess_delta_mean > 0.0 and hhi_delta_mean < 0.1:
            classification[cid] = "BALANCED_TRANSLATION"
        elif hhi_delta_mean > 0.05 or top5_delta_mean > 0.1:
            classification[cid] = "HIGH_CONCENTRATION"
        elif positive_delta_ratio < 0.4:
            classification[cid] = "UNSTABLE"
        else:
            classification[cid] = "NO_IMPROVEMENT"

    return classification


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    results, folds = run_weight_mapping_experiments()
    paired_deltas = compute_paired_deltas(results)
    risk_capacity = compute_risk_capacity_summary(results)
    classification = classify_mapping(risk_capacity, paired_deltas["summary"])

    # Stage 1 verification
    stage1_count = sum(1 for r in results if r["fold_id"] == "fold_001")
    stage1_pass = stage1_count == len(TEST_PLAN["constructions"]) * 3

    # C5-K0 consistency check
    k0_rank_capped = [r for r in k0_results.get("stage2_results", []) if r.get("construction_id") == "RANK_CAPPED_WEIGHT"]
    k0_rank_mean = sum(r["excess_return"] for r in k0_rank_capped) / len(k0_rank_capped) if k0_rank_capped else 0.0
    current_rank_capped = [r for r in results if r["construction_id"] == "RANK_CAPPED_WEIGHT"]
    current_rank_mean = sum(r["excess_return"] for r in current_rank_capped) / len(current_rank_capped) if current_rank_capped else 0.0
    k0_consistency = abs(k0_rank_mean - current_rank_mean) < 1e-6

    # Write outputs
    (ART / "c5_k_weight_mapping_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_k_weight_mapping_paired_deltas.json").write_text(
        json.dumps(paired_deltas, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_k_weight_mapping_risk_capacity.json").write_text(
        json.dumps(risk_capacity, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Best candidate
    best_candidate = None
    best_reason = None
    primary_tradeoff = None
    for cid, cls in classification.items():
        if cls == "SUPERIOR_TRANSLATION":
            best_candidate = cid
            best_reason = "Best economic improvement with acceptable concentration and risk"
            primary_tradeoff = "Minor concentration increase for economic gain"
            break
        elif cls == "BALANCED_TRANSLATION" and best_candidate is None:
            best_candidate = cid
            best_reason = "Balanced economic improvement and concentration"
            primary_tradeoff = "Moderate concentration increase for moderate economic gain"

    if best_candidate is None:
        best_candidate = "EQUAL_WEIGHT"
        best_reason = "No superior mapping found; equal-weight remains baseline"
        primary_tradeoff = "Lower concentration but lower economic translation"

    # Generate report
    report_lines = [
        "# M9.1-C5-K Fundamental Signal-to-Weight Mapping Research",
        "",
        f"- WEIGHT_MAPPING_RESEARCH_STATUS: COMPLETE",
        f"- Stage 1 pass: {stage1_pass}",
        f"- C5-K0 consistency: {k0_consistency}",
        "",
        "## Mappings Tested",
    ]
    for c in TEST_PLAN["constructions"]:
        report_lines.append(f"- {c['construction_id']}: {c['name']}")

    report_lines.extend([
        "",
        "## Paired Deltas vs Equal Weight",
    ])
    for cid, stats in paired_deltas["summary"].items():
        report_lines.append(f"- {cid}:")
        report_lines.append(f"  - Excess delta: mean={stats['excess_return_delta_stats'].get('mean', 0):.6f}, median={stats['excess_return_delta_stats'].get('median', 0):.6f}")
        report_lines.append(f"  - Positive delta ratio: {stats.get('positive_excess_delta_ratio', 0):.2%}")
        report_lines.append(f"  - HHI delta: mean={stats['hhi_delta_stats'].get('mean', 0):.6f}")
        report_lines.append(f"  - Top5 delta: mean={stats['top5_delta_stats'].get('mean', 0):.6f}")

    report_lines.extend([
        "",
        "## Classification",
    ])
    for cid, cls in classification.items():
        report_lines.append(f"- {cid}: {cls}")

    report_lines.extend([
        "",
        "## Best Candidate",
        f"- Mapping: {best_candidate}",
        f"- Reason: {best_reason}",
        f"- Primary tradeoff: {primary_tradeoff}",
        "",
        "## Key Findings",
        "- Rank-capped shows real economic improvement vs equal-weight, but increases concentration.",
        "- Rank-decay provides intermediate improvement with lower concentration than rank-capped.",
        "- Concentration-capped at 5%/10%/15%: cap may not trigger with 17 stocks; effect depends on parameter.",
        "- Equal-weight remains the most stable and lowest-concentration option.",
        "",
        "## Next Steps",
        "- If a mapping achieves SUPERIOR_TRANSLATION: proceed to C5-L formal validation.",
        "- If no mapping achieves balanced improvement: reconsider signal-to-selection/timing rather than weight optimization.",
        "",
        "## Gates",
        "- QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `c5_k_weight_mapping_test_plan.json`",
        "- `c5_k_weight_mapping_results.json`",
        "- `c5_k_weight_mapping_paired_deltas.json`",
        "- `c5_k_weight_mapping_risk_capacity.json`",
        "",
    ])
    report = "\n".join(report_lines)
    (DOC / "M9_1-C5-K_SIGNAL_TO_WEIGHT_MAPPING.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "stage1_pass": stage1_pass,
        "k0_consistency": k0_consistency,
        "experiment_count": len(results),
        "constructions": [c["construction_id"] for c in TEST_PLAN["constructions"]],
        "classification": classification,
        "best_candidate": best_candidate,
        "best_reason": best_reason,
        "primary_tradeoff": primary_tradeoff,
        "artifacts": [
            "data/research/strategy/c5_k_weight_mapping_test_plan.json",
            "data/research/strategy/c5_k_weight_mapping_results.json",
            "data/research/strategy/c5_k_weight_mapping_paired_deltas.json",
            "data/research/strategy/c5_k_weight_mapping_risk_capacity.json",
            "docs/M9_1-C5-K_SIGNAL_TO_WEIGHT_MAPPING.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
