baseline_id: HERMES-STOCK-IDS
baseline_version: 1.2.1
status: FROZEN
scope: Hermes Stock Agent
source_of_truth: governance/BASELINE.md

# Hermes Stock Agent

## Investment Decision System Baseline v1.2.1 FINAL

**Status：FREEZE**

**Scope：Hermes Stock Agent / A 股投资决策系统**

**Document Role：**
本文件是 Hermes Stock Agent 后续开发、代码审计、Research、Simulation、Production、Promotion、Outcome、Learning、Rollback 和验收的**最高行为基线**。

任何后续工作必须先判断：

> 是否违反本 Baseline？

如果没有违反 Baseline，可以修改 Contract、Policy、Parameter 或 Implementation。

如果违反 Baseline，则不得通过“实现方便”绕过，必须走 Baseline Change Procedure。

---

# 0. Executive Definition

Hermes Stock Agent 是一个：

> **面向 A 股市场的投资决策 Agent，拥有自动 Simulation 投资循环和人工执行 Real Investment Advisory 循环。**

系统最终目标不是产生更多分析、更多评分或更多研究，而是：

> **在风险、回撤、流动性、交易成本和执行约束下，提高用户长期实际资本净财富增长的概率与幅度。**

系统必须最终能够回答：

```text
当前市场是什么环境？
当前应该进攻还是防守？
应该买什么？
为什么买？
什么时候买？
目标配置多少？
实际可以买多少？
已有持仓怎么办？
什么时候减仓？
什么时候退出？
为什么？
过去这些决策究竟是否创造了资本价值？
```

---

# 1. Economic Objective Contract

## 1.1 Primary Objective

最高层目标：

> **Long-Term Real Net Wealth Growth**

即：

> 长期真实资本净财富增长。

最终评价必须考虑：

* 交易成本；
* 税费；
* 滑点；
* 实际执行；
* 资本占用；
* 风险；
* 回撤。

---

## 1.2 Non-Guarantee Principle

系统绝不把：

> “必须赚钱”

解释成数学意义上的盈利保证。

系统不得承诺：

* 每笔交易盈利；
* 每月盈利；
* 每年盈利；
* 永远跑赢指数；
* 永远不会发生回撤；
* 永远不会发生 Policy Failure。

系统承担的是：

> **通过可验证的投资决策机制，提高长期资本增值质量。**

---

## 1.3 Economic Objective Hierarchy

### 一级

```text
Long-Term Net Wealth Growth
```

### 二级

```text
Risk-Adjusted Capital Growth
```

### 三级

```text
Capital Loss / Drawdown Control
```

### 四级

```text
Capital Efficiency
```

包括：

* turnover；
* transaction cost；
* capital utilization；
* exposure。

### 五级

```text
Explainability
Auditability
Reproducibility
Execution Quality
```

第五级目标不能替代第一至第四级目标。

---

# 2. Economic Decision Model

系统最终的经济结果由五个核心投资贡献层共同决定：

```text
Alpha
Timing
Sizing
Exit
Portfolio
```

## 2.1 Alpha

回答：

> 买什么？

目标是找到具有足够预期收益/风险优势的投资机会。

---

## 2.2 Timing

回答：

> 什么时候买？

目标不是单纯预测价格，而是优化进入风险收益比。

---

## 2.3 Sizing

回答：

> 配多少资本？

通过 Target Weight、Portfolio Constraints 和 Risk Policy 决定资本分配。

---

## 2.4 Exit

回答：

> 什么时候减仓/退出？

包括：

* thesis break；
* risk deterioration；
* market regime change；
* relative deterioration；
* valuation；
* portfolio constraints；
* time-based exit。

---

## 2.5 Portfolio

回答：

> 单只股票放在整个组合里是否值得？

考虑：

* concentration；
* sector exposure；
* correlation；
* liquidity；
* drawdown；
* total portfolio risk。

---

# 3. System Operating Model

系统拥有两个并行但严格隔离的 Operating Domain：

```text
SIMULATION
REAL
```

二者可以共享：

* Market Data；
* Evidence；
* Investment Policy；
* Decision Semantics；
* Research；
* Outcome Definitions。

但不得共享：

* 真实资金状态；
* Simulation Fill；
* Real Fill；
* Real Execution State。

---

# 4. Simulation Loop

Canonical Simulation Loop：

```text
Market Data
    ↓
Market Environment
    ↓
Opportunity / Candidate
    ↓
Evidence Fusion
    ↓
Investment Decision Policy
    ↓
Entry / Exit Policy
    ↓
Policy Target Weight
    ↓
Simulated Order
    ↓
Simulation Execution Model
    ↓
Simulation Portfolio
    ↓
Outcome
    ↓
Economic Evaluation
    ↓
Attribution
    ↓
Research / Learning
    ↓
Candidate Policy
```

