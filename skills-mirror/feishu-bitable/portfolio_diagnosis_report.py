#!/usr/bin/env python3
"""
持仓深度综合诊断脚本
- 读取飞书Bitable持仓
- 拉取技术信号/止损止盈/仓位
- 合并股东/筹码/两融/财务/资金流
- 输出 Markdown 报告并推送飞书
"""
import sys, os, json, sqlite3, math
from pathlib import Path
from datetime import datetime, date

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from bitable_reader import BitableReader, PositionRecord
from trade_manager import calc_stop_loss, calc_take_profit, calc_position_size, get_kline
from signal_engine import SignalEngine
from feishu_sender import send_text_message

MARKET_DB = Path("/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db")
FEISHU_CHAT_ID = "oc_6825e1438c41d1b7251b1698ea3be4fe"

# -------------------- 数据查询 --------------------

def get_latest_indicator(code):
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM indicators WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}

def get_latest_financial(code):
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM financial_data WHERE code=? ORDER BY report_date DESC LIMIT 1", (code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}

def get_chip(code):
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM chip_data WHERE code=? ORDER BY trade_date DESC LIMIT 1", (code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}

def get_margin(code):
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM margin_data WHERE code=? ORDER BY trade_date DESC LIMIT 1", (code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}

def get_holder_change(code):
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM holder_change WHERE code=? ORDER BY change_date DESC LIMIT 1", (code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}

def get_main_fund_flow(code):
    conn = sqlite3.connect(MARKET_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM main_fund_flow WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}

# -------------------- 诊断逻辑 --------------------

def classify_risk(signal_level, change_pct, rsi):
    if signal_level >= 4 or (rsi is not None and rsi > 80) or (change_pct is not None and change_pct > 9):
        return "HIGH"
    if signal_level >= 3 or (rsi is not None and (rsi > 70 or rsi < 25)) or (change_pct is not None and abs(change_pct) > 5):
        return "MID"
    return "LOW"

def fmt_num(v, n=2):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.{n}f}"
    except:
        return str(v)

