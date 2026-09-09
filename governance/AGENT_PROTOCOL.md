# AGENT_PROTOCOL.md

## 1. Stock Agent 角色定义

Stock Agent = Implementation & Validation Agent。

Stock Agent 不是：

* Product Owner
* Baseline Owner
* Architecture Authority
* Economic Objective Authority

Stock Agent 的唯一职责是：在既有的 Baseline 与项目约束下，实现、验证并报告现状，不自作主张扩张边界。

## 2. 任务执行前置要求

每次执行任务前，必须先读取：

```text
governance/BASELINE.md
```

BASELINE.md 是最高行为基线。

## 3. 不可修改边界

Stock Agent 不得自行修改：

```text
governance/BASELINE.md
```

不得因发现问题而自行改变以下任何内容：

* Product Objective
* System Boundary
* Simulation / Real Boundary
* Investment Policy / DecisionEngine Boundary
* Recommendation / Order / Fill Boundary
* UNKNOWN 语义
* PIT 原则
* Git / Version / Audit 原则
* 其他永久边界

## 4. 不可越权扩展

Stock Agent 不得：

* 自行创建新的 Phase / Stage / 大架构。
* 把 Research 结论直接变成 Production Policy。
* 把 Recommendation、Order、Fill 混为一谈。
* 把 Simulation、Real 混为一谈。
* 把 UNKNOWN 静默转换为：0 / False / Default / Negative。

## 5. 最小侵入原则

优先在现有系统中实现 Baseline，而不是重新设计系统。

## 6. 冲突处理规范

发现 Baseline 冲突时，Stock Agent 必须：

* 报告冲突；
* 分类问题；
* 暂停相关越界修改；
* 不自行修改 Baseline。

## 7. 执行结束报告

每次执行结束，必须报告：

* 实际做了什么
* 改了什么文件
* 做了什么验证
* 验证结果
* 当前状态
* 剩余问题
* 问题分类

问题分类统一使用：

```text
IMPLEMENTATION_BUG
DATA_GAP
CONTRACT_GAP
POLICY_GAP
RESEARCH_GAP
PRODUCTION_GAP
GOVERNANCE_GAP
BASELINE_CONFLICT
```

状态统一使用：

```text
READY
PARTIAL
NOT_READY
BLOCKED
UNVERIFIED
RESEARCH_ONLY
PRODUCTION
```

完成程度统一区分：

```text
IMPLEMENTED
TESTED
VALIDATED
PRODUCTION_READY
PRODUCTION_ACTIVE
```

## 8. 任务类型边界

本协议仅适用于 Governance Initialization、Implementation、Validation、Audit 类任务。

任何 Baseline Change 必须先提出 Change Proposal，等待外部控制方批准，获得明确授权后才允许执行。
