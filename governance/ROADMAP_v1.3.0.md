# ROADMAP v1.3.0

## Baseline Transition

* baseline_from: HERMES-STOCK-IDS v1.2.1 FINAL
* baseline_to: HERMES-STOCK-IDS v1.3.0
* freeze_date: 2026-09-10
* status: PLANNED

## v1.2.1 冻结结论

* sections_satisfied: 75/76 (98.7%)
* sole_gap: §2.1 Alpha — 缺少独立 Alpha 信号生成/归因层
* gap_decision: 不进 v1.2.1，列为 v1.3.0 首项

## v1.3.0 规划项

### P0-1: §2.1 Alpha 独立信号层

**现状：** Alpha 隐含在 `double_up_scores` + A/B/D 技术信号中，无独立归因。

**目标：** 显式 Alpha 贡献层，支持：
1. 因子定义：`compute_alpha_score(symbol, factors)` — 多因子打分
2. 信号合成：`alpha_signal = merge(technical, fundamental, sentiment)`
3. 归因输出：`attribution = {'alpha': 0.02, 'timing': 0.01, 'sizing': 0.0}`
4. DecisionEngine 对接：`ctx['alpha_score']` → `Decision.alpha_contribution`

**验收标准：**
- `evidence_framework.py` 增加 `compute_alpha_score()` 函数
- `Decision` dataclass 增加 `alpha_contribution` 字段
- double_monitor.py 输出中显示 Alpha 归因

**依赖：** 无

**预估工作量：** 中等（需设计因子体系 + 回测验证）

---

### P1: 后续优化项（待补充）

* 经济评估数据闭环（等 19 笔交易产生完整 lifecycle）
* 日志结构化 + 轮转自动化
* 回测框架与模拟交易联动

## Change Ledger

| date | section | change | reason |
|------|---------|--------|--------|
| 2026-09-10 | §32.4 | Git/Policy Binding 补丁 | close MISSING item |
| 2026-09-10 | §2.1 | defer to v1.3.0 | FROZEN baseline, new capability |
