"""Small, numbered SQLite schema migrations for Merchant OS."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


class MigrationError(RuntimeError):
    """Raised when the database migration state is inconsistent."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: tuple[str, ...]
    backfill: str | None = None

    @property
    def checksum(self) -> str:
        text = "\n-- statement --\n".join(self.sql)
        if self.backfill is not None:
            text += "\n-- backfill --\n" + self.backfill
        payload = text.encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


MIGRATIONS = (
    Migration(
        version=1,
        name="migration_history",
        sql=(
            """CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )""",
        ),
    ),
    Migration(
        version=2,
        name="offer_merchant_and_inventory_mode",
        sql=(
            "ALTER TABLE offers ADD COLUMN merchant_id INTEGER REFERENCES merchants(merchant_id)",
            "ALTER TABLE offers ADD COLUMN inventory_managed INTEGER NOT NULL DEFAULT 0 CHECK (inventory_managed IN (0, 1))",
            "CREATE INDEX idx_offers_product_active ON offers(product_id, active)",
            "CREATE INDEX idx_offers_merchant_active ON offers(merchant_id, active)",
        ),
    ),
    Migration(
        version=3,
        name="order_item_historical_offer_identity",
        sql=(
            "ALTER TABLE order_items ADD COLUMN offer_id INTEGER REFERENCES offers(offer_id) ON DELETE RESTRICT",
            "ALTER TABLE order_items ADD COLUMN merchant_id INTEGER REFERENCES merchants(merchant_id) ON DELETE RESTRICT",
            "ALTER TABLE order_items ADD COLUMN currency TEXT",
            "ALTER TABLE order_items ADD COLUMN line_total REAL",
            "ALTER TABLE order_items ADD COLUMN product_name_snapshot TEXT",
            "ALTER TABLE order_items ADD COLUMN sku_snapshot TEXT",
            "ALTER TABLE order_items ADD COLUMN merchant_name_snapshot TEXT",
            "CREATE INDEX idx_order_items_order ON order_items(order_id)",
            "CREATE INDEX idx_order_items_offer ON order_items(offer_id)",
            "CREATE INDEX idx_order_items_merchant ON order_items(merchant_id)",
        ),
    ),
    Migration(
        version=4,
        name="guest_sessions_and_multi_merchant_cart_foundation",
        sql=(
            "CREATE TEMP TABLE _migration4_customer_sequence(seq INTEGER)",
            "INSERT INTO _migration4_customer_sequence(seq) SELECT seq FROM sqlite_sequence WHERE name='customers'",
            """CREATE TABLE customers_migration4 (
                customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT UNIQUE,
                name TEXT,
                phone TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                metadata TEXT
            )""",
            """INSERT INTO customers_migration4
                (customer_id, wa_id, name, phone, first_seen_at, last_seen_at, metadata)
                SELECT customer_id, wa_id, name, phone, first_seen_at, last_seen_at, metadata
                FROM customers""",
            "DROP TABLE customers",
            "ALTER TABLE customers_migration4 RENAME TO customers",
            """UPDATE sqlite_sequence
                SET seq = max(seq, COALESCE((SELECT max(seq) FROM _migration4_customer_sequence), 0))
                WHERE name='customers'""",
            """INSERT INTO sqlite_sequence(name, seq)
                SELECT 'customers', max(seq) FROM _migration4_customer_sequence
                HAVING max(seq) IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='customers')""",
            "DROP TABLE _migration4_customer_sequence",
            """CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                customer_id INTEGER NULL REFERENCES customers(customer_id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT NULL
            )""",
            """CREATE TABLE delivery_zones (
                zone_id INTEGER PRIMARY KEY,
                zone_code TEXT NOT NULL UNIQUE,
                city_name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )""",
            """CREATE TABLE merchant_delivery_policies (
                policy_id INTEGER PRIMARY KEY,
                merchant_id INTEGER NOT NULL REFERENCES merchants(merchant_id) ON DELETE RESTRICT,
                zone_id INTEGER NOT NULL REFERENCES delivery_zones(zone_id) ON DELETE RESTRICT,
                delivery_fee REAL NOT NULL CHECK(delivery_fee >= 0),
                currency TEXT NOT NULL DEFAULT 'YER' CHECK(currency = 'YER'),
                active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                UNIQUE(merchant_id, zone_id)
            )""",
            """CREATE TABLE carts (
                cart_id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
                customer_id INTEGER NULL REFERENCES customers(customer_id) ON DELETE SET NULL,
                delivery_zone_id INTEGER NULL REFERENCES delivery_zones(zone_id) ON DELETE RESTRICT,
                currency TEXT NOT NULL DEFAULT 'YER' CHECK(currency = 'YER'),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','checked_out','merged','expired')),
                merged_into_cart_id INTEGER NULL REFERENCES carts(cart_id) ON DELETE RESTRICT,
                checkout_order_id INTEGER NULL UNIQUE REFERENCES orders(order_id) ON DELETE RESTRICT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                checked_out_at TEXT NULL
            )""",
            "CREATE UNIQUE INDEX ux_carts_active_session ON carts(session_id) WHERE status = 'active'",
            "CREATE UNIQUE INDEX ux_carts_active_customer ON carts(customer_id) WHERE status = 'active' AND customer_id IS NOT NULL",
            """CREATE TABLE cart_items (
                cart_item_id INTEGER PRIMARY KEY,
                cart_id INTEGER NOT NULL REFERENCES carts(cart_id) ON DELETE CASCADE,
                offer_id INTEGER NOT NULL REFERENCES offers(offer_id) ON DELETE RESTRICT,
                quantity INTEGER NOT NULL CHECK(quantity > 0 AND typeof(quantity) = 'integer'),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(cart_id, offer_id)
            )""",
            "CREATE INDEX idx_cart_items_offer ON cart_items(offer_id)",
            """CREATE TRIGGER cart_items_require_eligible_offer_insert
                BEFORE INSERT ON cart_items
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM offers o
                    JOIN products p ON p.product_id=o.product_id
                    JOIN merchants m ON m.merchant_id=o.merchant_id
                    WHERE o.offer_id=NEW.offer_id
                      AND o.active=1 AND p.active=1
                      AND o.merchant_id IS NOT NULL
                      AND m.status='active' AND o.currency='YER'
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cart_offer_ineligible');
                END""",
            """CREATE TRIGGER cart_items_require_eligible_offer_update
                BEFORE UPDATE OF offer_id ON cart_items
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM offers o
                    JOIN products p ON p.product_id=o.product_id
                    JOIN merchants m ON m.merchant_id=o.merchant_id
                    WHERE o.offer_id=NEW.offer_id
                      AND o.active=1 AND p.active=1
                      AND o.merchant_id IS NOT NULL
                      AND m.status='active' AND o.currency='YER'
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cart_offer_ineligible');
                END""",
        ),
    ),
    Migration(
        version=5,
        name="order_architecture_foundation",
        sql=(
            """CREATE TABLE checkout_idempotency (
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
                cart_id INTEGER NOT NULL REFERENCES carts(cart_id) ON DELETE RESTRICT,
                key_hash TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                quote_revision TEXT NOT NULL,
                order_id INTEGER NOT NULL UNIQUE REFERENCES orders(order_id) ON DELETE RESTRICT,
                created_at TEXT NOT NULL,
                PRIMARY KEY(session_id, key_hash),
                UNIQUE(cart_id)
            )""",
            """CREATE TABLE merchant_orders (
                merchant_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE RESTRICT,
                merchant_id INTEGER NOT NULL REFERENCES merchants(merchant_id) ON DELETE RESTRICT,
                merchant_name_snapshot TEXT NOT NULL,
                products_subtotal REAL NOT NULL,
                delivery_fee REAL NOT NULL CHECK(delivery_fee >= 0),
                total REAL NOT NULL,
                currency TEXT NOT NULL CHECK(currency = 'YER'),
                status TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(order_id, merchant_id),
                UNIQUE(merchant_order_id, order_id, merchant_id)
            )""",
            """CREATE TABLE fulfillments (
                fulfillment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_order_id INTEGER NOT NULL REFERENCES merchant_orders(merchant_order_id) ON DELETE RESTRICT,
                fulfillment_number INTEGER NOT NULL CHECK(fulfillment_number > 0),
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(merchant_order_id, fulfillment_number)
            )""",
            "ALTER TABLE orders ADD COLUMN recipient_name_snapshot TEXT",
            "ALTER TABLE orders ADD COLUMN recipient_phone_snapshot TEXT",
            "ALTER TABLE orders ADD COLUMN payment_method TEXT CHECK(payment_method IS NULL OR payment_method = 'cod')",
            "ALTER TABLE deliveries ADD COLUMN fulfillment_id INTEGER REFERENCES fulfillments(fulfillment_id) ON DELETE RESTRICT",
            "ALTER TABLE settlements ADD COLUMN merchant_order_id INTEGER REFERENCES merchant_orders(merchant_order_id) ON DELETE RESTRICT",
            "CREATE TEMP TABLE _migration5_order_item_sequence(seq INTEGER)",
            "INSERT INTO _migration5_order_item_sequence(seq) SELECT seq FROM sqlite_sequence WHERE name='order_items'",
            """CREATE TABLE order_items_migration5 (
                order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                unit_price REAL NOT NULL,
                offer_id INTEGER REFERENCES offers(offer_id) ON DELETE RESTRICT,
                merchant_id INTEGER REFERENCES merchants(merchant_id) ON DELETE RESTRICT,
                currency TEXT,
                line_total REAL,
                product_name_snapshot TEXT,
                sku_snapshot TEXT,
                merchant_name_snapshot TEXT,
                merchant_order_id INTEGER REFERENCES merchant_orders(merchant_order_id) ON DELETE RESTRICT,
                FOREIGN KEY(order_id) REFERENCES orders(order_id),
                FOREIGN KEY(product_id) REFERENCES products(product_id),
                FOREIGN KEY(merchant_order_id, order_id, merchant_id)
                    REFERENCES merchant_orders(merchant_order_id, order_id, merchant_id) ON DELETE RESTRICT
            )""",
            """INSERT INTO order_items_migration5 (
                order_item_id, order_id, product_id, quantity, unit_price,
                offer_id, merchant_id, currency, line_total, product_name_snapshot,
                sku_snapshot, merchant_name_snapshot, merchant_order_id
            ) SELECT order_item_id, order_id, product_id, quantity, unit_price,
                offer_id, merchant_id, currency, line_total, product_name_snapshot,
                sku_snapshot, merchant_name_snapshot, NULL FROM order_items""",
            "DROP TABLE order_items",
            "ALTER TABLE order_items_migration5 RENAME TO order_items",
            """UPDATE sqlite_sequence
                SET seq = max(seq, COALESCE((SELECT max(seq) FROM _migration5_order_item_sequence), 0))
                WHERE name='order_items'""",
            """INSERT INTO sqlite_sequence(name, seq)
                SELECT 'order_items', max(seq) FROM _migration5_order_item_sequence
                HAVING max(seq) IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='order_items')""",
            "DROP TABLE _migration5_order_item_sequence",
            "CREATE INDEX idx_order_items_merchant_order ON order_items(merchant_order_id, order_id, merchant_id)",
            "CREATE INDEX idx_deliveries_fulfillment ON deliveries(fulfillment_id)",
            "CREATE INDEX idx_settlements_merchant_order ON settlements(merchant_order_id)",
            "CREATE INDEX idx_merchant_orders_merchant ON merchant_orders(merchant_id)",
            "CREATE INDEX idx_order_items_order ON order_items(order_id)",
            "CREATE INDEX idx_order_items_offer ON order_items(offer_id)",
            "CREATE INDEX idx_order_items_merchant ON order_items(merchant_id)",
        ),
    ),
    Migration(
        version=6,
        name="commerce_lifecycle_inventory_delivery_settlement",
        sql=(
            "ALTER TABLE merchant_delivery_policies ADD COLUMN merchant_receives_delivery_fee INTEGER NOT NULL DEFAULT 0 CHECK(merchant_receives_delivery_fee IN (0,1))",
            "ALTER TABLE deliveries ADD COLUMN delivery_address_snapshot TEXT",
            "ALTER TABLE deliveries ADD COLUMN delivery_zone_id INTEGER REFERENCES delivery_zones(zone_id) ON DELETE RESTRICT",
            "ALTER TABLE deliveries ADD COLUMN delivery_zone_snapshot TEXT",
            "ALTER TABLE deliveries ADD COLUMN customer_delivery_fee REAL CHECK(customer_delivery_fee IS NULL OR customer_delivery_fee >= 0)",
            "ALTER TABLE deliveries ADD COLUMN assigned_at TEXT",
            "ALTER TABLE deliveries ADD COLUMN shipped_at TEXT",
            "ALTER TABLE deliveries ADD COLUMN delivered_at TEXT",
            "ALTER TABLE deliveries ADD COLUMN cancelled_at TEXT",
            "ALTER TABLE deliveries ADD COLUMN creation_key_hash TEXT",
            "CREATE UNIQUE INDEX ux_deliveries_creation_key_hash ON deliveries(creation_key_hash) WHERE creation_key_hash IS NOT NULL",
            "ALTER TABLE merchant_orders ADD COLUMN merchant_receives_delivery_fee INTEGER NOT NULL DEFAULT 0 CHECK(merchant_receives_delivery_fee IN (0,1))",
            "ALTER TABLE merchant_orders ADD COLUMN delivery_zone_id INTEGER REFERENCES delivery_zones(zone_id) ON DELETE RESTRICT",
            "ALTER TABLE merchant_orders ADD COLUMN delivery_zone_snapshot TEXT",
            "ALTER TABLE settlements ADD COLUMN currency TEXT NOT NULL DEFAULT 'YER' CHECK(currency='YER')",
            "ALTER TABLE settlements ADD COLUMN commission_rate_bps INTEGER CHECK(commission_rate_bps IS NULL OR commission_rate_bps BETWEEN 0 AND 10000)",
            "ALTER TABLE settlements ADD COLUMN merchant_receives_delivery_fee INTEGER NOT NULL DEFAULT 0 CHECK(merchant_receives_delivery_fee IN (0,1))",
            "ALTER TABLE settlements ADD COLUMN delivery_fee_snapshot REAL NOT NULL DEFAULT 0 CHECK(delivery_fee_snapshot >= 0)",
            "CREATE UNIQUE INDEX ux_settlements_merchant_order ON settlements(merchant_order_id) WHERE merchant_order_id IS NOT NULL",
            "CREATE TABLE commerce_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, actor_type TEXT NOT NULL CHECK(actor_type IN ('SYSTEM','CUSTOMER','MERCHANT','ADMIN')), actor_ref TEXT, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, dedupe_key TEXT UNIQUE, details_json TEXT, created_at TEXT NOT NULL)",
            "CREATE INDEX idx_commerce_events_entity ON commerce_events(entity_type, entity_id, created_at)",
            "CREATE TABLE inventory_movements (movement_id INTEGER PRIMARY KEY AUTOINCREMENT, order_item_id INTEGER NOT NULL REFERENCES order_items(order_item_id) ON DELETE RESTRICT, offer_id INTEGER NOT NULL REFERENCES offers(offer_id) ON DELETE RESTRICT, movement_type TEXT NOT NULL CHECK(movement_type IN ('STOCK_DECREMENTED','STOCK_RESTORED')), quantity INTEGER NOT NULL CHECK(quantity > 0 AND typeof(quantity)='integer'), dedupe_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, UNIQUE(order_item_id, movement_type))",
            "CREATE INDEX idx_inventory_movements_offer ON inventory_movements(offer_id)",
            "CREATE TABLE fulfillment_items (fulfillment_item_id INTEGER PRIMARY KEY AUTOINCREMENT, fulfillment_id INTEGER NOT NULL REFERENCES fulfillments(fulfillment_id) ON DELETE RESTRICT, order_item_id INTEGER NOT NULL REFERENCES order_items(order_item_id) ON DELETE RESTRICT, quantity INTEGER NOT NULL CHECK(quantity > 0 AND typeof(quantity)='integer'), created_at TEXT NOT NULL, UNIQUE(fulfillment_id, order_item_id))",
            "CREATE INDEX idx_fulfillment_items_order_item ON fulfillment_items(order_item_id)",
            "CREATE TABLE delivery_items (delivery_item_id INTEGER PRIMARY KEY AUTOINCREMENT, delivery_id INTEGER NOT NULL REFERENCES deliveries(delivery_id) ON DELETE RESTRICT, fulfillment_item_id INTEGER NOT NULL REFERENCES fulfillment_items(fulfillment_item_id) ON DELETE RESTRICT, quantity INTEGER NOT NULL CHECK(quantity > 0 AND typeof(quantity)='integer'), created_at TEXT NOT NULL, UNIQUE(delivery_id, fulfillment_item_id))",
            "CREATE INDEX idx_delivery_items_fulfillment_item ON delivery_items(fulfillment_item_id)",
            "CREATE TRIGGER inventory_movement_matches_order_item BEFORE INSERT ON inventory_movements WHEN NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_item_id=NEW.order_item_id AND i.offer_id=NEW.offer_id AND i.quantity>0 AND i.quantity=CAST(i.quantity AS INTEGER) AND i.quantity=NEW.quantity) BEGIN SELECT RAISE(ABORT,'inventory_movement_order_item_mismatch'); END",
            "CREATE TRIGGER fulfillment_item_matches_order_item BEFORE INSERT ON fulfillment_items WHEN NOT EXISTS (SELECT 1 FROM fulfillments f JOIN order_items i ON i.merchant_order_id=f.merchant_order_id WHERE f.fulfillment_id=NEW.fulfillment_id AND i.order_item_id=NEW.order_item_id AND i.quantity>0 AND i.quantity=CAST(i.quantity AS INTEGER) AND NEW.quantity<=i.quantity) BEGIN SELECT RAISE(ABORT,'fulfillment_item_order_item_mismatch'); END",
            "CREATE TRIGGER delivery_matches_fulfillment_order BEFORE INSERT ON deliveries WHEN NEW.fulfillment_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM fulfillments f JOIN merchant_orders mo ON mo.merchant_order_id=f.merchant_order_id WHERE f.fulfillment_id=NEW.fulfillment_id AND mo.order_id=NEW.order_id) BEGIN SELECT RAISE(ABORT,'delivery_fulfillment_order_mismatch'); END",
            "CREATE TRIGGER settlement_matches_merchant_order BEFORE INSERT ON settlements WHEN NEW.merchant_order_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM merchant_orders mo WHERE mo.merchant_order_id=NEW.merchant_order_id AND mo.order_id=NEW.order_id) BEGIN SELECT RAISE(ABORT,'settlement_merchant_order_mismatch'); END",
            "CREATE TRIGGER delivery_item_matches_fulfillment BEFORE INSERT ON delivery_items WHEN NOT EXISTS (SELECT 1 FROM deliveries d JOIN fulfillment_items fi ON fi.fulfillment_item_id=NEW.fulfillment_item_id WHERE d.delivery_id=NEW.delivery_id AND d.fulfillment_id=fi.fulfillment_id AND typeof(NEW.quantity)='integer' AND NEW.quantity>0 AND (SELECT COALESCE(SUM(di.quantity),0) FROM delivery_items di JOIN deliveries dx ON dx.delivery_id=di.delivery_id WHERE di.fulfillment_item_id=NEW.fulfillment_item_id AND dx.status<>'cancelled')+NEW.quantity<=fi.quantity) BEGIN SELECT RAISE(ABORT,'delivery_item_fulfillment_mismatch'); END",
        ),
    ),
    Migration(
        version=7,
        name="yer_integer_minor_money_foundation",
        backfill="integer_yer_money_v1",
        sql=(
            "CREATE TABLE money_migration_issues (table_name TEXT NOT NULL, row_id INTEGER NOT NULL, legacy_column TEXT NOT NULL, legacy_value TEXT, reason TEXT NOT NULL, PRIMARY KEY(table_name,row_id,legacy_column))",
            "ALTER TABLE offers ADD COLUMN price_minor INTEGER CHECK(price_minor IS NULL OR (price_minor >= 0 AND typeof(price_minor)='integer'))",
            "ALTER TABLE merchant_delivery_policies ADD COLUMN delivery_fee_minor INTEGER CHECK(delivery_fee_minor IS NULL OR (delivery_fee_minor >= 0 AND typeof(delivery_fee_minor)='integer'))",
            "ALTER TABLE orders ADD COLUMN total_minor INTEGER CHECK(total_minor IS NULL OR (total_minor >= 0 AND typeof(total_minor)='integer'))",
            "ALTER TABLE order_items ADD COLUMN unit_price_minor INTEGER CHECK(unit_price_minor IS NULL OR (unit_price_minor >= 0 AND typeof(unit_price_minor)='integer'))",
            "ALTER TABLE order_items ADD COLUMN line_total_minor INTEGER CHECK(line_total_minor IS NULL OR (line_total_minor >= 0 AND typeof(line_total_minor)='integer'))",
            "ALTER TABLE merchant_orders ADD COLUMN products_subtotal_minor INTEGER CHECK(products_subtotal_minor IS NULL OR (products_subtotal_minor >= 0 AND typeof(products_subtotal_minor)='integer'))",
            "ALTER TABLE merchant_orders ADD COLUMN delivery_fee_minor INTEGER CHECK(delivery_fee_minor IS NULL OR (delivery_fee_minor >= 0 AND typeof(delivery_fee_minor)='integer'))",
            "ALTER TABLE merchant_orders ADD COLUMN total_minor INTEGER CHECK(total_minor IS NULL OR (total_minor >= 0 AND typeof(total_minor)='integer'))",
            "ALTER TABLE deliveries ADD COLUMN customer_delivery_fee_minor INTEGER CHECK(customer_delivery_fee_minor IS NULL OR (customer_delivery_fee_minor >= 0 AND typeof(customer_delivery_fee_minor)='integer'))",
            "ALTER TABLE deliveries ADD COLUMN collection_amount_minor INTEGER CHECK(collection_amount_minor IS NULL OR (collection_amount_minor >= 0 AND typeof(collection_amount_minor)='integer'))",
            "ALTER TABLE deliveries ADD COLUMN collected_amount_minor INTEGER CHECK(collected_amount_minor IS NULL OR (collected_amount_minor >= 0 AND typeof(collected_amount_minor)='integer'))",
            "ALTER TABLE settlements ADD COLUMN gross_amount_minor INTEGER CHECK(gross_amount_minor IS NULL OR (gross_amount_minor >= 0 AND typeof(gross_amount_minor)='integer'))",
            "ALTER TABLE settlements ADD COLUMN commission_amount_minor INTEGER CHECK(commission_amount_minor IS NULL OR (commission_amount_minor >= 0 AND typeof(commission_amount_minor)='integer'))",
            "ALTER TABLE settlements ADD COLUMN merchant_amount_minor INTEGER CHECK(merchant_amount_minor IS NULL OR (merchant_amount_minor >= 0 AND typeof(merchant_amount_minor)='integer'))",
            "ALTER TABLE settlements ADD COLUMN delivery_fee_minor INTEGER CHECK(delivery_fee_minor IS NULL OR (delivery_fee_minor >= 0 AND typeof(delivery_fee_minor)='integer'))",
        ),
    ),
)