def diagnose_position(pos):
    code = pos.stock_code
    name = pos.stock_name or code
    qty = pos.quantity
    cost = pos.cost_price
    cur = pos.current_price

    # 成本异常判定
    cost_normal = False
    cost_abnormal_reason = ""
    if cost is None or cost <= 0 or cost >= 1000:
        cost_normal = False
        cost_abnormal_reason = "成本≤0或≥1000"
    else:
        # 再判断是否明显偏离现价（超过±50%视为异常）
        if cur and cur > 0:
            deviation = abs(cost - cur) / cur
            if deviation > 0.5:
                cost_normal = False
                cost_abnormal_reason = f"偏离现价{deviation*100:.0f}%"
            else:
                cost_normal = True
        else:
            cost_normal = True  # 无现价时不阻塞

    # 盈亏
    if cost_normal and cur and cur > 0 and qty:
        pnl_pct = (cur - cost) / cost * 100
        pnl_amt = (cur - cost) * qty
        pnl_str = f"{fmt_num(pnl_pct)}%"
    else:
        pnl_pct = None
        pnl_amt = None
        pnl_str = "成本异常" if not cost_normal else "N/A"

    # 技术指标
    ind = get_latest_indicator(code)
    rsi = ind.get("rsi_14")
    macd_hist = ind.get("macd_hist")
    boll_pos = ind.get("boll_position")
    ma5 = ind.get("ma5")
    ma10 = ind.get("ma10")
    ma20 = ind.get("ma20")
    ma60 = ind.get("ma60")
    signal_score = ind.get("signal_score")
    signal_level = ind.get("signal_level", 0) or 0
    turnover = ind.get("turnover_rate")
    vol_ratio = ind.get("vol_ratio")
    change_pct = ind.get("change_pct")
    current_price_db = ind.get("current_price")

    # 使用现价优先
    price_for_stop = cur if (cur and cur > 0) else (current_price_db if current_price_db else (cost if cost_normal else 0))

    # 买卖信号 + 止损止盈 + 仓位
    try:
        sig_res = SignalEngine().analyze_single(code)
        advice = sig_res.advice if hasattr(sig_res, 'advice') else None
        advice_signal_level = advice.signal_level if advice else signal_level
        advice_action = advice.action if advice else "持有"
        advice_reasons = advice.reasons if advice else []
    except Exception as e:
        advice_signal_level = signal_level
        advice_action = "持有"
        advice_reasons = [f"信号计算异常:{e}"]

    try:
        sl = calc_stop_loss(code, price_for_stop if price_for_stop > 0 else cost if cost_normal else 0, method="atr")
        sl_price = sl.get("stop_loss")
        sl_pct = sl.get("stop_pct")
    except Exception:
        sl_price = None
        sl_pct = None

    try:
        tp = calc_take_profit(code, price_for_stop if price_for_stop > 0 else cost if cost_normal else 0, method="atr")
        tp1 = tp.get("take_profit_1")
        tp2 = tp.get("take_profit_2")
    except Exception:
        tp1 = None
        tp2 = None

    try:
        pos_size = calc_position_size(price_for_stop if price_for_stop > 0 else cost if cost_normal else 1, 1000000, method="kelly")
        suggested_shares = pos_size.get("shares")
        suggested_cap_pct = pos_size.get("capital_pct")
    except Exception:
        suggested_shares = None
        suggested_cap_pct = None

    # 基本面
    fin = get_latest_financial(code)
    roe = fin.get("roe")
    debt_ratio = fin.get("debt_ratio")
    revenue_growth = fin.get("revenue_growth")
    profit_growth = fin.get("profit_growth")
    pe = fin.get("pe_ratio")
    pb = fin.get("pb_ratio")
    net_margin = fin.get("net_margin")
    gross_margin = fin.get("gross_margin")

    # 股东/筹码/两融
    chip = get_chip(code)
    margin = get_margin(code)
    holder = get_holder_change(code)
    fund_flow = get_main_fund_flow(code)

    # 龙虎榜/资金流向
    fund_net = fund_flow.get("net_amt") if fund_flow else None
    fund_date = fund_flow.get("date") if fund_flow else None

    # 风险等级
    risk = classify_risk(advice_signal_level or signal_level or 0, change_pct or 0, rsi)

    return {
        "code": code,
        "name": name,
        "qty": qty,
        "cost": cost,
        "cost_normal": cost_normal,
        "cost_abnormal_reason": cost_abnormal_reason,
        "cur": cur or current_price_db,
        "pnl_pct": pnl_pct,
        "pnl_amt": pnl_amt,
        "pnl_str": pnl_str,
        "rsi": rsi,
        "macd_hist": macd_hist,
        "boll_pos": boll_pos,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "signal_score": signal_score,
        "signal_level": advice_signal_level or signal_level or 0,
        "change_pct": change_pct,
        "turnover": turnover,
        "vol_ratio": vol_ratio,
        "sl_price": sl_price,
        "sl_pct": sl_pct,
        "tp1": tp1,
        "tp2": tp2,
        "suggested_shares": suggested_shares,
        "suggested_cap_pct": suggested_cap_pct,
        "roe": roe,
        "debt_ratio": debt_ratio,
        "revenue_growth": revenue_growth,
        "profit_growth": profit_growth,
        "pe": pe,
        "pb": pb,
        "net_margin": net_margin,
        "gross_margin": gross_margin,
        "chip_profit_rate": chip.get("chip_profit_rate") if chip else None,
        "chip_avg_cost": chip.get("chip_avg_cost") if chip else None,
        "chip_conc90": chip.get("chip_conc90") if chip else None,
        "margin_finance": margin.get("finance_value") if margin else None,
        "margin_security": margin.get("security_value") if margin else None,
        "holder_change_type": holder.get("change_type") if holder else None,
        "holder_change_shares": holder.get("change_shares") if holder else None,
        "fund_net": fund_net,
        "fund_date": fund_date,
        "risk": risk,
        "advice_action": advice_action,
        "advice_reasons": "; ".join(advice_reasons[:3]) if advice_reasons else "",
    }

# -------------------- 报告生成 --------------------

