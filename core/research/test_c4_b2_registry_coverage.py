#!/usr/bin/env python3
"""
test_c4_b2_registry_coverage.py — M9.1-C4-B2-M registry consistency regression test.
Read-only. No production mutation.
"""
from __future__ import annotations

import json, os, sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.research.strategy_registry.strategy_registry import build_default_registry

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')

# Canonical authorized variants from D7-C4-B expansion registry
AUTHORIZED_VARIANTS = [
    ("trend_v1", "Trend"),
    ("trend_short_v1", "Trend"),
    ("trend_long_v1", "Trend"),
    ("momentum_v1", "Momentum"),
    ("momentum_medium_v1", "Momentum"),
    ("momentum_risk_adjusted_v1", "Momentum"),
    ("reversal_v1", "Reversal"),
    ("breakout_strength_v1", "Breakout"),
    ("breakout_confirmation_v1", "Breakout"),
    ("volatility_level_v1", "Volatility"),
    ("volatility_change_v1", "Volatility"),
    ("volume_trend_v1", "PriceVolume"),
    ("volume_price_correlation_v1", "PriceVolume"),
    ("naive_baseline_v1", "Baseline"),
]

def load_runner_variants(runner_path: Path) -> List[Tuple[str, str]]:
    """Extract (strategy_id, family) from a runner file."""
    content = runner_path.read_text(encoding="utf-8")
    variants = []
    import ast, re
    match = re.search(r'VARIANTS\s*=\s*\[(.*?)\]', content, re.DOTALL | re.IGNORECASE)
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
                    variants.append((sid, family))
                except Exception:
                    continue
    except Exception:
        pass
    return variants

def load_executed_variants() -> List[str]:
    """Load strategy_ids from executed stage3 chunk files."""
    executed = []
    artifact_dir = BASE / 'data/research/strategy'
    for p in artifact_dir.glob('c4_b2_stage3_chunk_*.json'):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            executed.append(obj.get("strategy_id"))
        except Exception:
            continue
    return executed

def main():
    full_matrix_runner = BASE / 'core/research/c4_b2_full_matrix_runner.py'
    stage3_runner = BASE / 'core/research/c4_b2_stage3_full_matrix.py'

    runner_variants = load_runner_variants(full_matrix_runner)
    stage3_variants = load_runner_variants(stage3_runner)
    executed = load_executed_variants()

    authorized_ids = {v[0] for v in AUTHORIZED_VARIANTS}
    runner_ids = {v[0] for v in runner_variants}
    stage3_ids = {v[0] for v in stage3_variants}
    executed_ids = set(executed)

    results = {
        "AUTHORIZED_VARIANTS_COUNT": len(authorized_ids),
        "RUNNER_DISCOVERED_COUNT": len(runner_ids),
        "STAGE3_RUNNER_COUNT": len(stage3_ids),
        "EXECUTED_COUNT": len(executed_ids),
        "AUTHORIZED_EQ_RUNNER": authorized_ids == runner_ids,
        "AUTHORIZED_EQ_STAGE3": authorized_ids == stage3_ids,
        "AUTHORIZED_EQ_EXECUTED": authorized_ids == executed_ids,
        "MISSING_FROM_RUNNER": sorted(authorized_ids - runner_ids),
        "MISSING_FROM_STAGE3": sorted(authorized_ids - stage3_ids),
        "MISSING_FROM_EXECUTED": sorted(authorized_ids - executed_ids),
        "UNEXPECTED_IN_RUNNER": sorted(runner_ids - authorized_ids),
        "UNEXPECTED_IN_STAGE3": sorted(stage3_ids - authorized_ids),
        "UNEXPECTED_IN_EXECUTED": sorted(executed_ids - authorized_ids),
    }

    passed = (
        results["AUTHORIZED_EQ_RUNNER"]
        and results["AUTHORIZED_EQ_STAGE3"]
        and results["AUTHORIZED_EQ_EXECUTED"]
        and len(results["MISSING_FROM_RUNNER"]) == 0
        and len(results["MISSING_FROM_STAGE3"]) == 0
        and len(results["MISSING_FROM_EXECUTED"]) == 0
        and len(results["UNEXPECTED_IN_RUNNER"]) == 0
        and len(results["UNEXPECTED_IN_STAGE3"]) == 0
        and len(results["UNEXPECTED_IN_EXECUTED"]) == 0
    )

    results["PASS"] = passed
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return passed

if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
