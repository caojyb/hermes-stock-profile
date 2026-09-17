# 新建脚本 Checklist

> 新建任何 `scripts/cron/*.py` 前，必须逐项确认并签字。

## 路径规范

- [ ] 使用了 `core.compat_paths` 或 `stock_db_paths.get_db_path()`？
- [ ] 如果用了 `compat_paths`，有没有 `sys.path.insert` 指向 `stock-work`？
- [ ] 没有硬编码绝对路径（如 `/home/caojy/...`）？
- [ ] 没有用 `parents[N]` 拼接 DB 文件名？
- [ ] 没有用 `Path('MARKET_DB')` 等字面量？

## 心跳规范

- [ ] 脚本开头有 `_t0 = time.time()`？
- [ ] 结束时写 `heartbeat.write(task=..., status=..., cost_ms=...)`？

## 飞书告警规范

- [ ] P0/P1 问题调用 `send_feishu()`？
- [ ] P2 问题写日志，不发飞书？

## 错误处理

- [ ] 异常场景有 `return 1` 防假成功？
- [ ] 空数据场景有兜底逻辑？

## 测试

- [ ] `python3 -m py_compile` 通过？
- [ ] 手动跑一次，确认输出正常？

---

**签字**: _______________
**日期**: _______________
