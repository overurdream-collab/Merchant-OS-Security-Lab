from .database import get_connection, utc_now


DELIVERY_TRANSITIONS = {
    "pending": {"assigned", "failed"},
    "assigned": {"out_for_delivery", "failed"},
    "out_for_delivery": {"delivered", "failed", "returned"},
    "delivered": {"returned"},
    "failed": set(),
    "returned": set(),
}

RETURN_TRANSITIONS = {
    "requested": {"approved", "rejected"},
    "approved": {"received", "rejected"},
    "received": {"closed"},
    "rejected": set(),
    "closed": set(),
}


def ensure_operations_schema():
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS deliveries (
                delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                provider TEXT,
                driver_name TEXT,
                driver_phone TEXT,
                address TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                collection_amount REAL NOT NULL DEFAULT 0,
                collected_amount REAL NOT NULL DEFAULT 0,
                collection_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Upgrade existing local databases without destructive migrations.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(deliveries)").fetchall()}
        if "collected_amount" not in columns:
            db.execute("ALTER TABLE deliveries ADD COLUMN collected_amount REAL NOT NULL DEFAULT 0")

        db.execute("""
            CREATE TABLE IF NOT EXISTS settlements (
                settlement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                merchant_name TEXT NOT NULL,
                gross_amount REAL NOT NULL DEFAULT 0,
                commission_amount REAL NOT NULL DEFAULT 0,
                merchant_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                settled_at TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS returns (
                return_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'requested',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.commit()


_ALLOWED_LOOKUPS = {
    "deliveries": {"delivery_id"},
    "returns": {"return_id"},
    "settlements": {"settlement_id"},
}


def _get_row(table, key, value):
    if table not in _ALLOWED_LOOKUPS:
        raise ValueError("invalid_table")
    if key not in _ALLOWED_LOOKUPS[table]:
        raise ValueError("invalid_key")
    with get_connection() as db:
        row = db.execute(
            f"SELECT * FROM {table} WHERE {key}=?",
            (value,),
        ).fetchone()
        return dict(row) if row else None


def create_delivery(order_id, address, provider=None, collection_amount=0):
    ensure_operations_schema()
    now = utc_now()
    with get_connection() as db:
        cur = db.execute(
            """INSERT INTO deliveries
            (order_id,provider,address,collection_amount,created_at,updated_at)
            VALUES (?,?,?,?,?,?)""",
            (order_id, provider, address, collection_amount, now, now),
        )
        db.commit()
        return cur.lastrowid


def get_delivery(delivery_id):
    ensure_operations_schema()
    return _get_row("deliveries", "delivery_id", delivery_id)


def update_delivery_status(delivery_id, status, note=None):
    ensure_operations_schema()
    delivery = get_delivery(delivery_id)
    if not delivery:
        raise ValueError("delivery_not_found")
    current = delivery["status"]
    if status != current and status not in DELIVERY_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid_delivery_transition:{current}->{status}")
    now = utc_now()
    with get_connection() as db:
        db.execute("UPDATE deliveries SET status=?,updated_at=? WHERE delivery_id=?",
                   (status, now, delivery_id))
        db.commit()
    return get_delivery(delivery_id)


def reconcile_collection(delivery_id, collected_amount):
    ensure_operations_schema()
    delivery = get_delivery(delivery_id)
    if not delivery:
        raise ValueError("delivery_not_found")
    if delivery["status"] != "delivered":
        raise ValueError("collection_requires_delivered")
    expected = round(float(delivery["collection_amount"]), 2)
    actual = round(float(collected_amount), 2)
    if actual != expected:
        with get_connection() as db:
            db.execute("UPDATE deliveries SET collected_amount=?,collection_status=?,updated_at=? WHERE delivery_id=?",
                       (actual, "mismatch", utc_now(), delivery_id))
            db.commit()
        raise ValueError(f"collection_mismatch:expected={expected}:actual={actual}")
    with get_connection() as db:
        db.execute("UPDATE deliveries SET collected_amount=?,collection_status=?,updated_at=? WHERE delivery_id=?",
                   (actual, "reconciled", utc_now(), delivery_id))
        db.commit()
    return get_delivery(delivery_id)


def request_return(order_id, reason=None):
    ensure_operations_schema()
    now = utc_now()
    with get_connection() as db:
        existing = db.execute(
            "SELECT * FROM returns WHERE order_id=? AND status NOT IN ('closed','rejected') ORDER BY return_id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if existing:
            return existing["return_id"]
        cur = db.execute(
            "INSERT INTO returns (order_id,reason,status,created_at,updated_at) VALUES (?,?,?,?,?)",
            (order_id, reason, "requested", now, now),
        )
        db.commit()
        return cur.lastrowid


def get_return(return_id):
    ensure_operations_schema()
    return _get_row("returns", "return_id", return_id)


def update_return_status(return_id, status):
    ensure_operations_schema()
    item = get_return(return_id)
    if not item:
        raise ValueError("return_not_found")
    current = item["status"]
    if status != current and status not in RETURN_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid_return_transition:{current}->{status}")
    with get_connection() as db:
        db.execute("UPDATE returns SET status=?,updated_at=? WHERE return_id=?",
                   (status, utc_now(), return_id))
        db.commit()
    return get_return(return_id)


def create_settlement(order_id, merchant_name, gross_amount, commission_rate):
    ensure_operations_schema()
    gross = float(gross_amount)
    rate = float(commission_rate)
    if gross < 0 or rate < 0 or rate > 1:
        raise ValueError("invalid_settlement_values")
    commission = round(gross * rate, 2)
    merchant_amount = round(gross - commission, 2)
    with get_connection() as db:
        cur = db.execute(
            """INSERT INTO settlements
            (order_id,merchant_name,gross_amount,commission_amount,merchant_amount,created_at)
            VALUES (?,?,?,?,?,?)""",
            (order_id, merchant_name, gross, commission, merchant_amount, utc_now()),
        )
        db.commit()
        return cur.lastrowid


def get_settlement(settlement_id):
    ensure_operations_schema()
    return _get_row("settlements", "settlement_id", settlement_id)


def _verified_order(order_id):
    ensure_operations_schema()
    with get_connection() as db:
        delivery = db.execute(
            "SELECT * FROM deliveries WHERE order_id=? ORDER BY delivery_id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if not delivery:
            return None
        return dict(delivery)


def approve_order_commission(order_id):
    """Create/activate commission liability when the merchant approves the order."""
    ensure_operations_schema()
    with get_connection() as db:
        row = db.execute(
            "SELECT * FROM settlements WHERE order_id=? ORDER BY settlement_id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if not row:
            raise ValueError("settlement_not_created")
        if row["status"] == "pending":
            db.execute("UPDATE settlements SET status=? WHERE settlement_id=?", ("due", row["settlement_id"]))
            db.commit()
        return get_settlement(row["settlement_id"])


def reverse_commission_for_approved_return(order_id):
    """Reverse the commission only after an approved return claim."""
    ensure_operations_schema()
    with get_connection() as db:
        row = db.execute(
            "SELECT * FROM settlements WHERE order_id=? ORDER BY settlement_id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        if not row:
            raise ValueError("settlement_not_found")
        if row["status"] not in {"due", "confirmed"}:
            raise ValueError("commission_not_reversible")
        db.execute(
            "UPDATE settlements SET status=?,commission_amount=0,merchant_amount=gross_amount WHERE settlement_id=?",
            ("reversed", row["settlement_id"]),
        )
        db.commit()
        return get_settlement(row["settlement_id"])


def finalize_settlement(order_id, settlement_id):
    ensure_operations_schema()
    settlement = get_settlement(settlement_id)
    if not settlement or settlement["order_id"] != order_id:
        raise ValueError("settlement_not_found")
    if settlement["status"] != "pending":
        return settlement
    with get_connection() as db:
        db.execute("UPDATE settlements SET status=? WHERE settlement_id=?", ("due", settlement_id))
        db.commit()
    return get_settlement(settlement_id)


def confirm_settlement(settlement_id):
    settlement = get_settlement(settlement_id)
    if not settlement:
        raise ValueError("settlement_not_found")
    if settlement["status"] not in {"due", "confirmed"}:
        raise ValueError("settlement_not_due")
    with get_connection() as db:
        db.execute("UPDATE settlements SET status=? WHERE settlement_id=?", ("confirmed", settlement_id))
        db.commit()
    return get_settlement(settlement_id)


def mark_settlement_paid(settlement_id):
    settlement = get_settlement(settlement_id)
    if not settlement:
        raise ValueError("settlement_not_found")
    if settlement["status"] != "confirmed":
        raise ValueError("settlement_requires_confirmation")
    with get_connection() as db:
        db.execute(
            "UPDATE settlements SET status=?,settled_at=? WHERE settlement_id=?",
            ("paid", utc_now(), settlement_id),
        )
        db.commit()
    return get_settlement(settlement_id)


def merchant_daily_statement(merchant_name):
    """Return a reconciliation-ready daily statement from recorded settlement events."""
    ensure_operations_schema()
    with get_connection() as db:
        rows = db.execute(
            "SELECT * FROM settlements WHERE merchant_name=? ORDER BY settlement_id DESC",
            (merchant_name,),
        ).fetchall()
    items = [dict(r) for r in rows]
    totals = {
        "gross_sales": round(sum(float(x["gross_amount"]) for x in items if x["status"] != "reversed"), 2),
        "commission_due": round(sum(float(x["commission_amount"]) for x in items if x["status"] in {"due", "confirmed"}), 2),
        "commission_paid": round(sum(float(x["commission_amount"]) for x in items if x["status"] == "paid"), 2),
        "reversed_commission": round(sum(float(x["gross_amount"]) * 0 + (0 if x["status"] != "reversed" else 1) for x in items), 2),
    }
    return {"merchant": merchant_name, "items": items, "totals": totals}
