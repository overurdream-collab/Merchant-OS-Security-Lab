import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from merchant_os import migrations
from merchant_os.database_audit import audit_database
from merchant_os.migrations import Migration, MigrationError, apply_migrations, create_backup


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "merchant.sqlite3"
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("""CREATE TABLE customers (
                customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT UNIQUE NOT NULL,
                name TEXT, phone TEXT,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, metadata TEXT
            )""")
            db.execute("INSERT INTO customers(customer_id, wa_id, name, phone, first_seen_at, last_seen_at, metadata) VALUES (44, 'legacy-44', 'Legacy Name', '967700000044', 'first', 'last', '{\"keep\":true}')")
            db.execute("CREATE TABLE merchants (merchant_id INTEGER PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'lead')")
            db.execute("CREATE TABLE products (product_id INTEGER PRIMARY KEY, sku TEXT, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)")
            db.execute("""CREATE TABLE offers (
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
            )""")
            db.execute("CREATE TABLE conversations (conversation_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(customer_id))")
            db.execute("CREATE TABLE messages (message_id TEXT PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(customer_id))")
            db.execute("CREATE TABLE customer_interest_events (event_id TEXT PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(customer_id))")
            db.execute("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(customer_id))")
            db.execute("""CREATE TABLE order_items (
                order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                unit_price REAL NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(order_id),
                FOREIGN KEY(product_id) REFERENCES products(product_id)
            )""")
            db.execute("""CREATE TABLE deliveries (
                delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                provider TEXT, driver_name TEXT, driver_phone TEXT, address TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                collection_amount REAL NOT NULL DEFAULT 0,
                collected_amount REAL NOT NULL DEFAULT 0,
                collection_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE settlements (
                settlement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL, merchant_name TEXT NOT NULL,
                gross_amount REAL NOT NULL DEFAULT 0,
                commission_amount REAL NOT NULL DEFAULT 0,
                merchant_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL, settled_at TEXT
            )""")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_migrates_from_zero_to_current_version_and_preserves_ids(self):
        result = apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], len(migrations.MIGRATIONS))
            self.assertEqual(db.execute("SELECT customer_id FROM customers").fetchone()[0], 44)
            self.assertEqual(db.execute("SELECT version FROM schema_migrations").fetchall(), [(1,), (2,), (3,), (4,), (5,), (6,), (7,)])
            wa_id_notnull = {r[1]: r[3] for r in db.execute("PRAGMA table_info(customers)")}['wa_id']
            self.assertEqual(wa_id_notnull, 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM delivery_zones").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM merchant_delivery_policies").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM carts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cart_items").fetchone()[0], 0)
        self.assertEqual(result["applied"], [1, 2, 3, 4, 5, 6, 7])

    def test_migration_does_not_apply_twice(self):
        apply_migrations(self.database)
        result = apply_migrations(self.database)
        self.assertEqual(result["applied"], [])
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 7)

    def test_migration_3_applies_once_and_preserves_existing_order_item_ids(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("INSERT INTO orders(order_id, customer_id) VALUES (51, 44)")
            db.execute("INSERT INTO products(product_id, sku, name) VALUES (61, 'OLD', 'Old product')")
            db.execute("INSERT INTO order_items(order_item_id, order_id, product_id, quantity, unit_price) VALUES (71, 51, 61, 2, 3.5)")
        first = apply_migrations(self.database)
        second = apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(db.execute("SELECT order_item_id, order_id, product_id, quantity, unit_price, offer_id, merchant_id FROM order_items").fetchone(), (71, 51, 61, 2.0, 3.5, None, None))
            self.assertEqual(db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall(), [(1,), (2,), (3,), (4,), (5,), (6,), (7,)])
            self.assertEqual(db.execute("SELECT table_name,row_id,legacy_column,legacy_value FROM money_migration_issues").fetchall(), [('order_items', 71, 'unit_price', '3.5')])
        self.assertEqual(first["applied"], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(second["applied"], [])

    def test_migration_preserves_legacy_offer_id_and_stock_without_mapping(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("INSERT INTO products(product_id, sku, name) VALUES (7, 'SKU-7', 'Legacy product')")
            db.execute("INSERT INTO offers(offer_id, product_id, merchant_name, price, stock, created_at, updated_at) VALUES (19, 7, 'Unmatched merchant', 12.5, 3.5, 'a', 'b')")
        apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            row = db.execute("SELECT offer_id, merchant_id, merchant_name, stock, inventory_managed FROM offers").fetchone()
        self.assertEqual(row, (19, None, "Unmatched merchant", 3.5, 0))
        report = audit_database(self.database)
        self.assertEqual(report["orphaned_records"][0]["relationship"], "offers without merchant")
        self.assertIn("unlinked offers; exact-name matches are candidates only", {
            warning["relationship"] for warning in report["ambiguous_or_suspicious_links"]
        })

    def test_migration_4_preserves_customer_fields_ids_and_child_relationships(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("INSERT INTO conversations VALUES (81, 44)")
            db.execute("INSERT INTO messages VALUES ('msg-81', 44)")
            db.execute("INSERT INTO customer_interest_events VALUES ('interest-81', 44)")
            db.execute("INSERT INTO orders VALUES (91, 44)")
            # Keep the sequence above current IDs to prove the rebuild preserves it.
            db.execute("UPDATE sqlite_sequence SET seq=144 WHERE name='customers'")
        with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:3]):
            apply_migrations(self.database)
        with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:4]):
            result = apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            row = db.execute("SELECT customer_id, wa_id, name, phone, first_seen_at, last_seen_at, metadata FROM customers WHERE customer_id=44").fetchone()
            self.assertEqual(row, (44, 'legacy-44', 'Legacy Name', '967700000044', 'first', 'last', '{\"keep\":true}'))
            self.assertEqual(db.execute("SELECT customer_id FROM conversations WHERE conversation_id=81").fetchone(), (44,))
            self.assertEqual(db.execute("SELECT customer_id FROM messages WHERE message_id='msg-81'").fetchone(), (44,))
            self.assertEqual(db.execute("SELECT customer_id FROM customer_interest_events WHERE event_id='interest-81'").fetchone(), (44,))
            self.assertEqual(db.execute("SELECT customer_id FROM orders WHERE order_id=91").fetchone(), (44,))
            self.assertEqual(db.execute("SELECT seq FROM sqlite_sequence WHERE name='customers'").fetchone(), (144,))
            db.execute("INSERT INTO customers(wa_id, first_seen_at, last_seen_at) VALUES (NULL, 'f', 'l')")
            db.execute("INSERT INTO customers(wa_id, first_seen_at, last_seen_at) VALUES (NULL, 'f2', 'l2')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO customers(wa_id, first_seen_at, last_seen_at) VALUES ('legacy-44', 'f', 'l')")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(result["applied"], [4])

    def test_migration_4_can_be_applied_from_version_3_exactly_once(self):
        with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:3]):
            self.assertEqual(apply_migrations(self.database)["version"], 3)
        with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:4]):
            first = apply_migrations(self.database)
            second = apply_migrations(self.database)
        self.assertEqual(first["before_version"], 3)
        self.assertEqual(first["applied"], [4])
        self.assertEqual(first["version"], 4)
        self.assertEqual(second["applied"], [])

    def test_rejects_migration_order_gap(self):
        future_migration = Migration(2, "out_of_order", ("CREATE TABLE should_not_exist (id INTEGER)",))
        with patch.object(migrations, "MIGRATIONS", (future_migration,)):
            with self.assertRaisesRegex(MigrationError, "contiguous"):
                apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_rejects_database_newer_than_supported(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("PRAGMA user_version = 9")
        with self.assertRaisesRegex(MigrationError, "newer"):
            apply_migrations(self.database)

    def test_backup_does_not_change_original(self):
        backup = Path(self.temp_dir.name) / "backups" / "before.sqlite3"
        before = self.database.read_bytes()
        create_backup(self.database, backup)
        self.assertEqual(self.database.read_bytes(), before)
        with closing(sqlite3.connect(self.database)) as original_db, closing(sqlite3.connect(backup)) as backup_db:
            self.assertEqual(original_db.execute("SELECT * FROM customers").fetchall(), backup_db.execute("SELECT * FROM customers").fetchall())
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_audit_reports_database_state_and_orphans(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("INSERT INTO orders VALUES (8, 999)")
            db.execute("INSERT INTO order_items VALUES (12, 8, 777, 1, 1)")
        report = audit_database(self.database)
        self.assertEqual(report["user_version"], 0)
        self.assertEqual(report["row_counts"]["customers"], 1)
        relationships = {item["relationship"] for item in report["orphaned_records"]}
        self.assertIn("orders without customer", relationships)
        self.assertIn("order items without product", relationships)
        self.assertTrue(report["foreign_key_violations"])

    def test_failed_migration_rolls_back_schema_and_version(self):
        broken = Migration(1, "broken", (
            "CREATE TABLE must_rollback (id INTEGER)",
            "THIS IS NOT VALID SQL",
        ))
        with patch.object(migrations, "MIGRATIONS", (broken,)):
            with self.assertRaises(sqlite3.OperationalError):
                apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='must_rollback'").fetchone())
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone())

    def _migrate_to_v4(self):
        with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:4]):
            return apply_migrations(self.database)

    def test_migration_5_preserves_legacy_order_rows_ids_values_and_sequence(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("INSERT INTO orders(order_id, customer_id) VALUES (51, 44)")
            db.execute("INSERT INTO products(product_id, sku, name) VALUES (61, 'LEG-61', 'Legacy item')")
            db.execute("INSERT INTO order_items(order_item_id, order_id, product_id, quantity, unit_price) VALUES (71, 51, 61, 2.5, 3.25)")
            db.execute("INSERT INTO deliveries(delivery_id, order_id, created_at, updated_at) VALUES (81, 51, 'a', 'b')")
            db.execute("INSERT INTO settlements(settlement_id, order_id, merchant_name, created_at) VALUES (91, 51, 'Legacy merchant', 'a')")
            db.execute("UPDATE sqlite_sequence SET seq=144 WHERE name='order_items'")
        self._migrate_to_v4()
        before = self.database.read_bytes()
        first = apply_migrations(self.database)
        second = apply_migrations(self.database)
        self.assertEqual(first["applied"], [5, 6, 7])
        self.assertEqual(second["applied"], [])
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(db.execute("SELECT order_item_id, order_id, product_id, quantity, unit_price, offer_id, merchant_id, merchant_order_id FROM order_items").fetchone(), (71, 51, 61, 2.5, 3.25, None, None, None))
            self.assertEqual(db.execute("SELECT seq FROM sqlite_sequence WHERE name='order_items'").fetchone(), (144,))
            self.assertEqual(db.execute("SELECT delivery_id, order_id, fulfillment_id FROM deliveries").fetchone(), (81, 51, None))
            self.assertEqual(db.execute("SELECT settlement_id, order_id, merchant_name, merchant_order_id FROM settlements").fetchone(), (91, 51, 'Legacy merchant', None))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_items").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall(), [(1,), (2,), (3,), (4,), (5,), (6,), (7,)])
        self.assertNotEqual(self.database.read_bytes(), before)

    def test_migration_5_schema_indexes_and_payment_method_check(self):
        self._migrate_to_v4()
        apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            order_columns = {row[1]: row for row in db.execute("PRAGMA table_info(orders)")}
            item_columns = {row[1]: row for row in db.execute("PRAGMA table_info(order_items)")}
            self.assertIn("recipient_name_snapshot", order_columns)
            self.assertIn("recipient_phone_snapshot", order_columns)
            self.assertEqual(order_columns["payment_method"][3], 0)
            self.assertEqual(item_columns["merchant_order_id"][3], 0)
            indexes = {row[1]: row[2] for row in db.execute("PRAGMA index_list(order_items)")}
            self.assertIn("idx_order_items_merchant_order", indexes)
            self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_order_items_merchant_order'").fetchone()[0], "CREATE INDEX idx_order_items_merchant_order ON order_items(merchant_order_id, order_id, merchant_id)")
            for table in ("checkout_idempotency", "merchant_orders", "fulfillments"):
                self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())
            for value in (None, "cod"):
                db.execute("INSERT INTO orders(order_id, customer_id, payment_method) VALUES (?, 44, ?)", (100 if value is None else 101, value))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO orders(order_id, customer_id, payment_method) VALUES (102, 44, 'card')")

    def test_migration_5_composite_merchant_order_fk_and_fulfillment_constraints(self):
        self._migrate_to_v4()
        apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("INSERT INTO merchants(merchant_id, name) VALUES (9, 'Merchant 9')")
            db.execute("INSERT INTO merchants(merchant_id, name) VALUES (10, 'Merchant 10')")
            db.execute("INSERT INTO products(product_id, sku, name) VALUES (61, 'P-61', 'Product')")
            db.execute("INSERT INTO orders(order_id, customer_id) VALUES (51, 44)")
            db.execute("INSERT INTO orders(order_id, customer_id) VALUES (52, 44)")
            db.execute("INSERT INTO merchant_orders(merchant_order_id, order_id, merchant_id, merchant_name_snapshot, products_subtotal, delivery_fee, total, currency, status, payment_status, created_at, updated_at) VALUES (101, 51, 9, 'M9', 10, 2, 12, 'YER', 'pending', 'unpaid', 'a', 'b')")
            db.execute("INSERT INTO merchant_orders(merchant_order_id, order_id, merchant_id, merchant_name_snapshot, products_subtotal, delivery_fee, total, currency, status, payment_status, created_at, updated_at) VALUES (102, 52, 10, 'M10', 10, 2, 12, 'YER', 'pending', 'unpaid', 'a', 'b')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO merchant_orders(order_id, merchant_id, merchant_name_snapshot, products_subtotal, delivery_fee, total, currency, status, payment_status, created_at, updated_at) VALUES (51, 9, 'duplicate', 1, 0, 1, 'YER', 'pending', 'unpaid', 'a', 'b')")
            db.execute("INSERT INTO order_items(order_item_id, order_id, product_id, quantity, unit_price, merchant_id, merchant_order_id) VALUES (71, 51, 61, 1, 10, 9, 101)")
            db.execute("INSERT INTO order_items(order_item_id, order_id, product_id, quantity, unit_price) VALUES (72, 51, 61, 1, 10)")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO order_items(order_item_id, order_id, product_id, quantity, unit_price, merchant_id, merchant_order_id) VALUES (73, 51, 61, 1, 10, 10, 101)")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO order_items(order_item_id, order_id, product_id, quantity, unit_price, merchant_id, merchant_order_id) VALUES (74, 52, 61, 1, 10, 10, 101)")
            db.execute("INSERT INTO fulfillments(merchant_order_id, fulfillment_number, created_at, updated_at) VALUES (101, 1, 'a', 'b')")
            db.execute("INSERT INTO fulfillments(merchant_order_id, fulfillment_number, created_at, updated_at) VALUES (101, 2, 'a', 'b')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO fulfillments(merchant_order_id, fulfillment_number, created_at, updated_at) VALUES (101, 1, 'a', 'b')")
            fulfillment_id = db.execute("SELECT fulfillment_id FROM fulfillments WHERE merchant_order_id=101 AND fulfillment_number=1").fetchone()[0]
            db.execute("INSERT INTO deliveries(delivery_id, order_id, fulfillment_id, created_at, updated_at) VALUES (81, 51, ?, 'a', 'b')", (fulfillment_id,))
            db.execute("INSERT INTO settlements(settlement_id, order_id, merchant_name, merchant_order_id, created_at) VALUES (91, 51, 'M9', 101, 'a')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM fulfillments WHERE fulfillment_id=?", (fulfillment_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM merchant_orders WHERE merchant_order_id=101")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM merchants WHERE merchant_id=9")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM orders WHERE order_id=51")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migration_5_idempotency_uniqueness_and_foreign_keys(self):
        self._migrate_to_v4()
        apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("INSERT INTO merchants(merchant_id, name) VALUES (9, 'Merchant')")
            db.execute("INSERT INTO orders(order_id, customer_id) VALUES (51, 44)")
            db.execute("INSERT INTO orders(order_id, customer_id) VALUES (52, 44)")
            db.execute("INSERT INTO sessions(session_id, token_hash, created_at, last_seen_at, expires_at) VALUES ('s1', 'hash', 'a', 'a', 'z')")
            for cart_id in (20, 21, 22):
                db.execute("INSERT INTO carts(cart_id, session_id, status, created_at, updated_at) VALUES (?, 's1', 'expired', 'a', 'b')", (cart_id,))
            db.execute("INSERT INTO checkout_idempotency VALUES ('s1', 20, 'keyhash', 'fingerprint', 'revision', 51, 'now')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO checkout_idempotency VALUES ('s1', 21, 'keyhash', 'different', 'revision', 52, 'now')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO checkout_idempotency VALUES ('s1', 20, 'otherkey', 'fingerprint', 'revision', 52, 'now')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO checkout_idempotency VALUES ('s1', 22, 'thirdkey', 'fingerprint', 'revision', 51, 'now')")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migration_5_failure_rolls_back_all_ddl_and_version(self):
        self._migrate_to_v4()
        good = migrations.MIGRATIONS[4]
        broken = Migration(5, good.name, good.sql + ("THIS IS NOT VALID SQL",))
        with patch.object(migrations, "MIGRATIONS", migrations.MIGRATIONS[:4] + (broken,)):
            with self.assertRaises(sqlite3.OperationalError):
                apply_migrations(self.database)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 4)
            for table in ("checkout_idempotency", "merchant_orders", "fulfillments"):
                self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM pragma_table_info('orders') WHERE name='payment_method'").fetchone())
        self.assertEqual(apply_migrations(self.database)["applied"], [5, 6, 7])

    def test_migration_6_7_foundations_and_exact_money_backfill(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("INSERT INTO products(product_id,sku,name) VALUES(9,'M-9','Money')")
            db.execute("INSERT INTO offers(offer_id,product_id,merchant_name,price,stock,created_at,updated_at) VALUES(19,9,'legacy',123,NULL,'a','b')")
            db.execute("INSERT INTO offers(offer_id,product_id,merchant_name,price,stock,created_at,updated_at) VALUES(20,9,'legacy',12.5,NULL,'a','b')")
        result=apply_migrations(self.database)
        with closing(sqlite3.connect(self.database,isolation_level=None)) as db:
            self.assertEqual(result["applied"],[1,2,3,4,5,6,7])
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],7)
            self.assertEqual(db.execute("SELECT price,price_minor FROM offers WHERE offer_id=19").fetchone(),(123.0,123))
            self.assertEqual(db.execute("SELECT price,price_minor FROM offers WHERE offer_id=20").fetchone(),(12.5,None))
            self.assertEqual(db.execute("SELECT table_name,row_id,legacy_column,legacy_value FROM money_migration_issues").fetchone(),('offers',20,'price','12.5'))
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory_movements'").fetchone(),('inventory_movements',))
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],'ok')
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
        report=audit_database(self.database)
        self.assertIn("legacy money values require manual integer-YER review",{w["relationship"] for w in report["ambiguous_or_suspicious_links"]})


if __name__ == "__main__":
    unittest.main()
