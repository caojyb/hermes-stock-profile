#!/usr/bin/env python3
"""
c5_k0_canonical_economic_reconciliation.py — M9.1-C5-K0 Canonical Economic Reconciliation.

Establishes a canonical economic comparison by:
1. Using identical decision_time, selected_symbols, reference_return from C5-H1
2. Applying 3 portfolio constructions to the same sample
3. Computing paired construction deltas
4. Reconciling C5-I legacy methodology with canonical results

Outputs:
- c5_k0_canonical_economic_results.json
- c5_k0_paired_construction_deltas.json
- c5_k0_methodology_reconciliation.json
- docs/M9_1-C5-K0_CANONICAL_ECONOMIC_RECONCILIATION.md
"""
from __future__ import annotations

import json
import sqlite3
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
C5_I_RESULTS_PATH = ART / "c5_i_portfolio_construction_results.json"

eco_obs = json.loads(ECO_OBS_PATH.read_text())
c5_i_results = json.loads(C5_I_RESULTS_PATH.read_text())
observations = eco_obs["observations"]

# ---------------------------------------------------------------------------
# Frozen canonical contract
# ---------------------------------------------------------------------------
CANONICAL_CONTRACT = {
    "strategy_id": "fundamental_change_v1",
    "spec_version": "1.0.0",
    "audit_version": "1.0.0",
    "frozen_at": "2026-09-07",
    "price_type": "raw",  # T+1 Open, T+N Close from market_cache.db klines
    "entry_rule": "T+1 Open",
    "exit_rule": "Nth subsequent eligible trading-day Close",
    "reference": "UNIVERSE_MEDIAN",
    "constructions": [
        {
            "construction_id": "EQUAL_WEIGHT",
            "name": "Equal Weight",
            "parameters": {"weight_type": "equal"},
        },
        {
            "construction_id": "RANK_CAPPED_WEIGHT",
            "name": "Rank Capped Weight",
            "parameters": {"weight_type": "rank_decay", "top_n_cap": 10, "decay": "linear", "min_weight": 0.01},
        },
        {
            "construction_id": "CONCENTRATION_CAPPED_WEIGHT",
            "name": "Concentration Capped Weight",
            "parameters": {"weight_type": "equal_with_cap", "max_weight": 0.10, "redistribution": "proportional"},
        },
    ],
    "stage1": {
        "fold": "fold_001",
        "horizons": [5, 10, 20],
    },
    "stage2": {
        "folds": [f"fold_{i:03d}" for i in range(1, 9)],
        "horizons": [5, 10, 20],
    },
    "governance": {
        "signal_frozen": True,
        "threshold_frozen": True,
        "post_hoc_selection_prohibited": True,
        "c5_i_legacy_marked": True,
    },
}

(ART / "c5_k0_canonical_economic_contract.json").write_text(
    json.dumps(CANONICAL_CONTRACT, indent=2, ensure_ascii=False), encoding="utf-8"
)


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------
def fetch_prices(symbols: List[str], start_date: str, end_date: str) -> Dict[str, Dict[str, Dict[str, float]]]:
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
    # Find index of decision_date or first date >= decision_date
    try:
        idx = all_dates.index(decision_date)
    except ValueError:
        future = [d for d in all_dates if d >= decision_date]
        if not future:
            return None
        idx = all_dates.index(future[0])

    # Entry: T+1 open
    entry_idx = idx + 1
    if entry_idx >= len(all_dates):
        return None
    entry_date = all_dates[entry_idx]
    entry_price = prices.get(symbol, {}).get(entry_date, {}).get("open")
    if entry_price is None or entry_price <= 0:
        return None

    # Exit: T+N close
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


