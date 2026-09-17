#!/bin/bash
# 盘后财报检查（每个交易日收盘后运行）
# 扫描候选池 + 持仓的财务勾稽检查
cd ~/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable || exit 1
source ~/.hermes/venv/bin/activate
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
echo "=== 盘后财报检查 $(date '+%Y-%m-%d %H:%M') ==="
/home/caojy/.hermes/profiles/stock/.venv/bin/python3 financial_screen.py --scan 2>&1
echo "=== done ==="