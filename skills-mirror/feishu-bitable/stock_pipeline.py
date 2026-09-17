#!/usr/bin/env python3
"""
五阶段闭环全流程引擎 v1.0

将已有模块串联为一条自动化流水线：
  行业筛选 → 财报检查 → 量化验证 → 开仓检查 → 风控压力测试

用法：
  python3 stock_pipeline.py                    # 完整流程
  python3 stock_pipeline.py --skip risk        # 跳过风控
  python3 stock_pipeline.py --quick            # 快速（减少候选数量）
  python3 stock_pipeline.py --json             # JSON 输出
"""

import os, sys, json, subprocess, argparse
from pathlib import Path
from datetime import datetime
from collections import OrderedDict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable  # 使用脚本所在解释器

# 桩脚本路径
SCRIPTS = {k: os.path.join(SCRIPT_DIR, v) for k, v in {
    "industry":   "industry_screener.py",
    "financial":  "financial_screen.py",
    "quant":      "double_up_screener.py",
    "pre_trade":  "pre_trade_checklist.py",
    "risk":       "portfolio_stress_test.py",
}.items()}


def _valid(p):
    if not os.path.exists(p):
        print(f"  [SKIP] 未找到: {p}", file=sys.stderr)
        return False
    return True


def _run(stage, args_list, timeout=120):
    """运行一个阶段脚本并解析JSON输出"""
    cmd = [PYTHON, SCRIPTS[stage]] + args_list
    # 子脚本（industry_screener 等）import core.*，需要 stock-work 在模块搜索路径上；
    # 继承当前 env 否则 ModuleNotFoundError → stage 静默返回空 → 报告"Top: 空"
    env = dict(os.environ)
    stock_work = str(Path(__file__).resolve().parents[5] / 'stock-work')
    env['PYTHONPATH'] = stock_work + os.pathsep + env.get('PYTHONPATH', '')
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        stdout = r.stdout.strip()
        stderr = r.stderr.strip()
        if r.returncode != 0:
            msg = stderr[:300] if stderr else f"exit={r.returncode}"
            return {"error": msg, "stdout": stdout, "stderr": stderr}
        # 尝试解析JSON（从第一个{到最后一个}）
        data = None
        start = stdout.find("\n{")
        if start < 0:
            start = stdout.find("{")
        end = stdout.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(stdout[start:end+1])
            except json.JSONDecodeError:
                pass
        # 尝试解析JSON数组
        if data is None:
            start_arr = stdout.find("\n[")
            if start_arr < 0:
                start_arr = stdout.find("[")
            end_arr = stdout.rfind("]")
            if start_arr >= 0 and end_arr > start_arr:
                try:
                    data = json.loads(stdout[start_arr:end_arr+1])
                except json.JSONDecodeError:
                    pass
        if data is None:
            # 尝试整段解析
            try:
                data = json.loads(stdout)
            except json.JSONDecodeError:
                data = {"text_output": stdout[:1000]}
        return {"data": data, "raw": stdout, "stderr": stderr}
    except subprocess.TimeoutExpired:
        return {"error": f"timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"error": f"script not found: {SCRIPTS.get(stage, stage)}"}
    except Exception as e:
        return {"error": str(e)}


def stage_industry(top=5):
    """① 行业筛选"""
    if not _valid(SCRIPTS["industry"]):
        return {"sectors": [], "raw": ""}
    r = _run("industry", ["--top", str(top), "--json"])
    if "error" in r:
        return {"error": r["error"], "sectors": []}
    d = r.get("data", {})
    sectors = d.get("top_sectors", [])
    return {
        "sectors": sectors,
        "total": d.get("total_sectors", 0),
        "raw": r.get("raw", ""),
    }


def stage_financial(limit=100):
    """② 财报勾稽检查"""
    if not _valid(SCRIPTS["financial"]):
        return {"stocks": [], "raw": ""}
    r = _run("financial", ["--scan", "--limit", str(limit), "--json"])
    if "error" in r:
        return {"error": r["error"], "stocks": []}
    d = r.get("data", {})
    return {
        "stocks": d.get("results", d.get("stocks", [])),
        "raw": r.get("raw", ""),
    }


def stage_quant(top=20, codes=None):
    """③ 量化验证（double_up_screener deep mode）"""
    if not _valid(SCRIPTS["quant"]):
        return {"stocks": [], "raw": ""}
    args = ["--mode", "deep", "--top", str(top), "--json"]
    if codes:
        args += ["--codes", codes]
    r = _run("quant", args, timeout=180)  # deep mode needs more time
    if "error" in r:
        return {"error": r["error"], "stocks": []}
    d = r.get("data", {})
    selected = d.get("top", d.get("selected", []))
    return {
        "stocks": selected,
        "summary": {
            "candidates": d.get("total_candidates", d.get("candidate_count", 0)),
            "mode": d.get("mode", "deep"),
        },
        "raw": r.get("raw", ""),
    }


def stage_pre_trade(code, price=None):
    """④ 开仓前检查"""
    if not _valid(SCRIPTS["pre_trade"]):
        return {"result": {}, "raw": ""}
    args = ["--code", code, "--json"]
    if price:
        args += ["--price", str(price)]
    r = _run("pre_trade", args)
    if "error" in r:
        return {"error": r["error"]}
    d = r.get("data", {})
    return {
        "result": d.get("checklist", d.get("result", d)),
        "raw": r.get("raw", ""),
    }


def stage_risk(codes_str):
    """⑤ 持仓压力测试"""
    if not _valid(SCRIPTS["risk"]):
        return {"result": {}, "raw": ""}
    r = _run("risk", ["--codes", codes_str, "--json"])
    if "error" in r:
        return {"error": r["error"]}
    d = r.get("data", r.get("raw"))
    if isinstance(d, list):
        return {"result": {"stocks": d}, "raw": r.get("raw", "")}
    return {
        "result": d.get("stress_test", d.get("result", d)) if isinstance(d, dict) else {},
        "raw": r.get("raw", ""),
    }


# ====== 主流程 ======

def pipeline(quick=False, skip_stages=None, json_output=False, top_n=20):
    skip = set(skip_stages or [])
    results = OrderedDict()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if "industry" not in skip:
        print(f"\n{'='*55}\n  ① 行业筛选 ...", file=sys.stderr)
        industry = stage_industry(top=3)
        results["industry"] = industry
        top_sectors = [s.get("sector","") for s in industry.get("sectors",[])][:5]
        print(f"  → Top: {', '.join(top_sectors[:3])}", file=sys.stderr)

    if "financial" not in skip:
        print(f"\n{'='*55}\n  ② 财报勾稽（全市场扫描）...", file=sys.stderr)
        limit = 50 if quick else 200
        fin = stage_financial(limit=limit)
        results["financial"] = fin
        print(f"  → 扫描 {limit} 只", file=sys.stderr)

    if "quant" not in skip:
        # 如果财报阶段有输出，用其codes作为量化输入（加速）
        fin_stocks = results.get("financial", {}).get("stocks", [])
        candidate_codes = [s.get("code","") for s in fin_stocks if s.get("code")][:50]
        codes_str = ",".join(candidate_codes) if candidate_codes else None

        print(f"\n{'='*55}\n  ③ 量化验证（deep评分）{' codes='+codes_str[:40] if codes_str else '...'}...", file=sys.stderr)
        quant = stage_quant(top=top_n, codes=codes_str)
        results["quant"] = quant
        stocks = quant.get("stocks", [])
        print(f"  → 选入 {len(stocks)} 只", file=sys.stderr)

        # 对 Top-5 自动执行开仓前检查
        top_codes = [s.get("code","") for s in stocks if s.get("code")][:5]
        if top_codes:
            print(f"\n{'='*55}\n  ④ 开仓前检查（Top-5）...", file=sys.stderr)
            pt_results = {}
            for code in top_codes:
                pt = stage_pre_trade(code)
                pt_results[code] = pt
                status = "✅" if "error" not in pt else "⚠️"
                print(f"  {status} {code}", file=sys.stderr)
            results["pre_trade"] = pt_results

            # 对选中的做压力测试
            if "risk" not in skip:
                print(f"\n{'='*55}\n  ⑤ 持仓压力测试 ...", file=sys.stderr)
                risk = stage_risk(",".join(top_codes))
                results["risk"] = risk
                print(f"  → {len(top_codes)} 只压力测试完成", file=sys.stderr)

    # ====== 输出报告 ======
    if json_output:
        return results

    lines = []
    lines.append(f"\n{'='*65}")
    lines.append(f"  五阶段闭环全流程报告")
    lines.append(f"  时间: {timestamp}")
    lines.append(f"{'='*65}")

    # ① 行业
    ind = results.get("industry", {})
    sectors = ind.get("sectors", [])
    if sectors:
        lines.append(f"\n📊 ① 行业筛选 | 全市场 {ind.get('total',0)} 个行业")
        for s in sectors[:5]:
            lines.append(f"  ▸ {s.get('sector','')}: 总分{s.get('total_score',0)} "
                        f"(估值{s.get('val_score',0)} 动量{s.get('mom_score',0)} 财务{s.get('fin_score',0)})")
    else:
        lines.append(f"\n📊 ① 行业筛选: 跳过")

    # ② 财报
    fin = results.get("financial", {})
    if fin:
        lines.append(f"\n📋 ② 财报勾稽检查")
        stocks = fin.get("stocks", [])
        if stocks:
            good = sum(1 for s in stocks if s.get("rating","") in ("A","B"))
            warn = sum(1 for s in stocks if s.get("rating","") in ("C","D"))
            lines.append(f"  扫描 {len(stocks)} 只 | A/B级 {good} 只 | C/D级 {warn} 只")
        else:
            lines.append(f"  扫描完成")

    # ③ 量化
    q = results.get("quant", {})
    stocks = q.get("stocks", [])
    if stocks:
        lines.append(f"\n🎯 ③ 量化验证 | Top {len(stocks)}")
        lines.append(f"  {'代码':<6s} {'名称':<10s} {'总分':>6s} {'行业':>10s}")
        lines.append(f"  {'-'*35}")
        for s in stocks[:10]:
            lines.append(f"  {s.get('code',''):<6s} {s.get('name','')[:8]:<10s} {s.get('total_score',0):>5.1f} "
                        f"{s.get('industry',s.get('sector',''))[:8]:>10s}")
    else:
        lines.append(f"\n🎯 ③ 量化验证: 跳过")

    # ④ 开仓检查
    pt = results.get("pre_trade", {})
    if pt:
        lines.append(f"\n🔒 ④ 开仓前检查")
        for code, r in pt.items():
            status = "✅ 允许" if "error" not in r else "⚠️ 谨慎"
            detail = r.get("result", {})
            if isinstance(detail, dict) and detail:
                checks = []
                for k, v in list(detail.items())[:5]:
                    if isinstance(v, (int, float)):
                        checks.append(f"{k}={v}")
                    elif isinstance(v, str) and v:
                        checks.append(f"{k}={v}")
                details = " | ".join(checks[:3])
            else:
                details = ""
            lines.append(f"  {status} {code}  {details}")

    # ⑤ 风控
    rk = results.get("risk", {})
    if rk:
        lines.append(f"\n🛡️ ⑤ 压力测试")
        detail = rk.get("result", {})
        if isinstance(detail, dict):
            stocks = detail.get("stocks", [])
            if stocks:
                for s in stocks[:5]:
                    name = s.get("name", s.get("code", ""))
                    mdd = s.get("max_drawdown_60d", "?")
                    scens = s.get("scenarios", [])
                    worst = max([x.get("est_drop_pct", 0) for x in scens]) if scens else "?"
                    risk = "高" if (isinstance(worst, (int,float)) and worst > 30) else "中"
                    lines.append(f"  {name}: 60日回撤{mdd}% | 极端预估{worst}% | 风险等级{risk}")
            else:
                for k, v in list(detail.items())[:5]:
                    if isinstance(v, (int, float)):
                        lines.append(f"  {k}: {v}")
                    elif isinstance(v, str):
                        lines.append(f"  {k}: {v[:60]}")
        else:
            lines.append(f"  完成")

    lines.append(f"\n{'='*65}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="五阶段闭环全流程引擎")
    parser.add_argument("--quick", action="store_true", help="快速模式（减少候选）")
    parser.add_argument("--skip", nargs="*", default=[],
                        help="跳过阶段: industry financial quant pre_trade risk")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--top", type=int, default=20, help="量化输出数量")
    args = parser.parse_args()

    report = pipeline(
        quick=args.quick,
        skip_stages=args.skip,
        json_output=args.json,
        top_n=args.top,
    )
    print(report if isinstance(report, str) else json.dumps(report, ensure_ascii=False, indent=2))
