#!/usr/bin/env python3
"""
weekly_pool_report.py — 推荐池每周跟踪报告
生成各档位胜率/盈亏比/最大回撤统计，输出到飞书群

用法:
  python3 weekly_pool_report.py              # 生成完整报告（含更新价格）
  python3 weekly_pool_report.py --no-update  # 不更新价格，直接生成报告
  python3 weekly_pool_report.py --days 14    # 统计最近14天推荐
"""
import sys
import os
import sqlite3
import json
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / 'stock-work'))
from pathlib import Path
import sys
# Resolve the Hermes stock profile root dynamically so this works
# regardless of how deeply nested the script is under profiles/stock/.
_profile_root = None
for parent in Path(__file__).resolve().parents:
    if parent.name == 'stock' and parent.parent.name == 'profiles':
        _profile_root = parent
        break
if _profile_root is None:
    raise RuntimeError('Cannot locate Hermes stock profile root')
_STOCK_WORK = _profile_root / 'stock-work'
if str(_STOCK_WORK) not in sys.path:
    sys.path.insert(0, str(_STOCK_WORK))
from core.bootstrap import ensure_stock_work_root
ensure_stock_work_root()

from core.compat_paths import RECOMMENDATION_POOL_DB as _STOCK_RECOMMENDATION_POOL_DB
from core.compat_paths import MARKET_DB as _STOCK_MARKET_DB

# ── 路径配置 ──────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent
POOL_DB = _STOCK_RECOMMENDATION_POOL_DB
MARKET_DB = _STOCK_MARKET_DB

# 飞书群ID
FEISHU_GROUP = 'oc_6825e1438c41d1b7251b1698ea3be4fe'


def update_prices():
    """更新推荐池中所有股票的价格和状态"""
    conn = sqlite3.connect(POOL_DB)
    cur = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    today = date.today().isoformat()

    # 获取所有active的推荐
    cur.execute("""
        SELECT id, code, entry_price, stop_loss, take_profit_1, take_profit_2,
               entry_date, hold_days_max
        FROM recommendations
        WHERE status = 'active'
    """)

    updated = 0
    for row in cur.fetchall():
        (id_, code, entry_price, stop_loss, tp1, tp2,
         entry_date, hold_days_max) = row

        # 从缓存或实时获取价格
        price = get_price_from_cache(code)
        if not price:
            price = get_current_price(code)

        if not price:
            continue

        days_held = (date.today() - date.fromisoformat(entry_date)).days
        pnl_pct = (price - entry_price) / entry_price * 100

        # 判断状态
        status = 'active'
        notes = ''
        if price <= stop_loss:
            status = 'hit_stop_loss'
            notes = f'触及止损({stop_loss:.2f})'
        elif price >= tp2:
            status = 'hit_tp2'
            notes = f'达成目标2({tp2:.2f}), +{pnl_pct:.1f}%'
        elif price >= tp1:
            status = 'hit_tp1'
            notes = f'达成目标1({tp1:.2f}), +{pnl_pct:.1f}%'
        elif days_held > hold_days_max:
            status = 'expired'
            notes = f'超时持有{days_held}天, +{pnl_pct:.1f}%'

        cur.execute("""
            UPDATE recommendations SET
                current_price = ?, days_held = ?, pnl_pct = ?,
                status = ?, notes = ?, updated_at = ?
            WHERE id = ?
        """, (price, days_held, pnl_pct, status, notes, now_str, id_))
        updated += 1

    conn.commit()
    conn.close()
    return updated


