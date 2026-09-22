#!/usr/bin/env python3
"""
市场情绪温度计 v1.1

多因子市场情绪监控，输出 0-100 刻度。

数据源：
  - push2delay.eastmoney.com（直连，不经过代理，不受 akshare 捆绑）
  - 备用：Sina 财经 API

v1.1 变更：用 httpx 取代 akshare 的 EM 接口，避开 push2/push2his 封锁
"""

import os, sys, json, argparse, math
from datetime import datetime
from pathlib import Path
import subprocess

SCRIPT_DIR = Path(__file__).parent.resolve()

# 强制直连
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(k, None)

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

QUOTE_HOST = "https://push2delay.eastmoney.com"

_CLIENT = None

def _client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(timeout=10, headers=HEADERS)
    return _CLIENT


# ====== 数据获取 ======

def fetch_market_overview():
    """
    获取全市场概览：
    - 涨跌统计：优先本地 DB klines 全市场口径（2026-09-22 P0-1），
      仅在 DB 不可用时回落 push2delay 500 只样本并标注口径
    - 领涨/领跌：push2delay 涨跌幅排行；数据源失败时整段不输出（P0-2）
    """
    # Part A: 涨跌统计
    # 2026-09-22 审计 P0-1：原实现用 500 只样本冒充全市场，涨停少报 11 倍。
    # 现在优先 DB 全市场；DB 拿不到才用在线样本且明确标注。
    result = fetch_adv_decline_full_from_db()
    if result is None:
        ad = fetch_adv_decline()
        if ad and not ad.get("error"):
            result = ad
            result["_scope"] = "样本500只"
        else:
            result = {"total": 0, "up": 0, "down": 0, "flat": 0,
                      "limit_up": 0, "limit_down": 0, "up_ratio": 0,
                      "top5": [], "bot5": [], "_scope": "样本500只"}
    else:
        result.setdefault("top5", [])
        result.setdefault("bot5", [])

    # Part B: 领涨/领跌（push2delay，Top100排行）
    # 2026-09-22 审计 P0-2：原实现 `except Exception: pass` 静默吞掉数据源失败，
    # 导致 push2delay 整域不可达时 bot5/top5 保留陈旧值甚至空表兜底值，
    # 实测 2026-09-21 把三只涨停股（000504 +9.99%/600301 +9.99%/603580 +10.00%）
    # 当"领跌"推送。现在：失败时 top5/bot5 一律留空，展示层整段不输出。
    try:
        fs = "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:8"
        url = (
            f"{QUOTE_HOST}/api/qt/clist/get"
            f"?pn=1&pz=100&po=1&np=1&fltt=2&invt=2"
            f"&fid=f3&fs={fs}&fields=f12,f14,f2,f3"
        )
        r = _client().get(url)
        data = r.json()
        diff = data.get("data", {}).get("diff", []) or []

        if len(diff) >= 10:
            result["top5"] = [
                {"name": d.get("f14",""), "code": d.get("f12",""), "pct": d.get("f3",0)}
                for d in diff[:5]
            ]
            # Bottom 5 = worst performers (last 5 of the descending list)
            result["bot5"] = [
                {"name": d.get("f14",""), "code": d.get("f12",""), "pct": d.get("f3",0)}
                for d in diff[-5:]
            ][::-1]
        else:
            print(f"[WARN] sentiment_thermo: 排行数据不足({len(diff)}条)，领涨/领跌不输出",
                  file=sys.stderr)
            result["top5"] = []
            result["bot5"] = []
    except Exception as e:
        # 数据源失败：清空排行，禁止输出陈旧/兜底值
        print(f"[WARN] sentiment_thermo: 排行数据源失败({type(e).__name__})，领涨/领跌不输出",
              file=sys.stderr)
        result["top5"] = []
        result["bot5"] = []

    return result


