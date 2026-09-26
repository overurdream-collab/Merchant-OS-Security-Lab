from .database import get_connection, utc_now
from .merchants import ensure_merchant_schema


def ensure_outreach_schema():
    ensure_merchant_schema()
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS outreach (
                outreach_id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                direction TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                sent_at TEXT,
                FOREIGN KEY(merchant_id) REFERENCES merchants(merchant_id)
            )
        """)
        db.commit()


def create_outreach(merchant_id, channel, message, status="draft"):
    ensure_outreach_schema()
    with get_connection() as db:
        cur = db.execute(
            """INSERT INTO outreach
            (merchant_id,channel,direction,message,status,created_at)
            VALUES (?,?,?,?,?,?)""",
            (merchant_id, channel, "outbound", message, status, utc_now()),
        )
        db.commit()
        return cur.lastrowid
