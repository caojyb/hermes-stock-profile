# Project TODOs

## Phase 6 遗留

### TODO-6-1：shell/core 硬编码扫描（盲点 B）
- **背景**: lint 脚本只扫 `scripts/cron/*.py`，shell 脚本和 `core/` 目录未覆盖
- **涉及**: shell 脚本（`.sh`）、`stock-work/core/*.py`
- **优先级**: P2
- **状态**: ✅ 扫描完成
- **发现活跃硬编码 3 处**:
  - `scripts/cron/db_backup.sh`：硬编码 market_cache.db 路径
  - `scripts/cron/stock_screener_wrapper.sh`：硬编码 market_cache.db 路径
  - `skills/stock/stock-expert/skills/feishu-bitable/portfolio_stress_test.py`：硬编码 MARKET_DB
- **已归档死代码**:
  - `skills/stock/stock-data-source-integration/scripts/validate_daily_refresh.py`（旧路径，无引用）
- **下一步**: 逐步替换为 `core.compat_paths.MARKET_DB`
- **记录时间**: 2026-09-15
- **更新时间**: 2026-09-16

### TODO-6-2：lint-db-paths 首次运行验证
- **背景**: cron job 已配置（工作日 08:30），但尚未执行
- **验证时间**: 2026-09-16 08:30 后
- **验证项**:
  - executions.db 是否记 `failed`（非 `completed`）
  - error 字段是否有内容
  - 飞书是否收到告警
- **记录时间**: 2026-09-15

### TODO-6-3：10 个历史遗留文件其他潜在硬编码
- **背景**: 已清理 `Path('MARKET_DB')`，但其他模式待观察
- **涉及**: audit_pit_quality.py, historical_features.py, historical_market_state.py, historical_replay_engine.py, historical_share_layer.py, pilot_sample.py, pilot_v2_sample.py, run_pilot_v2.py, run_pilot_v3.py, run_replay_pilot.py
- **优先级**: P2
- **记录时间**: 2026-09-15

### TODO-6-4：core/ symlink 评估
- **背景**: `core/compat_paths.py` 是 `stock-work/core/compat_paths.py` 的 symlink
- **现状**: symlink 正常工作，所有 `from core.compat_paths` 实际命中 `stock-work/core/compat_paths.py`
- **问题**: 这是 Phase 6 "路径规范化" 的目标之一——应评估是长期设计还是临时兼容层
- **选项**:
  - A. 保留 symlink 作为长期兼容入口
  - B. 移除 symlink，所有脚本直接 import `stock_work.core.compat_paths`
  - C. 保留 symlink 但加文档说明
- **优先级**: P2
- **依赖**: Phase 6 硬编码清理完成
- **记录时间**: 2026-09-16

## 明天验证（2026-09-16）

### 验证 lint-db-paths 端到端告警
- **时间**: 2026-09-16 08:30 后
- **验证 SQL**: 
  ```sql
  sqlite3 cron/executions.db "SELECT job_name, status, error, created_at FROM executions WHERE job_name='lint-db-paths' ORDER BY created_at DESC LIMIT 3;"
  ```
- **预期结果**:
  - lint PASS → status='completed' + error 空
  - lint FAIL → status='failed' + error 有内容
- **飞书验证**: 查飞书是否收到告警
- **记录时间**: 2026-09-15

## Phase 7：监控/告警完善

### TODO-7-1：health_check 加 updated_at 格式校验
- **目标**: 在 `check-market-cache-health` 中增加 `indicators.updated_at` 格式校验，防止 Phase 5.1 的格式问题复发
- **优先级**: P1
- **依赖**: Phase 5.1 修复完成
- **验证项**:
  - `updated_at` 符合 `YYYY-MM-DD HH:MM:SS`
  - 异常记录数 = 0
  - 异常时触发告警（P0）

### TODO-7-2：心跳覆盖剩余 15 个任务（当前 6/21）
- **目标**: 将心跳机制从当前 6 个任务扩展到全部 21 个 cron job
- **优先级**: P2
- **依赖**: Phase 6 硬编码清理完成
- **覆盖范围**:
  - 当前已覆盖：6 个
  - 待覆盖：15 个
  - 目标：100% 覆盖

### TODO-7-3：告警分级（P0/P1/P2）
- **目标**: 建立三级告警体系，区分紧急程度
- **优先级**: P1
- **分级标准**:
  - P0：系统不可用、数据丢失、实盘止损失败
  - P1：数据质量异常、cron 连续失败
  - P2：性能下降、非关键任务失败
- **依赖**: Phase 7-1、7-2 完成

## Phase 8：长期优化

### TODO-8-1：策略绩效评估（Phase 4 延伸）
- **目标**: 建立策略绩效评估框架，评估 Phase 4 策略的实际表现
- **优先级**: P2
- **依赖**: Phase 4 完成、simulation.db 数据完整
- **评估指标**:
  - 年化收益率
  - 最大回撤
  - 夏普比率
  - 胜率

### TODO-8-2：回测框架
- **目标**: 建立可复用的 A 股回测框架
- **优先级**: P2
- **依赖**: Phase 8-1 完成
- **核心功能**:
  - 历史数据 replay
  - 多策略对比
  - 参数敏感性分析

### TODO-8-3：参数调优
- **目标**: 基于回测框架进行策略参数调优
- **优先级**: P3
- **依赖**: Phase 8-2 完成
- **调优方法**:
  - 网格搜索
  - 遗传算法
  - Walk-Forward 分析

---

*更新时间: 2026-09-16*

### TODO-6-5：lint-db-paths 的 grep 模式覆盖
- **背景**: 用 `parent.parent.parent` 匹配——实际脚本用 `parents[2]`——误报
- **影响**: 28→25→2→1→0 的"需要修"变化，都是 grep 模式问题
- **行动**: 扩展匹配模式——覆盖 `parents[N]` 写法
- **优先级**: P2
- **记录时间**: 2026-09-16

### TODO-6-6：bitable_reader 外部 API timeout 诊断
- **背景**: intraday_monitor scan3 端到端 24s~58s，其中 bitable_reader 有 timeout 调用
- **发现**: bitable_reader.py line 39 `urlopen(req, timeout=10)`、line 154 `urlopen(req, timeout=15)`
- **问题**: 如果 read_positions() 或 write 超时，会阻塞整个 scan3
- **影响范围**: 10 code → 可能 +10~15s；50 code → 可能 +50~75s
- **未修改**: bitable_reader.py 本身不修改（符合用户指令）
- **下一步**: 用 cProfile 确认是否命中 timeout
- **优先级**: P1
- **记录时间**: 2026-09-17

### TODO-6-7：signal_engine analyze_position 单 code 耗时基线
- **背景**: 端到端 10 code 里 signal_engine 占 49.79s（85%），单 code ~5s
- **问题**: 不知道 5s 花在哪（API / 计算 / DB / sleep）
- **需要**: cProfile 拆内部耗时，找到热路径
- **未修改**: signal_engine.py 不修改（符合用户指令）
- **下一步**: 跑 probe_signal_engine.py 单 code cProfile
- **优先级**: P1
- **记录时间**: 2026-09-17