_MONEY_BACKFILL = (
    ("offers", "offer_id", "price", "price_minor"),
    ("merchant_delivery_policies", "policy_id", "delivery_fee", "delivery_fee_minor"),
    ("orders", "order_id", "total", "total_minor"),
    ("order_items", "order_item_id", "unit_price", "unit_price_minor"),
    ("order_items", "order_item_id", "line_total", "line_total_minor"),
    ("merchant_orders", "merchant_order_id", "products_subtotal", "products_subtotal_minor"),
    ("merchant_orders", "merchant_order_id", "delivery_fee", "delivery_fee_minor"),
    ("merchant_orders", "merchant_order_id", "total", "total_minor"),
    ("deliveries", "delivery_id", "customer_delivery_fee", "customer_delivery_fee_minor"),
    ("deliveries", "delivery_id", "collection_amount", "collection_amount_minor"),
    ("deliveries", "delivery_id", "collected_amount", "collected_amount_minor"),
    ("settlements", "settlement_id", "gross_amount", "gross_amount_minor"),
    ("settlements", "settlement_id", "commission_amount", "commission_amount_minor"),
    ("settlements", "settlement_id", "merchant_amount", "merchant_amount_minor"),
    ("settlements", "settlement_id", "delivery_fee_snapshot", "delivery_fee_minor"),
)


