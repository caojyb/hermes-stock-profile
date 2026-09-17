#!/usr/bin/env python3
"""
因子轮动模块 v1.0 — 基于IC值的因子权重动态调整

原理：
  用最近一期因子IC值作为权重依据，IC越高的因子权重越大。
  每月运行一次（在 factor_ic.py 之后），自动调整评分卡权重。

用法：
  python3 factor_rotation.py                        # 计算并输出当前权重
  python3 factor_rotation.py --apply                # 计算并应用到评分系统
  python3 factor_rotation.py --show                 # 显示当前权重
  python3 factor_rotation.py --history              # 显示历史权重变化

数据流：
  factor_ic.py (每月1日) → factor_rotation.py (每月1日) → score_upgrade.py
"""
from core.compat_paths import MARKET_DB as _DB_PATH
MARKET_DB = _DB_PATH


import os, sys, json, math, sqlite3, statistics
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
WEIGHTS_FILE = SCRIPT_DIR / "factor_weights.json"
HISTORY_FILE = SCRIPT_DIR / "factor_weights_history.jsonl"

# 因子分组
FACTOR_GROUPS = {
    "fundamental": ["roe", "net_margin", "profit_growth", "revenue_growth",
                    "gross_margin", "debt_ratio"],
    "valuation": ["pe_ttm", "pb_mrq"],
    "technical": ["rsi_14", "boll_position", "macd_hist", "ma_bullish", "volatility_20d"],
    "risk": ["beta", "ln_market_cap", "momentum_1m", "momentum_3m", "momentum_6m"],
}

# 反向因子（值越小越好）
REVERSE_FACTORS = {"debt_ratio": True, "pe_ttm": True, "pb_mrq": True, "volatility_20d": True}

# 默认权重 (IMA 5:3:2 + 风险因子)
DEFAULT_GROUP_WEIGHTS = {
    "fundamental": 0.50,
    "valuation": 0.30,
    "technical": 0.20,
    "risk": 0.0,  # 风险因子默认不参与评分卡权重，仅用于IC分析
}


def run_factor_ic():
    """运行因子IC计算，返回 {内部因子名: IC值}"""
    ic_script = Path.home() / ".hermes" / "scripts" / "cron" / "factor_ic.py"
    if not ic_script.exists():
        print(f"⚠️ factor_ic.py 不存在: {ic_script}", file=sys.stderr)
        return None

    import subprocess
    result = subprocess.run(
        [sys.executable, str(ic_script), "--json"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"⚠️ factor_ic.py 运行失败: {result.stderr[:200]}", file=sys.stderr)
        return None

    try:
        data = json.loads(result.stdout)
        # JSON 输出返回的因子名是中文标签，需要映射到内部名
        label_to_name = {
            'ROE': 'roe', '利润增速': 'profit_growth', '营收增速': 'revenue_growth',
            '负债率': 'debt_ratio', '毛利率': 'gross_margin', '净利率': 'net_margin',
            'PE(TTM)': 'pe_ttm', 'PB(MRQ)': 'pb_mrq',
            'RSI(14)': 'rsi_14', '布林位置': 'boll_position',
            'MACD直方图': 'macd_hist', '均线形态': 'ma_bullish',
            '波动率(20日)': 'volatility_20d',
            # 风险因子
            'BETA(60日)': 'beta', 'LN市值': 'ln_market_cap',
            '动量(1月)': 'momentum_1m', '动量(3月)': 'momentum_3m',
            '动量(6月)': 'momentum_6m',
        }
        factors = {}
        for label, ic in data.get("factors", {}).items():
            name = label_to_name.get(label)
            if name:
                factors[name] = ic
        return factors if factors else None
    except (json.JSONDecodeError, AttributeError):
        return None


def _parse_ic_text(text):
    """从 factor_ic.py 文本输出解析IC值"""
    factors = {}
    for line in text.split("\n"):
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0] in FACTOR_GROUPS["fundamental"] + \
                FACTOR_GROUPS["valuation"] + FACTOR_GROUPS["technical"]:
            try:
                ic = float(parts[1])
                factors[parts[0]] = ic
            except ValueError:
                continue
    return factors if factors else None


