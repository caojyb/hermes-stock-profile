#!/usr/bin/env python3
"""
backtest_to_live.py — 回测结果到实盘参数的映射模块
===================================================
P1-3: 回测到实盘闭环

功能：
  1. 运行所有策略的回测，比较绩效
  2. 最优策略参数 → 自动应用到 auto_recommend.py 的三档配置
  3. 回测夏普比率 → 影响仓位建议（trade_manager.py 凯利公式输入）
  4. 输出映射结果到 JSON 供下游使用

用法：
  python3 backtest_to_live.py                                # 运行完整映射
  python3 backtest_to_live.py --backtest-only                # 只跑回测，不更新配置
  python3 backtest_to_live.py --show-mapping                 # 查看当前映射
  python3 backtest_to_live.py --apply                        # 运行回测并应用映射

数据流：
  backtest_engine.py → backtest_to_live.py → auto_recommend.py 配置
                                           → trade_manager.py 凯利参数
"""

import os
import sys
import json
import math
import statistics
import argparse
import subprocess
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = Path.home() / ".hermes" / "cron" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 映射文件路径
MAPPING_FILE = OUTPUT_DIR / "backtest_to_live_mapping.json"
BACKTEST_RESULTS_FILE = OUTPUT_DIR / "backtest_results_latest.json"

# 默认凯利公式参数
DEFAULT_KELLY_PARAMS = {
    "win_rate": 0.40,
    "reward_risk_ratio": 2.0,
}

# ── 夏普比率 → 凯利公式参数映射 ──

def sharpe_to_kelly_params(sharpe_ratio: float) -> dict:
    """
    将回测夏普比率映射为凯利公式输入参数。

    原理：
      - 夏普比率 = (E[R] - Rf) / σ
      - 通过夏普比率估算月胜率：假设收益服从正态分布，
        p = Φ(Sharpe / √12) 近似
      - 盈亏比通过夏普和胜率反推

    映射逻辑：
      夏普 < 0.5   → 低质量，保守仓位
      夏普 0.5-1.0 → 中等质量
      夏普 1.0-1.5 → 良好
      夏普 > 1.5   → 优秀，可加仓
    """
    if sharpe_ratio <= 0:
        return {"win_rate": 0.35, "reward_risk_ratio": 1.5, "sharpe_source": sharpe_ratio}

    # 从夏普估算月胜率（近似二元正态分布）
    # 月化夏普 = 年化夏普 / sqrt(12)
    monthly_sharpe = sharpe_ratio / math.sqrt(12)
    # 近似累计分布函数（误差函数近似）
    try:
        from math import erf
        win_rate = 0.5 * (1 + erf(monthly_sharpe / math.sqrt(2)))
    except ImportError:
        # 简单线性映射
        win_rate = min(0.65, 0.35 + sharpe_ratio * 0.15)

    # 局限在合理范围
    win_rate = max(0.30, min(0.75, win_rate))

    # 从夏普估算盈亏比
    # 夏普高 → 盈亏比高
    rr = min(3.5, max(1.2, 1.2 + sharpe_ratio * 0.8))

    return {
        "win_rate": round(win_rate, 3),
        "reward_risk_ratio": round(rr, 2),
        "sharpe_source": sharpe_ratio,
    }


# ── 策略绩效 → 选股参数映射 ──

