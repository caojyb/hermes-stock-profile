# Cron DAG 文档

## 概述

股票系统 Cron 任务调度图。当前共 **24 个 job**，按触发时机分为日间链和周链。

## 日间链（交易日）

| 时间 | Job | 脚本 | 职责 | 飞书推送 | 状态 |
|------|-----|------|------|----------|------|
| 09:30 | `double-monitor-daily` | `double_monitor.py` | 持仓监控 + 风控 + 信号执行 | ✅ | 活跃 |
| 09:30 | `check-drawdown-weekly` | `check_drawdown_weekly.py` | 周回撤检查 (<15% 发飞书) | ✅ | 新增 |
| 10:00 | `stock-intraday-minute` | `stock_intraday_minute.py` | 分钟级 K 线缓存 | ❌ | 活跃 |
| 10:30 | `stock-opportunity-push` | `stock_opportunity_scan.py` | 翻倍潜力扫描 + 推送到候选人 | ❌ | 活跃 |
| 11:30 | `stock-recommendation-pool-weekly` | `weekly_pool_report.sh` | 推荐池周报 | ✅ | 活跃 |
| 15:30 | `daily-data-refresh` | `daily_data_refresh.py` | 盘后数据刷新 (K线/财务/龙虎榜) | ❌ | 活跃 |
| 15:35 | `stock-lhb-daily` | `lhb_monitor.py` | 龙虎榜数据 + 候选池关联 | ✅ | 加飞书 |
| 15:40 | `stock-news-sentiment-pilot` | `news_sentiment.py` | AI 新闻解读 | ✅ | 活跃 |
| 15:40 | `daily-sentiment-report` | `sentiment_thermo.sh` | 情绪温度计 | ✅ | 活跃 |
| 15:40 | `hot-sector-scanner` | `hot_sector_scanner.py` | 热点板块扫描 | ✅ | 加飞书 |
| 15:45 | `position-stop-loss-alert` | `position_stop_loss_alert.py` | 持仓止损告警 | ✅ | 活跃 |
| 17:00 | `market-env-report` | `market_env_report.sh` | 市场环境报告 | ✅ | 活跃 |

## 周链（周日）

| 时间 | Job | 脚本 | 职责 | 飞书推送 | 状态 |
|------|-----|------|------|----------|------|
| 16:00 | `weekly-fundamental-refresh` | `weekly_fundamental_refresh.sh` | PE/PB + 财务数据刷新 (合并 2→1) | ✅ | 合并完成 |
| 16:00 | `stock-weekly-screener` | `stock_screener_wrapper.sh` | 翻倍潜力周选 | ✅ | 活跃 |
| 16:30 | `stock-weekly-pipeline` | `weekly_pipeline.py` | 全流程引擎 | ✅ | 活跃 |
| 17:00 | `us-stock-weekly-update` | `us_stock_weekly_update.py` | 美股持仓更新 | ❌ | 活跃 |

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
