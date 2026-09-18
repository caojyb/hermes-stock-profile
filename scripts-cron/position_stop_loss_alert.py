#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实持仓统一决策（Phase 5）
============================
从飞书 Bitable 读取真实持仓，经统一 DecisionEngine 归一为 HOLD/REDUCE/SELL/ADD
+ current/target/delta 仓位建议。只建议，不自动交易。

现有止损参数（-8% 固定 / ATR×2 / 跌破MA20 / 移动止盈）完整保留，只归一为
Exit Assessment 输入 DecisionEngine，不再由本脚本独立拍板（消除第二决策中心）。

用法：
  python3 position_stop_loss_alert.py              # 标准输出
  python3 position_stop_loss_alert.py --send  # 推送到飞书
"""
import os
import sys
import json
import subprocess
import sqlite3
import urllib.request
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert')
from stock_db_paths import get_db_path

MARKET_DB = str(get_db_path('market_cache'))

# 飞书
FEISHU_SENDER = str(SCRIPT_DIR.parent / 'skills/stock/stock-expert/skills/feishu-bitable/feishu_sender.py')
import decision._local_constants as _local_constants
import sys as _hb_sys
_hb_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from heartbeat import write as _hb_write
FEISHU_CHAT_ID = _local_constants.FEISHU_CHAT_ID
BITABLE_TOKEN = _local_constants.BITABLE_BASE_TOKEN
TABLE_ID = _local_constants.BITABLE_TABLE_ID
TOTAL_CAPITAL = 1_000_000

# 止损参数（Phase 5 不修改，仅作为 Exit Assessment 输入）
FIXED_STOP_LOSS_PCT = 0.08       # 固定 -8% 止损
ATR_STOP_MULTIPLIER = 2.0        # ATR × 2 动态止损
TRAILING_STOP_ACTIVATE = 0.15    # 盈利超过 15% 后启动移动止盈
TRAILING_STOP_RETRACE = 0.10     # 高点回落 10% 止盈


def _get_feishu_token() -> str:
    """获取 tenant_access_token"""
    app_id = app_secret = None
    # stock profile 的凭据在 profiles/stock/.env（全局 ~/.hermes/.env 已无 FEISHU 凭据）
    env_path = Path.home() / ".hermes" / "profiles" / "stock" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
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


def _bitable_list_records(base_token: str, table_id: str, token: str) -> list:
    """直接调用飞书 Bitable REST API 获取记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records?page_size=100"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data.get("data", {}).get("items", [])


def get_real_positions():
    """从飞书 Bitable 读取真实持仓"""
    try:
        token = _get_feishu_token()
        records = _bitable_list_records(BITABLE_TOKEN, TABLE_ID, token)
        if not records:
            return []

        positions = []
        for rec in records:
            fields = rec.get('fields', {})
            code = str(fields.get('股票ID', '')).strip()
            name = str(fields.get('name', '')).strip()
            cost_price = float(fields.get('买入价格') or 0)
            current_price = float(fields.get('现价') or 0)
            buy_status = fields.get('是否买入', '')
            shares_raw = fields.get('买入数量')
            buy_date = ''
            buy_time = fields.get('买入时间')
            if buy_time is not None:
                buy_date = str(buy_time)
            sector = str(fields.get('sector', '') or '').strip()

            if buy_status == '已买入':
                shares = 0
                if shares_raw is not None:
                    try:
                        shares = int(float(str(shares_raw).replace(',', '')))
                    except (ValueError, TypeError):
                        shares = 0
                positions.append({
                    'code': code, 'name': name,
                    'cost_price': cost_price, 'current_price': current_price,
                    'shares': shares, 'buy_date': buy_date, 'sector': sector,
                })
        return positions
    except Exception as e:
        print(f"[WARN] Bitable 读取失败: {e}")
        return None


