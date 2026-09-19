"""
Baseline §30 / §49 Promotion Record 落盘与查询。
Research Candidate → Validation → Simulation → Production 四级链路可追溯。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import sqlite3

DB_PATH = Path(__file__).resolve().parents[3] / 'stock-work' / 'data' / 'runtime' / 'promotion_records.db'


def _ensure_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS promotion_records (
            promotion_id TEXT PRIMARY KEY,
            research_id TEXT,
            candidate_id TEXT,
            validation_id TEXT,
            simulation_id TEXT,
            decision_id TEXT,
            promotion_status TEXT DEFAULT 'PROMOTED',
            promoted_at TEXT,
            promoted_by TEXT DEFAULT 'system',
            notes TEXT,
            policy_version TEXT DEFAULT 'baseline-v1.2.1',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_promotion_decision ON promotion_records(decision_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_promotion_policy ON promotion_records(policy_version)")
    con.commit()
    return con


def record_promotion(
    *,
    research_id: str = '',
    candidate_id: str = '',
    validation_id: str = '',
    simulation_id: str = '',
    decision_id: str = '',
    promotion_status: str = 'PROMOTED',
    promoted_at: str | None = None,
    promoted_by: str = 'system',
    notes: str = '',
    policy_version: str = 'baseline-v1.2.1',
) -> dict:
    """落盘一条 Promotion Record。"""
    promoted_at = promoted_at or datetime.now().isoformat()
    promotion_id = f"promo_{promoted_at.replace('-','').replace(':','').replace(' ','T')[:15]}_{decision_id[-8:]}"
    record = {
        'promotion_id': promotion_id,
        'research_id': research_id,
        'candidate_id': candidate_id,
        'validation_id': validation_id,
        'simulation_id': simulation_id,
        'decision_id': decision_id,
        'promotion_status': promotion_status,
        'promoted_at': promoted_at,
        'promoted_by': promoted_by,
        'notes': notes,
        'policy_version': policy_version,
        'created_at': datetime.now().isoformat(),
    }
    con = _ensure_db()
    con.execute(
        """INSERT OR REPLACE INTO promotion_records
           (promotion_id, research_id, candidate_id, validation_id, simulation_id,
            decision_id, promotion_status, promoted_at, promoted_by, notes, policy_version, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (promotion_id, research_id, candidate_id, validation_id, simulation_id,
         decision_id, promotion_status, promoted_at, promoted_by, notes, policy_version, record['created_at']),
    )
    con.commit()
    con.close()
    return record


def query_by_decision(decision_id: str) -> dict | None:
    """按 decision_id 查询 Promotion Record。"""
    con = _ensure_db()
    row = con.execute(
        "SELECT * FROM promotion_records WHERE decision_id = ? ORDER BY created_at DESC LIMIT 1",
        (decision_id,)
    ).fetchone()
    con.close()
    if not row:
        return None
    cols = [d[0] for d in con.execute("PRAGMA table_info(promotion_records)").fetchall()]
    return dict(zip(cols, row))


def query_by_policy(policy_version: str) -> list[dict]:
    """按 policy_version 查询所有 Promotion Record。"""
    con = _ensure_db()
    rows = con.execute(
        "SELECT * FROM promotion_records WHERE policy_version = ? ORDER BY created_at DESC",
        (policy_version,)
    ).fetchall()
    cols = [d[0] for d in con.execute("PRAGMA table_info(promotion_records)").fetchall()]
    con.close()
    return [dict(zip(cols, r)) for r in rows]


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: promotion_record.py record|query <args>")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'record':
        rec = record_promotion(
            research_id='res_001',
            candidate_id='cand_001',
            validation_id='val_001',
            simulation_id='sim_001',
            decision_id='dec_001',
            notes='demo promotion record',
        )
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    elif cmd == 'query':
        dec_id = sys.argv[2] if len(sys.argv) > 2 else 'dec_001'
        rec = query_by_decision(dec_id)
        print(json.dumps(rec, ensure_ascii=False, indent=2) if rec else "NOT_FOUND")
    else:
        print(f"Unknown command: {cmd}")
