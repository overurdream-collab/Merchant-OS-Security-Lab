from .database import get_connection, utc_now
from .merchants import ensure_merchant_schema
from decimal import Decimal, InvalidOperation


def ensure_catalog_schema():
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                offer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                merchant_name TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'YER',
                stock REAL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(product_id)
            )
        """)
        db.commit()


def create_product(name, sku=None, description=None):
    ensure_catalog_schema()
    now = utc_now()
    with get_connection() as db:
        cur = db.execute(
            "INSERT INTO products (sku,name,description,created_at,updated_at) VALUES (?,?,?,?,?)",
            (sku, name, description, now, now),
        )
        db.commit()
        return cur.lastrowid


def add_offer(product_id, merchant_id, price, currency="YER", stock=None, inventory_managed=0):
    ensure_catalog_schema()
    ensure_merchant_schema()
    now = utc_now()
    try:
        amount = Decimal(str(price))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("price_must_be_nonnegative_integer_yer") from None
    if currency != "YER" or not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise ValueError("price_must_be_nonnegative_integer_yer")
    price_minor = int(amount)
    with get_connection() as db:
        offer_columns = {row[1] for row in db.execute("PRAGMA table_info(offers)")}
        if not {"merchant_id", "inventory_managed"}.issubset(offer_columns):
            raise RuntimeError("catalog_migration_required: run db-migrate before adding offers")
        # Enforce this relationship for offer writes without changing project-wide defaults.
        db.execute("PRAGMA foreign_keys=ON")
        merchant = db.execute(
            "SELECT name FROM merchants WHERE merchant_id=?", (merchant_id,)
        ).fetchone()
        if merchant is None:
            raise ValueError("merchant_not_found")
        columns = {row[1] for row in db.execute("PRAGMA table_info(offers)")}
        money_columns = ",price_minor" if "price_minor" in columns else ""
        values_tail = ",?" if money_columns else ""
        args = (product_id, merchant["name"], price_minor, currency, stock, now, now, merchant_id, inventory_managed)
        if money_columns:
            args += (price_minor,)
        cur = db.execute(
            """INSERT INTO offers
            (product_id,merchant_name,price,currency,stock,created_at,updated_at,merchant_id,inventory_managed"""
            + money_columns + ") VALUES (?,?,?,?,?,?,?,?,?" + values_tail + ")",
            args,
        )
        db.commit()
        return cur.lastrowid


def find_products(query, limit=5):
    ensure_catalog_schema()
    with get_connection() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(offers)")}
        if {"merchant_id", "inventory_managed"}.issubset(columns):
            sql = """
                SELECT p.*, o.offer_id, o.merchant_id,
                       COALESCE(m.name, o.merchant_name) AS merchant_name,
                       COALESCE(o.price_minor,o.price) AS price, o.price_minor, o.currency, o.stock, o.inventory_managed
                FROM products p
                LEFT JOIN offers o ON o.product_id=p.product_id AND o.active=1
                LEFT JOIN merchants m ON m.merchant_id=o.merchant_id
                WHERE p.active=1 AND (p.name LIKE ? OR p.sku LIKE ? OR p.description LIKE ?)
                ORDER BY p.updated_at DESC LIMIT ?
            """
        else:
            # Keep legacy catalog reads available while the database awaits migration 2.
            sql = """
                SELECT p.*, o.offer_id, NULL AS merchant_id, o.merchant_name,
                       o.price, NULL AS price_minor, o.currency, o.stock, 0 AS inventory_managed
                FROM products p
                LEFT JOIN offers o ON o.product_id=p.product_id AND o.active=1
                WHERE p.active=1 AND (p.name LIKE ? OR p.sku LIKE ? OR p.description LIKE ?)
                ORDER BY p.updated_at DESC LIMIT ?
            """
        rows = db.execute(sql, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
        return [dict(r) for r in rows]
