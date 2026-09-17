#!/usr/bin/env python3
"""
系统化学习记录 v1.0

自动归档每次分析/交易/观察为可回溯的学习日志。

用法:
  python3 learn_log.py record --type pipeline --title '全流程引擎' --content '...'
  python3 learn_log.py record --type trade --code 600519 --title '茅台观察' --content '...'
  python3 learn_log.py list                                    # 最近20条
  python3 learn_log.py search --code 600519                    # 搜索某只股票
  python3 learn_log.py search --tag 白酒                       # 按标签搜索
  python3 learn_log.py summary --days 7                       # 本周学习总结
  python3 learn_log.py push --id 5                            # 将第5条推送到IMA知识库
  python3 learn_log.py record-from-pipeline                   # 自动记录最后一次pipeline结果
"""

import os, sys, json, argparse, subprocess
from pathlib import Path
from datetime import datetime, timedelta

JOURNAL_DIR = Path.home() / ".hermes" / "skills" / "stock-knowledge" / "journal"
JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
JOURNAL_FILE = JOURNAL_DIR / "journal.jsonl"

# Pipeline status path
PIPELINE_DIR = Path.home() / ".hermes" / "profiles" / "stock" / "skills" / "stock" / "stock-expert" / "skills" / "feishu-bitable"


