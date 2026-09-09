# CODE_BASELINE.md

## Baseline Identity

baseline_id: HERMES-STOCK-IDS
baseline_version: 1.2.1

## Repository State

repository_root: /home/caojy/.hermes/profiles/stock/stock-work
git_branch: master
git_commit: 63779d4
git_tag: hermes-stock-baseline-v1.2.1
working_tree_status: CLEAN

## Included Scope

* governance/*
* core/*
* config/*
* tests/*
* check_parens.py
* check_syntax.py
* MANIFEST.yaml

## Excluded Scope

* data/archive/*
* data/production/*
* data/quarantine/*
* data/runtime/*
* data/snapshots/*
* data/research/*
* data/market_cache.db
* data/intraday_cache.db
* data/news_cache.db
* docs/architecture/*.json
* logs/*
* outputs/*
* recovery/*
* runtime/*
* core/__pycache__/*

## Audit Notes

* The repository was initialized with a scoped initial commit.
* Large data and runtime artifacts are excluded via `.gitignore`.
* `core/research/` and `docs/` remain untracked pending further audit.
* No business logic changes were made during this baseline establishment.

## Generated

generated_at: 2026-09-09
