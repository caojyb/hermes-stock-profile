"""
因子预处理工具
提供：去极值(Winsorize) + Z-score标准化 + 因子评分
"""

import math


def winsorize(values, lower=0.001, upper=0.999):
    """
    去极值：将超出分位数的值压缩到分位数
    values: list of floats (可能含None)
    returns: list of floats (None保持不变)
    """
    valid = [v for v in values if v is not None]
    if not valid:
        return values
    
    valid.sort()
    n = len(valid)
    l_idx = max(0, int(n * lower))
    u_idx = min(n - 1, int(n * upper))
    lower_val = valid[l_idx]
    upper_val = valid[u_idx]
    
    return [max(lower_val, min(v, upper_val)) if v is not None else None for v in values]


def zscore(values):
    """
    Z-score标准化：(x - mean) / std
    values: list of floats (可能含None)
    returns: list of floats (None保持不变)
    """
    valid = [v for v in values if v is not None]
    if len(valid) < 3:
        return values
    
    mean = sum(valid) / len(valid)
    var = sum((v - mean) ** 2 for v in valid) / len(valid)
    std = math.sqrt(var) if var > 0 else 1
    
    return [(v - mean) / std if v is not None else None for v in values]


def factor_score(values, reverse=False, scale=10, center=50):
    """
    完整因子处理：去极值 → Z-score → 映射到0-100分
    reverse=True: 值越小分数越高（如PE、负债率）
    scale=10: 每个Z-score对应10分
    center=50: Z-score=0时映射到50分
    """
    # 1. 去极值
    w = winsorize(values)
    # 2. Z-score
    z = zscore(w)
    # 3. 映射到分数
    scores = []
    for v in z:
        if v is None:
            scores.append(None)
        else:
            s = center + (v if not reverse else -v) * scale
            scores.append(max(0, min(100, s)))
    return scores


def process_factor_batch(stocks, factor_key, reverse=False):
    """
    批量处理单个因子
    stocks: list of dicts, 每个dict必须包含factor_key
    factor_key: 因子字段名
    reverse: 是否反向
    returns: 在stocks中原地添加 {factor_key}_score 字段
    """
    values = [s.get(factor_key) for s in stocks]
    scores = factor_score(values, reverse=reverse)
    score_key = f"{factor_key}_score"
    for s, sc in zip(stocks, scores):
        s[score_key] = sc


# ── 风险因子计算接口 ──

def compute_risk_factors_for_stocks(stocks, compute_fn=None, max_workers=8):
    """
    为股票列表批量计算风险因子（BETA/市值/动量）。
    
    参数:
        stocks: [{'code': str, ...}, ...]
        compute_fn: 外部计算函数，如果为None则使用本地risk_factors模块
        max_workers: 并发数
    
    返回: 在stocks中原地添加风险因子字段
    """
    codes = [s.get("code") for s in stocks if s.get("code")]
    
    if compute_fn is None:
        # 使用本地risk_factors模块
        try:
            from risk_factors import compute_all_risk_factors
            factors = compute_all_risk_factors(codes, max_workers=max_workers)
        except ImportError:
            print("⚠️ risk_factors.py 不可用，跳过风险因子计算")
            return
    
    # 建立code→因子映射
    factor_map = {}
    for f in factors:
        factor_map[f["code"]] = f
    
    # 合并到原数据
    for s in stocks:
        code = s.get("code")
        if code in factor_map:
            f = factor_map[code]
            s["beta"] = f.get("beta")
            s["ln_market_cap"] = f.get("ln_market_cap")
            s["momentum_1m"] = f.get("momentum_1m")
            s["momentum_3m"] = f.get("momentum_3m")
            s["momentum_6m"] = f.get("momentum_6m")


# 风险因子定义（供factor_ic.py和factor_rotation.py使用）
RISK_FACTORS = {
    "beta": {
        "label": "BETA(60日)",
        "description": "个股vs沪深300的60日回归系数",
        "reverse": False,  # BETA越高波动越大，正向
        "group": "risk",
    },
    "ln_market_cap": {
        "label": "LN市值",
        "description": "市值对数",
        "reverse": False,  # 市值越大越大盘
        "group": "risk",
    },
    "momentum_1m": {
        "label": "动量(1月)",
        "description": "过去1个月收益率",
        "reverse": False,
        "group": "risk",
    },
    "momentum_3m": {
        "label": "动量(3月)",
        "description": "过去3个月收益率",
        "reverse": False,
        "group": "risk",
    },
    "momentum_6m": {
        "label": "动量(6月)",
        "description": "过去6个月收益率",
        "reverse": False,
        "group": "risk",
    },
}


if __name__ == "__main__":
    # 测试
    test_data = [1, 2, 3, 4, 5, 100, -100, 3, 4, None]
    print(f"原始: {test_data}")
    print(f"去极值: {winsorize(test_data, 0.1, 0.9)}")
    print(f"Z-score: {zscore(test_data)}")
    print(f"评分: {factor_score(test_data)}")
    print(f"反向评分: {factor_score(test_data, reverse=True)}")
    
    # 批量测试
    stocks = [
        {'code': 'A', 'roe': 15, 'pe': 10},
        {'code': 'B', 'roe': 25, 'pe': 5},
        {'code': 'C', 'roe': 5, 'pe': 30},
        {'code': 'D', 'roe': -5, 'pe': 100},
        {'code': 'E', 'roe': None, 'pe': None},
    ]
    process_factor_batch(stocks, 'roe')
    process_factor_batch(stocks, 'pe', reverse=True)
    for s in stocks:
        print(f"{s['code']}: ROE={s.get('roe_score')}, PE={s.get('pe_score')}")