from .database import get_connection, utc_now


def ensure_merchant_schema():
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS merchants (
                merchant_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                channel TEXT,
                source_url TEXT,
                category TEXT,
                city TEXT,
                status TEXT NOT NULL DEFAULT 'lead',
                score REAL NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS merchant_contacts (
                contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                address TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                last_contact_at TEXT,
                FOREIGN KEY(merchant_id) REFERENCES merchants(merchant_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS merchant_scores (
                score_id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL,
                criterion TEXT NOT NULL,
                score REAL NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(merchant_id) REFERENCES merchants(merchant_id)
            )
        """)
        db.commit()


def create_merchant(name, phone=None, channel=None, source_url=None, category=None, city=None, notes=None):
    ensure_merchant_schema()
    now = utc_now()
    with get_connection() as db:
        cur = db.execute(
            """INSERT INTO merchants
            (name,phone,channel,source_url,category,city,notes,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (name, phone, channel, source_url, category, city, notes, now, now),
        )
        db.commit()
        return cur.lastrowid


def score_merchant(merchant_id, criteria):
    ensure_merchant_schema()
    total = sum(float(item["score"]) for item in criteria)
    with get_connection() as db:
        for item in criteria:
            db.execute(
                """INSERT INTO merchant_scores
                (merchant_id,criterion,score,reason,created_at) VALUES (?,?,?,?,?)""",
                (merchant_id, item["criterion"], item["score"], item.get("reason"), utc_now()),
            )
        db.execute(
            "UPDATE merchants SET score=?,updated_at=? WHERE merchant_id=?",
            (total, utc_now(), merchant_id),
        )
        db.commit()
    return total


def list_merchants(status=None, limit=50):
    ensure_merchant_schema()
    with get_connection() as db:
        if status:
            rows = db.execute(
                "SELECT * FROM merchants WHERE status=? ORDER BY score DESC, updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM merchants ORDER BY score DESC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def persist_ranked_merchants(ranked):
    """Persist explainable ranking snapshots without changing existing merchant IDs."""
    ensure_merchant_schema()
    saved = []
    with get_connection() as db:
        for item in ranked:
            merchant = item.get("merchant", {})
            name = merchant.get("name") or "Unnamed merchant"
            source_url = merchant.get("url") or merchant.get("source_url")
            row = None
            if source_url:
                row = db.execute("SELECT merchant_id FROM merchants WHERE source_url=? ORDER BY merchant_id LIMIT 1", (source_url,)).fetchone()
            if row is None:
                row = db.execute("SELECT merchant_id FROM merchants WHERE lower(name)=lower(?) AND COALESCE(city,'')=COALESCE(?, '') LIMIT 1", (name, merchant.get("city"))).fetchone()
            now = utc_now()
            if row is None:
                cur = db.execute(
                    """INSERT INTO merchants (name,phone,channel,source_url,category,city,score,notes,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (name, merchant.get("phone"), merchant.get("channel") or ((merchant.get("channels") or [None])[0]),
                     source_url, merchant.get("category"), merchant.get("city"), float(item.get("score", 0)),
                     merchant.get("snippet"), now, now))
                merchant_id = cur.lastrowid
            else:
                merchant_id = row["merchant_id"]
                db.execute("""UPDATE merchants SET phone=?,channel=?,source_url=?,category=?,city=?,score=?,notes=?,updated_at=?
                              WHERE merchant_id=?""",
                           (merchant.get("phone"), merchant.get("channel") or ((merchant.get("channels") or [None])[0]),
                            source_url, merchant.get("category"), merchant.get("city"), float(item.get("score", 0)),
                            merchant.get("snippet"), now, merchant_id))
            for criterion, value in item.get("factors", {}).items():
                db.execute("""INSERT INTO merchant_scores (merchant_id,criterion,score,reason,created_at)
                              VALUES (?,?,?,?,?)""",
                           (merchant_id, criterion, float(value), "Professor OS intelligence factor", now))
            saved.append(merchant_id)
        db.commit()
    return saved
