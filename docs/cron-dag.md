# Cron DAG 文档

## 概述

股票系统 Cron 任务调度图。当前共 **25 个 job**（25 enabled / 0 paused），按触发时机分为日间链和周链。

## 日间链（交易日）

| 时间 | Job | 脚本 | 职责 | 飞书推送 | 状态 |
|------|-----|------|------|----------|------|
| 08:05 | `cron-health-sentinel` | `cron_health_sentinel.py` | cron 健康哨兵（WARN 静默失败/停机缺口/failed）+ crash 日志轮转 | 异常时✅ | 2026-09-18 新增 |
| 07:50 | `overnight-risk-scan` | `overnight_risk_scan.py` | 持仓+关注池隔夜风险扫描（业绩预告/利空新闻/停牌，命中才推） | 命中✅ | 2026-09-18 新增（五轮审计①） |
| 08:25 | `mirror-drift-check` | `mirror_drift_check.sh` | 生产↔git 镜像漂移检测 | 漂移时✅ | 2026-09-18 新增 |
| 08:30 | `lint-db-paths` | `lint_no_hardcoded_db.sh` | 硬编码 DB 路径检查 | 失败时✅ | 活跃 |
| 09:35 | `position-stop-loss-alert` | `position_stop_loss_alert.py` | 真实持仓统一决策（止损/仓位建议，质量守卫硬失败） | 非HOLD✅ | 活跃 |
| 10:00 | `hot-sector-scanner` | `hot_sector_scanner.py` | 热点板块扫描 | ✅ | 活跃 |
| */30 9-11,13-15 | `stock-opportunity-push` | `stock_opportunity_scan.py` | 翻倍潜力扫描（当日已推折叠为"持续关注"行, 2026-09-19 B1 去重） | ✅ | 活跃 |
| */15 9-14 | `stock-intraday-minute` | `intraday_monitor.py` | 盘中监控（脚本内交易时段守卫，午休/盘后跳过） | 信号✅ | 活跃 |
| 11:30(六) | `stock-recommendation-pool-weekly` | `weekly_pool_report.sh` | 推荐池周报 | ✅ | 活跃 |
| 15:35 | `closing-snapshot` | `closing_snapshot.sh` | 收盘快照（情绪+龙虎榜+舆情三合一，FEISHU_DISABLE 全局禁推子脚本） | ✅ | 2026-09-19 合并 sentiment/lhb/news |
| 16:30 | `stock-market-cache-refresh` | `db_lock_refresh.run.sh` → `market_cache_refresh.sh` | 全市场K线增量刷新（**全局写锁持有者**） | 失败✅ | 2026-09-22 接入 db 写锁（P0 撞锁修复） |
| 16:40 | `daily-data-refresh` | `db_lock_daily.run.sh` → `daily_data_refresh.py` | 盘后数据刷新 (K线/财务/龙虎榜/主力资金) | ❌ | 2026-09-22 接入 db 写锁 |
| 16:50 | `double-monitor-daily` | `db_lock_monitor.run.sh` → `double_monitor.py` | 翻倍策略信号扫描+模拟交易 | ✅ | 2026-09-22 接入 db 写锁 |
| 17:10 | `deep-position-review` | (agent) | 持仓深度综合诊断 | ✅ | 2026-09-18 从16:50挪出避让 |
| 17:30 | `track-outcomes-daily` | `track_outcomes.py` | 推荐结果 outcome 回写 | 异常✅ | 2026-09-18 限交易日 |
| 17:50 | `check-market-cache-health` | `check_market_cache_health.py` | 健康检查 3 项（最近一次刷新语义：市场基数/stocks 表、duration 状态联动）+ 关键表新鲜度 4 项 | 异常✅ | 2026-09-19 模拟周一干跑后再修 2 语义 bug |
| ~~17:55~~ | ~~`table-freshness-check`~~ | — | 已并入 17:50 check-market-cache-health（Census 合并#1，2026-09-19） | — | paused |
| 17:35 | `verification-scorecard` | `verification_scorecard.py` | 验证期记分牌（Day/样本/tripwire/到期判定草案） | 每日✅ | 2026-09-18 新增（七轮） |

