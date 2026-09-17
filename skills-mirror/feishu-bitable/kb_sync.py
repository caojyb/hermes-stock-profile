#!/usr/bin/env python3
"""
IMA知识库双向同步工具 v1.0

Pull: 下载 IMA 知识库内容 → 本地文件
Push: 上传本地分析结果 → IMA 知识库

用法:
  python3 kb_sync.py status             # 查看同步状态
  python3 kb_sync.py pull               # 拉取知识库到本地
  python3 kb_sync.py push .             # 推送本地最新pipeline报告
  python3 kb_sync.py push "标题" "内容"  # 推送指定内容
  python3 kb_sync.py push --pipeline     # 自动推送最新 pipeline 结果
"""

import os, sys, json, subprocess, argparse, glob
from pathlib import Path
from datetime import datetime

# ── 路径配置 ──
IMA_SKILL_DIR = Path.home() / ".hermes" / "skills" / "ima-skill"
IMA_API = IMA_SKILL_DIR / "scripts" / "ima_api.cjs"
SYNC_DIR = Path.home() / ".hermes" / "skills" / "stock-knowledge" / "synced"
SYNC_DIR.mkdir(parents=True, exist_ok=True)

# ── 知识库ID（从IMA查询结果确认） ──
KBS = {
    "股票知识库": "ZfBlweFuuXuNqaZFetY3ei_BIpWXESsAuJMQUtjYPj0=",
    "行业知识库": "mNUKstybAR2LgzQrZu6VBnpknEWHE5SQQxT5YD3Tdfc=",
    "个人知识库": "R9BDkKL0P8ux060p-aph93l_OaF2fZFXJ4icj7S9voE=",
    "紫微斗数":   "N3kZLpMibfL4MjCVc6Btx3Ex1PabDMje07mDTK53e8E=",
}


def _creds():
    """Load IMA credentials"""
    cid = Path.home() / ".config" / "ima" / "client_id"
    key = Path.home() / ".config" / "ima" / "api_key"
    if cid.exists() and key.exists():
        return cid.read_text().strip(), key.read_text().strip()
    return None, None


def _ima(api_path, params):
    """Call IMA API. Returns parsed response dict."""
    cid, ak = _creds()
    if not cid or not ak:
        raise RuntimeError("IMA credentials not found in ~/.config/ima/")
    opts = json.dumps({"clientId": cid, "apiKey": ak})
    params_json = json.dumps(params) if isinstance(params, dict) else params
    r = subprocess.run(
        ["node", str(IMA_API), api_path, params_json, opts],
        capture_output=True, text=True, timeout=30,
        cwd=str(IMA_SKILL_DIR),
    )
    if r.returncode != 0:
        err = r.stderr.strip()[:200]
        # Try parsing stderr for error info
        if err.startswith("{"):
            try:
                err_d = json.loads(err)
                raise RuntimeError(f"IMA error {err_d.get('code','?')}: {err_d.get('msg', err)}")
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"IMA script error: {err}")
    # Parse stdout
    if not r.stdout.strip():
        return {"code": 0, "data": {}}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"IMA returned non-JSON: {r.stdout[:200]}")


def _get_kb_id(name="股票知识库"):
    """Resolve KB name to ID"""
    return KBS.get(name, name)


# ====== PULL ======

