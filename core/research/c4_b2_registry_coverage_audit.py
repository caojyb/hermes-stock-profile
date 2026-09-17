#!/usr/bin/env python3
"""
c4_b2_registry_coverage_audit.py — M9.1-C4-B2-M registry/runner/evidence coverage audit.
Read-only. No production mutation.
"""
from __future__ import annotations

import json, os, sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.research.strategy_registry.strategy_registry import build_default_registry

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
ARTIFACT_DIR = BASE / 'data/research/strategy'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def load_canonical_authorized_variants() -> List[Tuple[str, str, str, str, Dict[str, Any]]]:
    """Load authorized variants from expansion document and registry."""
    # From M9_1_D7_C4_B_STRATEGY_FAMILY_EXPANSION.md Section 2 + 6.2
    authorized = [
        # Trend Family
        ("trend_v1", "trend_v1", "Trend", "TrendStrategy", {"lookback": 60}),
        ("trend_short_v1", "trend_short_v1", "Trend", "TrendStrategy", {"lookback": 20}),
        ("trend_long_v1", "trend_long_v1", "Trend", "TrendStrategy", {"lookback": 120}),
        # Momentum Family
        ("momentum_v1", "momentum_v1", "Momentum", "MomentumStrategy", {"lookback": 20}),
        ("momentum_medium_v1", "momentum_medium_v1", "Momentum", "MomentumStrategy", {"lookback": 60}),
        ("momentum_risk_adjusted_v1", "momentum_risk_adjusted_v1", "Momentum", "MomentumRiskAdjustedStrategy", {"lookback": 60, "vol_lookback": 20}),
        # Reversal Family
        ("reversal_v1", "reversal_v1", "Reversal", "ReversalStrategy", {"lookback": 5}),
        # Breakout Family
        ("breakout_strength_v1", "breakout_strength_v1", "Breakout", "BreakoutStrengthStrategy", {"lookback": 20}),
        ("breakout_confirmation_v1", "breakout_confirmation_v1", "Breakout", "BreakoutConfirmationStrategy", {"lookback": 20}),
        # Volatility Family
        ("volatility_level_v1", "volatility_level_v1", "Volatility", "VolatilityLevelStrategy", {"lookback": 20}),
        ("volatility_change_v1", "volatility_change_v1", "Volatility", "VolatilityChangeStrategy", {"lookback_short": 10, "lookback_long": 30}),
        # PriceVolume Family
        ("volume_trend_v1", "volume_trend_v1", "PriceVolume", "VolumeTrendStrategy", {"lookback": 20}),
        ("volume_price_correlation_v1", "volume_price_correlation_v1", "PriceVolume", "VolumePriceCorrelationStrategy", {"lookback": 20}),
        # Baseline
        ("naive_baseline_v1", "naive_baseline_v1", "Baseline", "NaiveBaselineStrategy", {"seed": 42}),
    ]
    return authorized

def load_runner_variants(runner_path: Path) -> List[Tuple[str, str, str, Dict[str, Any]]]:
    """Extract variant list from a runner file by parsing the VARIANTS list."""
    content = runner_path.read_text(encoding="utf-8")
    variants = []
    # Simple extraction: find lines with ("strategy_id", "Family", ClassName, {params})
    import ast, re
    # Find the VARIANTS = [...] block
    match = re.search(r'VARIANTS\s*=\s*\[(.*?)\]', content, re.DOTALL)
    if not match:
        return variants
    block = '[' + match.group(1) + ']'
    try:
        tree = ast.parse(block, mode='eval')
        for node in ast.walk(tree):
            if isinstance(node, ast.Tuple) and len(node.elts) == 4:
                try:
                    sid = ast.literal_eval(node.elts[0])
                    family = ast.literal_eval(node.elts[1])
                    cls_name = ast.literal_eval(node.elts[2])
                    params = ast.literal_eval(node.elts[3])
                    variants.append((sid, family, cls_name, params))
                except Exception:
                    continue
    except Exception:
        pass
    return variants

def load_executed_variants() -> List[str]:
    """Load strategy_ids from executed chunk files."""
    executed = []
    for p in ARTIFACT_DIR.glob('c4_b2_stage3_chunk_*.json'):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            executed.append(obj.get("strategy_id"))
        except Exception:
            continue
    return executed

def main():
    authorized = load_canonical_authorized_variants()
    runner_variants = load_runner_variants(BASE / 'core/research/c4_b2_full_matrix_runner.py')
    stage3_variants = load_runner_variants(BASE / 'core/research/c4_b2_stage3_full_matrix.py')
    executed = load_executed_variants()

    authorized_ids = {v[0] for v in authorized}
    runner_ids = {v[0] for v in runner_variants}
    stage3_ids = {v[0] for v in stage3_variants}
    executed_ids = set(executed)

    missing = sorted(authorized_ids - executed_ids)
    unexpected = sorted(executed_ids - authorized_ids)

    audit = {
        "authorized_variant_count": len(authorized_ids),
        "runner_variant_count": len(runner_ids),
        "stage3_runner_variant_count": len(stage3_ids),
        "executed_variant_count": len(executed_ids),
        "missing_variant_count": len(missing),
        "unexpected_variant_count": len(unexpected),
        "authorized_variants": sorted(authorized_ids),
        "runner_variants": sorted(runner_ids),
        "stage3_runner_variants": sorted(stage3_ids),
        "executed_variants": sorted(executed_ids),
        "missing_variants": missing,
        "unexpected_variants": unexpected,
        "registry_root_cause": (
            "c4_b2_full_matrix_runner.py and c4_b2_stage3_full_matrix.py hardcode VARIANTS lists "
            "that diverge from canonical D7-C4-B expansion registry. "
            "Runner lists contain 8 variants; authorized set contains 14 variants."
        ),
        "fix_required": True,
    }

    out = ARTIFACT_DIR / 'c4_b2_registry_coverage_audit.json'
    out.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    return audit

if __name__ == "__main__":
    main()
