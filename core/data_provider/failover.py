#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Provider failover 实现（2026-09-18 二轮审计 P1-5）
================================================
此前 provider_manager.py 只有注册/健康计数，没有真正的"主源失败自动切备用源"
调用路径。本模块补齐 execute_with_failover：

    pm = ProviderManager(config)
    pm.register_provider('eastmoney', em_adapter)
    pm.register_provider('sina', sina_adapter)
    result = pm.execute_with_failover(
        channel='historical', operation='kline',
        adapter_method='get_kline', args=('600540',),
    )

行为：
- 按 config[channel][operation] 的 primary → fallback[*] 顺序尝试
- 每次 try 用该源的 timeout/retry 配置；失败记入健康计数
- 主源连续失败 >= threshold（默认 3）后续请求直接跳过（熔断），直到
  cooldown 秒数（默认 300s）过后重试一次探活
- 全部源失败 → 抛 DataProviderError（fail loud，不静默返回空数据）
"""
from __future__ import annotations

import time
from typing import Any

from core.data_provider.exceptions import DataProviderError, ProviderTimeoutError
from core.data_provider.provider_manager import ProviderManager

DEFAULT_BREAKER_THRESHOLD = 3
DEFAULT_BREAKER_COOLDOWN = 300.0


def execute_with_failover(
    self: ProviderManager,
    channel: str,
    operation: str,
    adapter_method: str,
    args: tuple = (),
    kwargs: dict | None = None,
) -> Any:
    """按 primary→fallback 顺序执行 adapter_method，带健康熔断。"""
    kwargs = kwargs or {}
    cfg = (self.config.get(channel, {}) or {}).get(operation, {})
    chain: list[dict] = []
    primary = cfg.get('primary')
    if primary:
        chain.append(primary)
    chain.extend(cfg.get('fallback', []) or [])

    if not chain:
        # 无配置时退化为单一已注册源
        chain = [{'provider': next(iter(self._providers), None), 'timeout': 10, 'retry': 1}]

    errors: list[str] = []
    for spec in chain:
        name = spec.get('provider')
        if not name or name not in self._providers:
            errors.append(f'{name}: not registered')
            continue
        health = self._health.get(name, {})
        # 熔断检查
        cf = health.get('consecutive_failures', 0)
        last_fail = health.get('last_failure_ts', 0.0)
        if cf >= DEFAULT_BREAKER_THRESHOLD:
            if time.time() - last_fail < DEFAULT_BREAKER_COOLDOWN:
                errors.append(f'{name}: circuit OPEN ({cf} consecutive failures, cooldown)')
                continue
            # 冷却期过，放行一次探活
        provider = self._providers[name]
        fn = getattr(provider, adapter_method, None)
        if fn is None:
            errors.append(f'{name}: no method {adapter_method}')
            continue

        timeout = float(spec.get('timeout', 10))
        retries = int(spec.get('retry', 1))
        for attempt in range(1, retries + 1):
            try:
                result = fn(*args, timeout=timeout, **kwargs) if 'timeout' in (fn.__code__.co_varnames[:fn.__code__.co_argcount] if hasattr(fn, '__code__') else ()) else fn(*args, **kwargs)
                self.record_success(name)
                return result
            except Exception as e:
                err = f'{name}#{attempt}: {type(e).__name__}: {e}'
                errors.append(err)
                if attempt == retries:
                    self.record_failure(name, str(e))
                    h = self._health[name]
                    h['last_failure_ts'] = time.time()
                else:
                    time.sleep(min(2 ** attempt, 8))

    raise DataProviderError(
        f'failover exhausted [{channel}/{operation}]: ' + ' | '.join(errors[-6:]),
        provider=','.join(str(s.get('provider')) for s in chain),
    )


# 注入为 ProviderManager 方法（保持原文件不动，向后兼容）
ProviderManager.execute_with_failover = execute_with_failover
