"""
飞书Bitable持仓数据读取模块
直接调用飞书 REST API，不再依赖 lark-cli
"""

import json
import os
import urllib.request
from dataclasses import dataclass, asdict
from typing import List, Optional


# 从环境变量或 _local_constants 读取配置
def _get_env_path():
    """获取飞书应用凭证"""
    env_path = os.path.expanduser("~/.hermes/profiles/stock/.env")
    app_id = app_secret = None
    if os.path.exists(env_path):
        for line in open(env_path, "r", encoding="utf-8").readlines():
            if line.startswith("FEISHU_APP_ID="):
                app_id = line.split("=", 1)[1].strip()
            elif line.startswith("FEISHU_APP_SECRET="):
                app_secret = line.split("=", 1)[1].strip()
    if not app_id or not app_secret:
        raise RuntimeError("~/.hermes/profiles/stock/.env 中缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
    return app_id, app_secret


# 进程内 token 缓存: 飞书 tenant_access_token 有效期 2h, 缓存到 2h-5min 安全边界
_TOKEN_CACHE = {"value": None, "expires_at": 0.0}


def _get_tenant_token() -> str:
    """获取 tenant_access_token（进程内缓存, TTL=2h-5min, 避免每次调用重新认证 0.2-0.8s）"""
    import time as _time
    now = _time.time()
    if _TOKEN_CACHE["value"] and _TOKEN_CACHE["expires_at"] > now + 60:
        return _TOKEN_CACHE["value"]
    app_id, app_secret = _get_env_path()
    auth_data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=auth_data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_data = json.loads(resp.read())
            if token_data.get("code") != 0:
                raise RuntimeError(f"获取 tenant_access_token 失败: {token_data}")
            token = token_data["tenant_access_token"]
            _TOKEN_CACHE["value"] = token
            _TOKEN_CACHE["expires_at"] = now + 2 * 3600 - 300
            return token
    except Exception as e:
        raise RuntimeError(f"获取 tenant_access_token 异常: {e}")


def _get_bitable_config():
    """获取 Bitable app_token 和 table_id"""
    try:
        import decision._local_constants as _local_constants
        app_token = _local_constants.BITABLE_BASE_TOKEN
        table_id = _local_constants.BITABLE_TABLE_ID
    except Exception:
        app_token = os.getenv("BITABLE_BASE_TOKEN", "REDACTED-TOKEN")
        table_id = os.getenv("BITABLE_TABLE_ID", "REDACTED-TABLE")
    if not app_token or not table_id:
        raise RuntimeError("Bitable app_token/table_id 为空，请检查 _local_constants 或环境变量")
    return app_token, table_id


# 字段映射：Bitable 字段名 -> 位置索引（用于 REST API 返回的 fields 对象）
FIELD_MAPPING = {
    "股票ID": "stock_code",
    "name": "stock_name",
    "操作信号": "status",
    "是否买入": "buy_flag",
    "买入数量": "quantity",
    "买入价格": "cost_price",
    "现价": "current_price",
    "盈亏": "profit_loss",
    "盈亏率": "change_pct",
    "买入时间": "trade_date",
    "所属板块": "industry",
    "最新RSI": "latest_rsi",
    "止损价": "stop_loss",
    "止盈价": "take_profit",
    "分析报告": "analysis_report",
}


@dataclass
class PositionRecord:
    """持仓记录"""
    stock_code: str
    stock_name: str
    quantity: float
    cost_price: float
    current_price: float
    status: str
    period: str
    industry: str
    sector_id: str
    profit_loss: float
    change_pct: float
    trade_date: str
    record_id: Optional[str] = None
    profit_pct: float = 0.0
    buy_flag: Optional[str] = None
    latest_rsi: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    analysis_report: Optional[str] = None
    signal_level: Optional[int] = None
    action: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self)


