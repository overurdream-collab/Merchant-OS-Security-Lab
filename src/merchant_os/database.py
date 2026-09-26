import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.getenv("MERCHANT_OS_DB", "data/merchant_os.db")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ensure_schema():
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT UNIQUE NOT NULL,
                name TEXT,
                phone TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                metadata TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                intent TEXT,
                last_message_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                conversation_id INTEGER,
                customer_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                message_type TEXT,
                text TEXT,
                received_at TEXT NOT NULL,
                raw_payload TEXT,
                FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
                FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_messages_customer ON messages(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)")


def upsert_customer(wa_id, name=None):
    if not isinstance(wa_id, str) or not wa_id.strip():
        raise ValueError("Missing WhatsApp customer ID")
    now = utc_now()
    with get_connection() as db:
        db.execute("""
            INSERT INTO customers (wa_id, name, phone, first_seen_at, last_seen_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(wa_id)
            DO UPDATE SET
                name = COALESCE(excluded.name, customers.name),
                last_seen_at = excluded.last_seen_at
        """, (wa_id, name, wa_id, now, now, json.dumps({}, ensure_ascii=False)))
        row = db.execute("SELECT * FROM customers WHERE wa_id = ?", (wa_id,)).fetchone()
        return dict(row)


def get_or_create_conversation(customer_id):
    now = utc_now()
    with get_connection() as db:
        row = db.execute("""
            SELECT * FROM conversations
            WHERE customer_id = ? AND status = 'open'
            ORDER BY updated_at DESC LIMIT 1
        """, (customer_id,)).fetchone()
        if row:
            return dict(row)
        cursor = db.execute("""
            INSERT INTO conversations (
                customer_id, status, intent, last_message_at, created_at, updated_at
            ) VALUES (?, 'open', NULL, ?, ?, ?)
        """, (customer_id, now, now, now))
        conversation_id = cursor.lastrowid
        row = db.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
        return dict(row)


def save_message(message_id, conversation_id, customer_id, direction, message_type, text, raw_payload):
    now = utc_now()
    with get_connection() as db:
        db.execute("""
            INSERT OR IGNORE INTO messages (
                message_id, conversation_id, customer_id, direction, message_type,
                text, received_at, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message_id, conversation_id, customer_id, direction, message_type,
            text, now, json.dumps(raw_payload, ensure_ascii=False),
        ))
        db.execute("""
            UPDATE conversations
            SET last_message_at = ?, updated_at = ?
            WHERE conversation_id = ?
        """, (now, now, conversation_id))


def ensure_interest_schema():
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS customer_interest_events (
                event_id TEXT PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                product_id TEXT,
                category TEXT,
                metadata TEXT,
                occurred_at TEXT NOT NULL,
                FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_interest_customer ON customer_interest_events(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_interest_category ON customer_interest_events(category)")


def save_interest_event(customer_id, event_type, product_id=None, category=None, metadata=None):
    import uuid
    event_id = str((metadata or {}).get("event_id") or uuid.uuid4())
    now = utc_now()
    with get_connection() as db:
        db.execute("""
            INSERT OR IGNORE INTO customer_interest_events
            (event_id, customer_id, event_type, product_id, category, metadata, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (event_id, customer_id, event_type, product_id, category,
              json.dumps(metadata or {}, ensure_ascii=False), now))
        row = db.execute("SELECT * FROM customer_interest_events WHERE event_id=?", (event_id,)).fetchone()
        return dict(row)


def get_interest_events(customer_id):
    with get_connection() as db:
        rows = db.execute(
            "SELECT * FROM customer_interest_events WHERE customer_id=? ORDER BY occurred_at ASC, event_id ASC",
            (customer_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def ensure_intelligence_schema():
    """Create the shared market-signal store used by intelligence agents."""
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS market_signals (
                signal_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                external_id TEXT,
                source_url TEXT,
                signal_type TEXT NOT NULL,
                category TEXT,
                subject TEXT,
                location TEXT,
                intent TEXT,
                urgency TEXT,
                confidence REAL NOT NULL DEFAULT 0,
                text TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                metadata TEXT
            )
        """)
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_market_signals_source_external "
            "ON market_signals(source, external_id) WHERE external_id IS NOT NULL"
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_market_signals_type ON market_signals(signal_type)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_market_signals_category ON market_signals(category)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_market_signals_captured ON market_signals(captured_at)")


def save_market_signal(signal):
    """Persist a normalized MarketSignal dict idempotently."""
    if not isinstance(signal, dict):
        raise TypeError("signal must be a dict")

    signal_id = str(signal.get("signal_id") or "").strip()
    if not signal_id:
        raise ValueError("signal_id is required")

    tags = signal.get("tags") or []
    metadata = signal.get("metadata") or {}

    with get_connection() as db:
        db.execute("""
            INSERT OR IGNORE INTO market_signals (
                signal_id, source, external_id, source_url, signal_type,
                category, subject, location, intent, urgency, confidence,
                text, captured_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id,
            signal.get("source"),
            signal.get("external_id"),
            signal.get("source_url"),
            signal.get("signal_type"),
            signal.get("category"),
            signal.get("subject"),
            signal.get("location"),
            signal.get("intent"),
            signal.get("urgency"),
            float(signal.get("confidence") or 0),
            signal.get("text"),
            signal.get("captured_at") or utc_now(),
            json.dumps(
                {"tags": tags, **metadata},
                ensure_ascii=False,
            ),
        ))
        row = db.execute(
            "SELECT * FROM market_signals WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        return dict(row)