Simulation 的核心目的：

> **验证投资决策是否在明确、可复现、可审计的交易执行规则下创造经济价值。**

---

# 5. Real Investment Advisory Loop

Canonical Real Loop：

```text
Real Market
    ↓
Market Environment
    ↓
Opportunity
    ↓
Evidence Fusion
    ↓
Investment Decision Policy
    ↓
Entry Timing
    ↓
Policy Position Sizing
    ↓
Tradability / Risk
    ↓
Portfolio Constraints
    ↓
DecisionEngine
    ↓
Final Recommendation
    ↓
Human Confirmation
    ↓
Manual Execution
    ↓
Execution Confirmation
    ↓
Real Portfolio Update
    ↓
Outcome
    ↓
Economic Evaluation
    ↓
Attribution
```

Real 资金执行权属于用户。

---

# 6. Responsibility Boundary

## 6.1 Investment Decision Policy

Investment Decision Policy 是：

> **投资大脑。**

它负责：

* Market Interpretation；
* Opportunity Evaluation；
* Evidence Integration；
* Entry Timing；
* Position Sizing；
* Exit；
* Portfolio Policy；
* Investment Recommendation。

---

## 6.2 DecisionEngine

DecisionEngine 是：

> **最终 Hard Constraint / Safety Arbiter。**

它不负责：

* Discover Alpha；
* 选股；
* 创造 Entry Strategy；
* 代替 Investment Policy；
* 产生投资观点。

它负责判断：

> **Policy Recommendation 是否允许进入执行层。**

---

# 7. Decision State Contract

任何正式 Decision 必须能够同时表示：

```text
policy_action
engine_result
final_action
block_reason
execution_status
```

典型状态：

```text
policy_action = BUY
engine_result = ALLOWED
final_action = BUY
execution_status = READY
```

或：

```text
policy_action = BUY
engine_result = BLOCKED
final_action = NO_TRADE
block_reason = TRADABILITY_BLOCKED
```

或：

```text
policy_action = BUY
engine_result = NOT_EXECUTABLE
final_action = BUY_RECOMMENDATION
execution_status = USER_INPUT_REQUIRED
```

---

# 8. Recommendation ≠ Order ≠ Fill

永久边界：

```text
Recommendation
      ≠
Order
      ≠
Fill
```

Policy 可以先产生：

```text
BUY
target_weight = 10%
```

之后才决定是否能够形成：

```text
account_execution_amount
account_execution_quantity
```

因此：

> **无法计算实际股数，不代表无法产生投资建议。**

---

# 9. Terminology Dictionary Contract v1.0

## 9.1 `policy_target_weight`

Investment Decision Policy 给出的理论目标权重。

---

## 9.2 `target_weight`

正式 Recommendation 中的目标组合权重。

其语义固定：

```text
weight_basis = TOTAL_ASSET
```

例如：

```text
target_weight = 0.10
```

表示：

> 该标的目标占组合总资产 10%。

不得解释成：

* 剩余现金 10%；
* 当前持仓 10%；
* 股票市值 10%。

---

## 9.3 `maximum_allowed_position`

该标的允许达到的最大组合权重。

它是 Hard Constraint。

必须满足：

```text
policy_target_weight
<=
maximum_allowed_position
```

---

## 9.4 `account_execution_amount`

本次账户实际应投入的货币金额。

---

## 9.5 `account_execution_quantity`

根据账户状态、价格、费用和交易规则计算出的实际股数。

---

## 9.6 `UNKNOWN`

UNKNOWN = 当前没有足够可信的数据得出该值。

禁止将 UNKNOWN 静默转换为：

```text
0
False
Default
Negative
```

---

# 10. Position Sizing Contract v1

Position Sizing 固定分为三个层级：

```text
Policy Sizing
      ↓
Account Sizing
      ↓
Execution Sizing
```

---

## 10.1 Policy Sizing

输入至少包括：

```text
market_regime
risk_mode
conviction
volatility
existing_position
sector_exposure
portfolio_constraints
correlation
tradability
```

输出至少包括：

```text
policy_target_weight
confidence
as_of
sizing_policy_version
input_completeness
assumptions
```

---

## 10.2 Policy Weight Basis

Policy Target Weight 永远基于：

```text
TOTAL_ASSET
```

如果 Total Asset UNKNOWN：

> 不得切换成当前持仓市值等其它基准。

---

## 10.3 Missing Portfolio Data

当：

```text
existing_position
sector_exposure
correlation
```

等数据 UNKNOWN 时：

允许：

* UNKNOWN 显式参与；
* confidence 降低；
* input_completeness = PARTIAL；
* 使用当前 Sizing Policy Version 规定的降级逻辑。

