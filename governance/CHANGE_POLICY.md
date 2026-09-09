# CHANGE_POLICY.md

## 一、默认不可直接修改 Baseline 的情形

以下情形默认只能修改对应 Implementation / Contract / Policy / Parameter / Research 对象，不得直接修改 Baseline：

* Bug Fix
* Provider Change
* Data Source Change
* Research
* Strategy
* Policy Parameter
* Threshold
* New Evidence Source
* Refactor
* Test Improvement
* Cron Adjustment

## 二、允许提出 Baseline Change 的情形

只有真正改变以下内容时，才允许提出 Baseline Change：

* Economic Objective
* Product Definition
* Simulation / Real Operating Model
* Investment Policy 与 DecisionEngine 核心职责
* Recommendation / Order / Fill 核心语义
* Daily / Intraday 产品范式
* Git / Version / Audit 核心治理原则
* 其他永久边界

## 三、Baseline Change 批准权限

Stock Agent 无权自行批准 Baseline Change。

任何 Baseline Change 只能：

* 提出 Change Proposal；
* 等待外部控制方批准；
* 获得明确授权后才允许执行。

## 四、Production Promotion 强制要求

任何 Production Promotion 必须满足：

* Git Working Tree CLEAN
* 有明确 Code Commit
* 有 Policy Version
* 有相关 Data / Contract / Execution Model Version
* 可追溯

## 五、记录要求

所有变更必须同步更新：

```text
governance/CHANGE_LEDGER.md
```

并确保可追溯。