def _load():
    """Load all entries"""
    entries = []
    if JOURNAL_FILE.exists():
        with open(JOURNAL_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return entries


def _save(entries):
    """Save all entries"""
    with open(JOURNAL_FILE, "w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _next_id(entries):
    return max([e.get("id", 0) for e in entries], default=0) + 1


def record(entry_type, title, content, code="", tags=None, source=""):
    """记录一条学习日志"""
    entries = _load()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = {
        "id": _next_id(entries),
        "date": now[:10],
        "time": now,
        "type": entry_type,
        "title": title[:80],
        "content": content[:2000] if content else "",
        "code": code,
        "tags": tags or [],
        "source": source,
    }
    entries.append(entry)
    _save(entries)
    print(f"✅ 已记录 #{entry['id']} [{entry_type}] {title[:40]}")
    return entry


def list_entries(limit=20):
    """列出最近记录"""
    entries = _load()
    if not entries:
        print("📭 暂无学习记录")
        return
    print(f"\n📖 学习记录（共 {len(entries)} 条，显示最近 {limit} 条）")
    print(f"{'─'*60}")
    for e in entries[-limit:][::-1]:
        eid = e.get("id", 0)
        dt = e.get("date", "?")
        tp = e.get("type", "?").ljust(10)
        code = e.get("code", "")
        title = e.get("title", "")[:35]
        tags = ",".join(e.get("tags", [])[:3])
        print(f"  #{eid:<3d} {dt} [{tp}] {code:<7s} {title}")
        if tags:
            print(f"      tags: {tags}")


def search_by_code(code):
    """按股票代码搜索"""
    entries = _load()
    results = [e for e in entries if e.get("code", "") == code]
    _show_search_results(results, f"代码 {code}")


def search_by_tag(tag):
    """按标签搜索"""
    entries = _load()
    results = [e for e in entries if tag in e.get("tags", [])]
    _show_search_results(results, f"标签 {tag}")


def search_by_text(query):
    """按文本搜索"""
    entries = _load()
    q = query.lower()
    results = [e for e in entries if q in e.get("title", "").lower()
               or q in e.get("content", "").lower()]
    _show_search_results(results, f"关键词 {query}")


def _show_search_results(results, label):
    print(f"\n🔍 搜索 {label}: {len(results)} 条结果")
    print(f"{'─'*60}")
    for e in results[-20:][::-1]:
        eid = e.get("id", 0)
        dt = e.get("date", "?")
        tp = e.get("type", "?")
        code = e.get("code", "")
        title = e.get("title", "")[:40]
        print(f"  #{eid:<3d} {dt} [{tp}] {code:<7s} {title}")
        content = e.get("content", "")
        if content:
            print(f"         {content[:80].strip()}")


def summary(days=7):
    """生成学习总结"""
    entries = _load()
    cutoff = datetime.now() - timedelta(days=days)
    recent = [e for e in entries if e.get("date", "2000-01-01") >= cutoff.strftime("%Y-%m-%d")]

    if not recent:
        print(f"📭 近 {days} 天无记录")
        return

    # Stats
    types = {}
    codes = set()
    tags = {}
    for e in recent:
        tp = e.get("type", "?")
        types[tp] = types.get(tp, 0) + 1
        if e.get("code"):
            codes.add(e["code"])
        for t in e.get("tags", []):
            tags[t] = tags.get(t, 0) + 1

    print(f"\n📊 {days}天学习总结 ({cutoff.strftime('%m-%d')} ~ {datetime.now().strftime('%m-%d')})")
    print(f"{'─'*50}")
    print(f"  总记录: {len(recent)} 条")
    print(f"  类型分布:")
    for tp, cnt in sorted(types.items(), key=lambda x: -x[1]):
        print(f"    {tp}: {cnt} 条")
    print(f"  涉及股票: {len(codes)} 只")
    if tags:
        top_tags = sorted(tags.items(), key=lambda x: -x[1])[:5]
        print(f"  热标签: {', '.join(f'{t}({c})' for t,c in top_tags)}")

    print(f"\n  最近记录:")
    for e in recent[-5:][::-1]:
        print(f"    #{e['id']} {e['date']} [{e['type']}] {e.get('code','')} {e['title'][:40]}")


def push_to_ima(entry_id):
    """将指定记录推送到IMA知识库"""
    entries = _load()
    target = None
    for e in entries:
        if e.get("id") == entry_id:
            target = e
            break
    if not target:
        print(f"❌ 未找到 #{entry_id}")
        return

    # Build content for IMA
    title = f"[学习记录] {target.get('code','')} {target['title']}"
    content = (f"# {target['title']}\n"
               f"日期: {target['date']}\n"
               f"类型: {target.get('type','')}\n"
               f"代码: {target.get('code','')}\n"
               f"标签: {', '.join(target.get('tags',[]))}\n"
               f"\n---\n"
               f"{target.get('content','')}")

    # Call kb_sync.py
    script = PIPELINE_DIR / "kb_sync.py"
    if not script.exists():
        print(f"❌ kb_sync.py 不存在")
        return

    r = subprocess.run(
        [sys.executable, str(script), "push", title, content],
        capture_output=True, text=True, timeout=30,
    )
    print(r.stdout)
    if r.stderr:
        print(r.stderr[:300])


def record_from_pipeline():
    """自动记录最新pipeline运行结果"""
    # Find the latest pipeline output (the most recent _index.json or run output)
    report = None

    # Try running pipeline in quick mode and capture output
    script = PIPELINE_DIR / "stock_pipeline.py"
    if script.exists():
        r = subprocess.run(
            [sys.executable, str(script), "--quick"],
            capture_output=True, text=True, timeout=120,
        )
        report = r.stdout.strip()
        if not report or len(report) < 50:
            report = r.stderr.strip() or "pipeline 运行完成"

    if not report:
        print("❌ 无法获取pipeline输出")
        return

    # Extract tickers mentioned and top info from report
    lines = report.split("\n")
    top_codes = []
    current_section = ""
    for line in lines:
        if "量化验证" in line:
            current_section = "quant"
        elif "开仓前检查" in line:
            current_section = "pre_trade"
        elif "行业筛选" in line:
            current_section = "industry"
        elif current_section == "quant" and "  " in line and len(line.strip()) > 10:
            parts = line.strip().split()
            if len(parts) >= 3 and parts[0] not in ("代码","---"):
                code = parts[0].strip()
                if len(code) == 6 and code.isdigit():
                    top_codes.append(code)

    # Extract industry info
    sectors = []
    for line in lines:
        if line.strip().startswith("▸"):
            sectors.append(line.strip())

    summary_text = f"行业: {'; '.join(sectors[:3])}\nTop股: {', '.join(top_codes[:5])}"

    record(
        entry_type="pipeline",
        title=f"全流程引擎 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        content=report[:1500],
        code=",".join(top_codes[:5]),
        tags=["pipeline", "全流程"],
        source="stock_pipeline.py",
    )


# ====== MAIN ======

def main():
    parser = argparse.ArgumentParser(description="系统化学习记录")
    sub = parser.add_subparsers(dest="cmd")

    # record
    rp = sub.add_parser("record")
    rp.add_argument("--type", required=True, choices=["pipeline", "analysis", "trade", "observation"])
    rp.add_argument("--title", required=True, help="标题")
    rp.add_argument("--content", default="", help="正文内容")
    rp.add_argument("--code", default="", help="股票代码")
    rp.add_argument("--tags", default="", help="标签，逗号分隔")
    rp.add_argument("--source", default="", help="来源")

    # list
    sub.add_parser("list")

    # search
    sp = sub.add_parser("search")
    sp.add_argument("--code", default="", help="按代码搜索")
    sp.add_argument("--tag", default="", help="按标签搜索")
    sp.add_argument("--text", default="", help="按文本搜索")

    # summary
    sm = sub.add_parser("summary")
    sm.add_argument("--days", type=int, default=7, help="回顾天数")

    # push
    pp = sub.add_parser("push")
    pp.add_argument("--id", type=int, required=True, help="条目ID")

    # record-from-pipeline
    sub.add_parser("record-from-pipeline")

    # Search defaults
    args = parser.parse_args()

    if args.cmd == "record":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        record(args.type, args.title, args.content, args.code, tags, args.source)
    elif args.cmd == "list":
        list_entries()
    elif args.cmd == "search":
        if args.code:
            search_by_code(args.code)
        elif args.tag:
            search_by_tag(args.tag)
        elif args.text:
            search_by_text(args.text)
        else:
            print("请指定搜索条件：--code / --tag / --text")
    elif args.cmd == "summary":
        summary(args.days)
    elif args.cmd == "push":
        push_to_ima(args.id)
    elif args.cmd == "record-from-pipeline":
        record_from_pipeline()
    else:
        list_entries()


if __name__ == "__main__":
    main()
