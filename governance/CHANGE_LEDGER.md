# CHANGE_LEDGER.md

## 字段定义

* date: 变更日期
* change_id: 变更唯一标识
* type: 变更类型
* description: 变更描述
* baseline_impact: 对 Baseline 的影响
* policy_version: 涉及策略版本
* code_commit: 涉及代码提交
* status: 状态
* notes: 备注

## 变更记录

|| date | change_id | type | description | baseline_impact | policy_version | code_commit | status | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-09-09 | CHANGE-2026-09-09-001 | BASELINE_INITIALIZATION | Install Hermes Stock Agent Investment Decision System Baseline v1.2.1 FINAL | ESTABLISHED | — | — | COMPLETE | Governance directory initialized with BASELINE.md, AGENT_PROTOCOL.md, CHANGE_POLICY.md, CHANGE_LEDGER.md |
| 2026-09-09 | CHANGE-2026-09-09-002 | GIT_BASELINE_INITIALIZATION | Establish Git repository and initial code governance baseline for Hermes Stock Agent v1.2.1 | NONE | — | 63779d4 | COMPLETE | Git initialized at /home/caojy/.hermes/profiles/stock/stock-work; tag hermes-stock-baseline-v1.2.1 created |
| 2026-09-10 | CHANGE-2026-09-10-001 | BASELINE_COMPLIANCE_REMEDIATION | Sync CODE_BASELINE.md with actual repo state; declare production boundary outside stock-work | NONE | — | f22cbc7 | COMPLETE | Updated CODE_BASELINE.md to reflect actual branch/commit/working_tree and production asset boundary |
| 2026-09-10 | CHANGE-2026-09-10-002 | CONTRACT_IMPLEMENTATION | Populate Decision State Contract fields in engine.py and real_portfolio_truth.py | NONE | — | f22cbc7 | COMPLETE | Added policy_action/engine_result/final_action/block_reason/execution_status and canonical source/quality_status |
| 2026-09-10 | CHANGE-2026-09-10-003 | CRON_CONTRACT_FIX | Add missing Baseline Cron Contract fields to all 22 production jobs | NONE | — | f22cbc7 | COMPLETE | jobs.json updated with purpose/input/output/consumer/frequency/dependency/failure_behavior/domain/production_or_research |
| 2026-09-18 | CHANGE-2026-09-18-001 | CONTENT_LEVEL_REMEDIATION | 24-job content-level audit: stop-loss credential path, 000300 backfill 900 rows, pipeline PYTHONPATH, hot-sector 09:30→10:00, weekly cost validation, deep-review 16:00→16:50, fetch_holdings error text | PRODUCTION_READY | — | (see git log) | COMPLETE | Changes live in profiles/stock/scripts/cron (outside this repo); simulation.db 1736 contaminated rows purged with backup |
| 2026-09-18 | CHANGE-2026-09-18-002 | DATA_INTEGRITY | klines full-DB dedup: 31.35M→17.71M rows (44% redundancy), calibre arbitration (quality-first, highest rowid), UNIQUE INDEX idx_klines_code_date added, VACUUM 4.6GB→2.4GB | HIGH | — | (see git log) | COMPLETE | Pre-dedup backup ~/tmp/market_cache.db.bak-before-dedup-20260917-232829 (md5 recorded); downstream regression verified (classify_market, get_klines 500-window) |
| 2026-09-18 | CHANGE-2026-09-18-003 | REPO_SYNC | Commit 7-day backlog: core resolver extensions, core/research (C4-B2/C4-C/C4-D/C5-A), docs, governance auditors, one-off scripts archived to scripts/oneoff; gitignore data/state/ | NONE | — | (this commit) | COMPLETE | Remote push still blocked: SSH key unregistered on GitHub + repo name typo (prorfile) — pending user action |
| 2026-09-18 | CHANGE-2026-09-18-004 | MIRROR_ESTABLISHMENT | Plan B mirror: scripts-cron/ (95 deploy targets) + skills-mirror/feishu-bitable/ (64 skill modules) committed as source of truth; scripts/sync_mirror.sh provides sync + --check drift detection (inject/verify-tested). Remote push to github caojyb/hermes-stock-profile completed (6 commits + 2 tags) | NONE | — | (this commit) | COMPLETE | Drift discipline: edit production side only, then sync_mirror.sh + commit |
| 2026-09-18 | CHANGE-2026-09-18-005 | P0_FIX | Bitable 持仓读取链路三断点：_execute_command 调用点×2 改 read_positions；0.0% 仓位根因= portfolio dict 键名 holdings_value/total_holdings_value 不匹配；质量守卫浮出+硬失败（ratio>3/<1/3 → ERROR → exit 1，5 只成本异常股当场拦截） | CRITICAL | 7029f12 (pre-filter-repo: cbd9aa9 前一提交 7029f12 重写为 1d1ec77) | (see git log) | COMPLETE | 悬置周一开盘首次真实运行验收 |
| 2026-09-18 | CHANGE-2026-09-18-006 | SCHEDULING | 调度错峰: track-outcomes 17:30/1-5, cache-health 17:50/1-5, deep-review 17:10, intraday 交易时段守卫; lint prompt 路径修正 | HIGH | b76b2ac | (see git log) | COMPLETE | executions.db + jobs.json 双源验证 |
| 2026-09-18 | CHANGE-2026-09-18-007 | NEW_GUARD | cron_health_sentinel.py (08:05, WARN/failed/缺口三类扫描+crash log 轮转) + mirror_drift_check.sh (08:25) + 系统 crontab 兜底 (20 8 * * 1-5, 仅 gateway 死亡时告警) | HIGH | b76b2ac | (see git log) | COMPLETE | 哨兵首跑抓到当日 4 次静默失败 + 8 周更缺口 |
| 2026-09-18 | CHANGE-2026-09-18-008 | HYGIENE | 51GB 冗余 gio trash (10 DB 副本+2 备份+WAL+1GB md, 留 1 份 pre-dedup); 0B 空壳×3+MARKET_DB+孤儿输出目录; 双 venv 收口; promotion_records schema 就绪不接线; 58 pending 记忆应用后清空 | HIGH | b76b2ac | (see git log) | COMPLETE | profile 56G→8.8G, 活跃库 klines 校验一致 |
| 2026-09-18 | CHANGE-2026-09-18-009 | SECURITY_P0 | 凭证治理: 仓库确认 public; bitable_reader/writer 凭证 default 全部移除（改 _local_constants 向上遍历查找）; .gitignore 补 override.json/.env; filter-repo 清洗全部历史 blob; force push; 遗留: Bitable base token 建议轮换（需用户在飞书操作） | CRITICAL | 436d111 | (forced push) | COMPLETE | 全历史 grep 零命中; app_secret 未泄露 |
