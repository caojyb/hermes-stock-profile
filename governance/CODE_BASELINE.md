# CODE_BASELINE.md

## Baseline Identity

baseline_id: HERMES-STOCK-IDS
baseline_version: 1.2.1

## Repository State

repository_root: /home/caojy/.hermes/profiles/stock/stock-work
git_branch: main
git_commit: f22cbc707c08177f0f61974d3fdee9ddd83e4bee
git_tag: hermes-stock-baseline-v1.2.1
working_tree_status: DIRTY

## Policy Binding

The following policy version is bound to the above git state:
policy_version: baseline-v1.2.1
binding_rule: Any change to policy, strategy, or execution behavior MUST increment policy_version and update CODE_BASELINE.md accordingly.

## Included Scope

* governance/*
* core/*
* config/*
* tests/*
* check_parens.py
* check_syntax.py
* MANIFEST.yaml

## Production Boundary (Outside stock-work)

Production runtime code is intentionally maintained outside `stock-work` under the Hermes profile root.
The following production paths are version-controlled and part of the effective baseline, but are not tracked by `stock-work`:

* PROFILE / 'stock-work/production/stock-work/production/stock-work/production/scripts/cron' / decision/engine.py
* PROFILE / 'stock-work/production/stock-work/production/stock-work/production/scripts/cron' / decision/real_portfolio_truth.py
* PROFILE / 'stock-work/production/stock-work/production/stock-work/production/scripts/cron' / decision/execution.py
* PROFILE / 'stock-work/production/stock-work/production/stock-work/production/scripts/cron' / double_monitor.py
* /home/caojy/.hermes/profiles/stock/cron/jobs.json

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

## Research Boundary (Inside stock-work)

These directories are tracked but classified as research/legacy assets, not included in production baseline scope:

* core/research/*
* core/data/research/*
* data/research/*
* tests/legacy/*

## Audit Flags

CODE_BASELINE_ESTABLISHED = YES
BASELINE_COMPLIANCE_VALIDATED = NO

## Audit Notes

* Initial scoped governance commit/tag are present in stock-work.
* Working tree is DIRTY with uncommitted changes; production promotion should not proceed until reconciled.
* Business logic in production code outside stock-work is not duplicated inside stock-work governance tracking; this boundary record makes the separation explicit.
* No business logic changes were made during this baseline establishment/update.

## Generated

generated_at: 2026-09-10
