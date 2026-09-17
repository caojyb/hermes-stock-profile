---
name: stock-feeshu-bitable
description: 飞书 Bitable 股票CRM技能——持仓管理、盘中监控、选股推荐
tags: [stock, feishu, bitable, CRM]
---

## 执行命令

所有操作都在目录下执行：
```bash
cd ~/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable
```

## Cron 部署关系（源文件 vs 编译产物）

- 本目录的 `intraday_monitor.py` 是**源文件**（手动调试/开发用），skill 侧不含 wakeAgent gate
- cron 执行的是**编译产物** `~/.hermes/profiles/stock/scripts/cron/intraday_monitor.py`
  （= 自动 header [sys.path.insert + atexit `{"wakeAgent": false}` gate] + 源文件全文）
- **修改源文件后必须重新同步**：`bash ~/.hermes/profiles/stock/scripts/cron/sync_intraday.sh`
- 漂移检测：`bash ~/.hermes/profiles/stock/scripts/cron/sync_intraday.sh --check`
  （产物第 2 行嵌入 src_md5，与源文件 md5 比对）
- 直接编辑编译产物会被下次 sync 覆盖——永远只改本目录源文件
- 资金流数据源：TDX opentdx 直连（Hermes venv），东财 push2 已移除；
  降级事件记录于 `stock-work/data/runtime/money_flow_degraded.log`（10MB 轮转）

## 可用脚本

| 脚本 | 用途 |
|------|------|
| `intraday_monitor.py scan3` | 盘中持仓监控，扫描技术信号，有预警才推送 |
| `intraday_monitor.py scan4` | 全市场个股推荐，独立推送，不依赖持仓 |
| `market_cache.py refresh` | 全市场K线下载（收盘后16:30），并发50线程，约40秒完成~5000只 |
| `market_cache.py incremental` | 增量更新（盘中用，持仓股+候选股），并发30线程 |
| `update_sector.py` | 补充/更新 stocks 表行业字段（EastMoney DataCenter API） |
| `double_up_screener.py --write-db --market-outlook` | 翻倍潜力股打分（每周日17:00运行，在financial_data 16:35更新完成后确保数据最新），五维评分+市场展望，一次输出完整周报。`--write-db` 写 double_up_scores 表供稳健档前置过滤；`--market-outlook` 输出板块动量/技术方向/中美关联 |
| `turnover_rate` | indicators 表新增字段，存储日换手率(%)，由腾讯行情实时更新 |
| `fetch_pe_pb.py 100` | 每周日16:00执行，全量更新所有股票的PE/PB数据（并发30线程，约2分钟完成5186只） |

## 新增策略模块 (2026-07-22，IMA知识库融合)

| 脚本 | 用途 |
|------|------|
| `financial_screen.py --code 600519` | 财报勾稽检查（ROE/负债/成长/毛利，10条规则，含红线警告） |
| `strategy_lowvol_highroe.py --top 20` | 低波动高ROE双因子策略（年化34%/夏普2.11） |
| `strategy_lowvol_highroe.py --mode main_up --top 20` | 低波动高ROE主升浪模式（ROE≥15%+均线多头+RSI 40-70） |
| `strategy_lowvol_highroe.py --mode oversold --top 20` | 低波动高ROE超跌反弹模式（ROE≥10%+布林下轨+RSI<30） |
| `strategy_lowvol_highroe.py --backtest --mode main_up` | 主升浪模式历史回测 |
| `strategy_lowvol_highroe.py --backtest --mode oversold` | 超跌反弹模式历史回测 |
| `backtest_engine.py --mode main_up` | 通用回测引擎主升浪模式 |
| `backtest_engine.py --mode oversold` | 通用回测引擎超跌反弹模式 |
| `portfolio_stress_test.py --codes 600519,300750` | 持仓压力测试（4剧本：加息/地缘/流动性/政策） |
| `pre_trade_checklist.py --code 600519` | 开仓前检查清单（数据/财务/估值/技术/情绪） |
| `industry_screener.py --top 15` | 行业筛选（华泰三因子：估值30%+动量40%+财务30%） |
| `score_upgrade.py --code 600519` | 5:3:2评分卡（基本面50%+估值30%+技术20%） |

## 节假日保护（交易日哨兵）

所有脚本在入口处均已内置 `is_trading_day()` 哨兵，基于 akshare `tool_trade_date_hist_sina()` 判断今天是否 A 股交易日，非交易日直接跳过，不依赖 cron 的 `1-5` 过滤。