def get_price_from_cache(code):
    """从缓存获取最新价格"""
    try:
        conn = sqlite3.connect(MARKET_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT current_price FROM indicators
            WHERE code = ? AND date = (SELECT MAX(date) FROM indicators)
        """, (code,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def get_current_price(code):
    """从腾讯财经获取实时价格"""
    try:
        import urllib.request
        import re
        market = 'sh' if code.startswith(('6', '601', '603', '605', '688')) else 'sz'
        full = f"{market}{code}"
        url = f"https://qt.gtimg.cn/q={full}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode('gbk', errors='replace')
        match = re.search(r'="([^"]+)"', text)
        if not match:
            return None
        parts = match.group(1).split('~')
        if len(parts) > 3:
            price = parts[3].strip()
            if price and price not in ('', '-', 'N/A'):
                return float(price)
    except Exception:
        pass
    return None


def generate_report(days: int = 7) -> str:
    """
    生成推荐池跟踪报告，按档位统计胜率/盈亏比/最大回撤
    """
    conn = sqlite3.connect(POOL_DB)
    cur = conn.cursor()
    today = date.today().isoformat()
    since = (date.today() - timedelta(days=days)).isoformat()

    lines = [
        "📊 **推荐池跟踪周报**",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"统计范围: 最近{days}天 ({since} ~ {today})",
        "",
    ]

    # ── 1. 整体概览 ────────────────────────────────────────
    cur.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status IN ('hit_tp1','hit_tp2') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status = 'hit_stop_loss' THEN 1 ELSE 0 END) as losses,
               SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
               SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) as expired
        FROM recommendations
        WHERE entry_date >= ?
    """, (since,))
    total, wins, losses, active, expired = cur.fetchone()
    total = total or 0
    wins = wins or 0
    losses = losses or 0
    active = active or 0
    expired = expired or 0

    closed = wins + losses + expired
    win_rate = (wins / closed * 100) if closed > 0 else 0

    lines.append("**【整体统计】**")
    lines.append(f"  总推荐: {total}只")
    lines.append(f"  已完结: {closed}只（止盈{wins} / 止损{losses} / 超时{expired}）")
    lines.append(f"  进行中: {active}只")
    lines.append(f"  🏆 胜率: {win_rate:.1f}% ({wins}/{closed})" if closed > 0 else "  🏆 胜率: N/A")
    lines.append("")

    # ── 2. 各档位详细统计 ──────────────────────────────────
    lines.append("**【各档位表现】**")

    cur.execute("""
        SELECT tier, 
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('hit_tp1','hit_tp2') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status = 'hit_stop_loss' THEN 1 ELSE 0 END) as losses,
               SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
               SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) as expired,
               AVG(CASE WHEN status IN ('hit_tp1','hit_tp2') THEN pnl_pct ELSE NULL END) as avg_win_pnl,
               AVG(CASE WHEN status = 'hit_stop_loss' THEN pnl_pct ELSE NULL END) as avg_loss_pnl,
               MAX(pnl_pct) as max_pnl,
               MIN(pnl_pct) as min_pnl
        FROM recommendations
        WHERE entry_date >= ?
        GROUP BY tier
        ORDER BY tier
    """, (since,))

    tier_rows = cur.fetchall()
    if not tier_rows:
        lines.append("  （暂无推荐记录）")
    else:
        for row in tier_rows:
            tier, t_total, t_wins, t_losses, t_active, t_expired, avg_win, avg_loss, max_pnl, min_pnl = row
            t_total = t_total or 0
            t_wins = t_wins or 0
            t_losses = t_losses or 0
            t_active = t_active or 0
            t_expired = t_expired or 0
            t_closed = t_wins + t_losses + t_expired
            t_win_rate = (t_wins / t_closed * 100) if t_closed > 0 else 0

            # 盈亏比
            avg_win = abs(avg_win or 0)
            avg_loss = abs(avg_loss or 0)
            rr = avg_win / max(avg_loss, 0.1) if avg_loss > 0 else (avg_win / 0.1 if avg_win > 0 else 0)

            # 最大回撤（所有记录的浮亏最大值）
            max_drawdown = abs(min_pnl) if min_pnl and min_pnl < 0 else 0

            tier_emoji = {'激进档': '🔥', '稳健档': '⚡', '价值档': '💰', '关注档': '👀', '盘中推荐': '📡'}.get(tier, '📌')

            lines.append(f"  {tier_emoji} **{tier}**")
            lines.append(f"    总推荐: {t_total}只 | 完结: {t_closed}只")
            lines.append(f"    止盈: {t_wins} | 止损: {t_losses} | 超时: {t_expired} | 进行中: {t_active}")
            lines.append(f"    🏆 胜率: {t_win_rate:.1f}%")
            lines.append(f"    📐 盈亏比: {rr:.2f} (平均止盈+{avg_win:.1f}% / 平均止损{avg_loss:.1f}%)")
            if max_drawdown > 0:
                lines.append(f"    📉 最大回撤: {max_drawdown:.1f}%")
            if max_pnl:
                lines.append(f"    🚀 最高收益: {max_pnl:+.1f}%")
            if min_pnl:
                lines.append(f"    💀 最低收益: {min_pnl:+.1f}%")

            # Kelly公式
            if t_closed > 0:
                w = t_win_rate / 100
                r = rr
                kelly = (w - (1 - w) / max(r, 0.1)) * 100
                kelly_cap = max(min(kelly, 10), -20)
                lines.append(f"    🎯 Kelly仓位: {kelly_cap:+.1f}%")
            lines.append("")

    # ── 3. 本周最佳/最差推荐 ───────────────────────────────
    lines.append("**【本周最佳推荐】**")
    cur.execute("""
        SELECT code, name, tier, pnl_pct, notes
        FROM recommendations
        WHERE entry_date >= ? AND status IN ('hit_tp1', 'hit_tp2')
        ORDER BY pnl_pct DESC
        LIMIT 3
    """, (since,))
    best = cur.fetchall()
    if best:
        for b in best:
            lines.append(f"  🎯 {b[1]}({b[0]}) {b[2]} | +{b[3]:.1f}% | {b[4]}")
    else:
        lines.append("  （本周暂无止盈记录）")
    lines.append("")

    lines.append("**【本周最差推荐】**")
    cur.execute("""
        SELECT code, name, tier, pnl_pct, notes
        FROM recommendations
        WHERE entry_date >= ? AND status = 'hit_stop_loss'
        ORDER BY pnl_pct ASC
        LIMIT 3
    """, (since,))
    worst = cur.fetchall()
    if worst:
        for w in worst:
            lines.append(f"  ⛔ {w[1]}({w[0]}) {w[2]} | {w[3]:.1f}% | {w[4]}")
    else:
        lines.append("  （本周无止损记录）")
    lines.append("")

    # ── 4. 活跃推荐（持仓超时预警）──────────────────────────
    lines.append("**【进行中 & 超时预警】**")
    cur.execute("""
        SELECT code, name, tier, entry_price, current_price, pnl_pct, days_held, hold_days_max, status
        FROM recommendations
        WHERE entry_date >= ? AND status = 'active'
        ORDER BY days_held DESC
        LIMIT 10
    """, (since,))
    active_recs = cur.fetchall()
    if active_recs:
        for r in active_recs:
            code, name, tier, ep, cp, pnl, days, max_days, status = r
            pnl_emoji = '🟢' if (pnl or 0) > 0 else '🔴'
            warn = " ⏰超时!" if (days or 0) > (max_days or 0) else ""
            lines.append(f"  {pnl_emoji} {name}({code}) {tier} | {pnl:+.1f}% | 持有{days}/{max_days}天{warn}")
    else:
        lines.append("  （无进行中推荐）")
    lines.append("")

    # ── 5. 改进建议 ────────────────────────────────────────
    lines.append("**【改进建议】**")
    suggestions = []

    # 分析各档位表现
    for row in tier_rows:
        tier, t_total, t_wins, t_losses, t_active, t_expired, avg_win, avg_loss, max_pnl, min_pnl = row
        t_total = t_total or 0
        t_wins = t_wins or 0
        t_losses = t_losses or 0
        t_closed = t_wins + t_losses + (t_expired or 0)
        if t_closed < 2:
            continue
        t_win_rate = (t_wins / t_closed * 100) if t_closed > 0 else 0
        avg_win = abs(avg_win or 0)
        avg_loss = abs(avg_loss or 0)
        rr = avg_win / max(avg_loss, 0.1) if avg_loss > 0 else (avg_win / 0.1 if avg_win > 0 else 0)

        if t_win_rate < 40:
            suggestions.append(f"  ⚠️ {tier}胜率仅{t_win_rate:.0f}%，建议收紧筛选条件或提高RSI阈值")
        elif t_win_rate > 70:
            suggestions.append(f"  ✅ {tier}胜率{t_win_rate:.0f}%表现优秀，可维持当前策略")

        if rr < 1.0:
            suggestions.append(f"  ⚠️ {tier}盈亏比{rr:.1f}<1，建议缩小止盈/扩大止损")
        elif rr > 2.0:
            suggestions.append(f"  ✅ {tier}盈亏比{rr:.1f}良好，收益风险比优秀")

    if active > 10:
        suggestions.append(f"  ⚠️ 活跃持仓{active}只偏多，建议暂停新推荐，优先处理已有持仓")
    elif active > 5:
        suggestions.append(f"  ⚡ 活跃持仓{active}只，注意控制总仓位")

    if suggestions:
        lines.extend(suggestions)
    else:
        lines.append("  数据不足，暂无法生成建议")

    conn.close()
    return '\n'.join(lines)