def calc_ic_volatility(window_months=12):
    """计算每个因子过去N个月的IC标准差
    从 HISTORY_FILE 读取历史IC数据
    返回: {因子名: IC标准差}
    """
    if not HISTORY_FILE.exists():
        return {}

    records = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # 取最近 window_months 条记录
    recent = records[-window_months:] if len(records) > window_months else records
    if len(recent) < 3:
        return {}  # 数据不足

    # 收集每个因子的IC序列
    factor_ic_series = {}
    for r in recent:
        ic_data = r.get("source_ic", {})
        if not ic_data:
            continue
        for name, ic in ic_data.items():
            if name not in factor_ic_series:
                factor_ic_series[name] = []
            factor_ic_series[name].append(ic)

    # 计算标准差
    ic_vol = {}
    for name, ics in factor_ic_series.items():
        if len(ics) >= 3:
            ic_vol[name] = statistics.stdev(ics)
    return ic_vol


def apply_turnover_cap(new_weights, old_weights, max_turnover=0.50):
    """应用换手率上限
    如果新旧权重变动总和超过 max_turnover，等比例压缩

    参数:
        new_weights: dict {因子名: 有效权重}
        old_weights: dict {因子名: 有效权重}
        max_turnover: 最大允许换手率（默认50%）
    返回:
        dict {因子名: 压缩后有效权重}
    """
    if not old_weights:
        return new_weights

    # 计算总变动
    total_change = 0
    for name in set(list(new_weights.keys()) + list(old_weights.keys())):
        nw = new_weights.get(name, 0)
        ow = old_weights.get(name, 0)
        total_change += abs(nw - ow)

    # 换手率 = 总变动 / 2
    turnover = total_change / 2

    if turnover <= max_turnover:
        return new_weights  # 无需压缩

    # 需要压缩：等比例缩小变动
    scale = max_turnover / turnover

    # 对每个权重：new = old + (new - old) * scale
    capped = {}
    for name in set(list(new_weights.keys()) + list(old_weights.keys())):
        nw = new_weights.get(name, 0)
        ow = old_weights.get(name, 0)
        capped[name] = ow + (nw - ow) * scale

    # 重新归一化
    total = sum(capped.values())
    if total > 0:
        capped = {k: v / total for k, v in capped.items()}

    return capped


