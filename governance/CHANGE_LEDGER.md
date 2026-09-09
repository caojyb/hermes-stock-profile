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

| date | change_id | type | description | baseline_impact | policy_version | code_commit | status | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-09-09 | CHANGE-2026-09-09-001 | BASELINE_INITIALIZATION | Install Hermes Stock Agent Investment Decision System Baseline v1.2.1 FINAL | ESTABLISHED | — | — | COMPLETE | Governance directory initialized with BASELINE.md, AGENT_PROTOCOL.md, CHANGE_POLICY.md, CHANGE_LEDGER.md |
| 2026-09-09 | CHANGE-2026-09-09-002 | GIT_BASELINE_INITIALIZATION | Establish Git repository and initial code governance baseline for Hermes Stock Agent v1.2.1 | NONE | — | 63779d4 | COMPLETE | Git initialized at /home/caojy/.hermes/profiles/stock/stock-work; tag hermes-stock-baseline-v1.2.1 created |
