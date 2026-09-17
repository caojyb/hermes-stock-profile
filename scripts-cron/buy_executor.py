# scripts/cron/buy_executor.py
"""
单股票 signals + trades 执行模块。
double_monitor.py 的 BUY_EXEC 分支抽离至此，
主文件只保留一行调用。
"""

from datetime import date
import math


def execute_buy_with_signals(
    sim_conn, sim_cur,
    code, name, sector,
    buy_price, buy_shares, buy_amount,
    signal_types, strategy, decision_id,
    today_str,
):
    """
    在 buy 循环内调用，处理单只股票的 signals + trades 写入。
    返回 (success: bool, message: str)
    """
    # 参数校验（必须在 BEGIN IMMEDIATE 之前，避免开启事务后再回滚）
    # 规则 1: price > 0
    if not isinstance(buy_price, (int, float)) or buy_price <= 0:
        return False, "buy_price 必须 > 0"
    # 规则 2: price 不是 NaN/bool
    if math.isnan(buy_price) or isinstance(buy_price, bool):
        return False, "buy_price 不能是 NaN/bool"
    # 规则 3: quantity > 0
    if not isinstance(buy_shares, int) or buy_shares <= 0:
        return False, "buy_shares 必须 > 0"
    # 规则 4: quantity 不是 bool
    if isinstance(buy_shares, bool):
        return False, "buy_shares 不能是 bool"
    # 规则 5: buy_amount 一致性（允许 ±1% 四舍五入差异）
    expected = buy_price * buy_shares
    if expected > 0:
        diff_pct = abs(buy_amount - expected) / expected
        if diff_pct > 0.01:
            return False, f"buy_amount 与 price×shares 不一致（差异 {diff_pct*100:.1f}%）"
    elif buy_amount != expected:
        return False, "buy_amount 与 price×shares 不一致"


    # 每只股票独立事务
    if sim_conn.in_transaction:
        sim_conn.commit()

    sim_conn.execute("BEGIN IMMEDIATE")
    try:
        # Step 1: 写入 signals 表（pending）
        sim_cur.execute(
            """
            INSERT INTO signals
            (code, signal_type, strategy, source, status,
             created_at, updated_at, reason, signal_date)
            VALUES (?, 'BUY', ?, 'double_monitor', 'pending', ?, ?, ?, ?)
            """,
            (
                code,
                strategy,
                today_str,
                today_str,
                None,
                date.today().isoformat(),
            ),
        )
        signal_id = sim_cur.lastrowid

        # Step 2: 检查是否已有活跃持仓
        sim_cur.execute(
            """
            SELECT COUNT(*) FROM trades
            WHERE code = ? AND status IN ('持有', '部分止盈')
            """,
            (code,),
        )
        existing = sim_cur.fetchone()[0]

        if existing > 0:
            sim_cur.execute(
                """
                UPDATE signals
                SET status='ignored',
                    reason='已有活跃持仓',
                    updated_at=?
                WHERE id = ?
                """,
                (today_str, signal_id),
            )
            sim_conn.commit()
            return False, f"已有活跃持仓，忽略 {code} {name}"

        # Step 3: 执行买入
        sim_cur.execute(
            """
            INSERT INTO trades
            (code, name, sector, buy_date, buy_price, buy_shares,
             buy_amount, status, signal_type, hold_mode, strategy,
             decision_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, '持有', ?, 'normal', ?, ?, ?)
            """,
            (
                code,
                name,
                sector,
                today_str,
                buy_price,
                buy_shares,
                buy_amount,
                '+'.join(signal_types),
                strategy,
                decision_id,
                today_str,
            ),
        )
        trade_id = sim_cur.lastrowid

        # Step 4: 更新 signals 为 executed
        sim_cur.execute(
            """
            UPDATE signals
            SET status='executed',
                trade_id=?,
                updated_at=?
            WHERE id = ?
            """,
            (trade_id, today_str, signal_id),
        )

        sim_conn.commit()
        return True, f"买入成功 {code} {name}"

    except Exception as e:
        try:
            sim_conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        return False, f"买入失败 {code}: {e}"
