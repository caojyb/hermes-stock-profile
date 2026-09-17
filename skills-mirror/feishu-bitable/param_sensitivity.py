#!/usr/bin/env python3
"""参数敏感性分析脚本"""
import sys, json, os
sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')
from backtest_engine import create_strategy_doubling_v1, run_backtest

DEFAULT = dict(price_pos_max=40, vol_ratio_min=1.3, atr_pct_min=3, mcap_min=5, mcap_max=50, turnover_min=1000)

params = [
    ("价格分位阈值", "price_pos_max", [20, 30, 40, 50, 60]),
    ("量比阈值", "vol_ratio_min", [1.5, 1.8, 2.0, 2.5, 3.0]),
    ("市值上限(亿)", "mcap_max", [30, 40, 50, 60, 80]),
    ("市值下限(亿)", "mcap_min", [3, 5, 8, 10]),
    ("成交额门槛(万)", "turnover_min", [2000, 3000, 5000, 8000, 10000]),
    ("ATR阈值(%)", "atr_pct_min", [2, 3, 4, 5]),
]

def run_and_measure(strategy_fn, label):
    """运行一次回测，返回指标"""
    try:
        result = run_backtest(strategy_fn, start_date="2021-01", end_date="2026-07",
                              top_n=30, benchmark="000300")
        if isinstance(result, dict) and "error" in result:
            return {"label": label, "error": result["error"]}
        if isinstance(result, tuple):
            ins, oos = result
            m = ins if ins else {}
        elif isinstance(result, dict):
            m = result
        else:
            return {"label": label, "error": f"unknown result type: {type(result)}"}
        return {
            "label": label,
            "ann_ret": round(m.get("annual_return_pct", 0), 2),
            "max_dd": round(m.get("max_drawdown_pct", 0), 2),
            "sharpe": round(m.get("sharpe_ratio", 0), 2),
            "calmar": round(m.get("calmar_ratio", 0), 2),
            "win_rate": round(m.get("win_rate", 0), 1),
            "n_months": m.get("total_months", 0),
        }
    except Exception as e:
        return {"label": label, "error": str(e)}

results = []
for param_name, param_key, values in params:
    for val in values:
        kwargs = dict(DEFAULT)
        kwargs[param_key] = val
        strategy_fn = create_strategy_doubling_v1(**kwargs)
        label = f"{param_key}={val}"
        print(f"  测试 {param_name}: {label}...", file=sys.stderr)
        r = run_and_measure(strategy_fn, label)
        results.append(r)
        print(f"    → {r.get('ann_ret','?')}% / {r.get('max_dd','?')}% / Sharpe={r.get('sharpe','?')}", file=sys.stderr)

# 输出结果
print(json.dumps({"params": params, "results": results, "default": DEFAULT}, ensure_ascii=False, indent=2))
