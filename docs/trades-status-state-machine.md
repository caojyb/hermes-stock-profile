# trades.status 状态机定稿

## 1. 状态定义

| 状态 | 含义 | 写入者 | 可否回滚 |
|------|------|--------|---------|
| `pending` | 未执行信号 | `signals` 表 | 可撤单 |
| `持有` | 信号已执行/意向持仓 | `double_monitor.py`、`track_flow_manager.py` | 可减仓/清仓 |
| `部分止盈` | 部分卖出，仍持有剩余 | `double_monitor.py` / `risk_controller_v2.py` UPDATE | 可继续止盈/清仓 |
| `减仓` | 风控减仓 | `risk_controller_v2.py` UPDATE | 不可逆 |
| `清仓止盈` | 全部止盈卖出 | `risk_controller_v2.py` / `double_monitor.py` UPDATE | 不可逆 |
| `止损` | 止损卖出 | `risk_controller_v2.py` / `double_monitor.py` UPDATE | 不可逆 |
| `失效` | 系统/人工标记作废 | 系统自动 / 人工 | 不可恢复 |

## 2. 合法转移路径

```
pending
  ├── → 持有      （double_monitor.py 执行买入）
  ├── → 失效      （系统自动：超时/熔断/人工）
  └── → 失效      （人工撤单）

持有
  ├── → 部分止盈  （double_monitor.py / risk_controller_v2.py，UPDATE 同一行）
  ├── → 减仓      （risk_controller_v2.py，UPDATE 同一行）
  ├── → 清仓止盈  （risk_controller_v2.py / double_monitor.py，UPDATE 同一行）
  ├── → 止损      （risk_controller_v2.py / double_monitor.py，UPDATE 同一行）
  └── → 失效      （系统自动：持仓异常/人工）

部分止盈
  ├── → 清仓止盈  （剩余部分全部卖出）
  ├── → 止损      （剩余部分止损）
  └── → 减仓      （风控减仓剩余部分）

减仓 / 清仓止盈 / 止损
  └── → 失效      （归档后标记，可选）

任何状态
  └── → 失效      （人工强制标记）
```

## 3. 转移约束

- `pending → 持有`：必须由 `double_monitor.py` 或 `track_flow_manager.py` 发起，且 `code` 在候选池 `double_up_scores` 中
- `持有 → 部分止盈`：必须是 UPDATE 同一行，不能 INSERT 新行
- `持有 → 减仓/清仓止盈/止损`：`risk_controller_v2.py` 只更新 `id IN (SELECT id FROM trades WHERE code=? AND status='持有')`
- `部分止盈 → 清仓止盈/止损/减仓`：UPDATE 同一行
- 任意 `status` → `失效`：系统自动或人工，不检查前置状态

## 4. pending 不进 trades 表

`pending` 状态写入独立的 `signals` 表，`trades` 表只存 `持有/部分止盈/减仓/清仓止盈/止损/失效`。

## 5. 唯一索引条件

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_active_code
ON trades(code) WHERE status IN ('持有', '部分止盈');
```

- 只约束 `status IN ('持有','部分止盈')`
- `减仓/清仓止盈/止损/失效` 不纳入唯一索引
- `pending` 不在 `trades` 表，不受此索引约束

## 6. 失效触发条件（具体值）

### 自动失效

| 触发条件 | 阈值 | 告警级别 | 执行脚本 |
|---------|------|---------|---------|
| pending 超时 | 3 个交易日未执行 | P1 | `double_monitor.py` 启动时检查 |
| 数据异常 | `market_cache.db` `max_trade_date < T-1` | P1 | `double_monitor.py` 启动时检查 |
| 风控熔断 | 账户日回撤 >= 5% | P0 | `risk_controller_v2.py` |
| 单标的跌停/停牌 | 连续 2 日无法交易 | P1 | `position-stop-loss-alert` |

### 人工失效

- 管理员通过飞书指令或后台脚本手动标记
- 需记录 `operator` 和 `reason`

### 失效后处理

- 状态改为 `失效`
- 不可恢复
- 必须重新生成信号才能继续

## 7. signals 表契约

### 表结构

```sql
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    signal_type TEXT NOT NULL,  -- BUY / SELL / REDUCE
    source TEXT NOT NULL,       -- double_monitor / track_flow / manual
    strategy TEXT NOT NULL,     -- v1_double / track_flow / ...
    status TEXT DEFAULT 'pending',  -- pending / executed / cancelled / expired
    created_at TEXT NOT NULL,
    executed_at TEXT,
    trade_id INTEGER,           -- 关联 trades.id
    notes TEXT,
    UNIQUE(code, signal_type, source, date(created_at))  -- 同一天同一来源同一标的只记一次
);
```

### 谁写

| 写入者 | 写入内容 |
|--------|---------|
| `double_monitor.py` | 主信号：`signal_type=BUY`，`source=double_monitor` |
| `track_flow_manager.py` | 资金流跟踪信号：`signal_type=BUY`，`source=track_flow` |
| 人工 | 手动信号：`signal_type=BUY/SELL/REDUCE`，`source=manual` |

### 谁读

| 读取者 | 读取内容 |
|--------|---------|
| `double_monitor.py` | 读取 `pending` 信号，执行后更新 `status='executed'` |
| `risk_controller_v2.py` | 读取 `pending` 风控信号 |
| `simulation_engine.py` | 读取全部信号用于统计 |

### pending → 持有 的转移

```
1. double_monitor.py 从 signals 表读取 status='pending' 的信号
2. 执行买入逻辑
3. INSERT INTO trades (status='持有')
4. UPDATE signals SET status='executed', trade_id=last_insert_rowid()
```

`signals.status` 的转移由 `double_monitor.py` 负责，不依赖外部调度。

## 8. 实施顺序（状态机定稿后）

1. 建 `signals` 表（如果不存在）
2. 建 `idx_trades_active_code` 部分唯一索引
3. 修改 `double_monitor.py`：写入 `signals` 表后再写 `trades` 表
4. 修改 `track_flow_manager.py`：写入 `signals` 表后再写 `trades` 表
5. 修改 `risk_controller_v2.py`：只做 UPDATE，不 INSERT
6. 验证：`trades` 表无重复，`signals` 表状态机正确

## 9. 回滚方案

- `signals` 表是可选的，不影响现有 `trades` 表运行
- 唯一索引可先建，不强制约束现有数据（用 `IF NOT EXISTS` + 部分索引）
- 如果状态机调整，只需修改 `signals` 表逻辑，`trades` 表不变