禁止：

* UNKNOWN → 0；
* 假设无仓位而不声明；
* 静默忽略；
* 改变 Target Weight 基准。

若使用假设：

```text
assumption = explicit
```

必须记录。

---

# 11. Account Sizing Contract

Account Sizing 将：

```text
policy_target_weight
```

转换为：

```text
account_execution_amount
```

至少依赖：

```text
total_asset
cash
existing_position
current_price
fees
constraints
```

如果关键账户信息 UNKNOWN：

```text
account_execution_amount = UNKNOWN
account_execution_quantity = UNKNOWN
```

但：

```text
policy_action
```

仍然可以存在。

---

# 12. Execution Sizing Contract

Execution Sizing 决定：

```text
order_quantity
order_price
order_value
```

必须考虑：

* 可用资金；
* 可卖数量；
* 100 股整数倍；
* 交易费用；
* 滑点；
* 涨跌停；
* 停牌；
* 账户交易权限。

---

# 13. Market Regime → Policy Contract

Market Environment 向 Investment Decision Policy 提供统一接口：

```text
regime
risk_mode
candidate_policy
entry_policy
sizing_policy
portfolio_policy
```

Baseline 不冻结具体：

* 阈值；
* 分数；
* 仓位比例；
* 风险系数；
* 过滤参数。

具体值属于：

```text
Versioned Policy Parameters
```

---

# 14. Evidence Fusion Contract

所有正式 Evidence 必须具备：

```text
source
symbol
feature / claim
value
available_time
as_of
quality
availability
provenance
version
```

Evidence Availability：

```text
AVAILABLE
UNAVAILABLE
UNKNOWN
STALE
QUERY_ERROR
```

禁止：

```text
QUERY_ERROR → UNKNOWN
UNKNOWN → 0
UNKNOWN → NEGATIVE
```

除非具体 Policy 明确声明转换规则，并保留转换记录。

---

# 15. PIT / Time Consistency Contract

所有正式 Production Decision 使用：

```text
decision_time
```

所有进入决策的 Evidence 必须满足：

```text
available_time <= decision_time
```

不得使用：

* 未来数据；
* 后验数据；
* 决策后才出现的财务数据；
* 事后更新的市场状态；
* 混合不同 as-of 的伪实时状态。

---

# 16. Decision Cycle Contract

V1.2.1 默认：

```text
decision_frequency = DAILY
decision_domain = DAILY_CLOSE
```

即：

> **系统是日线投资决策系统。**

对于交易日 T：

```text
decision_time(T)
=
T 日 Canonical Decision Cutoff
```

具体 cutoff 属于：

```text
Decision Cycle Policy Version
```

Baseline 不冻结具体：

```text
15:05
16:00
```

未来如果增加盘中决策：

> 必须建立新的 Intraday Decision Cycle Contract，不得污染 Daily Contract。

---

# 17. A-Share Tradability Contract

必须至少检查：

```text
trading_status
suspension_status
limit_up_status
limit_down_status
ST_status
listing_status
account_permission
lot_size
liquidity
price_availability
```

输出：

```text
TRADABLE
NOT_TRADABLE
UNKNOWN
STALE
```

---

# 18. Hard Constraint Registry v1

所有可能触发 BLOCKED 的 Hard Constraint 必须集中注册。

统一字段：

```text
constraint_id
name
domain
trigger
stage
action_scope
priority
block_reason
fail_safe
```

---

## 18.1 `domain`

必须显式声明：

```text
SIMULATION
REAL
BOTH
```

不得省略。

---

## 18.2 示例

```text
C001 PORTFOLIO_TRUTH_INCOMPLETE

domain:
REAL

stage:
ACCOUNT_SIZING

action_scope:
REAL_EXECUTION

trigger:
账户状态不足以计算 account-level execution size

block_reason:
PORTFOLIO_TRUTH_INCOMPLETE
```

该 Constraint：

> 不得否决 Policy BUY 本身。

它表示：

```text
Recommendation available
Execution not ready
```

---

另一个：

```text
C002 SUSPENDED

domain:
BOTH

stage:
TRADABILITY

action_scope:
BUY, SELL

block_reason:
TRADABILITY_BLOCKED
```

---

# 19. Constraint Priority

Priority 只解决：

> 多个 Hard Constraint 同时触发时，系统应该采用哪个主 Block Reason。

Priority 不得改变 Constraint 的业务语义。

最终记录：

```text
all_triggered_constraints
primary_block_reason
```

不能因为只显示一个 Block Reason 而丢掉其他触发原因。

---

# 20. Recommendation Object Contract

正式 Recommendation 至少包含：