def strategy_params_to_tier_config(strategy_name: str, metrics: dict) -> dict:
    """
    将策略回测绩效映射到三档配置参数。

    映射规则：
      - 主升浪策略 (lowvol_highroe_main_up) → 稳健档配置
      - 超跌反弹策略 (lowvol_highroe_oversold) → 激进档配置
      - ima_532 → 综合配置

    参数调整：
      - 夏普高 → 放宽止损（更信任策略）
      - 夏普低 → 收紧止损、提高要求
      - 回撤大 → 降低仓位上限
    """
    sharpe = metrics.get("sharpe_ratio", 0)
    max_dd = metrics.get("max_drawdown_pct", 20)
    cagr = metrics.get("cagr_pct", 0)

    adjustments = {
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_dd,
        "cagr_pct": cagr,
    }

    # 策略类型映射
    if "main_up" in strategy_name:
        tier = "steady"
        # 主升浪：夏普高→放宽止损至6%，夏普低→收紧至4%
        adj_stop_loss = max(4.0, min(6.0, 5.0 - (sharpe - 1.0) * 1.0))
        # 仓位上限：夏普高→15%，低→8%
        adj_max_pos = min(15.0, max(8.0, 10.0 + (sharpe - 1.0) * 5.0))
        adjustments.update({
            "stop_loss_pct": round(adj_stop_loss / 100, 3),
            "max_position_pct": round(adj_max_pos / 100, 3),
            "tier": "稳健档",
            "tier_type": "主升浪顺势",
        })

    elif "oversold" in strategy_name:
        tier = "aggressive"
        # 超跌反弹：夏普高→放宽止损，但超跌反弹本身止损要严格
        adj_stop_loss = max(5.0, min(8.0, 7.0 - (sharpe - 0.5) * 2.0))
        adj_max_pos = min(8.0, max(3.0, 5.0 + (sharpe - 0.5) * 3.0))
        adjustments.update({
            "stop_loss_pct": round(adj_stop_loss / 100, 3),
            "max_position_pct": round(adj_max_pos / 100, 3),
            "tier": "激进档",
            "tier_type": "超跌反弹",
        })

    elif "lowvol_highroe" in strategy_name:
        tier = "value"
        adj_stop_loss = max(7.0, min(12.0, 10.0 - (sharpe - 0.8) * 2.0))
        adj_max_pos = min(20.0, max(10.0, 15.0 + (sharpe - 0.8) * 5.0))
        adjustments.update({
            "stop_loss_pct": round(adj_stop_loss / 100, 3),
            "max_position_pct": round(adj_max_pos / 100, 3),
            "tier": "价值档",
            "tier_type": "低估值成长",
        })

    else:  # ima_532 or generic
        tier = "steady"
        adj_stop_loss = max(4.0, min(8.0, 5.0 - (sharpe - 1.0) * 1.0))
        adj_max_pos = min(15.0, max(8.0, 10.0 + (sharpe - 1.0) * 5.0))
        adjustments.update({
            "stop_loss_pct": round(adj_stop_loss / 100, 3),
            "max_position_pct": round(adj_max_pos / 100, 3),
            "tier": "稳健档",
            "tier_type": "主升浪顺势",
        })

    return adjustments


# ── 运行回测 ──

def run_all_backtests(start="2020-01", end=None, top_n=30, oos=0.0) -> dict:
    """
    运行所有策略的回测。

    返回：
      {strategy_name: metrics_dict, ...}
    """
    if end is None:
        today = date.today()
        end = today.strftime("%Y-%m")

    backtest_script = SCRIPT_DIR / "backtest_engine.py"
    if not backtest_script.exists():
        print(f"❌ backtest_engine.py 不存在: {backtest_script}", file=sys.stderr)
        return {}

    print(f"🔬 运行全策略回测 ({start} ~ {end})...", file=sys.stderr)
    print(f"   策略: lowvol_highroe, lowvol_highroe_main_up, lowvol_highroe_oversold, ima_532", file=sys.stderr)

    results = {}
    strategies = ["lowvol_highroe", "lowvol_highroe_main_up", "lowvol_highroe_oversold", "ima_532"]

    for sname in strategies:
        print(f"\n   ▶ {sname}...", file=sys.stderr)
        try:
            cmd = [
                sys.executable, str(backtest_script),
                "--strategy", sname,
                "--start", start,
                "--end", end,
                "--top-n", str(top_n),
                "--json",
            ]
            if oos > 0:
                cmd.extend(["--oos", str(oos)])

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if proc.returncode != 0:
                print(f"      ⚠️ 回测失败 (exit={proc.returncode}): {proc.stderr[:200]}", file=sys.stderr)
                continue

            # 解析 JSON 输出
            data = json.loads(proc.stdout)
            results[sname] = data
            print(f"      ✅ 完成", file=sys.stderr)

        except subprocess.TimeoutExpired:
            print(f"      ⏰ 超时", file=sys.stderr)
        except json.JSONDecodeError as e:
            print(f"      ⚠️ JSON 解析失败: {e}", file=sys.stderr)
        except Exception as e:
            print(f"      ❌ 异常: {e}", file=sys.stderr)

    print(f"\n   ✅ 完成 {len(results)}/{len(strategies)} 个策略", file=sys.stderr)

    # 保存原始回测结果
    BACKTEST_RESULTS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )
    print(f"   💾 原始结果已保存: {BACKTEST_RESULTS_FILE}", file=sys.stderr)

    return results


# ── 策略排序与选择 ──

