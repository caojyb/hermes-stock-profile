"""
飞书Bitable推荐记录写入模块
向股票持仓表写入"候选"类型的推荐记录
"""
import json
import datetime
import urllib.request
from typing import List, Dict, Any, Optional
from pathlib import Path

# 安全（2026-09-18 二轮审计 P0-2）: 凭证不进代码——从 decision/_local_constants（gitignored）或环境变量取
import os as _os
def _load_bitable_target():
    """安全（2026-09-18 P0-2）: 凭证不进代码 default。向上遍历父目录定位
    scripts/cron/decision/_local_constants（gitignored），找不到再退环境变量。"""
    try:
        import sys as _sys
        _cur = Path(__file__).resolve()
        for _p in _cur.parents:
            _dec = _p / 'scripts' / 'cron' / 'decision'
            if _dec.is_dir():
                # decision 包的导入根是它的父目录 scripts/cron
                _pkg_root = str(_dec.parent)
                if _pkg_root not in _sys.path:
                    _sys.path.insert(0, _pkg_root)
                import decision._local_constants as _lc
                return _lc.BITABLE_BASE_TOKEN, _lc.BITABLE_TABLE_ID
    except Exception:
        pass
    return _os.getenv("BITABLE_BASE_TOKEN", ""), _os.getenv("BITABLE_TABLE_ID", "")

APP_TOKEN, TABLE_ID = _load_bitable_target()
ENV_PATH = Path.home() / ".hermes" / "profiles" / "stock" / ".env"


def _get_token() -> str:
    """获取 tenant_access_token"""
    app_id = app_secret = None
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith("FEISHU_APP_ID="):
                app_id = line.split("=", 1)[1].strip()
            elif line.startswith("FEISHU_APP_SECRET="):
                app_secret = line.split("=", 1)[1].strip()

    if not app_id or not app_secret:
        raise RuntimeError("未找到 FEISHU_APP_ID 或 FEISHU_APP_SECRET")

    auth_data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=auth_data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["tenant_access_token"]


def _ensure_candidate_option(token: str, field_id: str, field_name: str) -> bool:
    """确保'候选'选项存在于'类型'字段，不存在则添加"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields/{field_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        items = json.loads(resp.read())["data"]["items"]
    for item in items:
        if item["field_id"] == field_id:
            opts = item.get("property", {}).get("options", [])
            opt_names = [o["name"] for o in opts]
            if "候选" not in opt_names:
                opts.append({"name": "候选"})
                update_body = {
                    "field_name": field_name,
                    "type": 3,
                    "property": {"options": opts},
                }
                put_req = urllib.request.Request(
                    url,
                    data=json.dumps(update_body, ensure_ascii=False).encode(),
                    method="PUT",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(put_req, timeout=10) as resp2:
                    result = json.loads(resp2.read())
                    if result.get("code") == 0:
                        print("✅ 已添加'候选'选项到 类型 字段")
                    else:
                        print(f"⚠️ 添加'候选'选项失败: {result}")
            return True
    return False


def add_recommendation_records(records: List[Dict[str, Any]]) -> List[Dict]:
    """
    向Bitable批量写入推荐记录（类型=候选）

    每条记录字段：
        stock_code:   股票代码
        stock_name:   股票名称
        price:       推荐价格（当前价）
        rsi:         推荐时RSI
        score:       综合评分
        tier:        层级（保守/正常/进攻）
        signal:      信号（建仓/重点/观察）
        boll_pos:    布林位
        today_chg:   今日涨跌幅

    Returns:
        每条记录的写入结果 {"code": int, "data": {...}}
    """
    if not records:
        return []

    token = _get_token()
    results = []

    for rec in records:
        # 毫秒时间戳（推荐时间 = 现在）
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        rec_time_ms = int(now.timestamp() * 1000)

        # 准备字段（现价是文本字段，用字符串）
        # 分析报告字段用于存推荐详情（含推荐时间）
        fields = {
            "股票ID": str(rec["stock_code"]),
            "name": str(rec["stock_name"]),
            "买入时间": rec_time_ms,
            "买入价格": float(rec["price"]),
            "现价": str(rec["price"]),
            "最新RSI": round(float(rec["rsi"]), 1) if rec.get("rsi") else None,
            "是否买入": "观察中",
            "类型": "候选",
            "分析报告": (
                f"【{rec.get('tier', '')}】推荐时间：{now.strftime('%Y-%m-%d %H:%M')} | "
                f"今日涨跌：{rec.get('today_chg', 0):+.2f}% | "
                f"布林位：{rec.get('boll_pos', 0):.0f}% | "
                f"综合评分：{rec.get('score', 0):.0f}分"
            ),
        }

        # 去除 None 值
        fields = {k: v for k, v in fields.items() if v is not None}

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
        body = json.dumps({"fields": fields}, ensure_ascii=False).encode()
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                code = result.get("code")
                if code == 0:
                    print(f"  ✅ {rec['stock_name']}({rec['stock_code']}) 已写入Bitable")
                elif code == 1254062:
                    # 单选字段选项不存在，尝试修复（理论上"观察中"和"候选"应该已存在）
                    print(f"  ⚠️ {rec['stock_name']} 写入失败，单选字段选项问题: {result.get('msg', '')}")
                else:
                    print(f"  ⚠️ {rec['stock_name']} 写入失败: {result.get('msg', '')}")
                results.append({"stock": rec["stock_name"], "code": code, "result": result})
        except Exception as e:
            print(f"  ❌ {rec['stock_name']} 请求异常: {e}")
            results.append({"stock": rec["stock_name"], "code": -1, "error": str(e)})

    return results
