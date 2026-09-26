from contextlib import closing

from .database import get_connection, utc_now


def ensure_order_schema():
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                total REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'YER',
                delivery_address TEXT,
                payment_status TEXT NOT NULL DEFAULT 'unpaid',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                unit_price REAL NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(order_id),
                FOREIGN KEY(product_id) REFERENCES products(product_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS order_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(order_id)
            )
        """)
        db.commit()


def create_order(customer_id, items, delivery_address=None, currency="YER"):
    ensure_order_schema()
    now = utc_now()
    total = sum(float(i["quantity"]) * float(i["unit_price"]) for i in items)
    with get_connection() as db:
        cur = db.execute(
            """INSERT INTO orders
            (customer_id,status,total,currency,delivery_address,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)""",
            (customer_id, "pending", total, currency, delivery_address, now, now),
        )
        order_id = cur.lastrowid
        for item in items:
            db.execute(
                """INSERT INTO order_items
                (order_id,product_id,quantity,unit_price) VALUES (?,?,?,?)""",
                (order_id, item["product_id"], item["quantity"], item["unit_price"]),
            )
        db.execute(
            "INSERT INTO order_events (order_id,status,note,created_at) VALUES (?,?,?,?)",
            (order_id, "pending", "Order created", now),
        )
        db.commit()
        return get_order(order_id)


def _persist_offer_order_item(order_id, offer_id, quantity):
    """Persist one historical offer-backed line; this is not a checkout flow."""
    ensure_order_schema()
    with closing(get_connection()) as db:
        # Keep this FK setting local to the persistence connection. The project-wide
        # connection default remains unchanged.
        db.execute("PRAGMA foreign_keys=ON")
        with db:
            source = db.execute(
                """SELECT o.offer_id, o.product_id, o.merchant_id, o.price, o.currency,
                          p.name AS product_name, p.sku AS product_sku,
                          m.name AS merchant_name
                   FROM offers o
                   JOIN products p ON p.product_id=o.product_id
                   JOIN merchants m ON m.merchant_id=o.merchant_id
                   WHERE o.offer_id=?""",
                (offer_id,),
            ).fetchone()
            if source is None:
                raise ValueError("offer_or_catalog_relationship_not_found")
            unit_price = source["price"]
            line_total = float(quantity) * float(unit_price)
            cursor = db.execute(
                """INSERT INTO order_items
                   (order_id, product_id, quantity, unit_price, offer_id, merchant_id,
                    currency, line_total, product_name_snapshot, sku_snapshot,
                    merchant_name_snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    source["product_id"],
                    quantity,
                    unit_price,
                    source["offer_id"],
                    source["merchant_id"],
                    source["currency"],
                    line_total,
                    source["product_name"],
                    source["product_sku"],
                    source["merchant_name"],
                ),
            )
            return cursor.lastrowid


def get_order(order_id):
    ensure_order_schema()
    with get_connection() as db:
        row = db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if not row:
            return None
        return dict(row)


def update_order_status(order_id, status, note=None):
    ensure_order_schema()
    now = utc_now()
    with get_connection() as db:
        db.execute("UPDATE orders SET status=?,updated_at=? WHERE order_id=?", (status, now, order_id))
        db.execute(
            "INSERT INTO order_events (order_id,status,note,created_at) VALUES (?,?,?,?)",
            (order_id, status, note, now),
        )
        db.commit()
    return get_order(order_id)