def pull(kb_name="股票知识库", output_dir=None, shallow=False):
    """拉取知识库全部条目到本地"""
    kb_id = _get_kb_id(kb_name)
    dst = Path(output_dir or SYNC_DIR) / kb_name
    dst.mkdir(parents=True, exist_ok=True)

    print(f"📥 拉取知识库「{kb_name}」→ {dst}")

    # Step 1: Get KB info
    kb_resp = _ima("openapi/wiki/v1/get_knowledge_base", {"ids": [kb_id]})
    if kb_resp.get("code") != 0:
        print(f"  ❌ 获取知识库信息失败: {kb_resp.get('msg', 'unknown')}")
        return
    infos = kb_resp.get("data", {}).get("infos", {})
    kb_info = infos.get(kb_id, {})
    print(f"  名称: {kb_info.get('name', kb_name)} | 描述: {kb_info.get('description','')[:50]}")

    # Step 2: List all entries with pagination
    all_entries = []
    folder_queue = [""]  # empty = root
    seen_folders = set()

    while folder_queue:
        folder_id = folder_queue.pop(0)
        cursor = ""
        while True:
            params = {"knowledge_base_id": kb_id, "cursor": cursor, "limit": 50}
            if folder_id:
                params["folder_id"] = folder_id
            resp = _ima("openapi/wiki/v1/get_knowledge_list", params)
            if resp.get("code") != 0:
                break
            data = resp.get("data", {})
            items = data.get("knowledge_list", [])
            for item in items:
                all_entries.append(item)
                mt = item.get("media_type", 0)
                if mt == 99 and item.get("media_id"):
                    fid = item["media_id"]
                    if fid not in seen_folders:
                        folder_queue.append(fid)
                        seen_folders.add(fid)
            is_end = data.get("is_end", True)
            cursor = data.get("next_cursor", "")
            if is_end or not cursor:
                break

    print(f"  📄 共 {len(all_entries)} 条 (含 {len(seen_folders)} 个文件夹)")

    # Save index
    with open(dst / "_index.json", "w") as f:
        json.dump({
            "kb_name": kb_name, "kb_id": kb_id,
            "total": len(all_entries),
            "folders": len(seen_folders),
            "updated": datetime.now().isoformat(),
            "entries": all_entries,
        }, f, ensure_ascii=False, indent=2)

    if shallow:
        print(f"  ✅ 索引已保存（{len(all_entries)} 条），未拉取内容")
        print(f"     使用 --deep 拉取全部正文内容")
        return

    # Step 3: Deep content fetch (SLOW - one API call per entry)
    text_count = 0
    for i, entry in enumerate(all_entries):
        mt = entry.get("media_type", 0)
        if mt == 99:
            continue
        media_id = entry.get("media_id", "")
        if not media_id:
            continue
        title = entry.get("title", media_id) or media_id
        safe_name = "".join(c if c.isalnum() or c in '-_ ' else '_' for c in title)[:60]

        if mt == 11:  # notes
            mi = _ima("openapi/wiki/v1/get_media_info", {"media_id": media_id})
            if mi.get("code") != 0:
                continue
            note_id = mi.get("data", {}).get("notebook_ext_info", {}).get("notebook_id")
            if note_id:
                cr = _ima("openapi/note/v1/get_doc_content", {"note_id": note_id, "target_content_format": 0})
                if cr.get("code") == 0:
                    content = cr.get("data", {}).get("content", "")
                    (dst / f"{safe_name}.md").write_text(content[:50000])
                    text_count += 1

        elif mt in (1, 2, 7, 13):  # files / links
            mi = _ima("openapi/wiki/v1/get_media_info", {"media_id": media_id})
            if mi.get("code") != 0:
                continue
            url_info = mi.get("data", {}).get("url_info", {})
            if url_info:
                (dst / f"{safe_name}.url.txt").write_text(
                    f"title: {title}\nurl: {url_info.get('url','')}\n"
                    f"desc: {url_info.get('description','')}\n"
                )
                text_count += 1

        if (i + 1) % 20 == 0:
            print(f"  ... 进度 {i+1}/{len(all_entries)} | 已提取 {text_count}")

    print(f"  ✅ 完成: {len(all_entries)} 条索引 + {text_count} 条内容")
    print(f"     路径: {dst}")


# ====== PUSH ======

def push(title, content=None, kb_name="股票知识库", file_path=None):
    """推送内容到知识库"""
    kb_id = _get_kb_id(kb_name)

    if file_path:
        # Read from file
        content = Path(file_path).read_text()
        if not title:
            title = Path(file_path).stem

    if not content:
        print("  ❌ 请提供内容或文件路径")
        return

    print(f"📤 推送「{title}」→ {kb_name}")

    # Step 1: Create a note in IMA
    import_resp = _ima("openapi/note/v1/import_doc", {
        "content_format": 1,  # markdown
        "content": content,
        "title": title,
    })
    if import_resp.get("code") != 0:
        print(f"  ❌ 创建笔记失败: {import_resp.get('msg', 'unknown')}")
        return

    note_id = import_resp.get("data", {}).get("note_id")
    if not note_id:
        print(f"  ❌ 创建笔记成功但未返回 note_id")
        return

    print(f"  ✅ 笔记已创建: {title} (note_id: {note_id[:20]}...)")

    # Step 2: Add the note to the knowledge base
    add_resp = _ima("openapi/wiki/v1/add_knowledge", {
        "media_type": 11,
        "note_info": {"content_id": note_id},
        "title": title,
        "knowledge_base_id": kb_id,
    })
    if add_resp.get("code") != 0:
        print(f"  ⚠️ 添加到知识库失败: {add_resp.get('msg', 'unknown')}")
        print(f"     笔记已存在IMA中，可通过搜索获取")
        return

    print(f"  ✅ 已添加到知识库「{kb_name}」✓")