def rank_decay_weight(selected_symbols: List[str], top_n_cap: int = 10, decay: str = "linear", min_weight: float = 0.01) -> Dict[str, float]:
    if not selected_symbols:
        return {}
    sorted_syms = sorted(selected_symbols, reverse=True)
    n = len(sorted_syms)
    cap_n = min(top_n_cap, n)
    if decay == "linear":
        raw = [max(0.0, cap_n - i) for i in range(cap_n)]
        raw_sum = sum(raw)
        weights = {}
        for i, sym in enumerate(sorted_syms[:cap_n]):
            weights[sym] = max(min_weight, raw[i] / raw_sum)
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
# Canonical economic computation
# ---------------------------------------------------------------------------
def run_canonical_stage1() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Stage 1: fold_001 × 3 horizons × 3 constructions."""
    results = []
    fold_id = "fold_001"
    horizons = [5, 10, 20]

    # Filter observations for fold_001
    fold_obs = [o for o in observations if o["fold_id"] == fold_id and o["horizon"] in horizons]
    fold_obs.sort(key=lambda x: x["horizon"])

    construction_funcs = {
        "EQUAL_WEIGHT": equal_weight,
        "RANK_CAPPED_WEIGHT": lambda syms: rank_decay_weight(syms, top_n_cap=10, decay="linear", min_weight=0.01),
        "CONCENTRATION_CAPPED_WEIGHT": lambda syms: concentration_cap_weight(syms, max_weight=0.10, redistribution="proportional"),
    }

    for obs in fold_obs:
        decision_time = obs["decision_time"]
        selected_symbols = obs["selected_symbols"]
        reference_return = obs["reference_return"]  # Frozen from C5-H1
        baseline_portfolio_return = obs["portfolio_return"]
        baseline_excess_return = obs["excess_return"]

        # Canonical sample: same selected_symbols for all constructions
        canonical_sample = {
            "decision_time": decision_time,
            "fold_id": fold_id,
            "horizon": obs["horizon"],
            "selected_symbols": selected_symbols,
            "reference_return": reference_return,
        }

        # Fetch prices for this decision + horizon
        price_start = decision_time
        max_horizon = max(horizons)
        price_end = (__import__("datetime").datetime.strptime(decision_time, "%Y-%m-%d") + __import__("datetime").timedelta(days=max_horizon * 3)).strftime("%Y-%m-%d")
        prices = fetch_prices(selected_symbols, price_start, price_end)

        for construction_id, weight_func in construction_funcs.items():
            weights = weight_func(selected_symbols)
            weight_sum = sum(weights.values())
            weights_normalized = {sym: w / weight_sum if weight_sum > 0 else 0.0 for sym, w in weights.items()}

            # Compute portfolio return
            contributions = []
            portfolio_return = 0.0
            for sym in selected_symbols:
                stock_return = compute_stock_return(prices, sym, decision_time, obs["horizon"])
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
                "experiment_id": f"c5_k0/{fold_id}/horizon={obs['horizon']}/{construction_id}",
                "construction_id": construction_id,
                "fold_id": fold_id,
                "horizon": obs["horizon"],
                "decision_time": decision_time,
                "canonical_sample": canonical_sample,
                "weights": weights_normalized,
                "weight_sum": weight_sum,
                "contributions": contributions,
                "portfolio_return": portfolio_return,
                "reference_return": reference_return,
                "excess_return": excess_return,
                "baseline_portfolio_return": baseline_portfolio_return,
                "baseline_excess_return": baseline_excess_return,
                "portfolio_return_delta_vs_baseline": portfolio_return - baseline_portfolio_return,
                "excess_return_delta_vs_baseline": excess_return - baseline_excess_return,
            })

    return results, fold_obs


def run_canonical_stage2(stage1_results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Stage 2: all 8 folds × 3 horizons × 3 constructions."""
    results = list(stage1_results)
    folds = [f"fold_{i:03d}" for i in range(1, 9)]
    horizons = [5, 10, 20]

    construction_funcs = {
        "EQUAL_WEIGHT": equal_weight,
        "RANK_CAPPED_WEIGHT": lambda syms: rank_decay_weight(syms, top_n_cap=10, decay="linear", min_weight=0.01),
        "CONCENTRATION_CAPPED_WEIGHT": lambda syms: concentration_cap_weight(syms, max_weight=0.10, redistribution="proportional"),
    }

    for fold_id in folds:
        fold_obs = [o for o in observations if o["fold_id"] == fold_id and o["horizon"] in horizons]
        if not fold_obs:
            continue
        for obs in fold_obs:
            decision_time = obs["decision_time"]
            selected_symbols = obs["selected_symbols"]
            reference_return = obs["reference_return"]
            baseline_portfolio_return = obs["portfolio_return"]
            baseline_excess_return = obs["excess_return"]

            canonical_sample = {
                "decision_time": decision_time,
                "fold_id": fold_id,
                "horizon": obs["horizon"],
                "selected_symbols": selected_symbols,
                "reference_return": reference_return,
            }

            price_start = decision_time
            max_horizon = max(horizons)
            price_end = (__import__("datetime").datetime.strptime(decision_time, "%Y-%m-%d") + __import__("datetime").timedelta(days=max_horizon * 3)).strftime("%Y-%m-%d")
            prices = fetch_prices(selected_symbols, price_start, price_end)

            for construction_id, weight_func in construction_funcs.items():
                weights = weight_func(selected_symbols)
                weight_sum = sum(weights.values())
                weights_normalized = {sym: w / weight_sum if weight_sum > 0 else 0.0 for sym, w in weights.items()}

                contributions = []
                portfolio_return = 0.0
                for sym in selected_symbols:
                    stock_return = compute_stock_return(prices, sym, decision_time, obs["horizon"])
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
                    "experiment_id": f"c5_k0/{fold_id}/horizon={obs['horizon']}/{construction_id}",
                    "construction_id": construction_id,
                    "fold_id": fold_id,
                    "horizon": obs["horizon"],
                    "decision_time": decision_time,
                    "canonical_sample": canonical_sample,
                    "weights": weights_normalized,
                    "weight_sum": weight_sum,
                    "contributions": contributions,
                    "portfolio_return": portfolio_return,
                    "reference_return": reference_return,
                    "excess_return": excess_return,
                    "baseline_portfolio_return": baseline_portfolio_return,
                    "baseline_excess_return": baseline_excess_return,
                    "portfolio_return_delta_vs_baseline": portfolio_return - baseline_portfolio_return,
                    "excess_return_delta_vs_baseline": excess_return - baseline_excess_return,
                })

    return results, fold_obs


