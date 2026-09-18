#!/usr/bin/env python3
"""
recommendation_pool.py — Phase 3: 推荐股票池追踪系统
追踪所有推荐股票的后续表现，每周汇总报告

用法:
  python3 recommendation_pool.py track     # 记录当前推荐
  python3 recommendation_pool.py report   # 生成追踪报告
  python3 recommendation_pool.py check   # 检查推荐股表现
"""

import sys
import os
sys.path.insert(0, '/home/caojy/.hermes/profiles/stock/skills/stock/stock-expert/skills/feishu-bitable')

import sqlite3
import json
import time
import requests
from datetime import date, datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path

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

from core.compat_paths import (
    MARKET_DB as _STOCK_MARKET_DB,
    RECOMMENDATION_POOL_DB as _STOCK_RECOMMENDATION_POOL_DB,
)

DB_PATH = _STOCK_MARKET_DB
POOL_DB = _STOCK_RECOMMENDATION_POOL_DB
PROXIES = {"http": "socks5://127.0.0.1:10808", "https": "socks5://127.0.0.1:10808"}


@dataclass
class TrackedRecommendation:
    """追踪的推荐"""
    code: str
    name: str
    tier: str                    # '激进档'/'稳健档'/'价值档'
    tier_type: str               # '超跌反弹'/'主升浪'/'价值投资'
    entry_price: float          # 买入价格
    entry_date: str             # 买入日期
    stop_loss: float            # 止损价
    take_profit_1: float        # 第一止盈价
    take_profit_2: float        # 第二止盈价
    hold_days_max: int          # 最长持有天数
    max_position_pct: float     # 建议仓位
    current_price: float = 0     # 当前价
    days_held: int = 0          # 持有天数
    pnl_pct: float = 0          # 盈亏%
    status: str = 'active'      # 'active'/'hit_stop_loss'/'hit_tp1'/'hit_tp2'/'expired'
    notes: str = ''