```text
decision_id
decision_time

symbol

policy_action
policy_target_weight

maximum_allowed_position

engine_result
final_action
block_reason

entry_policy
exit_policy

confidence

evidence_refs

portfolio_as_of

policy_version
decision_trace

account_execution_amount
account_execution_quantity
execution_status
```

---

# 21. Entry Timing Contract

Entry Timing 独立于 Stock Discovery。

支持：

```text
BUY_NOW
WAIT
WAIT_CONFIRMATION
BUY_ON_CONDITION
NO_ENTRY
```

必须至少包含：

```text
entry_condition
expected_trigger
valid_until
timing_policy_version
```

---

# 22. Exit Policy Contract

Exit 必须支持：

```text
HOLD
REDUCE
EXIT
```

Exit Policy 可以依据：

```text
thesis_break
market_regime_change
relative_strength
technical_deterioration
valuation
risk_deterioration
portfolio_constraint
time_based_exit
```

具体规则必须版本化。

---

# 23. Simulation Execution Model v1

V1 使用唯一 Canonical Daily Execution Model：

```text
Signal at T
    ↓
Order generated at T
    ↓
Next valid trading session T+1
    ↓
Execution at T+1 Open
```

该模型必须：

* deterministic；
* reproducible；
* auditable；
* free of look-ahead bias。

---

## 23.1 T+1

```text
Buy(T)
→
Sellable(T+1)
```

Simulation Portfolio 必须区分：

```text
quantity
available_quantity
frozen_quantity
```

---

## 23.2 Lot Size

股票买入：

```text
floor(quantity / 100) * 100
```

不足 100 股：

```text
NO_FILL
```

---

## 23.3 Suspension

停牌：

```text
REJECTED_SUSPENDED
```

---

## 23.4 Limit Up / Limit Down

V1 使用 Simulation Approximation：

```text
limit_up_locked
→ BUY rejected

limit_down_locked
→ SELL rejected
```

该规则属于：

```text
Simulation Model
```

而不是对真实交易撮合机制的完整复制。

---

## 23.5 Transaction Cost

必须单独版本化：

```text
commission_model_version
tax_model_version
slippage_model_version
```

---

## 23.6 Partial Fill

V1：

```text
ALL_OR_NONE
```

不模拟 Partial Fill。

---

# 24. Simulation Portfolio Contract

Simulation Portfolio 必须维护：

```text
cash
positions
available_quantity
frozen_quantity
average_cost
market_value
equity
realized_pnl
unrealized_pnl
```

Simulation Portfolio 的所有变化只能来自：

```text
Simulated Execution
```

不得由 Recommendation 直接修改持仓。

---

# 25. Real Manual Execution Contract

Real 默认：

```text
AUTO_TRADING = OFF
```

系统职责：

> **生成建议。**

用户职责：

> **决定是否执行并使用真实账户执行。**

标准 Execution Record：

```text
decision_id
symbol
side
quantity
price
execution_time
fees
execution_status
source
```

source：

```text
USER_CONFIRMATION
MANUAL_INPUT
IMPORTED_RECORD
```

---

# 26. Real Portfolio Truth Contract

Canonical Real Portfolio Source 必须唯一。

至少支持：

```text
symbol
quantity
cost
current_price
sector
source_timestamp
cash
total_asset
```

状态至少包括：

```text
AVAILABLE
UNKNOWN
STALE
```

---

# 27. Simulation 与 Real Portfolio 永久分离

禁止：

```text
Simulation Fill
→
Real Portfolio
```

也禁止：

```text
Real Fill
→
Simulation Portfolio
```

除非存在明确、版本化的数据转换 Contract。

---

# 28. Economic Evaluation Contract

所有 Simulation 与 Real Outcome 都必须从三个方向评价。

## 28.1 Absolute Performance

回答：

> 资本有没有增长？

包括：

```text
Net P&L
Cumulative Return
CAGR
Capital Growth
```

---

## 28.2 Relative Performance

回答：

> 有没有创造相对于 Benchmark 的额外价值？

包括：

```text
Excess Return
Benchmark Relative Return
Alpha
```

---

## 28.3 Risk

包括：

```text
Maximum Drawdown
Drawdown Duration
Volatility
Tail Risk
```

---

## 28.4 Efficiency

包括：

```text
Turnover
Transaction Cost
Capital Utilization
Exposure
```

---

# 29. Quality Measurement Contract v1

Quality Contract 冻结：

> **如何测。**

不把当前经验值永久写成真理。

固定维度：

```text
Market Judgment
Stock Discovery
Entry Timing
Position Sizing
Exit
Portfolio Construction
Decision Quality
Execution Quality
Economic Outcome
```

每项必须定义：

```text
metric
sample_definition
measurement_window
benchmark
data_source
as_of_rule
aggregation_method
```