def calc_ic_weights(factor_ics, smoothing=0.3, use_vol_penalty=True, max_turnover=0.50, ic_vol_override=None):
    """
    基于IC值计算因子权重

    方法：
      1. 对每个因子，取 abs(IC) 作为基础权重
      2. 组内归一化（∑组内权重 = 组权重）
      3. 组间权重 = 组内平均|IC| 加权
      4. 历史平滑：new_weight = smoothing * ic_weight + (1-smoothing) * old_weight
      5. 因子波动率惩罚（v1.1）：new_weight = raw_weight / (1 + IC_std)
      6. 换手率上限（v1.1）：超过50%时等比例压缩

    参数:
        factor_ics: {因子名: IC值}
        smoothing: 平滑系数 (0=完全不变, 1=完全跟随新IC)
        use_vol_penalty: 是否启用因子波动率惩罚
        max_turnover: 最大允许换手率（默认50%）
        ic_vol_override: 可选的IC波动率 override（用于模拟测试）
    """
    if not factor_ics:
        return None

    # 加载历史权重
    old_weights = load_weights()

    # 计算因子IC波动率（过去12个月）
    ic_vol = ic_vol_override if ic_vol_override is not None else (
        calc_ic_volatility(window_months=12) if use_vol_penalty else {})

    # 1. 计算每个因子的|IC|作为基础权重
    factor_abs_ic = {}
    for name, ic in factor_ics.items():
        factor_abs_ic[name] = abs(ic)

    # 2. 组内归一化 + 波动率惩罚
    group_factor_weights = {}
    for group_name, factor_names in FACTOR_GROUPS.items():
        group_ics = {n: factor_abs_ic.get(n, 0) for n in factor_names if n in factor_abs_ic}
        total_abs = sum(group_ics.values())
        if total_abs > 0:
            for n in factor_names:
                raw_weight = group_ics.get(n, 0) / total_abs if total_abs > 0 else 0
                # 因子波动率惩罚：波动越大的因子权重越低
                if use_vol_penalty and n in ic_vol and ic_vol[n] > 0:
                    penalty = 1.0 / (1.0 + ic_vol[n])
                    raw_weight = raw_weight * penalty
                # 历史平滑
                old_w = old_weights.get("factors", {}).get(n, {}).get("weight", raw_weight)
                smoothed = smoothing * raw_weight + (1 - smoothing) * old_w
                group_factor_weights[n] = smoothed
        else:
            # 组内无IC数据，等权
            for n in factor_names:
                group_factor_weights[n] = 1.0 / len(factor_names) if factor_names else 0

    # 3. 组间权重 = 组内平均|IC| 加权
    group_avg_ic = {}
    for group_name, factor_names in FACTOR_GROUPS.items():
        ics = [abs(factor_ics.get(n, 0)) for n in factor_names if n in factor_ics]
        group_avg_ic[group_name] = sum(ics) / len(ics) if ics else 0.01

    total_avg_ic = sum(group_avg_ic.values())
    if total_avg_ic > 0:
        raw_group_weights = {g: v / total_avg_ic for g, v in group_avg_ic.items()}
    else:
        raw_group_weights = dict(DEFAULT_GROUP_WEIGHTS)

    # 历史平滑（组间）
    group_weights = {}
    for g in FACTOR_GROUPS:
        old_gw = old_weights.get("groups", {}).get(g, DEFAULT_GROUP_WEIGHTS.get(g, 0.33))
        group_weights[g] = smoothing * raw_group_weights.get(g, 0.33) + (1 - smoothing) * old_gw

    # 归一化组权重
    total_gw = sum(group_weights.values())
    group_weights = {g: v / total_gw for g, v in group_weights.items()}

    # 4. 构建结果
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "groups": group_weights,
        "factors": {},
        "source_ic": {k: round(v, 4) for k, v in factor_ics.items()},
    }

    for group_name, factor_names in FACTOR_GROUPS.items():
        gw = group_weights.get(group_name, 0)
        for n in factor_names:
            fw = group_factor_weights.get(n, 0)
            result["factors"][n] = {
                "weight": round(fw, 4),
                "group_weight": round(gw, 4),
                "effective_weight": round(fw * gw, 4),
                "ic": round(factor_ics.get(n, 0), 4),
            }

    # 5. 换手率上限：压缩权重变动
    old_eff = old_weights.get("factors", {})
    old_eff_weights = {n: old_eff.get(n, {}).get("effective_weight", 0) for n in result["factors"]}
    new_eff_weights = {n: result["factors"][n]["effective_weight"] for n in result["factors"]}
    capped_eff = apply_turnover_cap(new_eff_weights, old_eff_weights, max_turnover)

    # 重新计算 factor-level weights 和 group weights
    for n in result["factors"]:
        result["factors"][n]["effective_weight"] = round(capped_eff.get(n, 0), 4)
    total_eff = sum(capped_eff.values())
    # 重新计算组权重
    new_gw = {}
    for g, fns in FACTOR_GROUPS.items():
        gw = sum(capped_eff.get(n, 0) for n in fns if n in capped_eff)
        new_gw[g] = gw / total_eff if total_eff > 0 else 0
    result["groups"] = new_gw
    result["turnover_capped"] = True

    return result


def load_weights():
    """加载上次保存的权重"""
    if WEIGHTS_FILE.exists():
        try:
            return json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"groups": dict(DEFAULT_GROUP_WEIGHTS), "factors": {}}
    return {"groups": dict(DEFAULT_GROUP_WEIGHTS), "factors": {}}


def save_weights(weights):
    """保存权重到文件"""
    WEIGHTS_FILE.write_text(json.dumps(weights, ensure_ascii=False, indent=2), encoding="utf-8")
    # 追加历史记录
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        record = {
            "date": weights.get("date", datetime.now().strftime("%Y-%m-%d")),
            "groups": weights.get("groups", {}),
            "source_ic": weights.get("source_ic", {}),
        }
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def show_weights(weights):
    """显示当前权重"""
    if not weights or "factors" not in weights:
        print("⚠️ 暂无权重数据")
        return

    print(f"\n{'='*55}")
    print(f"  因子权重  {weights.get('date', '?')}")
    print(f"{'='*55}")

    print(f"\n📊 组间权重:")
    for g, w in weights.get("groups", {}).items():
        bar = "█" * max(1, int(w * 30))
        label = {"fundamental": "基本面", "valuation": "估值", "technical": "技术", "risk": "风险"}
        print(f"  {label.get(g, g):<8s} {bar} {w*100:.1f}%")

    print(f"\n📐 因子权重:")
    print(f"  {'因子':<16s} {'有效权重':<10s} {'IC值':<10s} {'组内':<8s}")
    print(f"  {'-'*44}")
    for name, fw in sorted(weights.get("factors", {}).items(),
                            key=lambda x: -x[1].get("effective_weight", 0)):
        ew = fw.get("effective_weight", 0) * 100
        ic = fw.get("ic", 0)
        gw = fw.get("group_weight", 0) * 100
        if ew > 0.5:
            print(f"  {name:<16s} {ew:.2f}%    {'+' if ic>0 else ''}{ic:.4f}   {gw:.1f}%")

    print(f"\n📋 来源IC:")
    for name, ic in sorted(weights.get("source_ic", {}).items(),
                            key=lambda x: -abs(x[1])):
        print(f"  {name:<16s} IC={'+' if ic>0 else ''}{ic:.4f}")


