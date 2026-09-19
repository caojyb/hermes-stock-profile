"""
飞书消息推送模块
使用飞书 REST API 直接发送消息，不再依赖 lark-cli
"""
import json
import urllib.request
from typing import Optional
from pathlib import Path


FEISHU_CHAT_ID = "oc_88d1817efbb9f328f4376314ab7c8b05"  # 推送目标会话ID
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
        data = json.loads(resp.read())
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
        return data["tenant_access_token"]


def _post(path: str, body: dict, token: Optional[str] = None) -> dict:
    """通用 POST 请求"""
    # 2026-09-19: 全局禁推开关（手工验证/合并快照调用时用，一处修复覆盖全部调用方）
    # 原 lhb_monitor 单独打补丁，但 14 个脚本都有内部直推——在唯一出口 _post 加门
    import os as _os
    if _os.environ.get("FEISHU_DISABLE") == "1":
        text_preview = ""
        try:
            text_preview = json.loads(body.get("content", "{}")).get("text", "")[:60]
        except Exception:
            pass
        return {"code": 0, "msg": "FEISHU_DISABLE=1 (skipped)", "skipped": True,
                "preview": text_preview}
    if token is None:
        token = _get_token()
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        path,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def send_text_message(text: str, receive_id: str = FEISHU_CHAT_ID) -> dict:
    """
    发送纯文本消息到飞书
    """
    body = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    return _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id", body)


def send_rich_message(
    title: str,
    content_lines: list[str],
    receive_id: str = FEISHU_CHAT_ID
) -> dict:
    """
    发送富文本消息（卡片样式，通过文本模拟）

    Args:
        title: 消息标题
        content_lines: 内容行列表，每行格式 "标签 | 值 | 颜色指示"
        receive_id: 接收者ID
    """
    # 用文本块构建可读性好的消息
    lines = [f"📊 {title}", ""]
    for line in content_lines:
        if " | " in line:
            parts = line.split(" | ")
            label = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else ""
            emoji = parts[2].strip() if len(parts) > 2 else ""
            lines.append(f"{emoji} {label}：{value}")
        else:
            lines.append(line)
    text = "\n".join(lines)
    return send_text_message(text, receive_id)


def send_signal_alert(
    stock_code: str,
    stock_name: str,
    signal_level: int,
    action: str,
    current_price: float,
    change_pct: float,
    stop_loss: float,
    take_profit: float,
    reason: str,
    receive_id: str = FEISHU_CHAT_ID
) -> dict:
    """
    发送持仓股预警消息

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        signal_level: 信号等级 0-5
        action: 操作建议（持有/加仓/减仓/清仓）
        current_price: 当前价
        change_pct: 涨跌幅%
        stop_loss: 止损价
        take_profit: 止盈价
        reason: 信号原因
    """
    level_emoji = ["", "📌", "⚠️", "🔔", "🚨", "⛔"][min(signal_level, 5)]
    change_sign = "+" if change_pct >= 0 else ""
    lines = [
        f"{level_emoji} 【{stock_name}】{signal_level}级信号",
        f"---\n📈 现价：{current_price:.3f}（{change_sign}{change_pct:.2f}%）",
        f"🎯 操作：{action}",
        f"🛡️ 止损：{stop_loss:.3f}",
        f"💰 止盈参考：{take_profit:.3f}",
        f"---\n📋 原因：{reason}"
    ]
    text = "\n".join(lines)
    return send_text_message(text, receive_id)


def send_position_digest(
    positions: list,
    market_summary: dict,
    receive_id: str = FEISHU_CHAT_ID
) -> dict:
    """
    发送持仓诊断摘要消息

    Args:
        positions: 持仓分析结果列表
        market_summary: 大盘情绪 dict
    """
    lines = ["📊 【持仓诊断】", ""]

    # 大盘简况
    if market_summary:
        sh = market_summary.get("sh000001", {})
        sz = market_summary.get("sz399001", {})
        if sh:
            sh_pct = sh.get("change_pct", 0)
            sign = "+" if sh_pct >= 0 else ""
            lines.append(f"📈 上证 {sh.get('price', 'N/A')}（{sign}{sh_pct:.2f}%）")
        if sz:
            sz_pct = sz.get("change_pct", 0)
            sign = "+" if sz_pct >= 0 else ""
            lines.append(f"📉 深证 {sz.get('price', 'N/A')}（{sign}{sz_pct:.2f}%）")

    lines.append("")
    lines.append("---")

    # 持仓明细
    alert_count = 0
    for p in positions:
        level = p.get("signal_level", 0)
        if level >= 3:
            alert_count += 1
            emoji = ["", "📌", "⚠️", "🔔", "🚨", "⛔"][min(level, 5)]
            code = p.get("stock_code", "?")
            name = p.get("stock_name", code)
            price = p.get("current_price", 0)
            pct = p.get("change_pct", 0)
            action = p.get("action", "持有")
            sign = "+" if pct >= 0 else ""
            lines.append(
                f"{emoji} {name}({code}) {price:.3f}（{sign}{pct:.2f}%）→ {action}"
            )

    if alert_count == 0:
        lines.append("✅ 目前无需要关注的预警信号")

    text = "\n".join(lines)
    return send_text_message(text, receive_id)


def send_pre_market_brief(
    us_indices: dict,
    a50_pct: float,
    sentiment: dict,
    watchlist_news: list = None,
    receive_id: str = FEISHU_CHAT_ID
) -> dict:
    """
    发送盘前简报

    Args:
        us_indices: 美股指数 dict
        a50_pct: 富时A50期货涨跌幅
        sentiment: 大盘情绪 dict
        watchlist_news: 持仓相关消息列表
    """
    lines = ["🌅 【盘前简报】", ""]

    # 隔夜美股
    lines.append("🇺🇸 隔夜美股：")
    for name, info in us_indices.items():
        pct = info.get("change_pct", 0)
        sign = "+" if pct >= 0 else ""
        lines.append(f"  {name} {info.get('price', 'N/A')}（{sign}{pct:.2f}%）")

    # A50期货
    sign = "+" if a50_pct >= 0 else ""
    lines.append(f"🇨🇳 A50期货 {sign}{a50_pct:.2f}%")

    # 情绪面
    if sentiment:
        up = sentiment.get("limit_up", 0)
        down = sentiment.get("limit_down", 0)
        lines.append(f"📊 涨停/跌停 {up} / {down}")

    text = "\n".join(lines)
    return send_text_message(text, receive_id)


def feishu_send_message(text: str, receive_id: str = FEISHU_CHAT_ID) -> dict:
    """
    通用飞书消息发送入口（兼容旧接口）
    """
    return send_text_message(text, receive_id)