Threshold 由：

```text
Qualification Policy
```

管理。

---

# 30. Research Promotion Contract

任何 Research 不得直接进入 Production。

唯一允许的 Promotion Lifecycle：

```text
Research
    ↓
Candidate
    ↓
Offline Validation
    ↓
Out-of-Sample Validation
    ↓
Simulation Validation
    ↓
Promotion Candidate
    ↓
Versioned Production Policy
    ↓
Monitoring
    ↓
Rollback / Retire
```

---

## 30.1 Research Categories

至少区分：

```text
REGIME_POLICY
ENTRY_SIGNAL
POSITION_POLICY
EXIT_POLICY
PORTFOLIO_POLICY
```

不同类别可以采用不同的：

* Sample Requirement；
* Evaluation Metrics；
* Validation Horizon；
* Robustness Requirement。

不得用单一指标和单一时间长度评价全部 Research。

---

# 31. Policy Versioning Contract

任何进入 Production 的 Policy 必须具有：

```text
policy_version
source_research
evidence_version
promotion_record
effective_time
rollback_target
```

任何逻辑变化必须进入新版本。

---

# 32. Code / Git Baseline Contract

Git 是 Production Code 的唯一版本真源。

正式 Production Code：

> **必须存在于 Git Repository 中。**

不能依赖：

* 文件修改时间；
* 手工备份目录；
* snapshot；
* 临时复制；
* working directory 状态。

---

## 32.1 Production Code Baseline

正式 Production Baseline 必须记录：

```text
repository
branch
commit_sha
tag
working_tree_status
```

例如：

```text
code_baseline:
  repository: hermes-stock
  branch: main
  commit: <SHA>
  tag: hermes-stock-baseline-v1.2.1
  working_tree: CLEAN
```

---

## 32.2 Baseline Git Tag

正式 Baseline 必须有不可歧义的 Git Tag：

```text
hermes-stock-baseline-v1.2.1
```

该 Tag 对应：

```text
Baseline
Contracts
Production Code
Tests
Configuration Definitions
```

---

## 32.3 Dirty Tree Rule

```text
working_tree = DIRTY
```

允许：

* Development；
* Research；
* Local Experiment。

禁止：

```text
Production Promotion
```

---

## 32.4 Git / Policy Binding

任何 Production Policy 必须绑定：

```text
policy_version
code_commit
```

任何 Simulation Run 必须至少绑定：

```text
run_id
code_commit
policy_version
dataset_version
execution_model_version
config_version
```

---

# 33. Reproducibility Manifest

每个重要 Simulation、Promotion 和 Production Decision 都应该能够形成 Manifest：

```text
code_commit
policy_version
dataset_version
schema_version
execution_model_version
decision_cycle_version
config_version
decision_time
```

目标：

> **任何重要结果都可以被重新解释、复现和审计。**

---

# 34. Decision Identity Contract

每个 Decision 必须具备稳定身份。

逻辑身份至少关联：

```text
decision_date
decision_time
symbol
policy_version
decision_context
```

系统必须明确：

```text
NEW_DECISION
```

和：

```text
RERUN / REVISION
```

的区别。

同样输入重复运行不能无故产生多个无法解释的正式 Decision。

---

# 35. Decision Trace Contract

每个 Recommendation 必须能够逆向追踪：

```text
Market Context
    ↓
Opportunity
    ↓
Evidence
    ↓
Investment Policy
    ↓
Timing
    ↓
Sizing
    ↓
Constraints
    ↓
DecisionEngine
    ↓
Final Recommendation
```

---

# 36. Real Execution Outcome Contract

没有：

```text
ExecutionRecord
```

就不能声称：

```text
Real Outcome
```

真实闭环：

```text
Recommendation
    ↓
User Execution
    ↓
Execution Record
    ↓
Real Portfolio Update
    ↓
Outcome
```

---

# 37. Simulation Outcome Contract

Simulation：

```text
Decision
    ↓
Simulated Order
    ↓
Simulated Fill
    ↓
Simulation Portfolio
    ↓
Outcome
```

Simulation Outcome 必须引用：

```text
code_commit
policy_version
dataset_version
execution_model_version
```

---

# 38. Decision Attribution Contract

Outcome 必须尽量区分：

```text
Market Contribution
Opportunity Contribution
Evidence Contribution
Timing Contribution
Sizing Contribution
Portfolio Contribution
Execution Contribution
```

目标：

> 不只是知道赚没赚钱，而是知道哪一层创造了价值、哪一层破坏了价值。

---

# 39. Learning Contract

Learning 不得直接修改 Production Policy。

唯一允许路径：

