#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Production Research/Production Boundary Hard Isolation Enforcer（READ ONLY / NO MIGRATION）
Scope: enforce absolute boundary for runtime code only.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Dict, List

PROFILE_ROOT = Path(__file__).resolve().parents[3]
STOCK_WORK = PROFILE_ROOT / "stock-work"
SCRIPTS_CRON = PROFILE_ROOT / "scripts" / "cron"
SKILLS_STOCK_EXPERT = PROFILE_ROOT / "skills" / "stock" / "stock-expert"

PRODUCTION_RUNTIME_ROOTS = [SCRIPTS_CRON, SKILLS_STOCK_EXPERT]
RESEARCH_ROOTS = [STOCK_WORK / "data" / "research", STOCK_WORK / "core" / "research"]
EXCLUDE_DIRS = {"__pycache__", "venv", ".venv", "site-packages", "node_modules", ".git", "archive", "archived", "quarantine", "docs", "logs", "outputs", "runtime", "cache", "tests", "backups", "snapshots"}

_BOUNDARY_IMPORTS = {
    "scripts/cron/decision/engine.py": ["core.compat_paths", "decision.outcome"],
    "scripts/cron/decision/real_portfolio_truth.py": ["core.compat_paths", "decision.execution"],
    "scripts/cron/decision/execution.py": ["core.compat_paths"],
    "scripts/cron/decision/outcome.py": ["core.compat_paths"],
    "scripts/cron/decision/outcome_store.py": ["core.compat_paths"],
    "scripts/cron/decision/evidence_framework.py": ["core.compat_paths", "decision.execution", "decision.outcome"],
}


def _iter_py_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def _imports(path: Path) -> List[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
    return sorted(set(names))


def audit() -> Dict:
    production_imports: Dict[str, List[str]] = {}
    for root in PRODUCTION_RUNTIME_ROOTS:
        for p in _iter_py_files(root):
            rel = p.relative_to(PROFILE_ROOT).as_posix()
            production_imports[rel] = _imports(p)

    research_imports: Dict[str, List[str]] = {}
    for root in RESEARCH_ROOTS:
        if not root.exists():
            continue
        for p in _iter_py_files(root):
            rel = p.relative_to(PROFILE_ROOT).as_posix()
            research_imports[rel] = _imports(p)

    violations = []
    approved_imports = {}
    for rel, imps in _BOUNDARY_IMPORTS.items():
        allowed = set()
        for root in PRODUCTION_RUNTIME_ROOTS:
            candidate = PROFILE_ROOT / rel
            if candidate.exists() and candidate.resolve().is_relative_to(root.resolve()):
                allowed.update(imps)
                break
        approved_imports[rel] = sorted(allowed) if allowed else imps

    for rel, imps in production_imports.items():
        if rel in approved_imports:
            continue
        bad = []
        for imp in imps:
            parts = imp.split(".")
            top = parts[0]
            if top in {"core", "data", "stock_work"} or imp.startswith("data.research") or imp.startswith("core.research"):
                bad.append(imp)
        if bad:
            violations.append({"file": rel, "blocked_imports": bad})

    research_cross = []
    for rel, imps in research_imports.items():
        bad = []
        for imp in imps:
            parts = imp.split(".")
            top = parts[0]
            if top in {"scripts", "skills"}:
                bad.append(imp)
        if bad:
            research_cross.append({"file": rel, "blocked_imports": bad})

    return {
        "production_runtime_roots": [str(r.relative_to(PROFILE_ROOT)) for r in PRODUCTION_RUNTIME_ROOTS],
        "research_roots": [str(r.relative_to(PROFILE_ROOT)) for r in RESEARCH_ROOTS if r.exists()],
        "production_import_violations": violations,
        "research_cross_production_imports": research_cross,
        "approved_imports": approved_imports,
        "status": "SATISFIED" if not violations and not research_cross else "PARTIALLY",
    }


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