def init_pool_db():
    """初始化推荐池数据库"""
    conn = sqlite3.connect(POOL_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            tier TEXT,
            tier_type TEXT,
            entry_price REAL,
            entry_date TEXT,
            stop_loss REAL,
            take_profit_1 REAL,
            take_profit_2 REAL,
            hold_days_max INTEGER,
            max_position_pct REAL,
            current_price REAL,
            days_held INTEGER DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        
        CREATE INDEX IF NOT EXISTS idx_status ON recommendations(status);
        CREATE INDEX IF NOT EXISTS idx_code ON recommendations(code);
        CREATE INDEX IF NOT EXISTS idx_tier ON recommendations(tier);
    """)
    conn.commit()
    conn.close()


def get_current_price(code: str) -> Optional[float]:
    """获取单只股票当前价格（腾讯财经）"""
    try:
        market = 'sh' if code.startswith(('6', '601', '603', '605', '688')) else 'sz'
        full = f"{market}{code}"
        url = f"https://qt.gtimg.cn/q={full}"
        r = requests.get(url, timeout=5, proxies=PROXIES)
        text = r.text
        
        import re
        match = re.search(r'="([^"]+)"', text)
        if not match:
            return None
        parts = match.group(1).split('~')
        if len(parts) > 3:
            price = parts[3].strip()
            if price and price not in ('', '-', 'N/A'):
                return float(price)
    except:
        pass
    return None


def get_price_from_cache(code: str) -> Optional[float]:
    """从缓存获取最新价格"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT current_price FROM indicators
        WHERE code = ? AND date = (SELECT MAX(date) FROM indicators)
    """, (code,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def track_recommendations(recs: List, source: str = 'auto_recommend'):
    """记录推荐到追踪池"""
    conn = sqlite3.connect(POOL_DB)
    cur = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    tracked = 0
    for rec in recs:
        # 检查是否已存在（相同代码+档位+当天）
        cur.execute("""
            SELECT id FROM recommendations
            WHERE code = ? AND tier = ? AND entry_date = ?
        """, (rec.code, rec.tier, date.today().isoformat()))
        
        if cur.fetchone():
            # 更新
            # 注意：字段顺序与 UPDATE SET 后的列顺序一致
            # SET entry_price=?, current_price=?  →  填 rec.buy_price, rec.current_price
            cur.execute("""
                UPDATE recommendations SET
                    entry_price = ?, current_price = ?,
                    stop_loss = ?, take_profit_1 = ?, take_profit_2 = ?,
                    hold_days_max = ?, max_position_pct = ?, updated_at = ?
                WHERE code = ? AND tier = ? AND entry_date = ?
            """, (rec.buy_price, rec.current_price,
                  rec.stop_loss, rec.take_profit_1, rec.take_profit_2,
                  rec.hold_days_max, rec.max_position_pct, now_str,
                  rec.code, rec.tier, date.today().isoformat()))
        else:
            # 插入新推荐
            cur.execute("""
                INSERT INTO recommendations
                (code, name, tier, tier_type, entry_price, entry_date,
                 stop_loss, take_profit_1, take_profit_2, hold_days_max,
                 max_position_pct, current_price, status, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (rec.code, rec.name, rec.tier, rec.tier_type,
                  rec.buy_price, date.today().isoformat(),
                  rec.stop_loss, rec.take_profit_1, rec.take_profit_2,
                  rec.hold_days_max, rec.max_position_pct, rec.current_price,
                  'active', source, now_str, now_str))
            tracked += 1
    
    conn.commit()
    conn.close()
    print(f"已记录 {tracked} 条新推荐到追踪池")
    return tracked


def update_pool_prices():
    """更新追踪池中所有股票的价格和状态"""
    init_pool_db()
    conn = sqlite3.connect(POOL_DB)
    cur = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    today = date.today().isoformat()
    
    # 获取所有active的推荐（含 notes——更新时保留推送链元数据）
    cur.execute("""
        SELECT id, code, name, entry_price, stop_loss, take_profit_1, take_profit_2,
               entry_date, hold_days_max, tier, tier_type, max_position_pct, notes
        FROM recommendations
        WHERE status = 'active'
    """)
    
    updated = 0
    for row in cur.fetchall():
        (id_, code, name, entry_price, stop_loss, tp1, tp2,
         entry_date, hold_days_max, tier, tier_type, max_pos, row_notes) = row
        
        # 获取当前价格
        current_price = get_price_from_cache(code)
        if not current_price:
            current_price = get_current_price(code)
        
        if not current_price:
            continue
        
        # 手工验证留痕修复(2026-09-18): 原实现整列重写 notes，抹掉推送链写入的元数据
        # （source=intraday_scan/score 等），导致下游同源 SQL 失效。改为追加式保留。
        # 注意: 必须在空值防护分支之前定义（防护分支也要拼接）。
        _orig_notes = str(row_notes or '')
        
        # 计算盈亏
        days_held = (date.today() - date.fromisoformat(entry_date)).days
        pnl_pct = (current_price - entry_price) / entry_price * 100
        
        # 空值防护(2026-09-18 排查): stop_loss/take_profit_* 为 NULL 时跳过状态判定，
        # 只更新价格——避免 TypeError 崩掉整个 update 循环
        if not stop_loss or not tp1 or not tp2:
            cur.execute("""
                UPDATE recommendations SET
                    current_price = ?, days_held = ?, pnl_pct = ?,
                    status = 'active', notes = ?, updated_at = ?
                WHERE id = ?
            """, (current_price, days_held, pnl_pct,
                   (f' | {_orig_notes}' if _orig_notes else ''), now_str, id_))
            updated += 1
            continue
        
        # 判断状态
        status = 'active'
        notes = ''
        
        if current_price <= stop_loss:
            status = 'hit_stop_loss'
            notes = f'触及止损({stop_loss:.2f})'
        elif current_price >= tp2:
            status = 'hit_tp2'
            notes = f'达成目标2({tp2:.2f}), +{pnl_pct:.1f}%'
        elif current_price >= tp1:
            status = 'hit_tp1'
            notes = f'达成目标1({tp1:.2f}), +{pnl_pct:.1f}%'
        elif days_held > hold_days_max:
            status = 'expired'
            notes = f'超时持有{days_held}天, +{pnl_pct:.1f}%'
        
        # 更新（notes 追加式: 保留推送链元数据，状态描述放前面）
        _status_note = notes
        notes = f"{_status_note} | {_orig_notes}" if _orig_notes else (_status_note or _orig_notes)
        cur.execute("""
            UPDATE recommendations SET
                current_price = ?, days_held = ?, pnl_pct = ?,
                status = ?, notes = ?, updated_at = ?
            WHERE id = ?
        """, (current_price, days_held, pnl_pct, status, notes, now_str, id_))
        updated += 1
    
    conn.commit()
    conn.close()
    print(f"更新了 {updated} 条推荐的状态")
    return updated


def generate_report() -> str:
    """生成追踪报告"""
    init_pool_db()
    conn = sqlite3.connect(POOL_DB)
    cur = conn.cursor()
    
    # 统计各状态数量
    cur.execute("""
        SELECT status, COUNT(*) as cnt,
               AVG(pnl_pct) as avg_pnl,
               MAX(pnl_pct) as max_pnl,
               MIN(pnl_pct) as min_pnl
        FROM recommendations
        GROUP BY status
    """)
    status_stats = list(cur.fetchall())
    
    # 按档位统计
    cur.execute("""
        SELECT tier, status, COUNT(*) as cnt, AVG(pnl_pct) as avg_pnl
        FROM recommendations
        GROUP BY tier, status
        ORDER BY tier
    """)
    tier_stats = list(cur.fetchall())
    
    # 最近30天的活跃推荐
    cur.execute("""
        SELECT code, name, tier, tier_type, entry_price, current_price,
               pnl_pct, days_held, status, notes
        FROM recommendations
        WHERE status = 'active' AND entry_date >= date('now', '-30 days')
        ORDER BY pnl_pct DESC
        LIMIT 20
    """)
    active_recs = list(cur.fetchall())
    
    # 最近触发的推荐
    cur.execute("""
        SELECT code, name, tier, tier_type, entry_price, current_price,
               pnl_pct, status, notes, entry_date, updated_at
        FROM recommendations
        WHERE status IN ('hit_stop_loss', 'hit_tp1', 'hit_tp2')
        ORDER BY updated_at DESC
        LIMIT 10
    """)
    closed_recs = list(cur.fetchall())

    # ── Phase 4: 健康检查（afrexai框架）────────────────────────
    # 计算胜率和盈亏比（在关闭连接前先查好数据）
    cur.execute("""
        SELECT tier, status, COUNT(*) as cnt, AVG(pnl_pct) as avg_pnl
        FROM recommendations
        GROUP BY tier, status
    """)
    tier_status = list(cur.fetchall())
    tier_data = {}
    for tier, status, cnt, avg_pnl in tier_status:
        if tier not in tier_data:
            tier_data[tier] = {'total': 0, 'wins': 0, 'losses': 0,
                                'win_pnl': 0.0, 'loss_pnl': 0.0, 'active': 0}
        tier_data[tier]['total'] += cnt
        if status in ('hit_tp1', 'hit_tp2'):
            tier_data[tier]['wins'] += cnt
            tier_data[tier]['win_pnl'] += avg_pnl * cnt
        elif status == 'hit_stop_loss':
            tier_data[tier]['losses'] += cnt
            tier_data[tier]['loss_pnl'] += avg_pnl * cnt
        elif status == 'active':
            tier_data[tier]['active'] += cnt

    total_active = sum(v['active'] for v in tier_data.values())
    portfolio_heat = total_active

    # 预计算健康检查行（待会插入报告头部）
    health_lines = []
    health_lines.append("**【组合健康检查】**（afrexai Phase 4）")
    for tier, d in tier_data.items():
        if d['total'] == 0:
            continue
        win_rate = d['wins'] / max(d['wins'] + d['losses'], 1) * 100
        avg_win = d['win_pnl'] / max(d['wins'], 1)
        avg_loss = abs(d['loss_pnl'] / max(d['losses'], 1)) if d['losses'] else 0
        rr = avg_win / max(avg_loss, 0.1)
        # Kelly = W - (1-W)/R；边界保护
        win_rate_safe = min(win_rate, 95)  # 防止100%胜率导致除零
        rr_safe = max(rr, 0.1)
        kelly = (win_rate_safe / 100 - (1 - win_rate_safe / 100) / rr_safe) * 100
        kelly_cap = max(min(kelly, 10), -20)  # 上限10%，下限-20%
        health_lines.append(f"  {tier}: 胜率{win_rate:.0f}% | 盈亏比{rr:.1f} | Kelly{kelly_cap:.1f}% | 活跃{d['active']}只")
    health_lines.append(f"  组合Heat: {portfolio_heat}只活跃（建议<15只）")
    if portfolio_heat > 15:
        health_lines.append(f"  ⚠️ 活跃持仓过多，建议暂停新开仓，优先止损/止盈已有仓位")
    elif portfolio_heat > 10:
        health_lines.append(f"  ⚡ 组合偏满，谨慎加仓")
    health_lines.append("")

    conn.close()

    # 生成报告（先初始化，再插入健康检查）
    lines = [
        "📊 **推荐股票池追踪报告**",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # 插入健康检查
    lines.extend(health_lines)

    # 状态统计
    lines.append("**【整体统计】**")
    for status, cnt, avg_pnl, max_pnl, min_pnl in status_stats:
        emoji = {'active': '🔄', 'hit_stop_loss': '⛔', 'hit_tp1': '🎯', 'hit_tp2': '🎯🎯', 'expired': '⏰'}.get(status, '❓')
        lines.append(f"  {emoji} {status}: {cnt}只 | 均收益{avg_pnl:+.1f}% | 最高{max_pnl:+.1f}% | 最低{min_pnl:+.1f}%")
    lines.append("")
    
    # 按档位统计
    lines.append("**【各档表现】**")
    current_tier = None
    for tier, status, cnt, avg_pnl in tier_stats:
        if tier != current_tier:
            lines.append(f"  — {tier} —")
            current_tier = tier
        emoji = {'active': '🔄', 'hit_stop_loss': '⛔', 'hit_tp1': '🎯', 'hit_tp2': '🎯🎯', 'expired': '⏰'}.get(status, '❓')
        lines.append(f"    {emoji} {status}: {cnt}只 | 均收益{avg_pnl:+.1f}%")
    lines.append("")
    
    # 活跃推荐
    if active_recs:
        lines.append(f"**【活跃推荐】({len(active_recs)}只)**")
        for r in active_recs:
            code, name, tier, tier_type, entry_price, current_price, pnl_pct, days_held, status, notes = r
            pnl_emoji = '🟢' if pnl_pct > 0 else '🔴'
            lines.append(f"  {pnl_emoji} {name}({code}) {tier_type}")
            lines.append(f"     买入:{entry_price:.2f} 现价:{current_price:.2f} | {pnl_pct:+.1f}% | 持有{days_held}天 | {notes}")
        lines.append("")
    
    # 已触发推荐（无论有无数据都显示标题）
    lines.append(f"**【近期触发】({len(closed_recs)}只)**")
    if closed_recs:
        for r in closed_recs:
            code, name, tier, tier_type, entry_price, current_price, pnl_pct, status, notes, entry_date, updated_at = r
            emoji = {'hit_stop_loss': '⛔', 'hit_tp1': '🎯', 'hit_tp2': '🎯🎯'}.get(status, '❓')
            lines.append(f"  {emoji} {name}({code}) | {status} | {pnl_pct:+.1f}% | {notes}")
    else:
        lines.append("  （暂无触发记录）")
    lines.append("")
    
    return '\n'.join(lines)


def check_performance(days: int = 30) -> Dict:
    """检查近期推荐的执行表现"""
    conn = sqlite3.connect(POOL_DB)
    cur = conn.cursor()
    
    since = (date.today() - timedelta(days=days)).isoformat()
    
    cur.execute("""
        SELECT tier, status, COUNT(*) as cnt
        FROM recommendations
        WHERE entry_date >= ?
        GROUP BY tier, status
    """, (since,))
    
    rows = cur.fetchall()
    conn.close()
    
    # 统计
    stats = {}
    for tier, status, cnt in rows:
        if tier not in stats:
            stats[tier] = {'total': 0, 'hit_tp1': 0, 'hit_tp2': 0, 'stop_loss': 0, 'expired': 0, 'active': 0}
        stats[tier]['total'] += cnt
        if status == 'hit_tp1':
            stats[tier]['hit_tp1'] += cnt
        elif status == 'hit_tp2':
            stats[tier]['hit_tp2'] += cnt
        elif status == 'hit_stop_loss':
            stats[tier]['stop_loss'] += cnt
        elif status == 'expired':
            stats[tier]['expired'] += cnt
        elif status == 'active':
            stats[tier]['active'] += cnt
    
    return stats


if __name__ == '__main__':
    init_pool_db()
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'report'
    
    if cmd == 'track':
        # 从auto_recommend结果加载
        json_path = '/home/caojy/.hermes/profiles/stock/cron/output/auto_recommend_latest.json'
        if os.path.exists(json_path):
            with open(json_path) as f:
                data = json.load(f)
            
            from auto_recommend import Recommendation
            all_recs = []
            for tier in ('aggressive', 'steady', 'value'):
                for rec_dict in data.get(tier, []):
                    rec = Recommendation(**{k: v for k, v in rec_dict.items() if v is not None or k in ('code','name','current_price','tier','tier_type','buy_price','buy_range_low','buy_range_high','entry_way','stop_loss','stop_loss_pct','take_profit_1','take_profit_1_pct','take_profit_2','take_profit_2_pct','hold_days_max','signal_score','fundamental_score','combined_score')})
                    # 补充默认值字段
                    for field in ('max_position_pct','level','roe','profit_growth','debt_ratio','pe_ratio','reasons','risk_warning','rsi','boll_position','ma_bullish','atr','market_cap','sector'):
                        if not hasattr(rec, field):
                            setattr(rec, field, None)
                    all_recs.append(rec)
            
            track_recommendations(all_recs)
        else:
            print(f"未找到 auto_recommend 结果: {json_path}")
    
    elif cmd == 'check':
        stats = check_performance(30)
        print("最近30天推荐表现:")
        for tier, s in stats.items():
            print(f"  {tier}: 总{s['total']}只 | 目标1:{s['hit_tp1']} | 目标2:{s['hit_tp2']} | 止损:{s['stop_loss']} | 超时:{s['expired']} | 活跃:{s['active']}")
    
    elif cmd == 'update':
        update_pool_prices()
    
    elif cmd == 'report':
        update_pool_prices()
        report = generate_report()
        print(report)