```text
Outcome
    ↓
Evaluation
    ↓
Attribution
    ↓
Research
    ↓
Candidate Policy
    ↓
Validation
    ↓
Promotion
    ↓
New Policy Version
```

禁止：

```text
Loss Today
→
Automatic Rule Change Tomorrow
```

---

# 40. Cron Contract

Cron 是 Agent 生命周期执行器。

每个 Cron 必须明确：

```text
purpose
input
output
consumer
frequency
dependency
failure_behavior
domain
production_or_research
```

每个 Production Cron 必须能回答：

> **它在 Investment Decision Lifecycle 中的什么位置？**

不能无限堆叠只产生局部结果却没有消费者的 Cron。

---

# 41. Production / Research Boundary

Research 与 Production 永久分离。

允许：

```text
Research
→
Candidate
→
Validation
→
Promotion
→
Production
```

禁止：

```text
Research Script
→
Production Import
```

禁止 Production 直接依赖：

* Notebook；
* 临时脚本；
* 一次性实验；
* 未版本化实验逻辑；
* Research-only DB。

---

# 42. Configuration Contract

生产配置不得散落在：

* 脚本常量；
* 临时环境变量；
* Notebook；
* 未记录的 Local Override。

重要生产参数必须具有：

```text
config_version
parameter_name
value
effective_time
owner
reason
```

Policy 参数不得直接埋入代码。

---

# 43. Failure / Fail-Safe Contract

系统必须区分：

```text
DATA_MISSING
DATA_STALE
QUERY_ERROR
POLICY_UNAVAILABLE
TRADABILITY_UNKNOWN
PORTFOLIO_UNKNOWN
EXECUTION_NOT_READY
```

不能统一吞掉成：

```text
NO_TRADE
```

也不能统一吞掉成：

```text
UNKNOWN
```

Fail-safe 由各 Contract 明确定义。

---

# 44. Source of Truth Hierarchy

每一种核心状态必须存在唯一 Canonical Source。

至少包括：

```text
Market Data Source
Evidence Source
Portfolio Truth Source
Simulation Portfolio
Policy Version Source
Code Git Source
Execution Record Source
Outcome Source
```

允许：

> 多个 Provider。

不允许：

> 多个未经定义优先级的 Canonical Truth。

---

# 45. Data Contract

生产数据必须至少具有：

```text
source
timestamp
as_of
schema_version
quality_status
```

数据刷新不能只看：

```text
file exists
```

必须知道：

> 它是什么数据、来自哪里、截至何时、是否能进入当前 Decision。

---

# 46. Product Output Contract

每日最终产品输出必须围绕六个核心问题：

## Market

```text
regime
risk_mode
```

## Buy What

```text
symbol
policy_action
reason
confidence
```

## When

```text
entry_policy
entry_condition
```

## How Much

```text
policy_target_weight
```

以及：

```text
account_execution_amount
account_execution_quantity
```

无法计算时：

```text
UNKNOWN
USER_INPUT_REQUIRED
```

---

## Existing Position

```text
HOLD
REDUCE
EXIT
```

---

## Why

必须能追溯：

```text
Evidence
→
Policy
→
Constraint
→
Final Decision
```

---

# 47. Core Acceptance Test

只有下面链路完整，系统才算实现 Investment Decision Agent 核心能力：

```text
真实市场数据
    ↓
Market Environment
    ↓
Risk Mode
    ↓
Opportunity Universe
    ↓
Evidence Fusion
    ↓
Investment Decision Policy
    ↓
Entry Timing
    ↓
Policy Target Weight
    ↓
Portfolio / Risk / Tradability
    ↓
DecisionEngine
    ↓
Final Recommendation
    ↓
Simulation Execution
OR
Human Real Execution
    ↓
Outcome
    ↓
Economic Evaluation
    ↓
Attribution
    ↓
Research / Learning
    ↓
Versioned Policy
```

---

# 48. Perfect-State Matrix