def _backfill_integer_money(db: sqlite3.Connection) -> None:
    """Copy exact whole-YER amounts; preserve non-integral legacy values for review."""
    for table, pk, legacy, canonical in _MONEY_BACKFILL:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if legacy not in columns or canonical not in columns or pk not in columns:
            continue
        rows = db.execute(f"SELECT {pk}, {legacy} FROM {table} WHERE {legacy} IS NOT NULL").fetchall()
        for row in rows:
            try:
                value = Decimal(str(row[1]))
            except (InvalidOperation, TypeError, ValueError):
                value = None
            if value is None or not value.is_finite() or value < 0 or value != value.to_integral_value():
                db.execute("INSERT INTO money_migration_issues(table_name,row_id,legacy_column,legacy_value,reason) VALUES(?,?,?,?,?)",
                           (table, row[0], legacy, str(row[1]), "not_exact_nonnegative_integer_yer"))
                continue
            db.execute(f"UPDATE {table} SET {canonical}=? WHERE {pk}=?", (int(value), row[0]))


def _connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    db = sqlite3.connect(os.fspath(path), timeout=30)
    db.row_factory = sqlite3.Row
    return db


def migration_status(db: sqlite3.Connection) -> list[dict]:
    """Return recorded migrations and validate them against this code."""
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "schema_migrations" not in tables:
        if db.execute("PRAGMA user_version").fetchone()[0] != 0:
            raise MigrationError("user_version is nonzero but schema_migrations is missing")
        return []

    rows = [dict(row) for row in db.execute(
        "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
    )]
    known = {migration.version: migration for migration in MIGRATIONS}
    for expected_version, row in enumerate(rows, start=1):
        if row["version"] != expected_version:
            raise MigrationError("Migration history contains a gap or an out-of-order version")
        migration = known.get(row["version"])
        if migration is None:
            raise MigrationError(f"Database contains unknown migration version {row['version']}")
        if row["name"] != migration.name or row["checksum"] != migration.checksum:
            raise MigrationError(f"Migration {row['version']} does not match its recorded definition")

    user_version = db.execute("PRAGMA user_version").fetchone()[0]
    if user_version != len(rows):
        raise MigrationError(
            f"user_version ({user_version}) does not match migration history ({len(rows)})"
        )
    return rows


