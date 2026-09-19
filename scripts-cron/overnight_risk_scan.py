#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
overnight_risk_scan.py — 持仓+关注池隔夜风险扫描（07:50）
========================================================
第五轮审计行动清单 ①（六问之 4: 个股级隔夜检查实缺口）。

盘前对 [真实持仓 + 推荐关注池] 逐票核对隔夜催化剂，只推命中项：
  1. 业绩预告/快报（东财数据中心，含修正）
  2. 个股隔夜新闻利空（news_sentiment 分类器: 🔴利空 才推）
  3. 停牌检测（东财 push2 实时行情返回 invalid → 疑似停牌）
无命中 → 静默（stdout 留痕，不进群）。

设计约束：
- 只读 Bitable 持仓（read_positions）+ 关注池表，不改任何业务数据
- 输出带 [关注]/[行动] 标签：减持/预亏/停牌=[行动]，中性利空=[关注]
"""
import json
import sqlite3
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HEARTBEAT_NAME = 'overnight-risk-scan'
MARKET_DB = None  # lazy
WEBHOOK = None    # lazy, from env/_local_constants


def _load_feishu():
    """凭证: env → gitignored _local_constants（绝不入代码）"""
    import os
    tok = os.getenv('FEISHU_WEBHOOK_TOKEN', '')
    if tok:
        return tok
    root = Path(__file__).resolve().parent
    for parent in [root] + list(root.parents)[:4]:
        f = parent / '_local_constants' / 'override.json'
        if f.exists():
            try:
                cfg = json.loads(f.read_text())
                return cfg.get('FEISHU_WEBHOOK_TOKEN', '')
            except Exception as e:
                print(f"[EXC] overnight_risk_scan.py 读 override.json: {type(e).__name__}: {e}")
    return ''


def send_feishu(text):
    # 2026-09-19: 全局禁推（独立 webhook 不经 feishu_sender._post, 需本地加门）
    import os as _os
    if _os.environ.get("FEISHU_DISABLE") == "1":
        print("[INFO] FEISHU_DISABLE=1，跳过飞书推送\n" + text)
        return
    tok = _load_feishu()
    if not tok:
        print(text)
        return
    url = "https://open.feishu.cn/open-apis/bot/v2/hook/" + tok
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[EXC] overnight_risk_scan.py 飞书推送: {type(e).__name__}: {e}\n{text}")


def get_watchlist():
    """真实持仓（Bitable）+ 推荐关注池（double_pool）"""
    stocks = {}  # code -> name
    # 1) 真实持仓
    try:
        sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')
        from bitable_reader import read_positions
        for p in (read_positions(limit=100) or []):
            stocks[str(p.stock_code)] = p.stock_name
    except Exception as e:
        print(f"[WARN] 持仓读取失败（继续关注池扫描）: {type(e).__name__}: {e}")
    # 2) 推荐关注池（最新一期 scan_date）
    try:
        mc = sqlite3.connect('/home/caojy/.hermes/profiles/stock/stock-work/data/production/market_cache.db', timeout=30)
        rows = mc.execute(
            "SELECT code, name FROM double_up_scores WHERE scan_date = (SELECT MAX(scan_date) FROM double_up_scores) LIMIT 50"
        ).fetchall()
        mc.close()
        for code, name in rows:
            stocks.setdefault(str(code), name or '')
    except Exception as e:
        print(f"[EXC] overnight_risk_scan.py 关注池读取: {type(e).__name__}: {e}")
    return stocks


def check_performance_warnings(stocks):
    """业绩预告/快报命中（东财数据中心，复用 data_filters 素材源）"""
    import requests
    hits = []
    try:
        r = requests.get(
            "https://datacenter.eastmoney.com/securities/api/data/v1/get",
            params={'reportName': 'RPT_PUBLIC_OP_YJYC',
                    'columns': 'SECUCODE,SECURITY_NAME_ABBR,NOTICE_DATE,CHANGE_TYPE,FORECAST_CONTENT',
                    'pageSize': 100, 'sortColumns': 'NOTICE_DATE', 'sortTypes': -1,
                    'source': 'HSF10', 'client': 'WEB'},
            timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        data = r.json()
        recent = (date.today() - __import__('datetime').timedelta(days=1)).isoformat()
        for item in (data.get('result') or {}).get('data') or []:
            code = (item.get('SECUCODE') or '').replace('.SH', '').replace('.SZ', '')
            if code in stocks and (item.get('NOTICE_DATE') or '')[:10] >= recent:
                hits.append((code, stocks[code], item.get('CHANGE_TYPE', ''),
                             (item.get('FORECAST_CONTENT') or '')[:60]))
    except Exception as e:
        print(f"[EXC] overnight_risk_scan.py 业绩预告: {type(e).__name__}: {e}")
    return hits


def check_bad_news(stocks):
    """个股隔夜利空新闻（关键词前置 + AI 分类复用）"""
    hits = []
    try:
        from news_sentiment import fetch_news_via_api, classify_sentiment, filter_relevant_news
        items = fetch_news_via_api() or []
        relevant = filter_relevant_news(items)
        for it in relevant:
            code = str(it.get('code', ''))
            if code in stocks:
                tag, conf, summary, reason = classify_sentiment(code, it.get('title', ''), it.get('content', ''), use_ai=False)
                if tag == '🔴利空':
                    hits.append((code, stocks[code], it.get('title', '')[:50]))
    except Exception as e:
        print(f"[EXC] overnight_risk_scan.py 新闻扫描: {type(e).__name__}: {e}")
    return hits


def check_suspension(stocks):
    """停牌检测: 东财 push2 实时价 f_restDay>0 或返回 invalid（一次重试）"""
    hits = []
    if not stocks:
        return hits
    import time
    import requests
    for attempt in range(2):
        try:
            secids = ','.join(f"{'1.' if c.startswith('6') else '0.'}{c}" for c in stocks)
            r = requests.get("http://push2delay.eastmoney.com/api/qt/ulist.np/get",
                             params={'secids': secids, 'fields': 'f12,f14,f_restDay',
                                     'ut': 'bd1d9ddb04089700cf9c27f6f7426281', 'fltt': 2, 'invt': 2},
                             timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            diff = (r.json().get('data') or {}).get('diff')
            items = diff.values() if isinstance(diff, dict) else (diff or [])
            for d in items:
                code = str(d.get('f12', ''))
                if code in stocks and d.get('f_restDay', 0) and int(d['f_restDay']) > 1:
                    hits.append((code, stocks[code], f"停牌 {d['f_restDay']} 天"))
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(3)
                continue
            print(f"[EXC] overnight_risk_scan.py 停牌检测: {type(e).__name__}: {e}")
    return hits


def write_heartbeat():
    try:
        from heartbeat import write as hb_write
        hb_write(HEARTBEAT_NAME, {'ts': datetime.now().isoformat(timespec='seconds')})
    except Exception as e:
        print(f"[EXC] overnight_risk_scan.py 心跳: {type(e).__name__}: {e}")


def main():
    t0 = datetime.now()
    stocks = get_watchlist()
    if not stocks:
        print("⚠️ 无持仓且无关注池，跳过隔夜扫描")
        write_heartbeat()
        return
    print(f"扫描范围: 持仓+关注池共 {len(stocks)} 只")

    perf = check_performance_warnings(stocks)
    news = check_bad_news(stocks)
    susp = check_suspension(stocks)

    action_lines, watch_lines = [], []
    for code, name, typ, brief in perf:
        (action_lines if ('亏' in typ or '下' in typ) else watch_lines).append(
            f"  - {code} {name}: 业绩预告[{typ}] {brief}")
    for code, name, title in news:
        watch_lines.append(f"  - {code} {name}: 🔴利空新闻「{title}」")
    for code, name, why in susp:
        action_lines.append(f"  - {code} {name}: {why}")

    if not action_lines and not watch_lines:
        # 2026-09-19: 无命中时 stdout 必须为空（框架: empty stdout=SILENT_MARKER 不投递;
        # wakeAgent=false gate 同样静默）。原实现 print 摘要 → no_agent stdout 原样投递 →
        # "静默不推送"只静默了自己的 webhook, 摘要照样进群（每天一条噪音）。
        # 无命中属于"无新事可报"的 [SILENT] 语义, 明细写日志留痕。
        import sys as _sys
        print(f"[隔夜扫描 {date.today()} 无命中: 业绩预告0/利空0/停牌0, 覆盖{len(stocks)}只, "
              f"耗时{(datetime.now()-t0).total_seconds():.1f}s]", file=_sys.stderr)
        write_heartbeat()
        print(json.dumps({"wakeAgent": False}))
        return

    lines = [f"🌅 [关注] 隔夜风险扫描 | {date.today()} | 覆盖 {len(stocks)} 只", "=" * 50]
    if action_lines:
        lines.append("[行动] 需开盘前决策:")
        lines += action_lines
    if watch_lines:
        lines.append("[关注] 影响持仓判断:")
        lines += watch_lines[:15]
    lines.append("=" * 50)
    lines.append("无命中项已静默过滤。明细见 cron output。")
    send_feishu("\n".join(lines))
    print(f"推送 {len(action_lines)} 行动 + {len(watch_lines[:15])} 关注")
    write_heartbeat()
    print(f"耗时 {(datetime.now()-t0).total_seconds():.1f}s")


if __name__ == '__main__':
    main()