## 周链（周日）

| 时间 | Job | 脚本 | 职责 | 飞书推送 | 状态 |
|------|-----|------|------|----------|------|
| 03:00(日) | `db-backup-weekly` | `db_backup.sh` | market_cache.db + simulation.db 周备份（自校验 klines/表集，失败 exit 1 + 飞书告警） | 失败✅ | 2026-09-22 新增（审计整改 B2：原 BACKUP_ROOT 指向不存在的 /mnt 且从未注册 cron） |
| 16:00 | `sunday-mega` | `sunday_mega.sh` | 周日数据日：基本面→周选(含环境段)→全流程→解禁 | ✅ | 2026-09-19 合并 4→1 |


| 10:30(六) | `saturday-mega` | `saturday_mega.sh` | 周六组合日：美股持仓→推荐池周报 | ✅ | 2026-09-19 合并 2→1 |

## 纯 Prompt 任务（Hermes Agent）

| Job | 模型 | 职责 | Token 成本 | 状态 |
|-----|------|------|------------|------|
| `deep-position-review` | step-3.7-flash | 深度持仓分析 | 955k/次 (极高) | TODO 降本 |
| `weekly-portfolio-summary` | step-3.7-flash | 周度投资组合总结 | 中等 | 活跃 |
| `stock-weekly-analysis` | step-3.7-flash | 股票周度分析 | 中等 | 活跃 |
| `market-environment-analysis` | step-3.7-flash | 市场环境分析 | 中等 | 活跃 |

## 合并记录

### 合并 1 ✅
- **操作**: `stock-pe-pb-weekly-refresh` + `stock-financial-weekly-refresh` → `weekly-fundamental-refresh`
- **原因**: 同一触发时机 (周日 16:00)、同一数据源 (market_cache.db)、逻辑链相同 (读→刷新)
- **结果**: 22 → 21 job
- **证据**: 
  - wrapper 内容已验证
  - 日志已确认两个刷新都成功
  - jobs.json diff 已记录
  - jq 验证通过

### 合并 2 ❌ 不合并
- **候选**: `daily-sentiment-report` + `stock-news-sentiment-pilot`
- **原因**: 数据源不同 (情绪温度计 vs AI 新闻解读)、分析逻辑不同、输出格式不同、飞书分别推送
- **结论**: 合并后只是"一个 wrapper 跑两个独立脚本"，还是两条飞书，无价值

## 加飞书记录

| Job | 修改 | 验证 |
|-----|------|------|
| `hot-sector-scanner` | 加 `feishu-bitable` 路径 + `feishu_send_message(report)` | ✅ py_compile + 实际运行成功 |
| `stock-lhb-daily` | 加 `feishu_send_message(report)` | ✅ py_compile + 实际运行成功 (code=0, msg=success) |

## TODO 项

| 项目 | 优先级 | 说明 |
|------|--------|------|
| deep-position-review 降本 | P1 | 955k tokens/次，精简 skill 上下文或限制输入 |

## 路径规范

- 执行入口: `scripts/cron/`
- 生产数据: `stock-work/data/production/`
- 运行时数据: `stock-work/data/runtime/`
- 输出报告: `stock-work/data/outputs/`
- 状态文件: `stock-work/data/state/`

## 维护说明

- 新增 job 需在 `cron/jobs.json` 注册
- 脚本路径统一用 `cron/xxx` 格式
- 发飞书统一用 `feishu_send_message(text)` 单参数签名
- 合并 job 需先评估数据依赖链、触发时机、输出类型

