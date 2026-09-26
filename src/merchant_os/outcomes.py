from typing import Any, Dict

from .database import get_connection, utc_now


def ensure_outcomes_schema():
    with get_connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS decision_outcomes (
            outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT NOT NULL,
            decision_status TEXT NOT NULL,
            action_status TEXT,
            outcome TEXT,
            created_at TEXT NOT NULL
        )""")
        db.commit()


def record_outcome(mission_id: str, decision_status: str,
                   action_status: str | None = None,
                   outcome: Any = None) -> int:
    ensure_outcomes_schema()
    with get_connection() as db:
        cur = db.execute(
            "INSERT INTO decision_outcomes (mission_id,decision_status,action_status,outcome,created_at) VALUES (?,?,?,?,?)",
            (mission_id, decision_status, action_status,
             str(outcome) if outcome is not None else None, utc_now()),
        )
        db.commit()
        return int(cur.lastrowid)