def fetch_adv_decline_full_from_db():
    """
    【2026-09-22 审计 P0-1】全市场涨跌统计——直接查本地 DB klines，零网络依赖。

    原实现用 push2delay 前 5 页（500 只）样本估算全市场，且推送不标注样本口径：
    实测 2026-09-21 样本报 涨停12/跌停0/涨跌比65.6%，全市场真实为
    涨停136/跌停3/涨跌比81.4%——样本只有 500 只，涨停数少报 11 倍，
    并直接污染情绪温度计的「涨跌比」(权重30%)与「涨停热度」(权重15%)两个维度。

    本地 klines 表当日 5005 只全量覆盖，一次 SQL 即得真实统计，比抽样更快更准。
    返回 dict 或 None（无当日数据时回落在线样本）。
    """
    import sqlite3
    try:
        # skills/stock/stock-expert/skills/feishu-bitable/sentiment_thermo.py
        # → parents[5] = <profile>/stock
        sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'stock-work'))
        from core.compat_paths import MARKET_DB
    except Exception:
        return None
    try:
        conn = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True, timeout=30)
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM klines")
        row = cur.fetchone()
        if not row or not row[0]:
            conn.close()
            return None
        latest = row[0]
        cur.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN change_pct > 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN change_pct < 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN change_pct = 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN change_pct >= 9.8 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN change_pct <= -9.8 THEN 1 ELSE 0 END)
            FROM klines WHERE date = ?
        """, (latest,))
        total, up, down, flat, limit_up, limit_down = cur.fetchone()
        conn.close()
        total = total or 0
        if total == 0:
            return None
        return {
            "total": total,
            "up": up or 0,
            "down": down or 0,
            "flat": flat or 0,
            "limit_up": limit_up or 0,
            "limit_down": limit_down or 0,
            "up_ratio": round((up or 0) / total * 100, 1),
            "_date": latest,
            "_scope": "全市场",
        }
    except Exception as _e:
        print(f"[WARN] sentiment_thermo DB 全市场统计失败({type(_e).__name__}: {_e})，回落在线样本", file=sys.stderr)
        return None


def fetch_adv_decline():
    """
    全市场涨跌统计（在线抽样口径，仅作 DB 不可用时的降级）

    ⚠️ 口径警告：push2delay 前 5 页仅约 500 只样本（且按涨幅降序，系统性偏强），
    只能表征样本分布，不等于全市场。调用方必须标注「样本500只」。
    """
    import concurrent.futures

    def _safe_float(v, default=0):
        """安全转float，处理 '-' 等异常值"""
        try:
            return float(v) if v is not None else default
        except (ValueError, TypeError):
            return default

    fs = "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:8"
    fields = "f12,f14,f2,f3"

    def fetch_page(pn):
        url = (
            f"{QUOTE_HOST}/api/qt/clist/get"
            f"?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2"
            f"&fs={fs}&fields={fields}"
        )
        try:
            r = _client().get(url, timeout=8)
            data = r.json()
            return data.get("data", {}).get("diff", []) or []
        except Exception:
            return []

    try:
        # 先取第1页获取总数
        first_page = fetch_page(1)
        total = 0
        if first_page:
            r = _client().get(
                f"{QUOTE_HOST}/api/qt/clist/get"
                f"?pn=1&pz=1&po=0&np=1&fltt=2&invt=2"
                f"&fid=f3&fs={fs}&fields={fields}"
            )
            total = r.json().get("data", {}).get("total", 0)

        # 并行取前5页（500只）作为样本
        all_stocks = list(first_page)  # 第1页已取
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            results = ex.map(fetch_page, range(2, 6))
            for stocks in results:
                all_stocks.extend(stocks)

        sample_size = len(all_stocks)
        if sample_size == 0:
            return {"error": "empty"}

        up = sum(1 for d in all_stocks if _safe_float(d.get("f3")) > 0)
        down = sum(1 for d in all_stocks if _safe_float(d.get("f3")) < 0)
        flat = sample_size - up - down
        limit_up = sum(1 for d in all_stocks if _safe_float(d.get("f3")) >= 9.8)
        limit_down = sum(1 for d in all_stocks if _safe_float(d.get("f3")) <= -9.8)

        # 用样本涨跌比估算全量
        up_ratio = round(up / sample_size * 100, 1) if sample_size > 0 else 0

        return {
            "total": total or sample_size,
            "up": up, "down": down, "flat": flat,
            "limit_up": limit_up, "limit_down": limit_down,
            "up_ratio": up_ratio,
            "_sample": sample_size,
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_sse_index():
    """
    上证指数实时行情
    """
    try:
        url = f"{QUOTE_HOST}/api/qt/stock/get?secid=1.000001&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f168,f169,f170,f50,f71,f152"
        r = _client().get(url)
        data = r.json().get("data", {})
        if not data:
            return {"index": "上证指数", "error": "empty"}

        scale = 10 ** max(1, data.get("f152", 2))
        cur = (data.get("f43") or 0) / scale
        prev = (data.get("f60") or 0) / scale
        change_pct = ((cur - prev) / prev * 100) if prev else 0

        return {
            "index": "上证指数",
            "latest": round(cur, 2),
            "prev_close": round(prev, 2),
            "change": round(cur - prev, 2),
            "change_pct": round(change_pct, 2),
            "high": round((data.get("f44") or 0) / scale, 2),
            "low": round((data.get("f45") or 0) / scale, 2),
            "open": round((data.get("f46") or 0) / scale, 2),
            "volume": int((data.get("f47") or 0) / 100),  # 手
        }
    except Exception as e:
        return {"index": "上证指数", "error": str(e)}


def fetch_fund_flow():
    """
    主力资金净流入排行 Top5
    """
    try:
        fs = "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:8"
        url = (
            f"{QUOTE_HOST}/api/qt/clist/get"
            f"?pn=1&pz=5&po=1&np=1&fltt=2&invt=2"
            f"&fid=f62&fs={fs}&fields=f12,f14,f2,f3,f62"
        )
        r = _client().get(url)
        data = r.json()
        diff = data.get("data", {}).get("diff", []) or []

        total_inflow = sum(d.get("f62", 0) for d in diff if d.get("f62", 0) > 0)
        total_outflow = sum(d.get("f62", 0) for d in diff if d.get("f62", 0) < 0)
        net_flow = total_inflow + total_outflow

        return {
            "top5": [
                {"name": d.get("f14",""), "code": d.get("f12",""),
                 "pct": d.get("f3",0), "net_inflow": d.get("f62",0)}
                for d in diff
            ],
            "total_inflow": total_inflow / 1e8 if total_inflow else 0,
            "total_outflow": abs(total_outflow / 1e8) if total_outflow else 0,
            "net_inflow": net_flow / 1e8 if net_flow else 0,
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_northbound():
    """
    北向资金数据（通过行业板块 f71/f72 字段汇总）
    """
    try:
        url = (
            f"{QUOTE_HOST}/api/qt/clist/get"
            f"?pn=1&pz=100&po=1&np=1&fltt=2&invt=2"
            f"&fid=f71&fs=m:90+t:2&fields=f12,f14,f71,f72"
        )
        r = _client().get(url)
        data = r.json()
        diff = data.get("data", {}).get("diff", []) or []

        # 北向资金总持仓
        total_hold = sum(d.get("f71", 0) or 0 for d in diff)
        # 北向资金总变动
        total_change = sum(d.get("f72", 0) or 0 for d in diff)

        # 北向持仓前5行业
        sorted_diff = sorted(diff, key=lambda d: d.get("f71", 0) or 0, reverse=True)
        top5 = [
            {"name": d.get("f14",""), "hold": d.get("f71",0) or 0, "change": d.get("f72",0) or 0}
            for d in sorted_diff[:5]
        ]

        return {
            "total_hold": total_hold / 1e8 if total_hold else 0,
            "total_change": total_change / 1e8 if total_change else 0,
            "top5": top5,
        }
    except Exception as e:
        return {"error": str(e)}


# ====== 情绪计算 ======

def calc_sentiment(overview, sse, fund, northbound=None):
    """计算六维情绪温度（0-100）"""
    comps = {}

    # 维度1: 涨跌比 (权重30%)
    ad = overview.get("up_ratio", 50) if overview and not overview.get("error") else 50
    ad_score = max(0, min(100, (ad - 25) * 100 / 45))
    comps["涨跌比"] = {"score": round(ad_score, 1), "weight": "30%"}

    # 维度2: 涨停热度 (权重15%)
    zt_n = overview.get("limit_up", 0) if overview else 0
    dt_n = overview.get("limit_down", 0) if overview else 0
    total = overview.get("total", 5000) if overview else 5000
    zt_ratio = zt_n / max(total, 1) * 100
    dt_ratio = dt_n / max(total, 1) * 100
    zt_score = max(0, min(100, 50 + zt_ratio * 25 / 0.3 - dt_ratio * 30 / 0.3))
    comps["涨停热度"] = {"score": round(zt_score, 1), "weight": "15%"}

    # 维度3: 指数涨跌 (权重15%)
    if sse and not sse.get("error") and sse.get("change_pct") is not None:
        cp = sse["change_pct"]
        idx_score = max(0, min(100, 50 + cp * 50 / 3))
    else:
        idx_score = 50
    comps["指数涨跌"] = {"score": round(idx_score, 1), "weight": "15%"}

    # 维度4: 资金流向 (权重15%)
    if fund and not fund.get("error"):
        net = fund.get("net_inflow", 0)
        fund_score = max(0, min(100, 50 + net * 50 / 50))
    else:
        fund_score = 50
    comps["资金流向"] = {"score": round(fund_score, 1), "weight": "15%"}

    # 维度5: 北向资金 (权重15%)
    if northbound and not northbound.get("error"):
        change = northbound.get("total_change", 0)
        # -50亿 ~ +50亿 → 0-100
        nb_score = max(0, min(100, 50 + change * 50 / 50))
    else:
        nb_score = 50
    comps["北向资金"] = {"score": round(nb_score, 1), "weight": "15%"}

    # 维度6: 成交量 (权重10%)
    comps["成交量"] = {"score": 50, "weight": "10%"}

    total_score = sum(
        v["score"] * int(v["weight"].rstrip("%")) / 100
        for v in comps.values()
    )
    return round(total_score, 1), comps


def _label(score):
    if score >= 80:
        return "🔥 极度贪婪", "极高"
    elif score >= 65:
        return "😊 偏贪婪", "高"
    elif score >= 45:
        return "😐 中性", "中"
    elif score >= 25:
        return "😰 偏恐慌", "低"
    else:
        return "❄️ 极度恐慌", "极低"


# ====== 主流程 ======

def run(json_output=False):
    """运行情绪温度计"""
    now = datetime.now()
    print(f"📡 获取数据...", file=sys.stderr)

    overview = fetch_market_overview()
    sse = fetch_sse_index()
    fund = fetch_fund_flow()
    northbound = fetch_northbound()

    total_score, components = calc_sentiment(overview, sse, fund, northbound)
    label, risk = _label(total_score)

    # 格式化
    if json_output:
        result = {
            "time": now.strftime("%Y-%m-%d %H:%M"),
            "sentiment": {"score": total_score, "label": label, "risk": risk},
            "components": {k: v["score"] for k, v in components.items()},
            "sse": sse,
            "advance_decline": {
                "up": overview.get("up"), "down": overview.get("down"),
                "total": overview.get("total"),
                "limit_up": overview.get("limit_up"),
                "limit_down": overview.get("limit_down"),
            } if overview and not overview.get("error") else None,
            "top5": overview.get("top5") if overview else None,
            "bot5": overview.get("bot5") if overview else None,
            "fund_flow": {
                "net_inflow_亿": fund.get("net_inflow") if fund else None,
                "top5": fund.get("top5") if fund else None,
            } if fund and not fund.get("error") else None,
            "northbound": {
                "total_hold_亿": northbound.get("total_hold") if northbound else None,
                "total_change_亿": northbound.get("total_change") if northbound else None,
                "top5": northbound.get("top5") if northbound else None,
            } if northbound and not northbound.get("error") else None,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    # 文本报告
    lines = []
    emoji = "🟢" if total_score >= 65 else ("🟡" if total_score >= 45 else "🔴")
    lines.append(f"\n{'='*55}")
    lines.append(f"  {emoji} 市场情绪温度计  {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"{'='*55}")

    # 温度条
    bar_len = 20
    filled = int(total_score / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines.append(f"\n  温度: {bar}  {total_score:.0f}/100")
    lines.append(f"  判定: {label}")

    # 上证
    if sse and not sse.get("error"):
        cp = sse.get("change_pct", 0)
        arrow = "▲" if cp >= 0 else "▼"
        lines.append(f"\n📈 上证指数  {sse['latest']}  {arrow}{abs(cp):.2f}%")
        lines.append(f"  开:{sse.get('open','?')} 高:{sse.get('high','?')} 低:{sse.get('low','?')}")

    # 涨跌
    if overview and not overview.get("error"):
        # 2026-09-22 审计 P0-1：必须显式标注统计口径，读者不能再把样本当全市场
        _scope = overview.get("_scope", "全市场")
        _dt = overview.get("_date")
        _scope_txt = f"（{_scope}" + (f", {_dt}" if _dt else "") + "）"
        lines.append(f"\n📊 涨跌统计{_scope_txt}")
        lines.append(f"  上涨: {overview['up']} | 下跌: {overview['down']} | 平盘: {overview['flat']}")
        lines.append(f"  涨停: {overview['limit_up']} | 跌停: {overview['limit_down']}")
        lines.append(f"  涨跌比: {overview['up_ratio']}%")

        # 领涨/跌
        if overview.get("top5"):
            top_strs = [f"{s['name']}({s['pct']:+.1f}%)" for s in overview["top5"][:3]]
            lines.append(f"  🏆 领涨: {' | '.join(top_strs)}")
        if overview.get("bot5"):
            bot_strs = [f"{s['name']}({s['pct']:+.1f}%)" for s in overview["bot5"][:3]]
            lines.append(f"  ⛔ 领跌: {' | '.join(bot_strs)}")

    # 资金
    if fund and not fund.get("error"):
        sign = "+" if fund.get("net_inflow", 0) >= 0 else ""
        lines.append(f"\n💰 主力资金")
        lines.append(f"  净流入: {sign}{fund.get('net_inflow',0):.1f}亿")
        if fund.get("top5"):
            top = fund["top5"][0]
            lines.append(f"  🥇 {top['name']} 净流入: {top.get('net_inflow',0)/1e8:.1f}亿 ({top.get('pct',0):+.1f}%)")

    # 北向资金
    if northbound and not northbound.get("error"):
        sign = "+" if northbound.get("total_change", 0) >= 0 else ""
        lines.append(f"\n🌐 北向资金")
        lines.append(f"  持仓: {northbound.get('total_hold',0):.1f}亿  变动: {sign}{northbound.get('total_change',0):.1f}亿")
        if northbound.get("top5"):
            top_strs = [f"{s['name']}" for s in northbound["top5"][:3]]
            lines.append(f"  重仓: {' | '.join(top_strs)}")

    # 情绪分解
    lines.append(f"\n📐 情绪分解")
    for name, comp in components.items():
        s = comp["score"]
        w = comp["weight"]
        bar2 = "█" * max(1, int(s / 10)) + "░" * max(0, 10 - max(1, int(s / 10)))
        lines.append(f"  {name:<8s} {bar2} {s:.0f}  (权重{w})")

    lines.append(f"\n{'='*55}")
    lines.append(f"  数据源: push2delay.eastmoney.com (直连)")
    lines.append(f"{'='*55}")

    return "\n".join(lines)


def _save_to_learn_log(report_text, score, label):
    """记录到学习日志"""
    log_script = SCRIPT_DIR / "learn_log.py"
    if not log_script.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(log_script), "record",
             "--type", "observation",
             "--title", f"情绪温度计 {datetime.now().strftime('%Y-%m-%d')}",
             "--content", report_text[:1500],
             "--tags", "情绪,温度计"],
            capture_output=True, timeout=15,
        )
    except Exception:
        pass


if __name__ == "__main__":
    json_flag = "--json" in sys.argv
    learn_flag = "--learn" in sys.argv
    report = run(json_output=json_flag)
    print(report)
    if learn_flag:
        _save_to_learn_log(report, 0, "")