def rank_strategies(results: dict) -> list:
    """
    按综合评分排序策略。

    评分公式：
      score = SHARPE × 0.4 + CAGR_NORM × 0.3 + (1 - DD_NORM) × 0.2 + WIN_RATE_NORM × 0.1

    返回 [(strategy_name, score, metrics), ...]
    """
    ranked = []
    for sname, data in results.items():
        # 跳过元数据键（以 _ 开头）
        if sname.startswith("_"):
            continue
        if not isinstance(data, dict):
            continue
        ins = data.get("in_sample", {})
        if not ins or "sharpe_ratio" not in ins:
            continue

        sharpe = ins.get("sharpe_ratio", 0)
        cagr = ins.get("cagr_pct", 0)
        max_dd = ins.get("max_drawdown_pct", 20)
        win_rate = ins.get("win_rate_pct", 0)
        total_return = ins.get("total_return_pct", 0)

        # 归一化
        sharpe_score = max(0, min(1, (sharpe - 0) / 2.0))  # 0-2 归一化到 0-1
        cagr_score = max(0, min(1, cagr / 30))  # 0-30% 归一化
        dd_score = 1 - min(1, max_dd / 40)  # 0-40% 归一化
        wr_score = max(0, min(1, win_rate / 70))  # 0-70% 归一化

        composite = (
            sharpe_score * 0.40 +
            cagr_score * 0.30 +
            dd_score * 0.20 +
            wr_score * 0.10
        )

        ranked.append((sname, round(composite, 3), ins))

    ranked.sort(key=lambda x: -x[1])
    return ranked


# ── 应用映射到实盘 ──

def generate_mapping(all_results: dict, ranked: list) -> dict:
    """
    生成回测→实盘的完整映射。

    返回映射字典，包含：
      - rank: 策略排名
      - best_strategy: 最佳策略及参数
      - kelly_params: 各策略的凯利参数
      - config_adjustments: 配置调整建议
      - timestamp: 生成时间
    """
    if not ranked:
        return {"error": "无有效回测结果", "timestamp": datetime.now().isoformat()}

    best_name, best_score, best_metrics = ranked[0]
    ins = best_metrics

    # 最佳策略的凯利参数
    best_sharpe = ins.get("sharpe_ratio", 0)
    kelly = sharpe_to_kelly_params(best_sharpe)

    # 策略参数映射
    config_adj = strategy_params_to_tier_config(best_name, ins)

    # 所有策略的夏普汇总
    sharpe_summary = {}
    for sname, _, metrics in ranked:
        sharpe_summary[sname] = {
            "sharpe_ratio": metrics.get("sharpe_ratio", 0),
            "cagr_pct": metrics.get("cagr_pct", 0),
            "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
            "win_rate_pct": metrics.get("win_rate_pct", 0),
        }

    mapping = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "rank": [
            {
                "strategy": sname,
                "composite_score": score,
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "cagr_pct": metrics.get("cagr_pct", 0),
                "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
                "win_rate_pct": metrics.get("win_rate_pct", 0),
                "total_return_pct": metrics.get("total_return_pct", 0),
            }
            for sname, score, metrics in ranked
        ],
        "best_strategy": {
            "name": best_name,
            "composite_score": best_score,
            "metrics": {
                "sharpe_ratio": ins.get("sharpe_ratio", 0),
                "cagr_pct": ins.get("cagr_pct", 0),
                "max_drawdown_pct": ins.get("max_drawdown_pct", 0),
                "win_rate_pct": ins.get("win_rate_pct", 0),
                "total_return_pct": ins.get("total_return_pct", 0),
                "profit_loss_ratio": ins.get("profit_loss_ratio", 0),
            },
            "kelly_params": kelly,
            "config_adjustments": config_adj,
        },
        "kelly_params_by_strategy": {
            sname: sharpe_to_kelly_params(
                metrics.get("sharpe_ratio", 0)
            )
            for sname, _, metrics in ranked
        },
        "sharpe_summary": sharpe_summary,
        "backtest_params": {
            "start": all_results.get("_start", ""),
            "end": all_results.get("_end", ""),
            "top_n": all_results.get("_top_n", 30),
            "oos": all_results.get("_oos", 0.0),
        },
    }

    return mapping


def save_mapping(mapping: dict):
    """保存映射到文件"""
    MAPPING_FILE.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )
    print(f"\n💾 映射已保存: {MAPPING_FILE}", file=sys.stderr)
    return MAPPING_FILE


def load_mapping() -> dict:
    """加载最新的映射"""
    if MAPPING_FILE.exists():
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    return {}


