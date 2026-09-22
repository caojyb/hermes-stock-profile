#!/usr/bin/env python3
"""
系统健康检查模块 — 每日15:00任务后自动执行
"""
import os, sys, sqlite3, json
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path

MARKET_DB = str(get_db_path('market_cache'))
SIM_DB = str(get_db_path('simulation'))
# 候选池统一从 double_up_scores 表读取（pool_loader）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 飞书发送依赖
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills' / 'stock' / 'stock-expert' / 'skills' / 'feishu-bitable'))
from pool_loader import load_pool
from core.compat_paths import MARKET_DB

def _truncate(s: str, max_len: int = 500) -> str:
    return s if len(s) <= max_len else s[:max_len] + "..."

def send_feishu(msg: str) -> None:
    """发飞书提醒。"""
    try:
        from feishu_sender import feishu_send_message
        feishu_send_message(msg)
    except Exception as e:
        print(f"[WARN] 飞书发送失败: {e}")

def run_health_check():
    issues = []
    report_lines = []

    # 检查项分级：P0=立即处理, P1=当日处理, P2=次日汇总
    levels = {
        'heartbeat': 'P0',
        'K线': 'P1',
        '财务': 'P1',
        '候选池': 'P1',
        '模拟交易': 'P1',
        '止盈止损': 'P0',
        '新股虹吸': 'P2',
        '板块强度': 'P2',
        '数据库连接': 'P0',
        '日志': 'P2',
    }

    # 心跳过期检查
    try:
        hb_dir = Path(__file__).resolve().parent.parent.parent / 'stock-work' / 'data' / 'state' / 'heartbeats'
        if hb_dir.exists():
            # 读 jobs.json 的 cron 表达式，用于判断"下一个计划执行时间是否在未来"
            cron_exprs = {}
            try:
                _jd = json.loads((Path(__file__).resolve().parent.parent.parent / 'cron' / 'jobs.json').read_text())
                _jobs = _jd if isinstance(_jd, list) else _jd.get('jobs', [])
                if isinstance(_jobs, dict):
                    _jobs = list(_jobs.values())
                for _j in _jobs:
                    if isinstance(_j, dict) and _j.get('name'):
                        _sc = _j.get('schedule') or _j.get('cron') or ''
                        _e = _sc.get('expr') if isinstance(_sc, dict) else _sc
                        if _e:
                            cron_exprs[_j['name']] = _e
            except Exception:
                pass

            def _window_passed(expr: str, last_run: datetime, now: datetime) -> bool:
                """若 cron 的分钟/小时位不在当前时刻之前，说明今天还没到执行时间 → 不算过期。
                简化实现：只解析 'M H * * 1-5' 这类固定日内的表达式，取 (分,时) 组合，
                若 now 当天的该时刻还没到，则返回 False（未过期）。"""
                try:
                    parts = expr.split()
                    if len(parts) < 2:
                        return True
                    minute_s, hour_s = parts[0], parts[1]
                    if minute_s == '*' or hour_s == '*':
                        return True
                    # 只处理单个数字
                    if not (minute_s.isdigit() and hour_s.isdigit()):
                        return True
                    sched_today = now.replace(hour=int(hour_s), minute=int(minute_s),
                                              second=0, microsecond=0)
                    if now < sched_today:
                        return False   # 今天的执行时间还没到
                    # 已过：若 last_run 就是今天这个时刻附近，则正常
                    return True
                except Exception:
                    return True

            for hb_file in hb_dir.glob('*.json'):
                try:
                    hb = json.loads(hb_file.read_text())
                    last_run = datetime.fromisoformat(hb.get('last_run', ''))
                    expected = hb.get('expected_interval_seconds', 86400)
                    now = datetime.now()
                    lag = (now - last_run).total_seconds()
                    if lag > expected * 1.5:
                        task = hb.get('task') or hb_file.stem
                        # P1-4 修复（2026-09-21）：若该任务的今日计划执行时间还没到，跳过
                        # 典型如 stock-opportunity-push（expected=1800s 但只在 9:30-15:30 跑），
                        # 15:30 之后 lag 必然超过阈值，属于计划内停机而非故障。
                        expr = cron_exprs.get(task)
                        if expr and not _window_passed(expr, last_run, now):
                            continue
                        issues.append({"level": levels['heartbeat'], "msg": f"⚠️ 心跳过期: {task} 最后运行 {last_run.isoformat()}，已滞后 {lag/3600:.1f} 小时"})
                except Exception as e:
                    issues.append({"level": levels['heartbeat'], "msg": f"❌ 心跳读取失败 {hb_file.name}: {e}"})
    except Exception as e:
        issues.append({"level": levels['heartbeat'], "msg": f"❌ 心跳目录检查失败: {e}"})

    report_lines.append(f"\n{'='*55}")
    report_lines.append("🏥 系统健康检查")
    report_lines.append(f"   检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append(f"{'='*55}")

    # 1. K线缓存最后更新时间
    try:
        conn = sqlite3.connect(MARKET_DB, timeout=60)
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM klines")
        last_kline = cur.fetchone()[0]
        if last_kline:
            last_dt = datetime.strptime(last_kline, '%Y-%m-%d').date()
            today = datetime.now().date()
            days_lag = (today - last_dt).days
            # 判断今天是否为交易日：klines 表里是否已有今天的数据（与 double_monitor 同口径）
            cur.execute("SELECT COUNT(*) FROM klines WHERE date=?", (today.isoformat(),))
            is_today_trading = cur.fetchone()[0] > 0
            # 新鲜度判定：若今天是交易日，则数据必须到今天；若非交易日，允许滞后到最近交易日
            if is_today_trading:
                stale = last_dt < today
            else:
                stale = days_lag > 5  # 非交易日（如周末/长假），数据滞后超过5天视为异常
            if stale:
                issues.append(f"⚠️ K线缓存最后更新: {last_kline}（{'今天无当日K线' if is_today_trading else f'滞后{days_lag}天'}）")
            else:
                status = '今日数据' if last_dt == today else f'最近交易日 {last_kline}'
                report_lines.append(f"✅ K线缓存最后更新: {last_kline}（{status}）")
        else:
            issues.append("⚠️ K线缓存无数据!")
    except Exception as e:
        issues.append(f"❌ K线检查失败: {e}")
    
    # 2. 财务数据最后更新时间
    try:
        cur.execute("SELECT MAX(report_date) FROM financial_data")
        last_fin = cur.fetchone()[0]
        if last_fin:
            last_fin_dt = datetime.strptime(last_fin, '%Y-%m-%d').date()
            days_lag = (date.today() - last_fin_dt).days
            if days_lag > 90:
                issues.append({"level": levels['财务'], "msg": f"⚠️ 财务数据过期: {last_fin}（滞后 {days_lag} 天）"})
            else:
                report_lines.append(f"✅ 财务数据最后更新: {last_fin}")
        else:
            issues.append({"level": levels['财务'], "msg": "⚠️ 财务数据为空!"})
    except Exception as e:
        issues.append({"level": levels['财务'], "msg": f"❌ 财务数据检查失败: {e}"})
    
    # 3. 候选池数量
    try:
        cnt = len(load_pool())
        if cnt == 0:
            issues.append("⚠️ 候选池数量为0! 筛选可能过于严格")
        else:
            report_lines.append(f"✅ 候选池数量: {cnt} 只")
    except Exception as e:
        issues.append(f"❌ 候选池检查失败: {e}")
    
    # 4. 模拟交易状态
    try:
        if os.path.exists(SIM_DB):
            sim = sqlite3.connect(SIM_DB, timeout=60)
            sim_cur = sim.cursor()
            sim_cur.execute("SELECT COUNT(*) FROM trades WHERE sell_date >= date('now', '-1 day')")
            today_sells = sim_cur.fetchone()[0]
            sim_cur.execute("SELECT COUNT(*) FROM trades WHERE buy_date >= date('now', '-1 day')")
            today_buys = sim_cur.fetchone()[0]
            sim_cur.execute("SELECT COUNT(*) FROM trades WHERE status IN ('持有','部分止盈')")
            active_positions = sim_cur.fetchone()[0]
            report_lines.append(f"✅ 模拟交易: 今日开仓{today_buys}笔 / 平仓{today_sells}笔 / 活跃持仓{active_positions}笔")
            sim.close()
        else:
            issues.append("⚠️ 模拟交易数据库不存在!")
    except Exception as e:
        issues.append(f"❌ 模拟交易检查失败: {e}")
    
    # 5. 止盈止损条件单数量
    try:
        if os.path.exists(SIM_DB):
            sim = sqlite3.connect(SIM_DB, timeout=60)
            sim_cur = sim.cursor()
            sim_cur.execute("SELECT COUNT(*) FROM trades WHERE status IN ('持有','部分止盈')")
            pos_cnt = sim_cur.fetchone()[0]
            if pos_cnt == 0:
                report_lines.append("✅ 止盈止损条件单: 0个（无持仓）")
            else:
                # 真实情况：模拟仓无独立条件单表，止盈止损由 double_monitor 内联执行
                report_lines.append(f"✅ 止盈止损: {pos_cnt}个持仓由 double_monitor 内联执行（无独立条件单）")
            sim.close()
    except Exception as e:
        issues.append(f"❌ 止盈止损检查失败: {e}")
    
    # 6. 新股虹吸
    try:
        if os.path.exists(SIM_DB):
            sim = sqlite3.connect(SIM_DB, timeout=60)
            sim_cur = sim.cursor()
            sim_cur.execute("SELECT COUNT(*) FROM ipo_blocks WHERE active=1")
            active_blocks = sim_cur.fetchone()[0]
            report_lines.append(f"✅ 新股虹吸: 活跃暂缓{active_blocks}个")
            sim.close()
    except Exception as e:
        issues.append(f"❌ 新股虹吸检查失败: {e}")
    
    # 7. 板块强度
    # 7. 板块强度（检查 hot_sector_scanner 今日输出 + 内容质量）
    try:
        today_str = date.today().isoformat()
        sector_file = Path(__file__).resolve().parent.parent.parent / 'stock-work' / 'data' / 'outputs' / 'hot_sectors' / f'hot_sector_{today_str}.md'
        if sector_file.exists():
            sector_content = sector_file.read_text()
            if '涨停' in sector_content and len(sector_content) > 500:
                report_lines.append(f"✅ 板块强度: 今日已生成 ({len(sector_content)} 字符)")
            else:
                issues.append({"level": levels['板块强度'], "msg": f"⚠️ 板块强度: 内容不完整（{len(sector_content)} 字符）"})
        else:
            issues.append({"level": levels['板块强度'], "msg": f"⚠️ 板块强度: 今日未生成 ({sector_file.name})"})
    except Exception as e:
        issues.append({"level": levels['板块强度'], "msg": f"❌ 板块强度检查失败: {e}"})
    
    # 8. 数据库连接（实际查询验证）
    try:
        test_conn = sqlite3.connect(MARKET_DB, timeout=5)
        test_conn.execute("SELECT 1").fetchone()
        test_conn.close()
        report_lines.append("✅ 数据库连接: 正常")
    except Exception as e:
        issues.append({"level": levels['数据库连接'], "msg": f"❌ 数据库连接异常: {e}"})
    
    # 9. 日志文件大小
    log_dir = str(Path.home() / ".hermes" / "logs")
    if os.path.exists(log_dir):
        total_size = 0
        for f in os.listdir(log_dir):
            fp = os.path.join(log_dir, f)
            if os.path.isfile(fp):
                total_size += os.path.getsize(fp)
        size_mb = total_size / 1024 / 1024
        if size_mb > 100:
            issues.append(f"⚠️ 日志文件大小: {size_mb:.1f}MB（超过100MB，建议清理!）")
        else:
            report_lines.append(f"✅ 日志文件大小: {size_mb:.1f}MB")
    
    # 输出
    if issues:
        print("\n" + "!" * 55)
        for issue in issues:
            print(f"  {issue}")
        print("!" * 55)
    
    for line in report_lines:
        print(line)
    
    if issues:
        print(f"\n⚠️ 发现 {len(issues)} 个问题，建议处理")
    else:
        print(f"\n✅ 系统运行正常，无异常")
    
    # 写入检查日志
    log_entry = {
        'time': datetime.now().isoformat(),
        'issues': issues,
        'status': '异常' if issues else '正常'
    }
    log_path = str(Path(__file__).resolve().parent.parent.parent / 'stock-work' / 'data' / 'state' / 'logs' / 'health_log.json')
    history = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            try: history = json.load(f)
            except Exception as _e: print(f"[EXC] health_check.py: {type(_e).__name__}: {_e}"); pass
    history.append(log_entry)
    history = history[-30:]  # 保留最近30条
    with open(log_path, 'w') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    # 飞书推送：P0/P1 分组，P2 只写日志
    p0_issues = [i for i in issues if i.get('level') == 'P0']
    p1_issues = [i for i in issues if i.get('level') == 'P1']
    if p0_issues or p1_issues:
        feishu_lines = [f"🏥 系统健康检查 [{date.today().isoformat()}]", ""]
        if p0_issues:
            feishu_lines.append(f"🔴 P0 级问题（{len(p0_issues)} 项）:")
            for i in p0_issues:
                feishu_lines.append(f"  {_truncate(i['msg'])}")
            feishu_lines.append("")
        if p1_issues:
            feishu_lines.append(f"🟡 P1 级问题（{len(p1_issues)} 项）:")
            for i in p1_issues:
                feishu_lines.append(f"  {_truncate(i['msg'])}")
            feishu_lines.append("")
        send_feishu(chr(10).join(feishu_lines))

    return issues

def main():
    issues = run_health_check()

    # P0 issues → exit 1
    p0_issues = []
    for issue in issues:
        if isinstance(issue, dict) and issue.get('level') == 'P0':
            p0_issues.append(issue.get('msg', issue))
        elif isinstance(issue, str) and '❌' in issue:
            p0_issues.append(issue)

    if p0_issues:
        print(f"[ERROR] 健康检查发现 {len(p0_issues)} 个 P0 问题")
        for issue in p0_issues:
            print(f"  {issue}")
        sys.exit(1)


if __name__ == '__main__':
    main()