def push_pipeline(kb_name="股票知识库"):
    """自动推送最新pipeline运行结果"""
    # Find latest pipeline output
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"全流程引擎报告 {ts}"

    # Run pipeline in JSON mode, use its output as content
    script_dir = Path.home() / ".hermes" / "profiles" / "stock" / "skills" / "stock" / "stock-expert" / "skills" / "feishu-bitable"
    pipeline = script_dir / "stock_pipeline.py"
    if not pipeline.exists():
        print(f"  ❌ pipeline 脚本不存在: {pipeline}")
        return

    r = subprocess.run(
        [sys.executable, str(pipeline), "--quick"],
        capture_output=True, text=True, timeout=120,
        cwd=str(script_dir),
    )
    content = r.stdout.strip()
    if not content or len(content) < 50:
        content = r.stderr.strip() or "pipeline 运行完成，无文本输出"
    push(title, content=content, kb_name=kb_name)


# ====== STATUS ======

def status(kb_name="股票知识库"):
    """查看同步状态"""
    kb_id = _get_kb_id(kb_name)

    print(f"📊 知识库同步状态")
    print(f"{'─'*50}")

    # KB info
    resp = _ima("openapi/wiki/v1/get_knowledge_base", {"ids": [kb_id]})
    if resp.get("code") == 0:
        infos = resp.get("data", {}).get("infos", {})
        info = infos.get(kb_id, {})
        print(f"  知识库: {info.get('name', kb_name)}")
        print(f"  描述: {info.get('description', '?')[:50]}")
    else:
        print(f"  ❌ 获取信息失败: {resp.get('msg', '')}")

    # Local state
    sync_dir = SYNC_DIR / kb_name
    if sync_dir.exists():
        index = sync_dir / "_index.json"
        if index.exists():
            meta = json.loads(index.read_text())
            print(f"  本地缓存: {meta.get('total', 0)} 条 (更新: {meta.get('updated', '?')[:19]})")
        else:
            files = list(sync_dir.glob("*"))
            print(f"  本地缓存: {len(files)} 个文件（无索引）")
    else:
        print(f"  本地缓存: 无")

    # list recent sync entries
    print(f"\n📋 最近10条")
    resp = _ima("openapi/wiki/v1/get_knowledge_list", {
        "knowledge_base_id": kb_id, "cursor": "", "limit": 10
    })
    if resp.get("code") == 0:
        items = resp.get("data", {}).get("knowledge_list", [])
        for i, item in enumerate(items, 1):
            title = item.get("title", "?")
            mtype = {1: "📄", 2: "🔗", 11: "📝"}.get(item.get("media_type", 0), "📦")
            print(f"  {i}. {mtype} {title[:40]}")
    else:
        print(f"  ❌ 列表获取失败")

    print()


# ====== MAIN ======

def main():
    parser = argparse.ArgumentParser(description="IMA知识库双向同步")
    parser.add_argument("action", choices=["pull", "push", "status"],
                        help="操作: pull(拉取) / push(推送) / status(状态)")
    parser.add_argument("args", nargs="*", help="push: 标题 内容, 或 --pipeline / 文件路径")
    parser.add_argument("--kb", default="股票知识库", help="知识库名称 (默认: 股票知识库)")
    parser.add_argument("--pipeline", action="store_true", help="推送最新pipeline结果")
    parser.add_argument("--file", type=str, help="从文件读取内容")
    parser.add_argument("--shallow", action="store_true", help="pull时仅拉索引（快速）")
    parser.add_argument("--deep", action="store_true", help="pull时拉取全部正文（慢）")
    args = parser.parse_args()

    if args.action == "status":
        status(args.kb)
    elif args.action == "pull":
        shallow = args.shallow
        pull(args.kb, shallow=shallow)
    elif args.action == "push":
        if args.pipeline:
            push_pipeline(args.kb)
        elif args.file:
            push(Path(args.file).stem, kb_name=args.kb, file_path=args.file)
        elif len(args.args) >= 2:
            push(args.args[0], " ".join(args.args[1:]), kb_name=args.kb)
        elif len(args.args) == 1:
            # Single arg could be a path or a title with piped content
            p = Path(args.args[0])
            if p.exists():
                push(p.stem, kb_name=args.kb, file_path=str(p))
            else:
                print("❌ 用法: kb_sync.py push \"标题\" \"内容\"")
                print("       kb_sync.py push --file 结果文件路径")
                print("       kb_sync.py push --pipeline")
        else:
            print("❌ 用法: kb_sync.py push \"标题\" \"内容\"")
            print("       kb_sync.py push --pipeline")


if __name__ == "__main__":
    main()