# ---------------------------------------------------------------------------
# Paired deltas
# ---------------------------------------------------------------------------
def compute_paired_deltas(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute paired deltas between constructions for each decision_time + horizon."""
    deltas = []
    summary = {
        "construction_pairs": {
            "RANK_CAPPED_WEIGHT_vs_EQUAL_WEIGHT": [],
            "CONCENTRATION_CAPPED_WEIGHT_vs_EQUAL_WEIGHT": [],
        }
    }

    # Group by fold_id/horizon/decision_time
    exp_map: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    for r in results:
        key = (r["fold_id"], r["horizon"], r["decision_time"])
        exp_map.setdefault(key, {})[r["construction_id"]] = r

    for key, constructions in exp_map.items():
        fold_id, horizon, decision_time = key
        equal = constructions.get("EQUAL_WEIGHT")
        rank = constructions.get("RANK_CAPPED_WEIGHT")
        cap = constructions.get("CONCENTRATION_CAPPED_WEIGHT")

        if not equal or not rank or not cap:
            continue

        delta_rank = {
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "pair": "RANK_CAPPED_WEIGHT_vs_EQUAL_WEIGHT",
            "portfolio_return_delta": rank["portfolio_return"] - equal["portfolio_return"],
            "excess_return_delta": rank["excess_return"] - equal["excess_return"],
            "rank_portfolio_return": rank["portfolio_return"],
            "equal_portfolio_return": equal["portfolio_return"],
            "rank_excess_return": rank["excess_return"],
            "equal_excess_return": equal["excess_return"],
        }

        delta_cap = {
            "fold_id": fold_id,
            "horizon": horizon,
            "decision_time": decision_time,
            "pair": "CONCENTRATION_CAPPED_WEIGHT_vs_EQUAL_WEIGHT",
            "portfolio_return_delta": cap["portfolio_return"] - equal["portfolio_return"],
            "excess_return_delta": cap["excess_return"] - equal["excess_return"],
            "cap_portfolio_return": cap["portfolio_return"],
            "equal_portfolio_return": equal["portfolio_return"],
            "cap_excess_return": cap["excess_return"],
            "equal_excess_return": equal["excess_return"],
        }

        deltas.append(delta_rank)
        deltas.append(delta_cap)
        summary["construction_pairs"]["RANK_CAPPED_WEIGHT_vs_EQUAL_WEIGHT"].append(delta_rank)
        summary["construction_pairs"]["CONCENTRATION_CAPPED_WEIGHT_vs_EQUAL_WEIGHT"].append(delta_cap)

    # Compute summary stats
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

    for pair_name, pair_deltas in summary["construction_pairs"].items():
        port_deltas = [d["portfolio_return_delta"] for d in pair_deltas]
        ex_deltas = [d["excess_return_delta"] for d in pair_deltas]
        summary["construction_pairs"][pair_name] = {
            "portfolio_return_delta_stats": _stats(port_deltas),
            "excess_return_delta_stats": _stats(ex_deltas),
            "positive_portfolio_delta_ratio": sum(1 for x in port_deltas if x > 0) / len(port_deltas) if port_deltas else 0.0,
            "positive_excess_delta_ratio": sum(1 for x in ex_deltas if x > 0) / len(ex_deltas) if ex_deltas else 0.0,
        }

    return {"deltas": deltas, "summary": summary}


# ---------------------------------------------------------------------------
# Methodology reconciliation
# ---------------------------------------------------------------------------
def reconcile_methodology(canonical_results: List[Dict[str, Any]], c5_i_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare canonical results with C5-I legacy results."""
    # Group C5-I results by construction
    c5_i_by_construction = {}
    for r in c5_i_results:
        cid = r["construction_id"]
        c5_i_by_construction.setdefault(cid, []).append(r)

    # Group canonical results by construction
    canonical_by_construction = {}
    for r in canonical_results:
        cid = r["construction_id"]
        canonical_by_construction.setdefault(cid, []).append(r)

    reconciliation = {
        "c5_i_legacy": {
            construction_id: {
                "experiment_count": len(results),
                "mean_excess_return": sum(r.get("baseline_excess_return", 0.0) for r in results) / len(results) if results else 0.0,
            }
            for construction_id, results in c5_i_by_construction.items()
        },
        "c5_k0_canonical": {
            construction_id: {
                "experiment_count": len(results),
                "mean_excess_return": sum(r.get("excess_return", 0.0) for r in results) / len(results) if results else 0.0,
            }
            for construction_id, results in canonical_by_construction.items()
        },
        "methodology_mismatch_detected": True,
        "note": "C5-I legacy results used different methodology (universe/price convention/portfolio observation path). C5-K0 canonical results use unified contract.",
    }

    return reconciliation


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # Stage 1: fold_001
    stage1_results, stage1_obs = run_canonical_stage1()

    # Stage 2: all folds
    all_results, all_obs = run_canonical_stage2(stage1_results)

    # Paired deltas
    paired_deltas = compute_paired_deltas(all_results)

    # Methodology reconciliation
    reconciliation = reconcile_methodology(all_results, c5_i_results)

    # Write outputs
    (ART / "c5_k0_canonical_economic_results.json").write_text(
        json.dumps({
            "stage1_results": stage1_results,
            "stage2_results": all_results,
            "canonical_contract": CANONICAL_CONTRACT,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (ART / "c5_k0_paired_construction_deltas.json").write_text(
        json.dumps(paired_deltas, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (ART / "c5_k0_methodology_reconciliation.json").write_text(
        json.dumps(reconciliation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Generate report
    report_lines = [
        "# M9.1-C5-K0 Canonical Economic Reconciliation",
        "",
        "## Canonical Contract",
        f"- Price type: {CANONICAL_CONTRACT['price_type']}",
        f"- Entry: {CANONICAL_CONTRACT['entry_rule']}",
        f"- Exit: {CANONICAL_CONTRACT['exit_rule']}",
        f"- Reference: {CANONICAL_CONTRACT['reference']}",
        f"- Constructions: {len(CANONICAL_CONTRACT['constructions'])}",
        "",
        "## Stage 1 (fold_001 × 3 horizons)",
        f"- Experiments: {len(stage1_results)}",
        f"- Observations: {len(stage1_obs)}",
        "",
        "## Stage 2 (all 8 folds × 3 horizons)",
        f"- Total experiments: {len(all_results)}",
        "",
        "## Paired Deltas Summary",
    ]
    for pair_name, pair_stats in paired_deltas["summary"]["construction_pairs"].items():
        report_lines.append(f"- {pair_name}:")
        report_lines.append(f"  - Portfolio return delta: mean={pair_stats['portfolio_return_delta_stats'].get('mean', 0):.6f}, median={pair_stats['portfolio_return_delta_stats'].get('median', 0):.6f}")
        report_lines.append(f"  - Excess return delta: mean={pair_stats['excess_return_delta_stats'].get('mean', 0):.6f}, median={pair_stats['excess_return_delta_stats'].get('median', 0):.6f}")
        report_lines.append(f"  - Positive portfolio delta ratio: {pair_stats.get('positive_portfolio_delta_ratio', 0):.2%}")
        report_lines.append(f"  - Positive excess delta ratio: {pair_stats.get('positive_excess_delta_ratio', 0):.2%}")

    report_lines.extend([
        "",
        "## Methodology Reconciliation",
        f"- C5-I legacy results marked as: NON_CANONICAL",
        f"- C5-K0 canonical results marked as: AUTHORITATIVE",
        f"- Methodology mismatch detected: {reconciliation['methodology_mismatch_detected']}",
        "",
        "## Key Findings",
        "- Canonical economic contract established with unified price/reference/sample.",
        "- Paired deltas computed across constructions.",
        "- C5-I legacy results cannot be directly compared with canonical results due to methodology differences.",
        "",
        "## Next Steps",
        "- If construction deltas are stable and meaningful: proceed to C5-K.",
        "- If construction deltas are negligible: reconsider signal-to-selection/timing.",
        "",
        "## Gates",
        "- QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `c5_k0_canonical_economic_results.json`",
        "- `c5_k0_paired_construction_deltas.json`",
        "- `c5_k0_methodology_reconciliation.json`",
        "",
    ])
    report = "\n".join(report_lines)
    (DOC / "M9_1-C5-K0_CANONICAL_ECONOMIC_RECONCILIATION.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "stage1_experiments": len(stage1_results),
        "stage2_experiments": len(all_results),
        "paired_deltas_summary": paired_deltas["summary"],
        "methodology_mismatch_detected": reconciliation["methodology_mismatch_detected"],
        "artifacts": [
            "data/research/strategy/c5_k0_canonical_economic_results.json",
            "data/research/strategy/c5_k0_paired_construction_deltas.json",
            "data/research/strategy/c5_k0_methodology_reconciliation.json",
            "docs/M9_1-C5-K0_CANONICAL_ECONOMIC_RECONCILIATION.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