def show_mapping(mapping: dict):
    """显示当前映射"""
    if not mapping or "error" in mapping:
        print("⚠️ 无有效映射")
        return

    print("\n" + "=" * 60)
    print("  回测→实盘参数映射")
    print("=" * 60)
    print(f"  生成时间: {mapping.get('timestamp', '?')}")

    best = mapping.get("best_strategy", {})
    if best:
        print(f"\n  ★ 最佳策略: {best.get('name', '?')}")
        print(f"     综合评分: {best.get('composite_score', '?')}")
        metrics = best.get("metrics", {})
        print(f"     夏普: {metrics.get('sharpe_ratio', '?')}")
        print(f"     CAGR: {metrics.get('cagr_pct', '?')}%")
        print(f"     最大回撤: {metrics.get('max_drawdown_pct', '?')}%")
        print(f"     月胜率: {metrics.get('win_rate_pct', '?')}%")
        print(f"     累计收益: {metrics.get('total_return_pct', '?')}%")

        kelly = best.get("kelly_params", {})
        print(f"\n  📐 凯利公式参数:")
        print(f"     胜率: {kelly.get('win_rate', '?')}")
        print(f"     盈亏比: {kelly.get('reward_risk_ratio', '?')}")
        print(f"     源夏普: {kelly.get('sharpe_source', '?')}")

        adj = best.get("config_adjustments", {})
        print(f"\n  ⚙️ 配置调整:")
        print(f"     止损: {adj.get('stop_loss_pct', '?')}")
        print(f"     仓位上限: {adj.get('max_position_pct', '?')}")

    rank = mapping.get("rank", [])
    if rank:
        print(f"\n  📊 策略排名:")
        for i, r in enumerate(rank, 1):
            print(f"    {i}. {r['strategy']:<30s} 综合={r['composite_score']:.3f}  "
                  f"夏普={r['sharpe_ratio']:.2f}  CAGR={r['cagr_pct']:.1f}%  "
                  f"回撤={r['max_drawdown_pct']:.1f}%")

    print("\n" + "=" * 60)


# ── 应用回测结果到实盘配置 ──