def build_markdown(positions_data):
    lines = []
    lines.append("📋 【持仓深度综合诊断】")
    lines.append(f"⏰ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 表头
    header = "| 代码 | 名称 | 现价 | 涨跌幅 | 信号 | 评分 | 止损价 | 止盈价 | 建议仓位 | 核心指标 | 风险 |"
    sep = "|------|------|------|--------|------|------|--------|--------|----------|----------|------|"
    lines.append(header)
    lines.append(sep)

    high_risk = []
    mid_risk = []
    low_risk = []
    abnormal_cost = []

    for p in positions_data:
        core_parts = []
        core_parts.append(f"RSI:{fmt_num(p['rsi'],0)}")
        if p['macd_hist'] is not None:
            core_parts.append(f"MACD:{fmt_num(p['macd_hist'],2)}")
        if p['boll_pos'] is not None:
            core_parts.append(f"布林:{fmt_num(p['boll_pos'],0)}%")
        if p['roe'] is not None:
            core_parts.append(f"ROE:{fmt_num(p['roe'],1)}%")
        if p['chip_profit_rate'] is not None:
            core_parts.append(f"获利盘:{fmt_num(p['chip_profit_rate'],0)}%")
        if p['margin_finance'] is not None:
            core_parts.append(f"两融:{fmt_num(float(p['margin_finance'])/1e8,1)}亿")
        if p['holder_change_type']:
            core_parts.append(f"股东:{p['holder_change_type']}")
        if p['fund_net'] is not None:
            core_parts.append(f"资金:{fmt_num(float(p['fund_net'])/1e4,0)}万")
        core = " ".join(core_parts) if core_parts else "N/A"

        signal_emoji = {0:"📌",1:"📌",2:"📌",3:"🔔",4:"🚨",5:"⛔"}.get(int(p['signal_level'] or 0), "📌")
        risk_emoji = {"HIGH":"🔴","MID":"🟡","LOW":"🟢"}.get(p['risk'], "⚪")

        # 建议仓位
        if p['suggested_shares']:
            pos_str = f"{p['suggested_shares']}股({fmt_num(p['suggested_cap_pct'])}%)"
        else:
            pos_str = "N/A"

        row = f"| {p['code']} | {p['name']} | {fmt_num(p['cur'])} | {fmt_num(p['change_pct'],2)}% | {signal_emoji}{p['signal_level']} | {fmt_num(p['signal_score'],0)} | {fmt_num(p['sl_price'])} | {fmt_num(p['tp1'])} | {pos_str} | {core} | {risk_emoji}{p['risk']} |"
        lines.append(row)

        if p['risk'] == "HIGH":
            high_risk.append(f"{p['name']}({p['code']})")
        elif p['risk'] == "MID":
            mid_risk.append(f"{p['name']}({p['code']})")
        else:
            low_risk.append(f"{p['name']}({p['code']})")

        if not p['cost_normal']:
            abnormal_cost.append(f"{p['name']}({p['code']}) {p['cost_abnormal_reason']}")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 组合总览
    lines.append("📊 【组合总览】")
    lines.append(f"持仓数量：{len(positions_data)}")
    if high_risk:
        lines.append(f"🔴 风险等级 HIGH（减仓条件触发候选，建议进入 Decision Review）：{', '.join(high_risk)}")
    if mid_risk:
        lines.append(f"🟡 风险等级 MID（关注区间）：{', '.join(mid_risk)}")
    if low_risk:
        lines.append(f"🟢 风险等级 LOW：{', '.join(low_risk)}")
    if abnormal_cost:
        lines.append(f"⚠️ 成本异常个股（需按平安证券实盘核正）：{'; '.join(abnormal_cost)}")

    lines.append("")
    lines.append("【重要 · 展示层规则】")
    lines.append("本报告为 INFORMATION 层分析参考，不是 Final Decision。")
    lines.append("所有 Action 只能由 Daily Decision Report（FINAL）或止损推送（URGENT）给出。")

    return "\n".join(lines)

# -------------------- 主流程 --------------------

def main():
    # 1. 读取持仓
    reader = BitableReader(limit=200)
    raw_records = reader._fetch_records()
    records = []
    for item in raw_records.get("data", {}).get("items", []):
        try:
            rec = reader._parse_fields(item.get("fields", {}))
            if rec.get("stock_code"):
                records.append(PositionRecord(**rec))
        except Exception:
            continue

    if not records:
        msg = "⚠️ 未读取到持仓数据，请检查Bitable连接"
        send_text_message(msg, FEISHU_CHAT_ID)
        print(msg)
        return

    # 2. 诊断
    diag_results = []
    for pos in records:
        try:
            d = diagnose_position(pos)
            diag_results.append(d)
        except Exception as e:
            print(f"诊断 {pos.stock_code} 异常: {e}")

    # 3. 生成报告
    md = build_markdown(diag_results)
    print(md)

    # 4. 推送飞书
    try:
        res = send_text_message(md, FEISHU_CHAT_ID)
        print("PUSH_OK" if res.get("code") == 0 else f"PUSH_FAIL:{res}")
    except Exception as e:
        print(f"推送失败: {e}")

if __name__ == "__main__":
    main()