class BitableReader:
    """飞书Bitable读取器（基于 REST API）"""

    def __init__(
        self,
        app_token: str = None,
        table_id: str = None,
        limit: int = 100
    ):
        """
        初始化 BitableReader

        Args:
            app_token: 飞书应用Token（默认从 _local_constants 读取）
            table_id: 数据表ID（默认从 _local_constants 读取）
            limit: 单次查询返回的最大记录数
        """
        if app_token is None or table_id is None:
            _app_token, _table_id = _get_bitable_config()
            self.app_token = app_token or _app_token
            self.table_id = table_id or _table_id
        else:
            self.app_token = app_token
            self.table_id = table_id
        self.limit = limit

    def _fetch_records(self, page_token: str = None) -> dict:
        """从飞书 REST API 获取记录"""
        token = _get_tenant_token()
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records"
        )
        params = {"page_size": min(self.limit, 100)}
        if page_token:
            params["page_token"] = page_token

        req = urllib.request.Request(
            url + "?" + "&".join(f"{k}={v}" for k, v in params.items()),
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as e:
            raise RuntimeError(f"读取 Bitable 失败: {e}")

    def _parse_fields(self, fields: dict) -> dict:
        """解析 Bitable fields 对象为结构化数据"""
        result = {}

        # 股票代码
        code_val = fields.get("股票ID", "")
        result["stock_code"] = str(code_val).strip() if code_val else ""

        # 股票名称
        name_val = fields.get("name", "")
        result["stock_name"] = str(name_val).strip() if name_val else ""

        # 操作信号（单选）
        status_val = fields.get("操作信号", "")
        if isinstance(status_val, list):
            status_val = status_val[0] if status_val else ""
        result["status"] = str(status_val).strip() if status_val else ""

        # 是否买入（单选）
        buy_val = fields.get("是否买入", "")
        if isinstance(buy_val, list):
            buy_val = buy_val[0] if buy_val else None
        result["buy_flag"] = str(buy_val).strip() if buy_val else None

        # 买入数量（数字）
        qty_val = fields.get("买入数量", 0)
        try:
            result["quantity"] = float(qty_val) if qty_val else 0.0
        except (ValueError, TypeError):
            result["quantity"] = 0.0

        # 买入价格（数字）
        cost_val = fields.get("买入价格", 0)
        try:
            result["cost_price"] = float(cost_val) if cost_val else 0.0
        except (ValueError, TypeError):
            result["cost_price"] = 0.0

        # 现价（数字）
        cur_val = fields.get("现价", 0)
        try:
            result["current_price"] = float(cur_val) if cur_val else 0.0
        except (ValueError, TypeError):
            result["current_price"] = 0.0

        # 盈亏（金额）
        pnl_val = fields.get("盈亏", 0)
        try:
            result["profit_loss"] = float(pnl_val) if pnl_val else 0.0
        except (ValueError, TypeError):
            result["profit_loss"] = 0.0

        # 盈亏率（百分比）
        chg_val = fields.get("盈亏率", 0)
        try:
            result["change_pct"] = float(chg_val) if chg_val else 0.0
        except (ValueError, TypeError):
            result["change_pct"] = 0.0

        # 买入时间（日期）
        date_val = fields.get("买入时间", "")
        result["trade_date"] = str(date_val).strip() if date_val else ""

        # 所属板块（文本）
        sector_val = fields.get("所属板块", "")
        result["industry"] = str(sector_val).strip() if sector_val else ""

        # 最新 RSI（数字）
        rsi_val = fields.get("最新RSI")
        try:
            result["latest_rsi"] = float(rsi_val) if rsi_val else None
        except (ValueError, TypeError):
            result["latest_rsi"] = None

        # 止损价（数字）
        sl_val = fields.get("止损价")
        try:
            result["stop_loss"] = float(sl_val) if sl_val else None
        except (ValueError, TypeError):
            result["stop_loss"] = None

        # 止盈价（数字）
        tp_val = fields.get("止盈价")
        try:
            result["take_profit"] = float(tp_val) if tp_val else None
        except (ValueError, TypeError):
            result["take_profit"] = None

        # 分析报告（文本）
        report_val = fields.get("分析报告", "")
        result["analysis_report"] = str(report_val).strip() if report_val else None

        # period 和 sector_id（可选字段）
        period_val = fields.get("周期", "")
        if isinstance(period_val, list):
            period_val = period_val[0] if period_val else ""
        result["period"] = str(period_val).strip() if period_val else ""

        sector_id_val = fields.get("sector_id", "")
        result["sector_id"] = str(sector_id_val).strip() if sector_id_val else ""

        return result

    def get_positions(self) -> List[PositionRecord]:
        """获取持仓数据"""
        records = []
        page_token = None
        while True:
            data = self._fetch_records(page_token)
            items = data.get("data", {}).get("items", []) or []
            if not items:
                break

            for item in items:
                fields = item.get("fields", {}) or {}
                parsed = self._parse_fields(fields)

                # 计算盈亏百分比
                qty = parsed.get("quantity", 0) or 0
                cost = parsed.get("cost_price", 0) or 0
                pnl = parsed.get("profit_loss", 0) or 0
                if cost > 0 and qty > 0:
                    cost_total = cost * qty
                    profit_pct = (pnl / cost_total * 100) if cost_total != 0 else 0.0
                else:
                    profit_pct = 0.0

                record = PositionRecord(
                    stock_code=parsed.get("stock_code", ""),
                    stock_name=parsed.get("stock_name", ""),
                    quantity=parsed.get("quantity", 0.0),
                    cost_price=parsed.get("cost_price", 0.0),
                    current_price=parsed.get("current_price", 0.0),
                    status=parsed.get("status", ""),
                    period=parsed.get("period", ""),
                    industry=parsed.get("industry", ""),
                    sector_id=parsed.get("sector_id", ""),
                    profit_loss=parsed.get("profit_loss", 0.0),
                    change_pct=parsed.get("change_pct", 0.0),
                    trade_date=parsed.get("trade_date", ""),
                    record_id=item.get("record_id"),
                    profit_pct=profit_pct,
                    buy_flag=parsed.get("buy_flag"),
                    latest_rsi=parsed.get("latest_rsi"),
                    stop_loss=parsed.get("stop_loss"),
                    take_profit=parsed.get("take_profit"),
                    analysis_report=parsed.get("analysis_report"),
                    signal_level=None,
                    action=parsed.get("status"),
                )
                records.append(record)

            page_token = data.get("data", {}).get("page_token")
            has_more = data.get("data", {}).get("has_more", False)
            if not page_token or not has_more:
                break

        return records

    def get_positions_by_status(self, status: str) -> List[PositionRecord]:
        """根据持仓状态筛选数据"""
        all_positions = self.get_positions()
        return [p for p in all_positions if p.status == status]

    def get_positions_by_period(self, period: str) -> List[PositionRecord]:
        """根据持仓周期筛选数据"""
        all_positions = self.get_positions()
        return [p for p in all_positions if p.period == period]

    def get_hold_positions(self) -> List[PositionRecord]:
        """获取已买入的持仓数据"""
        all_positions = self.get_positions()
        return [p for p in all_positions if getattr(p, "buy_flag", None) == "已买入"]

    def to_json(self, positions: Optional[List[PositionRecord]] = None) -> str:
        """将持仓数据转换为JSON字符串"""
        if positions is None:
            positions = self.get_positions()
        return json.dumps(
            [p.to_dict() for p in positions],
            ensure_ascii=False,
            indent=2
        )


class BitableReadError(Exception):
    """Bitable读取错误异常"""
    pass


def read_positions(
    app_token: str = None,
    table_id: str = None,
    limit: int = 100
) -> List[PositionRecord]:
    """
    便捷函数：读取飞书 Bitable 持仓数据

    Args:
        app_token: 飞书应用Token（默认从 _local_constants 读取）
        table_id: 数据表ID（默认从 _local_constants 读取）
        limit: 最大记录数

    Returns:
        PositionRecord 列表
    """
    reader = BitableReader(app_token, table_id, limit)
    return reader.get_positions()


if __name__ == "__main__":
    # 测试代码
    try:
        reader = BitableReader()
        positions = reader.get_positions()
        print(f"成功读取 {len(positions)} 条持仓记录:")
        for pos in positions:
            print(f"  {pos.stock_name}({pos.stock_code}): {pos.quantity}股, 现价{pos.current_price}, 涨跌{pos.change_pct}%")
    except BitableReadError as e:
        print(f"读取失败: {e}")