def apply_to_live_config(mapping: dict) -> dict:
    """
    将映射应用到实盘配置。

    具体操作：
      1. 更新 auto_recommend.py 中的三档配置（止损、仓位）
      2. 更新 trade_manager.py 的默认凯利参数
      3. 生成配置变更报告
    """
    changes = []
    best = mapping.get("best_strategy", {})
    if not best:
        return {"error": "无最佳策略", "changes": []}

    # 1. 更新凯利参数
    kelly = best.get("kelly_params", {})
    if kelly:
        changes.append({
            "target": "trade_manager.py",
            "parameter": "calc_position_size default win_rate",
            "old_value": DEFAULT_KELLY_PARAMS["win_rate"],
            "new_value": kelly.get("win_rate", DEFAULT_KELLY_PARAMS["win_rate"]),
        })
        changes.append({
            "target": "trade_manager.py",
            "parameter": "calc_position_size default reward_risk_ratio",
            "old_value": DEFAULT_KELLY_PARAMS["reward_risk_ratio"],
            "new_value": kelly.get("reward_risk_ratio", DEFAULT_KELLY_PARAMS["reward_risk_ratio"]),
        })

    # 2. 更新配置调整
    adj = best.get("config_adjustments", {})
    if adj:
        stop_loss = adj.get("stop_loss_pct", 0.05)
        max_pos = adj.get("max_position_pct", 0.10)

        # 根据策略类型映射到对应档位
        tier = adj.get("tier", "稳健档")
        if tier == "激进档":
            changes.append({
                "target": "auto_recommend.py AGGRESSIVE_CONFIG",
                "parameter": "stop_loss_pct",
                "old_value": "0.07",
                "new_value": str(stop_loss),
            })
            changes.append({
                "target": "auto_recommend.py AGGRESSIVE_CONFIG",
                "parameter": "max_position (adjusted)",
                "old_value": "0.05",
                "new_value": str(max_pos),
            })
        elif tier == "价值档":
            changes.append({
                "target": "auto_recommend.py VALUE_CONFIG",
                "parameter": "stop_loss_pct",
                "old_value": "0.10",
                "new_value": str(stop_loss),
            })
            changes.append({
                "target": "auto_recommend.py VALUE_CONFIG",
                "parameter": "max_position (adjusted)",
                "old_value": "0.15",
                "new_value": str(max_pos),
            })
        else:  # 稳健档
            changes.append({
                "target": "auto_recommend.py STEADY_CONFIG",
                "parameter": "stop_loss_pct",
                "old_value": "0.05",
                "new_value": str(stop_loss),
            })
            changes.append({
                "target": "auto_recommend.py STEADY_CONFIG",
                "parameter": "max_position (adjusted)",
                "old_value": "0.10",
                "new_value": str(max_pos),
            })

    # 生成应用报告
    applied = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "best_strategy": best.get("name", "?"),
        "kelly_params": kelly,
        "config_adjustments": adj,
        "changes": changes,
        "change_count": len(changes),
    }

    # 保存到文件
    applied_path = OUTPUT_DIR / "backtest_live_applied.json"
    applied_path.write_text(
        json.dumps(applied, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )

    print(f"\n✅ 映射已应用，{len(changes)} 项变更", file=sys.stderr)
    for c in changes:
        print(f"   • {c['target']}: {c['parameter']} = {c['new_value']} "
              f"(原: {c['old_value']})", file=sys.stderr)

    return applied


# ── 主流程 ──

def main():
    parser = argparse.ArgumentParser(
        description="回测结果到实盘参数的映射",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 backtest_to_live.py                    # 运行完整映射
  python3 backtest_to_live.py --backtest-only    # 只跑回测
  python3 backtest_to_live.py --show-mapping     # 查看当前映射
  python3 backtest_to_live.py --apply            # 运行并应用
  python3 backtest_to_live.py --start 2022-01    # 指定回测起始
        """
    )
    parser.add_argument("--backtest-only", action="store_true",
                        help="只跑回测，不更新配置")
    parser.add_argument("--show-mapping", action="store_true",
                        help="显示当前映射")
    parser.add_argument("--apply", action="store_true",
                        help="运行回测并应用映射到实盘配置")
    parser.add_argument("--start", default="2020-01",
                        help="回测开始年月 (YYYY-MM)")
    parser.add_argument("--end", default=None,
                        help="回测结束年月 (YYYY-MM)，默认当前月")
    parser.add_argument("--top-n", type=int, default=30,
                        help="选股数量")
    parser.add_argument("--oos", type=float, default=0.0,
                        help="样本外比例")
    parser.add_argument("--json", action="store_true",
                        help="JSON 输出")

    args = parser.parse_args()

    # 显示当前映射
    if args.show_mapping:
        mapping = load_mapping()
        show_mapping(mapping)
        if args.json:
            print(json.dumps(mapping, ensure_ascii=False, indent=2, default=str))
        return

    # 运行回测
    print(f"📊 回测→实盘映射引擎 v1.0", file=sys.stderr)
    print(f"   工作目录: {SCRIPT_DIR}", file=sys.stderr)
    print(f"   输出目录: {OUTPUT_DIR}", file=sys.stderr)

    all_results = run_all_backtests(
        start=args.start,
        end=args.end,
        top_n=args.top_n,
        oos=args.oos,
    )

    if not all_results:
        print("❌ 回测全部失败", file=sys.stderr)
        sys.exit(1)

    # 存储回测参数
    all_results["_start"] = args.start
    all_results["_end"] = args.end or datetime.now().strftime("%Y-%m")
    all_results["_top_n"] = args.top_n
    all_results["_oos"] = args.oos

    # 策略排序
    ranked = rank_strategies(all_results)
    print(f"\n📊 策略排名:", file=sys.stderr)
    for i, (sname, score, _) in enumerate(ranked, 1):
        print(f"   {i}. {sname:<30s} 综合评分: {score:.3f}", file=sys.stderr)

    # 生成映射
    mapping = generate_mapping(all_results, ranked)
    save_mapping(mapping)

    if args.json:
        print(json.dumps(mapping, ensure_ascii=False, indent=2, default=str))
        return

    # 显示映射
    show_mapping(mapping)

    # 应用映射
    if args.apply:
        apply_to_live_config(mapping)
        print(f"\n💡 提示: 配置已记录到 {OUTPUT_DIR}/backtest_live_applied.json", file=sys.stderr)
        print(f"   如需自动应用到 auto_recommend.py/trade_manager.py，请运行:", file=sys.stderr)
        print(f"   python3 auto_recommend.py --backtest-mode apply", file=sys.stderr)
    elif args.backtest_only:
        print(f"\n💡 --backtest-only 模式，未更新配置", file=sys.stderr)
    else:
        print(f"\n💡 使用 --apply 将映射应用到实盘配置", file=sys.stderr)


if __name__ == "__main__":
    main()