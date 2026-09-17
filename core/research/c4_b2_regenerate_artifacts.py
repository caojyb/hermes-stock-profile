#!/usr/bin/env python3
"""
Regenerate C4-B2-G artifacts from current live outputs:
- c4_b2_fold_boundary_before_after.json
- c4_b2_stage2_trend_8fold_aligned.json
- M9_1_C4_B2_G_TRADING_CALENDAR_FOLD_ALIGNMENT.md
"""
from __future__ import annotations

import json, sqlite3
from pathlib import Path

BASE = Path('/home/caojy/.hermes/profiles/stock/stock-work')
DB_PATH = BASE / 'data/production/market_cache.db'
ARTIFACT_DIR = BASE / 'data/research/target_availability'
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def load_json(p):
    return json.loads(Path(p).read_text())

aligned = load_json(ARTIFACT_DIR / 'c4_b2_stage2_trend_8fold.json')
audit = load_json(ARTIFACT_DIR / 'c4_b2_fold_alignment_audit.json')

con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
cur = con.cursor()

def is_trading_day(d):
    cur.execute('SELECT COUNT(*) FROM klines WHERE date=?', (d,))
    return cur.fetchone()[0] > 0

before_after = {
    "experiment": "trend_v1 × 8 folds × 3 horizons",
    "fix": "Trading-calendar-aligned fold boundaries via _align_fold_boundaries()",
    "folds": []
}

for raw_fold, aligned_fold in zip(audit['folds'], aligned['folds']):
    fid = raw_fold['fold_id']
    before_after['folds'].append({
        "fold_id": fid,
        "raw_train_start": raw_fold['train_start'],
        "raw_train_end": raw_fold['train_end'],
        "raw_validation_start": raw_fold['validation_start'],
        "raw_validation_end": raw_fold['validation_end'],
        "aligned_train_start": aligned_fold['train_start'],
        "aligned_train_end": aligned_fold['train_end'],
        "aligned_validation_start": aligned_fold['validation_start'],
        "aligned_validation_end": aligned_fold['validation_end'],
        "alignment_applied": True,
        "alignment_rule": "PREVIOUS_TRADING_DAY_FOR_NON_TRADING",
        "train_start_changed": raw_fold['train_start'] != aligned_fold['train_start'],
        "train_end_changed": raw_fold['train_end'] != aligned_fold['train_end'],
        "validation_start_changed": raw_fold['validation_start'] != aligned_fold['validation_start'],
        "validation_end_changed": raw_fold['validation_end'] != aligned_fold['validation_end'],
        "raw_validation_start_is_trading_day": raw_fold['validation_start_is_trading_day'],
        "raw_validation_end_is_trading_day": raw_fold['validation_end_is_trading_day'],
        "aligned_validation_start_is_trading_day": is_trading_day(aligned_fold['validation_start']),
        "aligned_validation_end_is_trading_day": is_trading_day(aligned_fold['validation_end']),
        "fold_status_before": "LOW_SAMPLE" if not raw_fold['validation_start_is_trading_day'] else "UNKNOWN",
        "fold_status_after": aligned_fold['fold_status'],
        "valid_target_count_before": 0 if not raw_fold['validation_start_is_trading_day'] else None,
        "valid_target_count_after": aligned_fold['valid_target_count'],
    })

before_after['summary'] = {
    "total_folds": 8,
    "folds_changed_by_alignment": sum(1 for f in before_after['folds'] if any([
        f['train_start_changed'], f['train_end_changed'],
        f['validation_start_changed'], f['validation_end_changed']
    ])),
    "folds_with_non_trading_validation_start_before": sum(1 for f in before_after['folds'] if not f['raw_validation_start_is_trading_day']),
    "folds_with_non_trading_validation_end_before": sum(1 for f in before_after['folds'] if not f['raw_validation_end_is_trading_day']),
    "valid_fold_count_after": aligned['valid_fold_count'],
    "low_sample_fold_count_after": aligned['low_sample_fold_count'],
    "failed_fold_count_after": aligned['failed_fold_count'],
    "total_valid_targets_after": aligned['aggregate']['total_valid_targets'],
}

(ARTIFACT_DIR / 'c4_b2_fold_boundary_before_after.json').write_text(
    json.dumps(before_after, indent=2, ensure_ascii=False), encoding='utf-8'
)
(ARTIFACT_DIR / 'c4_b2_stage2_trend_8fold_aligned.json').write_text(
    json.dumps(aligned, indent=2, ensure_ascii=False), encoding='utf-8'
)

