#!/usr/bin/env python3
"""
c5_l_selection_timing_research.py — M9.1-C5-L Fundamental Signal → Selection / Timing Research.

Studies whether the Fundamental strategy's economic translation improves with
alternative selection rules, while keeping the signal frozen. Uses canonical
economic contract from C5-K0.

Outputs:
- c5_l_selection_test_plan.json
- c5_l_selection_results.json
- c5_l_signal_quantile_analysis.json
- c5_l_selection_concentration.json
- c5_l_selection_economic.json
- docs/M9_1-C5-L_FUNDAMENTAL_SELECTION_TIMING_RESEARCH.md
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

eco_obs = json.loads(ECO_OBS_PATH.read_text())
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
    "portfolio_control": "EQUAL_WEIGHT",
    "selection_rules": [
        {
            "rule_id": "ALL_ELIGIBLE",
            "name": "All Eligible",
            "description": "Use all eligible stocks (current baseline)",
            "parameters": {"type": "all_eligible"},
            "trial_id": "C5-L-001",
        },
        {
            "rule_id": "TOP_20PCT",
            "name": "Top 20%",
            "description": "Select top 20% by signal score",
            "parameters": {"type": "top_percent", "percent": 0.20, "min_count": 3},
            "trial_id": "C5-L-002",
        },
        {
            "rule_id": "TOP_30PCT",
            "name": "Top 30%",
            "description": "Select top 30% by signal score",
            "parameters": {"type": "top_percent", "percent": 0.30, "min_count": 5},
            "trial_id": "C5-L-003",
        },
        {
            "rule_id": "TOP_50PCT",
            "name": "Top 50%",
            "description": "Select top 50% by signal score",
            "parameters": {"type": "top_percent", "percent": 0.50, "min_count": 8},
            "trial_id": "C5-L-004",
        },
        {
            "rule_id": "QUANTILE_Q5",
            "name": "Top Quintile",
            "description": "Select top 20% quantile (Q5)",
            "parameters": {"type": "top_quantile", "quantile": 5, "min_count": 3},
            "trial_id": "C5-L-005",
        },
    ],
    "horizons": [5, 10, 20],
    "folds": [f"fold_{i:03d}" for i in range(1, 9)],
    "governance": {
        "signal_frozen": True,
        "threshold_frozen": True,
        "post_hoc_selection_prohibited": True,
        "note": "All selection rules pre-defined; results observed, not optimized post-hoc",
    },
}

(ART / "c5_l_selection_test_plan.json").write_text(
    json.dumps(TEST_PLAN, indent=2, ensure_ascii=False), encoding="utf-8"
)


# ---------------------------------------------------------------------------
# Fundamental signal computation (frozen spec)
# ---------------------------------------------------------------------------
def compute_fundamental_signals(symbols: List[str], decision_time: str) -> Dict[str, Optional[float]]:
    """
    Recompute fundamental_change_v1 signals for given symbols at decision_time.
    Returns raw_score per symbol.
    """
    import sys
    sys.path.insert(0, str(BASE / "core/research"))
    from strategies.fundamental_change_strategy import FundamentalChangeStrategy

    strategy = FundamentalChangeStrategy()
    signals = {}
    for symbol in symbols:
        signal = strategy.generate_signal({"code": symbol}, decision_time)
        if signal and signal.eligibility and signal.raw_score is not None:
            signals[symbol] = signal.raw_score
        else:
            signals[symbol] = None
    return signals


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
# Selection rules
# ---------------------------------------------------------------------------
def apply_selection_rule(selected_symbols: List[str], scores: Dict[str, Optional[float]], rule: Dict[str, Any]) -> List[str]:
    """Apply selection rule to get final portfolio constituents."""
    rule_type = rule["parameters"]["type"]

    if rule_type == "all_eligible":
        return selected_symbols

    elif rule_type == "top_percent":
        percent = rule["parameters"]["percent"]
        min_count = rule["parameters"].get("min_count", 3)
        valid = [(sym, scores[sym]) for sym in selected_symbols if scores.get(sym) is not None]
        if not valid:
            return selected_symbols
        valid.sort(key=lambda x: x[1], reverse=True)
        k = max(min_count, int(len(valid) * percent))
        k = min(k, len(valid))
        return [sym for sym, _ in valid[:k]]

    elif rule_type == "top_quantile":
        quantile = rule["parameters"]["quantile"]
        min_count = rule["parameters"].get("min_count", 3)
        valid = [(sym, scores[sym]) for sym in selected_symbols if scores.get(sym) is not None]
        if not valid:
            return selected_symbols
        valid.sort(key=lambda x: x[1], reverse=True)
        k = max(min_count, len(valid) // quantile)
        k = min(k, len(valid))
        return [sym for sym, _ in valid[:k]]

    return selected_symbols


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


def equal_weight(selected_symbols: List[str]) -> Dict[str, float]:
    n = len(selected_symbols)
    if n == 0:
        return {}
    w = 1.0 / n
    return {sym: w for sym in selected_symbols}


# ---------------------------------------------------------------------------
# Run experiments
# ---------------------------------------------------------------------------
def run_selection_experiments() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    results = []
    folds = [f"fold_{i:03d}" for i in range(1, 9)]
    horizons = [5, 10, 20]

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

            # Recompute fundamental signals for this decision
            scores = compute_fundamental_signals(selected_symbols, decision_time)
            valid_scores = {sym: score for sym, score in scores.items() if score is not None}

            # Canonical price fetch
            from datetime import datetime, timedelta
            price_start = decision_time
            price_end = (datetime.strptime(decision_time, "%Y-%m-%d") + timedelta(days=horizon * 3)).strftime("%Y-%m-%d")
            prices = fetch_prices(selected_symbols, price_start, price_end)

            for rule in TEST_PLAN["selection_rules"]:
                rule_id = rule["rule_id"]
                selected = apply_selection_rule(selected_symbols, scores, rule)
                weights = equal_weight(selected)
                weight_sum = sum(weights.values())
                weights_normalized = {sym: w / weight_sum if weight_sum > 0 else 0.0 for sym, w in weights.items()}
                conc = compute_concentration_metrics(weights_normalized)

                # Compute portfolio return
                portfolio_return = 0.0
                for sym in selected:
                    stock_return = compute_stock_return(prices, sym, decision_time, horizon)
                    w = weights_normalized.get(sym, 0.0)
                    if stock_return is not None:
                        portfolio_return += w * stock_return

                excess_return = portfolio_return - reference_return

                results.append({
                    "experiment_id": f"c5_l/{fold_id}/horizon={horizon}/{rule_id}",
                    "selection_rule": rule_id,
                    "fold_id": fold_id,
                    "horizon": horizon,
                    "decision_time": decision_time,
                    "selected_symbols": selected,
                    "selected_count": len(selected),
                    "scores": {sym: valid_scores.get(sym) for sym in selected if sym in valid_scores},
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
# Signal quantile analysis
# ---------------------------------------------------------------------------
def analyze_signal_quantiles() -> Dict[str, Any]:
    """
    Analyze whether Fundamental signal excess return is monotonic across quintiles.
    Uses all available decision dates and computes per-quintile performance.
    """
    quantile_analysis = []
    folds = [f"fold_{i:03d}" for i in range(1, 9)]
    horizons = [5, 10, 20]

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

            scores = compute_fundamental_signals(selected_symbols, decision_time)
            valid = [(sym, scores[sym]) for sym in selected_symbols if scores.get(sym) is not None]
            if len(valid) < 5:
                continue
            valid.sort(key=lambda x: x[1])

            q_size = len(valid) // 5
            quintiles = []
            for q in range(5):
                start = q * q_size
                end = start + q_size if q < 4 else len(valid)
                q_syms = [sym for sym, _ in valid[start:end]]
                quintiles.append({
                    "quantile": q + 1,
                    "symbols": q_syms,
                    "avg_score": sum(score for _, score in valid[start:end]) / len(valid[start:end]) if valid[start:end] else 0.0,
                })

            from datetime import datetime, timedelta
            price_start = decision_time
            price_end = (datetime.strptime(decision_time, "%Y-%m-%d") + timedelta(days=horizon * 3)).strftime("%Y-%m-%d")
            prices = fetch_prices(selected_symbols, price_start, price_end)

            for q in quintiles:
                q_return = 0.0
                valid_count = 0
                for sym in q["symbols"]:
                    ret = compute_stock_return(prices, sym, decision_time, horizon)
                    if ret is not None:
                        q_return += ret
                        valid_count += 1
                if valid_count > 0:
                    q["portfolio_return"] = q_return / valid_count
                    q["excess_return"] = q["portfolio_return"] - reference_return
                else:
                    q["portfolio_return"] = None
                    q["excess_return"] = None

            quantile_analysis.append({
                "fold_id": fold_id,
                "horizon": horizon,
                "decision_time": decision_time,
                "quintiles": quintiles,
            })

    return {"quantile_analysis": quantile_analysis}


# ---------------------------------------------------------------------------
# Selection concentration
# ---------------------------------------------------------------------------
def compute_selection_concentration(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_rule = {}
    for r in results:
        rule = r["selection_rule"]
        by_rule.setdefault(rule, []).append(r)

    summary = {}
    for rule, items in by_rule.items():
        hhis = [r["hhi"] for r in items]
        top5s = [r["top5_weight"] for r in items]
        top10s = [r["top10_weight"] for r in items]
        selected_counts = [r["selected_count"] for r in items]
        summary[rule] = {
            "experiment_count": len(items),
            "selected_count_mean": sum(selected_counts) / len(selected_counts) if selected_counts else 0,
            "selected_count_min": min(selected_counts) if selected_counts else 0,
            "selected_count_max": max(selected_counts) if selected_counts else 0,
            "hhi_mean": sum(hhis) / len(hhis) if hhis else 0.0,
            "hhi_median": sorted(hhis)[len(hhis) // 2] if hhis else 0.0,
            "hhi_max": max(hhis) if hhis else 0.0,
            "top5_weight_mean": sum(top5s) / len(top5s) if top5s else 0.0,
            "top5_weight_max": max(top5s) if top5s else 0.0,
            "top10_weight_mean": sum(top10s) / len(top10s) if top10s else 0.0,
        }

    return summary


# ---------------------------------------------------------------------------
# Selection economic summary
# ---------------------------------------------------------------------------
def compute_selection_economic(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_rule = {}
    for r in results:
        rule = r["selection_rule"]
        by_rule.setdefault(rule, []).append(r)

    summary = {}
    for rule, items in by_rule.items():
        excess = [r["excess_return"] for r in items]
        portfolio = [r["portfolio_return"] for r in items]
        positive_excess = sum(1 for x in excess if x > 0) if excess else 0
        mean_excess = sum(excess) / len(excess) if excess else 0.0
        median_excess = sorted(excess)[len(excess) // 2] if excess else 0.0
        std_excess = (sum((x - mean_excess) ** 2 for x in excess) / len(excess)) ** 0.5 if excess else 0.0
        summary[rule] = {
            "experiment_count": len(items),
            "mean_excess_return": mean_excess,
            "median_excess_return": median_excess,
            "mean_portfolio_return": sum(portfolio) / len(portfolio) if portfolio else 0.0,
            "positive_excess_ratio": positive_excess / len(excess) if excess else 0.0,
            "std_excess_return": std_excess,
            "min_excess_return": min(excess) if excess else 0.0,
            "max_excess_return": max(excess) if excess else 0.0,
        }

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    results, folds = run_selection_experiments()
    quantile_analysis = analyze_signal_quantiles()
    concentration = compute_selection_concentration(results)
    economic = compute_selection_economic(results)

    # Stage 1 verification
    stage1_count = sum(1 for r in results if r["fold_id"] == "fold_001")
    stage1_pass = stage1_count == len(TEST_PLAN["selection_rules"]) * 3

    # Write outputs
    (ART / "c5_l_selection_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_l_signal_quantile_analysis.json").write_text(
        json.dumps(quantile_analysis, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_l_selection_concentration.json").write_text(
        json.dumps(concentration, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ART / "c5_l_selection_economic.json").write_text(
        json.dumps(economic, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Determine if selection research is justified
    all_eligible = economic.get("ALL_ELIGIBLE", {})
    best_rule = None
    best_excess = all_eligible.get("mean_excess_return", 0.0)
    for rule, data in economic.items():
        if rule != "ALL_ELIGIBLE" and data.get("mean_excess_return", 0.0) > best_excess:
            best_excess = data["mean_excess_return"]
            best_rule = rule

    selection_justified = best_rule is not None and best_excess > all_eligible.get("mean_excess_return", 0.0)
    selection_status = "STRONG" if selection_justified else "WEAK"

    # Generate report
    report_lines = [
        "# M9.1-C5-L Fundamental Selection / Timing Research",
        "",
        f"- SELECTION_RESEARCH_STATUS: {selection_status}",
        f"- Stage 1 pass: {stage1_pass}",
        f"- Experiments: {len(results)}",
        "",
        "## Selection Rules Tested",
    ]
    for r in TEST_PLAN["selection_rules"]:
        report_lines.append(f"- {r['rule_id']}: {r['name']}")

    report_lines.extend([
        "",
        "## Economic Summary vs Equal-Weight Control",
    ])
    for rule, data in economic.items():
        report_lines.append(f"- {rule}:")
        report_lines.append(f"  - Mean excess return: {data['mean_excess_return']:.6f}")
        report_lines.append(f"  - Positive excess ratio: {data['positive_excess_ratio']:.2%}")
        report_lines.append(f"  - Std excess return: {data['std_excess_return']:.6f}")

    report_lines.extend([
        "",
        "## Concentration Summary",
    ])
    for rule, data in concentration.items():
        report_lines.append(f"- {rule}:")
        report_lines.append(f"  - Selected count mean: {data['selected_count_mean']:.1f}")
        report_lines.append(f"  - HHI mean: {data['hhi_mean']:.4f}")
        report_lines.append(f"  - Top5 weight mean: {data['top5_weight_mean']:.4f}")

    report_lines.extend([
        "",
        "## Key Findings",
    ])
    if selection_justified:
        report_lines.append(f"- Selection improvement found: {best_rule} shows better excess return than all-eligible.")
    else:
        report_lines.append("- No selection rule shows consistent improvement over all-eligible equal weight.")
        report_lines.append("- This suggests the issue may not be in selection, but in signal design or timing.")

    report_lines.extend([
        "",
        "## Next Steps",
        "- If selection shows stable improvement: proceed to C5-M formal validation.",
        "- If selection shows no improvement: reconsider signal design or timing hypothesis.",
        "",
        "## Gates",
        "- QUALIFICATION_STATUS = INSUFFICIENT_EVIDENCE",
        "- D8_H_ALLOWED = NO",
        "- PRODUCTION_PROMOTION = NO",
        "",
        "## Artifacts",
        "- `c5_l_selection_test_plan.json`",
        "- `c5_l_selection_results.json`",
        "- `c5_l_signal_quantile_analysis.json`",
        "- `c5_l_selection_concentration.json`",
        "- `c5_l_selection_economic.json`",
        "",
    ])
    report = "\n".join(report_lines)
    (DOC / "M9_1-C5-L_FUNDAMENTAL_SELECTION_TIMING_RESEARCH.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "COMPLETE",
        "selection_research_status": selection_status,
        "stage1_pass": stage1_pass,
        "experiment_count": len(results),
        "best_rule": best_rule,
        "best_excess": best_excess,
        "control_excess": all_eligible.get("mean_excess_return", 0.0),
        "selection_justified": selection_justified,
        "artifacts": [
            "data/research/strategy/c5_l_selection_test_plan.json",
            "data/research/strategy/c5_l_selection_results.json",
            "data/research/strategy/c5_l_signal_quantile_analysis.json",
            "data/research/strategy/c5_l_selection_concentration.json",
            "data/research/strategy/c5_l_selection_economic.json",
            "docs/M9_1-C5-L_FUNDAMENTAL_SELECTION_TIMING_RESEARCH.md",
        ],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