## 治理规则（Census 2026-09-18）
- **手工验证必须留痕**：任何手动触发的验证必须 tee 到 cron/output/manual-verification-<日期>/ 或写入 heartbeat detail——不留档的验证视为未发生（2026-09-18 治理瑕疵整改）。禁止手工验证后不留任何产物。
- **新 job 上线必须声明 consumer**：输出被谁消费（哪个脚本读/进哪条推送/写哪张表）。填不出 consumer 不许上线。
- **本轮 Census 处置**：intraday-minute 改挂 intraday_cache.py（修复分钟数据断供，*/15→每日4次）；check-drawdown-weekly 停用（被 risk-guard+scorecard 覆盖）；recommendation-pool-weekly 实测已自愈（95只/93.3%，审计证据过时）保留；lhb/sentiment/news 暂保留（P2 合并待周一验收后执行）。
- **爆炸半径教训**：33 个独立部署单元=33 个"修 A 破 B"风险点。Census 目标 ~20 已达成：jobs 24 total/24 enabled/0 paused（CHANGE-039 周末收尾）。物理删除 12 个已合并 job（归档 jobs.json.archived-paused-20260919 可恢复）。hot-sector 保留（health_check 板块强度检查是其 consumer）。CHANGE-040/041 已清全部待办：IMA 1.1.10 更新、fetch_financial 分批、B1 推送去重（7条/日→1+1行）、C1 死模型配置删除+C2 fallback 配置、锁清理（32 fire-lock+3 陈锁+πthon 软链）。archive 4.4G 保留（dedup/reset 前快照, 外置冷存待确认设备）。

---

## 2026-09-19 铁律：测试门禁（强制）

**背景**：9/11 清理时决策链 36 个回归测试连同类被关进 `data/quarantine/cleanup_20250911_scripts_cron/`，现役树 0 测试；`phase8b` 测试的 autouse fixture 还会删生产 snapshots。导致前九轮所有修改缺回归保护。

**规则**：
1. **改动以下模块后，必须全套跑绿才算 COMPLETE**（冒烟从一次性变常态）：
   - `scripts/cron/decision/`（决策链：engine/execution/user_authority/validation_integrity_gate/风控守卫）
   - `stock-work/core/`（研究平面，尤其 target_engine / strategy_runner / walk_forward）
   ```bash
   # 一条命令跑全套（venv 已装 pytest）。
   # 2026-09-19: 原命令缺 HERMES_HOME → 原样执行撞
   # RuntimeError: HERMES_HOME or STOCK_WORK_ROOT must be defined;
   # 且 ... 占位符 + tail 会掩盖退出码。现为可原样复制的完整版:
   set -e
   P=~/.hermes/profiles/stock
   cd $P/scripts/cron && \
     HERMES_HOME=$P PYTHONPATH=$P/stock-work:$P/scripts/cron \
     $P/.venv/bin/python3 -m pytest decision/ -q --no-header -p no:cacheprovider
   # ↑ exit 0 才算过; 期望: 534 passed, 17 skipped
   # 测试隔离核对（必须 == 165）:
   ls $P/scripts/cron/decision/snapshots | wc -l
   cd $P/stock-work && \
     HERMES_HOME=$P PYTHONPATH=$P/stock-work \
     $P/.venv/bin/python3 -m pytest core/research -q --no-header -p no:cacheprovider
   # ↑ exit 0 才算过; 期望: 214 passed
   ```
2. **baseline（2026-09-19 green）**：decision/ 534 passed + 17 skipped；core/research 214 passed。
3. **测试隔离纪律**：任何测试不得写生产目录（snapshots/executions/outcomes/reports）。用 monkeypatch 隔离 SNAP_DIR（参考 conftest.isolate_snapshots）；跑完核对 `ls decision/snapshots | wc -l` == 165。
4. **新测试必须放现役树**（scripts/cron/decision/test_*.py 或 core/**/test_*.py）；禁止再关 quarantine。
5. **decision/ 已纳入 sync_mirror**（生产→scripts-cron/decision/ 镜像，排除 snapshots/executions/outcomes/reports/__pycache__/*.db/*.json），`--check` 会抓漂移。