def get_market_data(codes):
    """从 market_cache.db 获取最新价格和 ATR"""
    if not codes:
        return {}
    conn = sqlite3.connect(MARKET_DB, timeout=60)
    cur = conn.cursor()
    data = {}
    for code in codes:
        cur.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
        close_row = cur.fetchone()
        close_price = float(close_row[0]) if close_row and close_row[0] else 0

        cur.execute("SELECT atr_14, ma20 FROM indicators WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
        ind_row = cur.fetchone()
        atr = float(ind_row[0]) if ind_row and ind_row[0] else None
        ma20 = float(ind_row[1]) if ind_row and ind_row[1] else None

        cur.execute("SELECT MAX(high) FROM klines WHERE code=? ORDER BY date DESC LIMIT 60", (code,))
        high_row = cur.fetchone()
        high_60d = float(high_row[0]) if high_row and high_row[0] else None

        data[code] = {'price': close_price, 'atr_14': atr, 'ma20': ma20, 'high_60d': high_60d}
    conn.close()
    return data


def _exit_assessment(p, mkt):
    """现有止损逻辑 → Exit Assessment（参数不修改）。返回 (exit_signal, exit_triggers, reasons)。"""
    cost, shares = p['cost_price'], p['shares']
    current_price = mkt.get('price', p['current_price'])
    if cost <= 0 or shares <= 0 or current_price <= 0:
        return 'NONE', [], []
    pnl_pct = (current_price - cost) / cost
    atr, ma20, high_60d = mkt.get('atr_14'), mkt.get('ma20'), mkt.get('high_60d')
    triggers, reasons = [], []
    if pnl_pct <= -FIXED_STOP_LOSS_PCT:
        triggers.append('STOP_LOSS'); reasons.append(f'固定止损 -{FIXED_STOP_LOSS_PCT*100:.0f}%')
    if atr and atr > 0:
        atr_stop = cost - atr * ATR_STOP_MULTIPLIER
        if current_price <= atr_stop:
            triggers.append('STOP_LOSS'); reasons.append('ATR动态止损')
    if ma20 and ma20 > 0 and current_price < ma20:
        pct_below = (ma20 - current_price) / ma20 * 100
        if pct_below > 3:
            triggers.append('MA20_BREAK'); reasons.append('跌破MA20')
    if pnl_pct > TRAILING_STOP_ACTIVATE:
        peak = max(cost * (1 + TRAILING_STOP_ACTIVATE), high_60d or current_price)
        retrace = (peak - current_price) / peak if peak > 0 else 0
        if retrace >= TRAILING_STOP_RETRACE:
            triggers.append('TRAILING_STOP'); reasons.append('移动止盈')
    return ('RISK' if triggers else 'NONE'), triggers, reasons


def _portfolio_context(snap):
    """从 Real Portfolio Snapshot 提取 Portfolio context（真实数据，不读 simulation）。
    返回 (position_count, sector_counts, total_mv, drawdown_status, drawdown)。"""
    p = snap.get('portfolio', {})
    total_mv = p.get('total_holdings_value') or p.get('holdings_value') or 0
    return (p.get('position_count', 0), p.get('sector_exposure', {}),
            total_mv, p.get('drawdown_status', 'UNKNOWN'), p.get('drawdown'))


def build_position_decision(p, mkt, regime, permission, snap, total_capital=None):
    """单只真实持仓 → 统一 Decision（HOLD/REDUCE/SELL/ADD + 仓位建议）。
    使用 Real Portfolio Snapshot（真实数据），不读 simulation。"""
    if total_capital is None:
        total_capital = snap.get('portfolio', {}).get('total_asset') or TOTAL_CAPITAL
    from decision.contract import EXIT_NONE
    from decision.engine import DecisionEngine
    from decision.adapters import position_ctx
    from decision.portfolio import assess_portfolio
    from decision import snapshot as snap_mod
    code, name = p['code'], p['name']
    cur_price = mkt.get('price', p.get('current_price', p.get('current_price', 0))) or 0
    market_value = p.get('quantity', p.get('shares', 0)) * cur_price
    pos_count, sector_counts, total_mv, drawdown_status, drawdown = _portfolio_context(snap)
    # current_position：真实仓总资产缺失 → 用相对持仓市值口径（明确标注非总资产占比）
    current_position = market_value / total_mv if total_mv > 0 else 0.0

    exit_signal, exit_triggers, reasons = _exit_assessment(p, mkt)

    pa = assess_portfolio(candidate_sector=p.get('sector', ''), target_position=0,
                          total_capital=total_capital, position_count=pos_count, max_positions=20,
                          max_position_pct=0.05, max_sector_cnt=3, sector_counts=sector_counts,
                          drawdown=drawdown, drawdown_limit=0.15, drawdown_status=drawdown_status)

    eng = DecisionEngine(strategy='v1_double', config_version='phase1', code_version='real_portfolio_p55')
    ref_p = p.get('current_price')
    if ref_p is None and cur_price:
        ref_p = cur_price
    ctx = position_ctx(
        symbol=code, name=name, regime_label=regime['label'], regime_score=regime['score'],
        permission=permission, permission_status=permission['status'],
        data_health='VALID', exit_signal=exit_signal, exit_triggers=exit_triggers,
        drawdown=drawdown or 0, position_count=pos_count, current_exposure=current_position,
        current_position=current_position,
        portfolio_risk='OK' if pa['allowed'] else 'BLOCKED', portfolio_assessment=pa,
        entry_signal='NONE', as_of_time=snap.get('as_of_time', ''),
        portfolio_snapshot_id=snap.get('snapshot_id', ''),
        portfolio_source=snap.get('source', ''),
        portfolio_as_of_time=snap.get('as_of_time', ''),
        reference_price=ref_p if ref_p is not None else 0.0,
        target_position=0.0 if exit_signal != EXIT_NONE else current_position,
    )
    dec = eng.decide(ctx)

    # 记录 execution + outcome，补全 lifecycle
    try:
        from decision.execution import record_simulation_execution, record_sim_exit_and_outcome, _normalize_action
        entry_price = p.get('current_price', 0)
        qty = p.get('shares', 0)
        if qty > 0 and entry_price > 0:
            _d = {
                'decision_id': dec.decision_id,
                'symbol': dec.symbol,
                'name': dec.name,
                'reference_price': entry_price,
                'target_position': qty * entry_price,
                'reason_codes': list(dec.reason_codes),
                'timestamp': getattr(dec, 'timestamp', ''),
                'market_regime': getattr(dec, 'market_regime', '') or getattr(dec, 'regime_label', ''),
            }
            if _normalize_action(dec.action) in ('SELL', 'REDUCE', 'EXIT'):
                eid = record_simulation_execution(
                    decision=_d, action=dec.action, entry_price=entry_price,
                    quantity=qty, position=0.0, status='CLOSED',
                    run_mode='SIMULATION', environment='STOP_LOSS_ALERT')
                try:
                    record_sim_exit_and_outcome(
                        symbol=dec.symbol, exit_price=entry_price, exit_quantity=qty,
                        exit_reason='|'.join(dec.reason_codes) or 'stop_loss_alert',
                        decision_id=dec.decision_id, entry_execution_id=eid,
                        exit_regime=_d.get('market_regime', ''))
                except Exception as _out_e:
                    print(f"[WARN] outcome record failed for {dec.symbol}: {_out_e}")
            else:
                record_simulation_execution(
                    decision=_d, action=dec.action, entry_price=entry_price,
                    quantity=qty, position=0.0, status='EXECUTED',
                    run_mode='SIMULATION', environment='STOP_LOSS_ALERT')
    except Exception as _exec_e:
        print(f"[WARN] execution record failed: {_exec_e}")
    snap_mod.save_snapshot(dec)
    # ── Phase 8-K1: persistence self-check + 受控重试 + 醒目失败告警 ──
    # 顺序锁定：Decision → Snapshot → Verify → Delivery。不重算 Decision，不改 decision_id。
    _p_status = 'UNKNOWN'
    try:
        from decision.snapshot_verify import persist_with_verification, format_persistence_failure
        _p_status, _p_info = persist_with_verification(dec)
        if _p_status == 'FAILED':
            print(format_persistence_failure(
                dec.symbol, dec.action, dec.decision_id, _p_info,
                timestamp=dec.timestamp))
            print("  标记: DECISION_PERSISTENCE_FAILED")
        else:
            print(f"  [PERSIST] {_p_status}: {_p_info}")
    except Exception as _pv_e:
        _p_status = 'FAILED'
        print(f"🚨 FINAL DECISION PERSISTENCE FAILED 🚨 (verify module error): {_pv_e}")
        print("  标记: DECISION_PERSISTENCE_FAILED")
    return dec, reasons


def run_decision():
    """读取真实持仓 → 构建 Real Portfolio Snapshot → 逐只统一 Decision → 返回 decisions。"""
    sys.path.insert(0, str(SCRIPT_DIR))
    positions = get_real_positions()
    if positions is None:
        print("[ERROR] Bitable 读取失败，无法获取持仓")
        sys.exit(1)
    if not positions:
        print("⚠️ 无真实持仓数据，跳过")
        return []
    # 构建 Real Portfolio Snapshot（真实数据，不读 simulation）
    from decision.real_portfolio_truth import build_real_snapshot
    holdings = [{'code': p['code'], 'name': p['name'], 'quantity': p['shares'],
                 'avg_cost': p['cost_price'], 'current_price': p['current_price'],
                 'sector': p.get('sector', '')} for p in positions]
    snap = build_real_snapshot(holdings=holdings, source='bitable')
    if not snap.get('ok'):
        print(f"[ERROR] Real snapshot 构建失败: {snap.get('error')}")
        sys.exit(1)
    _snap_holdings = snap.get('holdings', []) or []
    if len(_snap_holdings) != len(positions):
        print(f"🚨 HOLDINGS_CONTEXT_MISMATCH: bitable读取={len(positions)} vs "
              f"snapshot持仓={len(_snap_holdings)} — 持仓上下文残缺，拒绝出建议")
        sys.exit(1)
    _zero_qty = [h for h in _snap_holdings if (h.get('quantity') or 0) <= 0]
    if _zero_qty:
        print(f"🚨 QUANTITY_ZERO: {[(h['symbol'], h['name']) for h in _zero_qty]} "
              f"— 持仓数量解析为0，拒绝出建议")
        sys.exit(1)
    # 2026-09-18 三轮: 用户确认成本真实（ratio 大是实际盈亏），成本异常不再硬失败。
    # 保留: build_real_snapshot 内的 WARNING 打印（醒目但不拦截）。
    # 仅 quantity<=0 / 持仓数不一致（上方）仍硬失败——那才是真正的解析层错误。
    codes = [p['code'] for p in positions]
    market_data = get_market_data(codes)
    # regime + permission
    from trading_permission import evaluate as tp_eval, classify_data_health
    from stock_strategy_config import get_market_env_scale
    from datetime import datetime as dt
    scale, label, total = get_market_env_scale()
    conn = sqlite3.connect(MARKET_DB, timeout=60)
    mx = conn.execute("SELECT MAX(date) FROM klines").fetchone()[0]
    lag = (date.today() - dt.strptime(str(mx)[:10], '%Y-%m-%d').date()).days if mx else 999
    conn.close()
    dh = classify_data_health(timing_ok=True, kline_lag_days=lag)
    permission = tp_eval(regime_label=label, timing_safe=True, timing_ok=True, data_health=dh,
                         position_count=snap.get('portfolio', {}).get('position_count', 0),
                         max_positions=20)
    regime = {'label': label, 'score': total or 0}
    decisions = []
    for p in positions:
        dec, reasons = build_position_decision(p, market_data.get(p['code'], {}), regime, permission,
                                               snap, TOTAL_CAPITAL)
        decisions.append({'decision': dec, 'exit_reasons': reasons})
    # 落盘到 Decision Snapshots，供 daily_decision_contract 读入
    # （Phase 8-K1: canonical writer = decision/snapshot.save_snapshot，
    #   每只决策经 persist_with_verification 自校验；失败在 build_position_decision 内醒目告警）
    persistence_failed = []
    try:
        from decision.snapshot import save_snapshot
        from decision.snapshot_verify import persist_with_verification, format_persistence_failure
        for item in decisions:
            dec = item['decision']
            _st, _info = persist_with_verification(dec)
            if _st == 'FAILED':
                persistence_failed.append(dec.decision_id)
                print(format_persistence_failure(
                    dec.symbol, dec.action, dec.decision_id, _info, timestamp=dec.timestamp))
    except Exception as _e:
        print(f"[WARN] snapshot save failed: {_e}")
        for item in decisions:
            persistence_failed.append(item['decision'].decision_id)
    if persistence_failed:
        print(f"  ⚠️ DECISION_PERSISTENCE_FAILED x{len(persistence_failed)}: {persistence_failed}")
    return decisions


def format_decisions(decisions):
    """格式化统一 Position Decision（只建议）。"""
    if not decisions:
        return ""
    # Phase 8-K2: URGENT·FINAL 层级标签（决策来自 DecisionEngine，含 decision_id）
    from decision.presentation import LABEL_URGENT, sanitize_user_surface
    lines = [f"{LABEL_URGENT} 📊 **真实持仓统一决策** | {date.today()}", "=" * 55]
    for item in decisions:
        d = item['decision']
        action = d.action
        icon = {'HOLD': '🟢', 'SELL': '🔴', 'REDUCE': '🟠', 'ADD': '🟡'}.get(action, '⚪')
        lines.append(f"{icon} {d.symbol} {d.name} → **{action}**")
        lines.append(f"   当前仓位: {d.current_position*100:.1f}% → 目标: {d.target_position*100:.1f}% (Δ{d.delta_position*100:+.1f}%)")
        lines.append(f"   原因: {', '.join(d.reason_codes)}")
        if item['exit_reasons']:
            lines.append(f"   触发: {' | '.join(item['exit_reasons'])}")
        lines.append(f"   Decision ID: {d.decision_id}")
    lines.append("=" * 55)
    lines.append("仅建议，不自动交易。请人工在券商确认。")
    text, _removed = sanitize_user_surface('\n'.join(lines))
    return text


def send_feishu(text):
    try:
        sys.path.insert(0, str(SCRIPT_DIR.parent / 'skills/stock/stock-expert/skills/feishu-bitable'))
        from feishu_sender import feishu_send_message
        feishu_send_message(FEISHU_CHAT_ID, text)
        print("✅ 已推送到飞书")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")


def main():
    send = '--send' in sys.argv
    today_str = date.today().isoformat()
    print(f"📊 真实持仓统一决策 | {today_str}")
    decisions = run_decision()
    if not decisions:
        return
    report = format_decisions(decisions)
    print(report)
    try:
        _hb_write('position-stop-loss-alert', 'ok', detail=f'decisions={len(decisions)}', expected_interval_seconds=86400)
    except Exception as _e:
        print(f"[EXC] stop_loss_alert.heartbeat: {type(_e).__name__}: {_e}")
    # 只对非 HOLD 告警（HOLD 静默）
    actionable = [i for i in decisions if i['decision'].action != 'HOLD']
    if send and actionable:
        send_feishu(report)


if __name__ == '__main__':
    main()