def send_to_feishu(text):
    """发送报告到飞书群"""
    import urllib.request
    token = os.environ.get("FEISHU_BOT_TOKEN", "")
    if not token:
        # 尝试从hermes secrets获取
        try:
            import subprocess
            result = subprocess.run(
                ["hermes", "secrets", "get", "FEISHU_BOT_TOKEN"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                token = result.stdout.strip()
        except Exception:
            pass

    if not token:
        print("⚠️ 未设置 FEISHU_BOT_TOKEN，仅输出到控制台")
        print(text)
        return

    # 飞书群Webhook
    url = "https://open.feishu.cn/open-apis/bot/v2/hook/" + token
    payload = {
        "msg_type": "text",
        "content": {"text": text}
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
        if result.get("code") == 0:
            print("✅ 报告已推送到飞书群")
        else:
            print(f"⚠️ 飞书推送返回: {result}")
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")
        print(text)


if __name__ == '__main__':
    # 解析参数
    no_update = '--no-update' in sys.argv
    days = 7
    for i, arg in enumerate(sys.argv):
        if arg == '--days' and i + 1 < len(sys.argv):
            try:
                days = int(sys.argv[i + 1])
            except ValueError:
                pass

    # 1. 更新价格
    if not no_update:
        print(f"更新推荐池价格...")
        updated = update_prices()
        if updated:
            print(f"已更新 {updated} 条推荐价格")
        else:
            print("无活跃推荐需要更新")

    # 2. 生成报告
    print(f"生成最近{days}天推荐跟踪报告...")
    report = generate_report(days=days)
    print(report)

    # 3. 推送到飞书
    print("\n推送报告到飞书群...")
    send_to_feishu(report)
