# Phase 5 TODO

## 5.1 代码层完成，运行验证待定
- [x] 根因链确认：9-04 00:13 改 DB_PATH → 新 DB → 假成功 → 9-14 全量重建
- [x] 代码修复：`market_cache.py` 空 stocks 兜底 + 飞书告警 + 非零退出
- [x] 验证：py_compile + 空 stocks 场景 + <100 告警场景
- [x] 飞书通道验证：真实发送成功（code=0, msg=success）
- [ ] 运行验证：待 9-15 16:30 market_cache_refresh 真实运行后确认
- [x] 自动验证脚本：`check_market_cache_health.py`（每天 17:30 自动检查）

## 5.2 待办（非阻塞）

### TODO-5.2-1：deep-position-review 380s 异常
- **job_id**: `e4a2c0461481`
- **时间**: 2026-09-14 16:00~16:06（380s）
- **现象**: 正常日频 prompt 任务应 < 60s，380s 可能意味着 prompt 太长 / 输入数据太大 / 重复跑
- **与 market_cache 关系**: 无关，是独立 LLM 任务
- **跟进人**: [待定]
- **什么时候查**: Phase 6 或独立任务
- **怎么查**: 查 9-14 输入/输出、对比其他日期、看是否 prompt 膨胀
- **记录时间**: 2026-09-14

### TODO-5.2-2：下游补跑决策
- **决策**: 不做
- **理由**: 重跑得到的是"当前数据"，不是"9-04~9-11 当时数据"，对历史复盘无价值
- **涉及脚本**:
  - `stock_opportunity_scan`: 重跑得到"今天推荐"，不是"当时错过什么"
  - `stock_weekly_screener`: 同上
  - 9-04~9-11 历史推荐: 永久丢失，无法恢复
- **如果将来要做**: 明确"重跑得到什么"，不能盲目补跑
- **记录时间**: 2026-09-14

## 5.3 系统性 TODO

### TODO-5.3-1：所有改过 DB_PATH 的脚本做检查
- **背景**: Phase 4 遇到 recommendation_pool.db 分裂；Phase 5 遇到 market_cache.db 分裂
- **问题**: "路径分裂"不是 market_cache 独有，是系统性问题
- **行动**: grep 所有脚本的 DB_PATH / get_db_path，确认改过路径的都有迁移/兼容策略
- **涉及脚本**:
  - `market_cache.py`: 已修复（加兜底 + 告警）
  - `stock_opportunity_scan.py`: 用 `MARKET_DB`，需确认路径一致性
  - `pre_market_brief.py`: 不读 DB，无需检查
  - 其他脚本: 待盘点
- **记录时间**: 2026-09-14

### TODO-5.3-2：market_cache_refresh 监控
- **监控**: 每天 stocks 列表长度（已有日志：`[INFO] incremental_update 待更新 stocks=N`）
- **告警阈值**:
  - stocks = 0 → 飞书 P1（已实现）
  - stocks < 100 → 飞书 P1（已实现）
- **观察 1-2 周后调阈值**: 根据实际运行数据调整
- **记录时间**: 2026-09-14

## 5.4 9-15 自动验证
- **脚本**: `scripts/cron/check_market_cache_health.py`（157 行）
- **调度**: 每天 17:30（cron job: check-market-cache-health）
- **检查项**:
  - 今天 klines 数量 > 5000
  - 今天 stocks 列表长度（从日志）
  - duration > 100 秒
- **不满足**: 飞书告警
- **记录时间**: 2026-09-15

## 5.5 后续建议
- 监控 `market_cache_refresh` 的 `stocks` 列表长度，若再出现 0 或 <100，飞书告警已就位
- 改 DB_PATH 时建议同步迁移旧 DB 数据，避免再出现"空 DB 假成功"
- 9-15 17:30 `check_market_cache_health.py` 将自动验证修复是否生效

## 5.6 历史遗留脚本 Path('MARKET_DB') 清理 TODO

### TODO-5.6-1：10 个历史遗留脚本的字面量 DB 路径
- **背景**: lint H3 发现 10 个脚本使用 `Path('MARKET_DB')` 字面量
- **涉及脚本**: audit_pit_quality.py, historical_features.py, historical_market_state.py, historical_replay_engine.py, historical_share_layer.py, pilot_sample.py, pilot_v2_sample.py, run_pilot_v2.py, run_pilot_v3.py, run_replay_pilot.py
- **引用情况**:
  - `historical_replay_engine`: 被 run_pilot_v2/run_pilot_v3/run_replay_pilot import
  - `historical_share_layer`: 被 audit_pit_quality/run_pilot_v2/run_replay_pilot import
  - 其他: 无引用
- **cron 调度**: 无（10 个文件均未被 cron jobs.json 调度）
- **风险**: 字面量 `Path('MARKET_DB')` 在运行时会被 sqlite3 解析为相对路径，可能指向错误 DB
- **优先级**: P2（历史遗留，无 cron 调度，但被部分脚本 import）
- **行动**: 待 Phase 6 或独立任务批量替换为 `core.compat_paths.MARKET_DB`
- **记录时间**: 2026-09-15