def show_history():
    """显示历史权重变化"""
    if not HISTORY_FILE.exists():
        print("⚠️ 暂无历史数据")
        return

    records = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not records:
        print("⚠️ 暂无历史数据")
        return

    print(f"\n{'='*55}")
    print(f"  因子权重历史变化")
    print(f"{'='*55}")

    # 表头
    print(f"\n{'日期':<12s} {'基本面':<8s} {'估值':<8s} {'技术':<8s} {'IC来源':<20s}")
    print(f"{'─'*56}")
    for r in records[-12:]:  # 最近12个月
        g = r.get("groups", {})
        ic = r.get("source_ic", {})
        top_ic = sorted(ic.items(), key=lambda x: -abs(x[1]))[:2]
        ic_str = "|".join(f"{n}={v:+.2f}" for n, v in top_ic) if top_ic else ""
        print(f"{r.get('date', '?'):<12s} "
              f"{g.get('fundamental',0)*100:>5.1f}% "
              f"{g.get('valuation',0)*100:>5.1f}% "
              f"{g.get('technical',0)*100:>5.1f}%  "
              f"{ic_str:<20s}")


def apply_weights(weights):
    """验证权重配置（score_upgrade.py 已改为运行时动态读取）"""
    if not weights or "groups" not in weights:
        print("⚠️ 无权重数据")
        return False

    score_upgrade = SCRIPT_DIR / "score_upgrade.py"
    if not score_upgrade.exists():
        print(f"⚠️ score_upgrade.py 不存在")
        return False

    gw = weights["groups"]
    fw = gw.get("fundamental", 0.50) * 100
    vw = gw.get("valuation", 0.30) * 100
    tw = gw.get("technical", 0.20) * 100

    print(f"✅ 权重已保存到 factor_weights.json")
    print(f"   score_upgrade.py 启动时自动读取该文件")
    print(f"   当前权重: 基本面={fw:.0f}% / 估值={vw:.0f}% / 技术={tw:.0f}%")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="因子轮动模块")
    parser.add_argument("--apply", action="store_true", help="计算并应用到评分系统")
    parser.add_argument("--show", action="store_true", help="显示当前权重")
    parser.add_argument("--history", action="store_true", help="显示历史权重变化")
    parser.add_argument("--smoothing", type=float, default=0.3,
                        help="平滑系数 (默认0.3)")
    parser.add_argument("--json", action="store_true", help="JSON输出")

    args = parser.parse_args()

    if args.show:
        show_weights(load_weights())
        sys.exit(0)

    if args.history:
        show_history()
        sys.exit(0)

    # 计算IC并生成权重
    print("📡 计算因子IC...", file=sys.stderr)
    factor_ics = run_factor_ic()

    if not factor_ics:
        print("⚠️ 无法获取IC数据，使用默认权重", file=sys.stderr)
        weights = load_weights()
    else:
        weights = calc_ic_weights(factor_ics, smoothing=args.smoothing)

    if not weights:
        print("❌ 权重计算失败")
        sys.exit(1)

    # 保存
    save_weights(weights)

    if args.json:
        print(json.dumps(weights, ensure_ascii=False, indent=2))
    else:
        show_weights(weights)

    if args.apply:
        print("\n📌 应用权重...", file=sys.stderr)
        apply_weights(weights)
    else:
        print(f"\n💡 使用 --apply 将权重应用到评分系统", file=sys.stderr)