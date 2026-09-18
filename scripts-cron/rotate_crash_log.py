#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tui_gateway_crash.log 轮转（2026-09-18 审计 P2 修复）
保留最近 3 个 5MB 分片，超过即滚动删除最旧。
挂在 cron-health-sentinel 之后每日执行（同一脚本内调用亦安全）。
"""
import sys
from pathlib import Path

LOG = Path('/home/caojy/.hermes/profiles/stock/logs/tui_gateway_crash.log')
MAX_BYTES = 5 * 1024 * 1024
KEEP = 3


def main():
    if not LOG.exists() or LOG.stat().st_size < MAX_BYTES:
        return
    # 滚动: crash.log.2 -> 删, .1 -> .2, .0 -> .1, log -> .0
    for i in range(KEEP - 1, -1, -1):
        src = LOG.with_suffix(LOG.suffix + (f'.{i}' if i else ''))
        dst = LOG.with_suffix(LOG.suffix + f'.{i + 1}')
        if src.exists():
            if i + 1 >= KEEP:
                src.unlink()
            else:
                src.rename(dst)
    LOG.rename(LOG.with_suffix(LOG.suffix + '.0'))
    LOG.touch()
    print(f'rotated: {LOG.name} > 5MB, kept {KEEP} shards')


if __name__ == '__main__':
    sys.exit(main())
