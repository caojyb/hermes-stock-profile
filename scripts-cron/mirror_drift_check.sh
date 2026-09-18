#!/usr/bin/env bash
# sync_mirror 漂移检测（2026-09-18 审计 P2 修复）
# 生产侧与 git 镜像漂移时非零退出，触发告警
set -u
cd /home/caojy/.hermes/profiles/stock/stock-work
bash scripts/sync_mirror.sh --check
exit $?