**覆盖脚本：** `pre_market_brief.py`、`intraday_monitor.py`、`position_diagnosis.py`、`market_cache.py refresh`、`double_up_screener.py --market-outlook`

**注意：** `market_cache.py` 的哨兵在脚本级别上下文（`if __name__ == "__main__"`），判断失败时用 `sys.exit(0)`，不能 `return`。

**验证节假日判断：**
```bash
cd ~/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable
python3 -c "
import importlib.util, sys; sys.path.insert(0, '.')
spec = importlib.util.spec_from_file_location('t', 'pre_market_brief.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.is_trading_day())
"
```

## 每日收盘后行情更新（market_cache refresh）

```bash
cd ~/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable && python3 market_cache.py refresh
```

- 每天 16:30 收盘后执行（cron: `stock-market-cache-refresh`）
- 从东方财富分页获取全量 A 股列表（~4000 只）
- 下载每只股票近 66 天 K 线
- 计算 RSI/MACD/布林带/均线/ATR 等指标
- 存入本地 SQLite，盘中 scan3/scan4 直接查询，无需联网

## 每周PE/PB数据更新（fetch_pe_pb.py）

```bash
cd ~/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable && python3 fetch_pe_pb.py 100
```

- 每周日16:00执行（cron: `stock-pepb-weekly`）
- 从腾讯财经获取实时PE/PB数据，存入 `pe_pb_data` 表
- 并发30线程，约2分钟完成全量更新（~5186只）
- 使用 `INSERT OR REPLACE`，同一天重复运行会覆盖旧数据

## 持仓监控（scan3，--position-only 模式）

```bash
cd ~/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable && python3 intraday_monitor.py --position-only
```

- 盘中每30分钟自动运行（cron: `stock-intraday-monitor`）
- **仅扫描持仓股票**，推送技术预警信号（RSI/MACD/布林/均线等）
- 有预警才推送，无预警静默（输出 `无需要推送的预警信号`）
- 不再推送市场机会推荐，避免重复

## 个股推荐（scan4）

```bash
cd ~/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable && python3 intraday_monitor.py scan4
```

- 独立推送全市场买入信号，不依赖持仓状态
- **前置过滤**：JOIN `double_up_scores` 表（周六更新的五维打分），只从≥60分候选股中筛选技术面买点
- 若 `double_up_scores` 表不存在（周更数据未写入），自动退化为全市场扫描（向后兼容）
- **只推送买入信号**（`signal_level >= 4`），观察/跟踪/回避信号一律过滤
- 两层分级：
  - 🟢🚀建仓级：RSI < 30 且 score ≥ 50
  - 🔵⚡重点关注：RSI < 40 且 score ≥ 45
- RSI 实时重算：取最近15天K线收盘价 + 实时价格，重算 RSI 再判断层级
- 布林位实时校正：基于实时价重算布林位置
- **每条推荐包含**：
  - 现价、今日涨跌幅、RSI、布林位置、综合评分
  - ⬆️ 压力位（布林上轨 boll_upper）
  - ⬇️ 支撑位（布林下轨 boll_lower）
  - 📌 推荐理由（最多3条，从 RSI/MACD/均线/布林带综合生成）
- 有机会才推送，无机会输出 `无满足条件的个股推荐`
- **推送后自动同步到 Bitable**（类型=候选），记录推荐时间/价格/RSI/评分

### 推荐原因生成逻辑

`get_market_opportunities()` 中对每只候选股生成原因列表，最多取前3条最关键的：

| 条件 | 推荐原因文本 |
|------|-------------|
| RSI < 30 | RSI严重超卖({rsi:.0f})，反弹概率大 |
| RSI 30-40 | RSI处于低位({rsi:.0f})，向上空间充足 |
| RSI 40-50 | RSI健康区间({rsi:.0f}) |
| MACD红柱（hist > 0）| MACD红柱，动能向上 |
| MACD绿柱 | MACD绿柱(历史)，等待转红 |
| MA5>MA10>MA20>MA60 | 均线多头排列，上涨趋势清晰 |
| MA5>MA10>MA20 | 短期均线多头，短线强势 |
| 布林位置 < 20% | 股价贴近布林下轨({boll_pos:.0f}%)，超卖区域 |
| 布林位置 20-40% | 股价处于布林中下轨({boll_pos:.0f}%)，相对低位 |
| score ≥ 60 | 综合评分强劲({score:.0f}分) |
| score ≥ 45 | 综合评分良好({score:.0f}分) |