def apply_migrations(path: str | os.PathLike[str]) -> dict:
    """Apply every pending migration atomically, one version at a time."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Database does not exist: {path}")
    db = _connect(path)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise MigrationError(
                f"Database version {version} is newer than supported version {len(MIGRATIONS)}"
            )
        recorded = migration_status(db)
        applied = []
        for migration in MIGRATIONS:
            if migration.version <= version:
                continue
            if migration.version != version + 1:
                raise MigrationError("Migration versions must be contiguous and applied in order")
            db.execute("BEGIN IMMEDIATE")
            try:
                for statement in migration.sql:
                    db.execute(statement)
                if migration.backfill == "integer_yer_money_v1":
                    _backfill_integer_money(db)
                applied_at = datetime.now(timezone.utc).isoformat()
                db.execute(
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, applied_at),
                )
                db.execute(f"PRAGMA user_version = {migration.version}")
                db.commit()
            except Exception:
                db.rollback()
                raise
            version = migration.version
            applied.append(migration.version)
        return {"before_version": len(recorded), "version": version, "applied": applied}
    finally:
        db.close()


def create_backup(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    """Create a consistent SQLite backup without modifying the source database."""
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise FileNotFoundError(f"Database does not exist: {source}")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_db = sqlite3.connect(os.fspath(source), timeout=30)
    backup_db = sqlite3.connect(os.fspath(destination), timeout=30)
    try:
        source_db.backup(backup_db)
        result = backup_db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {result}")
    except Exception:
        backup_db.close()
        source_db.close()
        destination.unlink(missing_ok=True)
        raise
    else:
        backup_db.close()
        source_db.close()
    return destination