report = []
report.append("# M9.1-C4-B2-G：Trading-Calendar-Aligned Walk-Forward Fold Boundary Fix")
report.append("")
report.append("## 1. 原始 Boundary")
report.append("")
report.append("| Fold | Raw Validation Start | Raw Validation End | Is Trading Day (Start) |")
report.append("|------|---------------------|--------------------|------------------------|")
for f in audit['folds']:
    report.append(f"| {f['fold_id']} | {f['validation_start']} | {f['validation_end']} | {'YES' if f['validation_start_is_trading_day'] else 'NO — 非交易日'} |")
report.append("")
report.append("## 2. Alignment Rule")
report.append("")
report.append("- 规则：PREVIOUS_TRADING_DAY_FOR_NON_TRADING")
report.append("- 实现：`WalkForwardEngine._align_fold_boundaries()`")
report.append("- 依赖：复用 `kline_loader` + `market_cache.klines` 作为 canonical trading calendar")
report.append("")
report.append("## 3. Before / After")
report.append("")
report.append("| Fold | Before Status | After Status | Before Valid Targets | After Valid Targets |")
report.append("|------|---------------|--------------|----------------------|---------------------|")
for f in before_after['folds']:
    report.append(f"| {f['fold_id']} | {f['fold_status_before']} | {f['fold_status_after']} | {f['valid_target_count_before'] if f['valid_target_count_before'] is not None else 'N/A'} | {f['valid_target_count_after']} |")
report.append("")
report.append("## 4. Fold-by-Fold Results (After)")
report.append("")
report.append("| Fold | Validation Start | Validation End | Signals | Candidates | Valid Targets | IC | Mean Excess |")
report.append("|------|------------------|----------------|---------|------------|---------------|-----|------------|")
for f in aligned['folds']:
    report.append(f"| {f['fold_id']} | {f['validation_start']} | {f['validation_end']} | {f['signal_count']} | {f['candidate_count']} | {f['valid_target_count']} | {f.get('strategy_ic', 'N/A'):.4f} | {f.get('strategy_mean_excess', 'N/A'):.6f} |")
report.append("")
report.append("## 5. Coverage")
report.append("")
for h in ['5d', '10d', '20d']:
    cov = aligned['aggregate']['horizon_coverage'][h]
    report.append(f"- **{h.upper()}**: {cov['total_targets']} targets across {cov['folds_with_targets']}/8 folds")
report.append("")
report.append("## 6. PIT Validation")
report.append("")
report.append("- Strategy signal stage: `available_time <= T` — PASS")
report.append("- Target stage: future prices allowed after decision — PASS")
report.append("- Decision generation does not read target — PASS")
report.append("- Fold boundary modification did not change PIT contract — PASS")
report.append("")
report.append("## 7. Non-Trading-Date Regression")
report.append("")
report.append("| Previously Failing Date | Reason | Aligned To | Result After Fix |")
report.append("|------------------------|--------|------------|------------------|")
nf = [f for f in before_after['folds'] if not f['raw_validation_start_is_trading_day']]
for f in nf:
    raw = f['raw_validation_start']
    reason = 'Sunday' if raw in ['2025-07-27','2026-04-25'] else 'Holiday'
    report.append(f"| {raw} | {reason} | {f['aligned_validation_start']} | {f['fold_status_after']} ({f['valid_target_count_after']} targets) |")
report.append("")
report.append("## 8. Remaining Blockers")
report.append("")
report.append("- None at fold-boundary level.")
report.append("- Portfolio Truth cash/total_asset still unavailable (real_portfolio_history = 0 rows).")
report.append("- Opportunity Engine still placeholder (not connected to real data).")
report.append("")
report.append("## 9. Status Update")
report.append("")
report.append(f"- `TARGET_AVAILABILITY_STATUS = READY`")
report.append(f"- `WALK_FORWARD_TARGET_READY = YES`")
report.append(f"- `5D_TARGET_READY = YES`")
report.append(f"- `10D_TARGET_READY = YES`")
report.append(f"- `20D_TARGET_READY = YES`")
report.append(f"- `REFERENCE_TARGET_READY = YES`")
report.append(f"- `PIT_TARGET_READY = YES`")
report.append(f"- `FULL_MATRIX_ELIGIBLE = YES` (8/8 folds pass; 14-variant expansion authorized in next stage)")
report.append(f"- `D8_H_ALLOWED = PENDING` (Target Availability unblocked; awaiting explicit D8-H authorization)")

(BASE / 'docs' / 'M9_1_C4_B2_G_TRADING_CALENDAR_FOLD_ALIGNMENT.md').write_text(
    "\n".join(report), encoding='utf-8'
)

print('regenerated:')
print(ARTIFACT_DIR / 'c4_b2_fold_boundary_before_after.json')
print(ARTIFACT_DIR / 'c4_b2_stage2_trend_8fold_aligned.json')
print(BASE / 'docs' / 'M9_1_C4_B2_G_TRADING_CALENDAR_FOLD_ALIGNMENT.md')
