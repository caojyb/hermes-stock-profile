#!/usr/bin/env python3
"""
股票命理集成系统
================
融合 国学体系（紫微斗数/梅花易数/命卦）+ 股票技术分析

功能:
1. 个股命理诊断 - 股票五行 + 用户命格匹配
2. 大盘时机分析 - 流年运势 + 市场技术信号
3. 仓位管理建议 - 基于用户运势调整风险敞口

用法:
    python3 stock_fortune.py diagnose --stock 605058
    python3 stock_fortune.py timing --birth-date 1984-10-18 --birth-time 03:00
    python3 stock_fortune.py position-size --birth-date 1984-10-18 --market bullish
"""

import sys
import json
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# 路径配置
FORTUNE_DIR = Path.home() / ".openclaw/workspace-fortunetelling"
SKILL_DIR = FORTUNE_DIR / "skills"
ZIWEI_SCRIPT = SKILL_DIR / "ziweidoushu/scripts/ziwei_chart.py"
MEIHUA_SCRIPT = SKILL_DIR / "meihua-yishu/scripts/meihua.py"
FORTUNE_ANALYSIS = FORTUNE_DIR / "scripts/fortune_analysis.py"
MEMORY_FILE = FORTUNE_DIR / "memories/MEMORY.md"

# 股票五行分类（简化版，实际需更完整的数据库）
STOCK_WUXING = {
    # 木行业
    "林业": "木", "造纸": "木", "家具": "木", "纺织": "木", "服装": "木",
    "医药": "木", "教育": "木", "环保": "木",
    # 火行业
    "能源": "火", "电力": "火", "化工": "火", "电子": "火", "半导体": "火",
    "互联网": "火", "软件": "火", "通信": "火",
    # 土行业
    "房地产": "土", "建筑": "土", "建材": "土", "农业": "土", "旅游": "土",
    "酒店": "土", "食品": "土",
    # 金行业
    "金融": "金", "银行": "金", "保险": "金", "证券": "金", "钢铁": "金",
    "有色金属": "金", "军工": "金", "汽车": "金", "机械": "金",
    # 水行业
    "水务": "水", "港口": "水", "航运": "水", "物流": "水", "商贸": "水",
    "水产": "水", "酿酒": "水", "食品饮料": "水",
}

# 五行相生相克
WUXING_CYCLE = {
    "木": {"生": "火", "泄": "水", "克": "土", "被克": "金"},
    "火": {"生": "土", "泄": "木", "克": "金", "被克": "水"},
    "土": {"生": "金", "泄": "火", "克": "水", "被克": "木"},
    "金": {"生": "水", "泄": "土", "克": "木", "被克": "火"},
    "水": {"生": "木", "泄": "金", "克": "火", "被克": "土"},
}


def get_user_birth_info():
    """从memories/MEMORY.md获取用户出生信息"""
    if not MEMORY_FILE.exists():
        return None
    content = MEMORY_FILE.read_text()
    # 解析出生日期
    for line in content.split("\n"):
        if "出生" in line and ("日期" in line or "时间" in line):
            # 简化解析
            pass
    return None