| Area                 | 完成标准                                |
| -------------------- | ----------------------------------- |
| Economic Objective   | 长期真实资本净财富增长                         |
| Market               | 可形成 Market Regime                   |
| Risk                 | 可形成 Risk Mode                       |
| Opportunity          | 可进入 Investment Policy               |
| Evidence             | 有 provenance / as_of / availability |
| PIT                  | `available_time <= decision_time`   |
| Entry                | 独立 Entry Contract                   |
| Sizing               | Policy / Account / Execution 三层分离   |
| Tradability          | 覆盖 A 股交易关键条件                        |
| Constraints          | Registry + domain                   |
| Policy               | 有明确版本                               |
| DecisionEngine       | 唯一 Hard Constraint 仲裁器              |
| Recommendation       | 可完整追溯                               |
| Simulation           | 自动执行                                |
| Simulation Execution | 确定性、可重放                             |
| Simulation Portfolio | 与 Simulation Fill 一致                |
| Real                 | 人工执行                                |
| Execution Feedback   | Execution Record                    |
| Real Portfolio       | Canonical Truth                     |
| Outcome              | Decision→Execution→Outcome          |
| Attribution          | 可分析经济贡献                             |
| Learning             | 不绕过 Promotion                       |
| Research             | 与 Production 隔离                     |
| Quality              | 有统一测量方法                             |
| Promotion            | 有版本化流程                              |
| Code                 | Git 唯一版本真源                          |
| Baseline             | 有 Git Commit + Tag                  |
| Reproducibility      | 有 Manifest                          |
| Rollback             | Code + Policy 成对回滚                  |
| Config               | Versioned                           |
| Cron                 | 有生命周期职责                             |
| Failure              | 有显式 Fail-Safe                       |
| Product Output       | 回答买什么/什么时候/买多少/什么时候卖                |

---

# 49. Production Promotion Record

任何 Production Policy Promotion 必须形成一条完整记录：

```text
promotion_id

research_id

policy_version

code_commit

dataset_version

schema_version

execution_model_version

decision_cycle_version

validation_result

simulation_result

quality_result

promotion_decision

effective_time

rollback_target

owner
```

缺少关键版本绑定：

> 不得成为正式 Production Policy。

---

# 50. Rollback Contract

Rollback 必须成套进行：

```text
Policy
+
Code
+
Relevant Contract Versions
+
Execution Model
+
Configuration
```

至少能够恢复：

```text
policy_version
code_commit
config_version
execution_model_version
```

不能只把 Policy 名字改回来，却留下不同代码。

---

# 51. Monitoring Contract

Production Policy 进入生产后，不等于永久有效。

必须持续观察：

```text
Economic Outcome
Decision Quality
Execution Quality
Data Quality
Policy Stability
```

Monitoring 发现异常后：

```text
Monitor
→
Investigate
→
Research
→
Promotion
```

必要时：

```text
Rollback
```

不能直接在 Production 上“现场调参”。

---

# 52. Baseline Change Control

Baseline 冻结以下内容：

```text
Product Objective
Responsibility Boundary
Decision Semantics
Operating Domains
PIT Rules
Execution Separation
Safety Boundary
Versioning Principles
Audit Requirements
```

以下内容不是 Baseline 永久真理：

```text
Alpha Parameters
Entry Parameters
Sizing Parameters
Exit Parameters
Portfolio Parameters
Thresholds
Transaction Cost Values
Specific Strategies
Research Hypotheses
```

这些属于：

```text
Versioned Policy Parameters
```

---

# 53. Baseline Change Procedure

只有以下情况允许修改 Baseline：

```text
1. Product Objective changed
2. Operating Domain changed
3. Responsibility Boundary changed
4. Fundamental Decision Semantics changed
5. Simulation / Real boundary changed
6. Versioning / Audit principle changed
7. Daily → Intraday or similar major paradigm change
8. Real Broker Auto-Execution becomes a formal product domain
```

普通：

* Bug Fix；
* Provider Change；
* Strategy Change；
* Threshold Change；
* New Research；
* New Evidence Source；
* New Policy；

不得修改 Baseline。

---

# 54. Permanent Boundaries

以下规则永久有效：

### Boundary 1

Simulation 与 Real 永久分离。

### Boundary 2

Investment Decision Policy 与 DecisionEngine 永久分离。

### Boundary 3

Recommendation 与 Order / Fill 永久分离。

### Boundary 4

Policy Target Weight 与 Account Execution Quantity 永久分离。

### Boundary 5

UNKNOWN 不得隐式转换。

### Boundary 6

Real Portfolio Truth 不完整，不等于 Policy Recommendation 不可产生。

### Boundary 7

Research 不得直接绕过 Promotion 进入 Production。

### Boundary 8

Production 不得依赖未版本化 Research Logic。

### Boundary 9

Production Evidence 必须满足：

```text
available_time <= decision_time
```

### Boundary 10

真实成交必须具有 Execution Record 才能进入 Real Outcome。

### Boundary 11

Simulation 必须使用 Versioned Execution Model。

### Boundary 12

Production Policy 必须绑定 Code Commit。

### Boundary 13

Production Code 必须由 Git 唯一确定。

### Boundary 14

Production Promotion 禁止 Dirty Working Tree。

### Boundary 15

Policy Rollback 与 Code Rollback 必须保持兼容。

### Boundary 16

所有系统优化最终必须服务于 Economic Objective。

---

# 55. Final Product Definition

Hermes Stock Agent 的最终职责可以压缩成一句话：

