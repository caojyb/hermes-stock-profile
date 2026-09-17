#!/bin/bash
# 可转债每日扫描推送
cd ~/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable
http_proxy= https_proxy= HTTP_PROXY= HTTPS_PROXY= /home/caojy/.hermes/profiles/stock/.venv/bin/python3 convertible_bond.py 2>&1