def run_fortune_analysis(birth_date: str, birth_time: str, gender: str, target_year: int = None) -> dict:
    """运行命理分析"""
    cmd = [
        sys.executable, str(FORTUNE_ANALYSIS),
        "--date", birth_date,
        "--time", birth_time,
        "--gender", gender,
        "--output", "json"
    ]
    if target_year:
        cmd += ["--target-year", str(target_year)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            # 找到JSON输出
            lines = result.stdout.split("\n")
            in_json = False
            json_str = ""
            for line in lines:
                if "???JSON???" in line:
                    in_json = True
                    continue
                if in_json:
                    json_str += line
            if json_str:
                return json.loads(json_str)
    except Exception as e:
        return {"error": str(e)}
    return {"error": "分析失败"}


def run_meihua_now() -> dict:
    """运行梅花易数当前卦象"""
    cmd = [sys.executable, str(MEIHUA_SCRIPT), "now"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            # 解析输出
            return {"output": result.stdout}
    except Exception as e:
        return {"error": str(e)}
    return {"error": "梅花易数分析失败"}


def analyze_stock_wuxing(stock_code: str, stock_name: str = "") -> dict:
    """
    分析股票五行
    简化版：通过股票名称的行业特征判断
    """
    # 实际应该接入实时数据，这里简化
    if not stock_name:
        return {"wuxing": "未知", "method": "名称为空"}

    # 遍历行业关键词匹配
    for industry, wuxing in STOCK_WUXING.items():
        if industry in stock_name:
            return {"wuxing": wuxing, "industry": industry, "method": "行业匹配"}

    # 默认根据代码范围猜测（不准确）
    if stock_code.startswith(("0", "3")):
        return {"wuxing": "木", "industry": "深交所", "method": "代码猜测"}
    elif stock_code.startswith(("6", "5", "8")):
        return {"wuxing": "金", "industry": "上交所", "method": "代码猜测"}
    return {"wuxing": "土", "industry": "综合", "method": "默认"}


def match_fortune_stock(fortune_data: dict, stock_wuxing: str) -> dict:
    """
    命格与股票五行匹配分析
    """
    result = {
        "match_score": 0,
        "verdict": "中性",
        "analysis": "",
        "suggestion": ""
    }

    # 从命理数据提取关键信息
    ming_gua = fortune_data.get("命卦", {}).get("命卦", "")
    ming_gua_wuxing = fortune_data.get("命卦", {}).get("五行", "")

    if not ming_gua_wuxing:
        result["verdict"] = "无法判断"
        result["analysis"] = "缺少命卦五行信息"
        return result

    # 五行相生相克分析
    wuxing_info = WUXING_CYCLE.get(ming_gua_wuxing, {})

    if stock_wuxing == ming_gua_wuxing:
        # 同五行：比和，平稳
        result["match_score"] = 70
        result["verdict"] = "适合"
        result["analysis"] = f"股票属{stock_wuxing}，与命格{ming_gua_wuxing}比和，性格稳健"
        result["suggestion"] = "适合中长线持有，稳步增值"
    elif stock_wuxing in wuxing_info.get("生", ""):
        # 股票生命格：相生，大吉
        result["match_score"] = 90
        result["verdict"] = "非常适合"
        result["analysis"] = f"股票属{stock_wuxing}，生助命格{ming_gua_wuxing}，天人合一"
        result["suggestion"] = "重点关注，可重仓配置"
    elif stock_wuxing in wuxing_info.get("被克", ""):
        # 股票被命格克：小凶
        result["match_score"] = 40
        result["verdict"] = "谨慎"
        result["analysis"] = f"命格{ming_gua_wuxing}克股票{stock_wuxing}，用力过猛"
        result["suggestion"] = "控制仓位，避免过度投入"
    elif stock_wuxing in wuxing_info.get("泄", ""):
        # 命格泄股票：消耗
        result["match_score"] = 50
        result["verdict"] = "一般"
        result["analysis"] = f"命格{ming_gua_wuxing}泄股票{stock_wuxing}，得不偿失"
        result["suggestion"] = "短线为主，不宜长持"
    else:
        # 相克
        result["match_score"] = 30
        result["verdict"] = "不适合"
        result["analysis"] = f"股票{stock_wuxing}克制命格{ming_gua_wuxing}，冲突明显"
        result["suggestion"] = "回避为主，若持有需严格止损"

    return result


def get_luck_adjustment(fortune_data: dict) -> dict:
    """
    根据流年运势调整风险敞口
    """
    adjustment = {
        "position_mult": 1.0,  # 仓位倍数
        "risk_level": "正常",
        "analysis": "",
        "suggestion": ""
    }

    # 从命理数据提取流年信息
    ming = fortune_data.get("命卦", {})
    dz = fortune_data.get("大运", {})

    # 简单的运势判断
    ming_type = ming.get("命格", "")

    # 吉格增加仓位，凶格减少
    if any(x in ming_type for x in ["生财", "旺", "吉", "喜"]):
        adjustment["position_mult"] = 1.2
        adjustment["risk_level"] = "积极"
        adjustment["analysis"] = "命格吉利，可适当放大风险敞口"
        adjustment["suggestion"] = "仓位提升至120%，进取操作"
    elif any(x in ming_type for x in ["刑", "冲", "煞", "凶", "破"]):
        adjustment["position_mult"] = 0.5
        adjustment["risk_level"] = "保守"
        adjustment["analysis"] = "命格带刑冲，宜静不宜动"
        adjustment["suggestion"] = "仓位降至50%，观望为主"
    else:
        adjustment["analysis"] = "命格平稳，顺势而为"
        adjustment["suggestion"] = "保持常规仓位"

    return adjustment


def diagnose_stock(stock_code: str, birth_date: str = None, birth_time: str = None, gender: str = "男"):
    """
    综合诊断：股票 + 命理
    """
    output = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stock_code": stock_code,
    }

    # 1. 获取股票信息（技术面）
    try:
        from stock_data import get_stock_quote
        q = get_stock_quote("A", stock_code)
        output["stock_info"] = {
            "name": q.get("name", "未知"),
            "price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
        }
        stock_name = q.get("name", "")
    except Exception as e:
        output["stock_info"] = {"error": str(e)}
        stock_name = ""

    # 2. 股票五行分析
    stock_wuxing = analyze_stock_wuxing(stock_code, stock_name)
    output["stock_wuxing"] = stock_wuxing

    # 3. 命理分析（如果提供了出生信息）
    if birth_date and birth_time:
        fortune = run_fortune_analysis(birth_date, birth_time, gender)
        output["fortune"] = fortune

        # 五行匹配
        if "命卦" in fortune:
            ming_gua_wuxing = fortune.get("命卦", {}).get("五行", "土")
            match = match_fortune_stock(fortune, stock_wuxing.get("wuxing", "土"))
            output["fortune_stock_match"] = match

            # 仓位调整
            luck_adj = get_luck_adjustment(fortune)
            output["luck_adjustment"] = luck_adj

    # 4. 梅花易数当前卦象
    meihua = run_meihua_now()
    output["meihua_today"] = meihua

    return output


def print_diagnosis_report(report: dict):
    """打印诊断报告"""
    print()
    print("=" * 60)
    print("  📊 股票命理诊断报告")
    print("=" * 60)
    print(f"时间: {report['timestamp']}")
    print()

    # 股票信息
    si = report.get("stock_info", {})
    if "error" not in si:
        print(f"📈 {si.get('name', '未知')}({report['stock_code']})")
        print(f"   现价: {si.get('price', 0):.3f}  涨跌: {si.get('change_pct', 0):+.2f}%")
    print()

    # 股票五行
    sw = report.get("stock_wuxing", {})
    if sw.get("wuxing"):
        print(f"🪙 股票五行: {sw['wuxing']}（{sw.get('industry', '综合')}）")
        print(f"   判断方式: {sw.get('method', '')}")
    print()

    # 命理匹配
    fsm = report.get("fortune_stock_match", {})
    if fsm.get("verdict"):
        print(f"🔮 命格匹配: {fsm['verdict']}（{fsm.get('match_score', 0)}分）")
        print(f"   {fsm.get('analysis', '')}")
        print(f"   💡 建议: {fsm.get('suggestion', '')}")
        print()

    # 仓位调整
    la = report.get("luck_adjustment", {})
    if la.get("risk_level"):
        print(f"📊 风险敞口: {la['risk_level']}（仓位×{la.get('position_mult', 1.0):.1f}）")
        print(f"   {la.get('analysis', '')}")
        print(f"   💡 {la.get('suggestion', '')}")
        print()

    # 梅花卦象
    mh = report.get("meihua_today", {})
    if mh.get("output"):
        print(f"🌸 梅花易数今日卦象:")
        # 简化输出
        for line in mh["output"].split("\n")[:5]:
            if line.strip():
                print(f"   {line.strip()}")
    print()

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="股票命理集成系统")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # 诊断命令
    diag = subparsers.add_parser("diagnose", help="个股命理诊断")
    diag.add_argument("--stock", required=True, help="股票代码")
    diag.add_argument("--birth-date", help="出生日期 YYYY-MM-DD")
    diag.add_argument("--birth-time", default="00:00", help="出生时间 HH:MM")
    diag.add_argument("--gender", default="男", help="性别")

    # 时机分析
    timing = subparsers.add_parser("timing", help="大盘时机分析")
    timing.add_argument("--birth-date", required=True, help="出生日期 YYYY-MM-DD")
    timing.add_argument("--birth-time", default="00:00", help="出生时间 HH:MM")
    timing.add_argument("--gender", default="男", help="性别")

    # 仓位建议
    pos = subparsers.add_parser("position-size", help="仓位管理建议")
    pos.add_argument("--birth-date", required=True, help="出生日期 YYYY-MM-DD")
    pos.add_argument("--birth-time", default="00:00", help="出生时间 HH:MM")
    pos.add_argument("--gender", default="男", help="性别")
    pos.add_argument("--market", default="neutral", choices=["bullish", "bearish", "neutral"], help="市场状态")

    args = parser.parse_args()

    if args.command == "diagnose":
        report = diagnose_stock(args.stock, args.birth_date, args.birth_time, args.gender)
        print_diagnosis_report(report)
    elif args.command == "timing":
        fortune = run_fortune_analysis(args.birth_date, args.birth_time, args.gender)
        meihua = run_meihua_now()
        print("大盘时机分析:")
        print(f"流年运势: {fortune.get('命卦', {}).get('命格', '分析中')}")
        print(f"梅花卦象: {meihua.get('output', '分析中')[:200]}")
    elif args.command == "position-size":
        fortune = run_fortune_analysis(args.birth_date, args.birth_time, args.gender)
        adj = get_luck_adjustment(fortune)
        base = 50 if args.market == "bearish" else (80 if args.market == "bullish" else 60)
        final = int(base * adj.get("position_mult", 1.0))
        print(f"建议仓位: {final}%")
        print(f"风险等级: {adj.get('risk_level', '正常')}")
        print(f"分析: {adj.get('analysis', '')}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