> **在当前 A 股市场环境下，使用当时真正可获得的数据，通过统一、可审计、可验证、版本化的 Investment Decision Policy，决定资本应该投资什么、什么时候投资、配置多少、什么时候减仓或退出，并通过自动 Simulation 与真实人工执行反馈持续验证这些决策是否真正改善长期资本净财富增长。**

系统最终不是：

```text
Score Engine
```

不是：

```text
Stock Screener
```

不是：

```text
Backtest Framework
```

不是：

```text
Risk Engine
```

不是：

```text
News Agent
```

而是：

```text
Investment Decision Agent
```

---

# 56. Final System Chain

整个系统最终冻结为：

```text
ECONOMIC OBJECTIVE
长期真实资本增值
        ↓
MARKET
        ↓
REGIME
        ↓
OPPORTUNITY
        ↓
EVIDENCE
        ↓
INVESTMENT DECISION POLICY
        ↓
ENTRY TIMING
        ↓
POLICY TARGET WEIGHT
        ↓
PORTFOLIO / RISK / TRADABILITY
        ↓
DECISION ENGINE
        ↓
FINAL RECOMMENDATION
        ↓
┌───────────────────────┐
│                       │
│      SIMULATION       │
│                       │
│      ↓                │
│   Auto Execution      │
│      ↓                │
│   Simulation Outcome  │
│                       │
└───────────────────────┘

OR

┌───────────────────────┐
│                       │
│         REAL          │
│                       │
│      ↓                │
│ Human Confirmation    │
│      ↓                │
│ Manual Execution      │
│      ↓                │
│ Execution Record      │
│                       │
└───────────────────────┘

        ↓
ECONOMIC OUTCOME
        ↓
ATTRIBUTION
        ↓
RESEARCH
        ↓
VALIDATION
        ↓
PROMOTION
        ↓
VERSIONED POLICY
        ↓
PRODUCTION
```

同时：

```text
Git Code Version
+
Policy Version
+
Data Version
+
Execution Model Version
+
Decision Cycle Version
```

共同构成任何正式结果的可追溯运行身份。

---

# 57. Freeze Statement

**Hermes Stock Agent Baseline v1.2.1 自本文件正式冻结后，不再因普通功能开发、研究发现或实现便利而修改。**

后续变化必须分别归类到：

```text
Implementation Change
Contract Change
Policy Change
Parameter Change
Research Result
```

只有真正改变产品范式或核心行为语义时，才允许发起新的 Baseline Version。

---

# 58. Ultimate Acceptance Criterion

最终只有当下面三个条件同时成立，Hermes Stock Agent 才算完成其产品目标：

## A. Decision Capability

它能够稳定回答：

```text
买什么？
什么时候买？
买多少？
什么时候卖？
为什么？
```

## B. Economic Validation

它能够通过 Simulation 和真实 Outcome 判断：

```text
这些决策是否真正创造资本价值？
```

## C. Continuous Improvement

它能够：

```text
Outcome
→ Evaluation
→ Attribution
→ Research
→ Validation
→ Promotion
→ New Policy Version
```

而且全过程：

```text
可追溯
可复现
可审计
可回滚
```

这三项缺一不可。

---

# 59. Final Principle

> **Baseline 不负责证明某个策略能赚钱。**
>
> **Baseline 负责保证：任何被认为“有可能帮助赚钱”的策略，都必须通过统一、严格、可复现的方式进入投资决策、Simulation、Outcome、Evaluation 和 Promotion。**
>
> **最终是否值得生产，不由想法决定，不由模型名字决定，不由分数决定，而由真实经济结果和可重复证据决定。**

因此，Hermes Stock Agent 的最终判断标准不是：

```text
系统有多少模块？
有多少指标？
有多少策略？
有多少回测？
```

而是：

```text
Capital
→
Decision
→
Execution
→
Outcome
→
Learning
→
Better Capital Allocation
```

**这条链能否持续成立。**

---

# 60. Freeze Boundary

**本文件之后，原则上停止 Baseline Architecture Design。**

下一阶段不再讨论：

> “Baseline 还应该设计什么？”

而只做：

> **Current Hermes Stock Assets → Baseline v1.2.1 Gap Audit**

逐项检查：

```text
现有数据
现有 Provider
现有 Cron
现有 Opportunity
现有 Evidence
现有 Market Regime
现有 DecisionEngine
现有 Portfolio
现有 Simulation
现有 Backtest
现有 Outcome
现有 Research
现有 Git / Code 状态
```

分别落到：

```text
Already Satisfies
Partially Satisfies
Research Only
Production
Duplicate
Disconnected
Missing
Unsafe
```

并最终定位：

> **距离“真正能够帮助用户做出更有盈利概率的投资决策”最近、价值最高、且能够直接落地的下一个缺口。**
