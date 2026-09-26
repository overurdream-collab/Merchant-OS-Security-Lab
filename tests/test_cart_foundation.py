import gc
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing

from src.merchant_os import catalog, database, merchants, operations, orders
from src.merchant_os.database_audit import audit_database
from src.merchant_os.migrations import apply_migrations


class TestCartFoundation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "cart.sqlite3")
        database.ensure_schema()
        merchants.ensure_merchant_schema()
        catalog.ensure_catalog_schema()
        orders.ensure_order_schema()
        operations.ensure_operations_schema()
        apply_migrations(database.DB_PATH)
        self.now = "2026-09-24T12:00:00+00:00"

    def tearDown(self):
        gc.collect()
        self.tmp.cleanup()

    def connect_fk(self):
        db = database.get_connection()
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def make_customer(self, wa_id):
        return database.upsert_customer(wa_id, "Customer")['customer_id']

    def make_session(self, session_id, customer_id=None, token_hash=None):
        with closing(self.connect_fk()) as db:
            db.execute("""INSERT INTO sessions
                (session_id, token_hash, customer_id, created_at, last_seen_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, token_hash or f"sha256:{session_id}", customer_id,
                 self.now, self.now, "2026-10-24T12:00:00+00:00"))
            db.commit()

    def make_cart(self, session_id, customer_id=None, zone_id=None, status="active"):
        with closing(self.connect_fk()) as db:
            cur = db.execute("""INSERT INTO carts
                (session_id, customer_id, delivery_zone_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, customer_id, zone_id, status, self.now, self.now))
            db.commit()
            return cur.lastrowid

    def make_zone(self, code="Z1"):
        with closing(self.connect_fk()) as db:
            cur = db.execute("INSERT INTO delivery_zones(zone_code, city_name, display_name) VALUES (?, 'City', 'Zone')", (code,))
            db.commit()
            return cur.lastrowid

    def make_merchant(self, name="Merchant", status="active"):
        merchant_id = merchants.create_merchant(name)
        with closing(database.get_connection()) as db:
            db.execute("UPDATE merchants SET status=? WHERE merchant_id=?", (status, merchant_id))
            db.commit()
        return merchant_id

    def make_offer(self, merchant_id, currency="YER", product_active=1, offer_active=1):
        product_id = catalog.create_product("Product")
        with closing(database.get_connection()) as db:
            db.execute("UPDATE products SET active=? WHERE product_id=?", (product_active, product_id))
            db.commit()
        offer_id = catalog.add_offer(product_id, merchant_id, 10, currency=currency)
        with closing(database.get_connection()) as db:
            db.execute("UPDATE offers SET active=? WHERE offer_id=?", (offer_active, offer_id))
            db.commit()
        return offer_id

    def make_policy(self, merchant_id, zone_id, fee=5, currency="YER"):
        with closing(self.connect_fk()) as db:
            cur = db.execute("""INSERT INTO merchant_delivery_policies
                (merchant_id, zone_id, delivery_fee, currency, updated_at)
                VALUES (?, ?, ?, ?, ?)""", (merchant_id, zone_id, fee, currency, self.now))
            db.commit()
            return cur.lastrowid

    def test_sessions_store_only_hash_column_and_allow_optional_customer(self):
        self.make_session("guest-a", token_hash="hash-a")
        customer_id = self.make_customer("wa-customer")
        self.make_session("customer-session", customer_id, token_hash="hash-b")
        with closing(database.get_connection()) as db:
            columns = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
            self.assertIn("token_hash", columns)
            self.assertNotIn("raw_token", columns)
            self.assertEqual(db.execute("SELECT customer_id, expires_at FROM sessions WHERE session_id='guest-a'").fetchone()[0], None)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO sessions VALUES ('duplicate', 'hash-a', NULL, ?, ?, ?, NULL)", (self.now, self.now, self.now))

    def test_customer_upsert_rejects_missing_ids_and_preserves_whatsapp_upsert(self):
        for bad in (None, ""):
            with self.assertRaisesRegex(ValueError, "WhatsApp customer ID"):
                database.upsert_customer(bad)
        first = database.upsert_customer("wa-stable", "First")
        second = database.upsert_customer("wa-stable", "Updated")
        self.assertEqual(first["customer_id"], second["customer_id"])
        self.assertEqual(second["wa_id"], "wa-stable")
        self.assertEqual(second["name"], "Updated")

    def test_active_cart_uniqueness_and_historical_cart_behavior(self):
        customer_id = self.make_customer("wa-active-cart")
        self.make_session("session-a")
        first = self.make_cart("session-a", customer_id=customer_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.make_cart("session-a")
        self.make_cart("session-a", status="checked_out")
        self.make_cart("session-a", status="expired")

        self.make_session("session-b")
        with self.assertRaises(sqlite3.IntegrityError):
            self.make_cart("session-b", customer_id=customer_id)
        self.assertIsInstance(first, int)

        self.make_session("session-c")
        self.make_session("session-d")
        self.make_cart("session-c")
        self.make_cart("session-d")

    def test_schema_ownership_lookup_is_session_scoped(self):
        self.make_session("owner-session")
        self.make_session("other-session")
        owner_cart = self.make_cart("owner-session")
        other_cart = self.make_cart("other-session")
        with closing(database.get_connection()) as db:
            # Cart retrieval is keyed by the server-resolved session, not an input cart/customer ID.
            visible = db.execute("SELECT cart_id FROM carts WHERE session_id=? AND status='active'", ("owner-session",)).fetchall()
        self.assertEqual([r[0] for r in visible], [owner_cart])
        self.assertNotIn(other_cart, [r[0] for r in visible])

    def test_cart_item_quantity_uniqueness_and_derived_merchant_group(self):
        merchant_id = self.make_merchant()
        offer_id = self.make_offer(merchant_id)
        self.make_session("items-a")
        self.make_session("items-b")
        cart_a = self.make_cart("items-a")
        cart_b = self.make_cart("items-b")
        with closing(self.connect_fk()) as db:
            db.execute("INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at) VALUES (?, ?, 2, ?, ?)", (cart_a, offer_id, self.now, self.now))
            db.execute("INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at) VALUES (?, ?, 1, ?, ?)", (cart_b, offer_id, self.now, self.now))
            for bad in (0, -1, 1.5):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (cart_a, offer_id, bad, self.now, self.now))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at) VALUES (?, ?, 1, ?, ?)", (cart_a, offer_id, self.now, self.now))
            db.commit()
            db.execute("DELETE FROM cart_items WHERE cart_id=? AND offer_id=?", (cart_a, offer_id))
            groups = db.execute("SELECT DISTINCT o.merchant_id FROM cart_items i JOIN offers o ON o.offer_id=i.offer_id WHERE i.cart_id=?", (cart_a,)).fetchall()
            self.assertEqual(groups, [])

    def test_currency_and_cart_status_checks(self):
        self.make_session("checks")
        with closing(self.connect_fk()) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO carts(session_id, currency, created_at, updated_at) VALUES ('checks', 'USD', ?, ?)", (self.now, self.now))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO carts(session_id, status, created_at, updated_at) VALUES ('checks', 'unknown', ?, ?)", (self.now, self.now))

    def test_delivery_zone_and_policy_constraints(self):
        merchant_id = self.make_merchant()
        zone_id = self.make_zone()
        self.make_policy(merchant_id, zone_id)
        with closing(self.connect_fk()) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO delivery_zones(zone_code, city_name, display_name) VALUES ('Z1', 'Other', 'Duplicate')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO merchant_delivery_policies(merchant_id, zone_id, delivery_fee, updated_at) VALUES (?, ?, 3, ?)", (merchant_id, zone_id, self.now))
            for fee, currency in ((-1, 'YER'), (1, 'USD')):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT INTO merchant_delivery_policies(merchant_id, zone_id, delivery_fee, currency, updated_at) VALUES (?, ?, ?, ?, ?)", (merchant_id, zone_id + 1, fee, currency, self.now))

    def test_delivery_policy_fk_restricts_merchant_and_zone_deletion(self):
        merchant_id = self.make_merchant()
        zone_id = self.make_zone()
        self.make_policy(merchant_id, zone_id)
        with closing(self.connect_fk()) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM merchants WHERE merchant_id=?", (merchant_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM delivery_zones WHERE zone_id=?", (zone_id,))

    def test_cart_zone_and_offer_restrict_delete(self):
        merchant_id = self.make_merchant()
        zone_id = self.make_zone()
        offer_id = self.make_offer(merchant_id)
        self.make_session("restrict-session")
        cart_id = self.make_cart("restrict-session", zone_id=zone_id)
        with closing(self.connect_fk()) as db:
            db.execute("INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at) VALUES (?, ?, 1, ?, ?)", (cart_id, offer_id, self.now, self.now))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM offers WHERE offer_id=?", (offer_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM delivery_zones WHERE zone_id=?", (zone_id,))

    def test_customer_set_null_and_session_restrict(self):
        customer_id = self.make_customer("wa-set-null")
        self.make_session("set-null-session", customer_id)
        cart_id = self.make_cart("set-null-session", customer_id=customer_id)
        with closing(self.connect_fk()) as db:
            db.execute("DELETE FROM customers WHERE customer_id=?", (customer_id,))
            self.assertEqual(db.execute("SELECT customer_id FROM sessions WHERE session_id='set-null-session'").fetchone()[0], None)
            self.assertEqual(db.execute("SELECT customer_id FROM carts WHERE cart_id=?", (cart_id,)).fetchone()[0], None)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM sessions WHERE session_id='set-null-session'")

    def test_eligible_offer_selection_requires_all_approved_conditions(self):
        active = self.make_merchant("Active", "active")
        lead = self.make_merchant("Lead", "lead")
        suspended = self.make_merchant("Suspended", "suspended")
        eligible = self.make_offer(active)
        bad_status = self.make_offer(lead)
        bad_currency = self.make_offer(active)
        with closing(database.get_connection()) as db:
            db.execute("UPDATE offers SET currency='USD' WHERE offer_id=?", (bad_currency,))
            db.commit()
        inactive_offer = self.make_offer(active, offer_active=0)
        inactive_product = self.make_offer(active, product_active=0)
        unlinked_product = catalog.create_product("Unlinked")
        self.make_session("eligibility-session")
        cart_id = self.make_cart("eligibility-session")
        with closing(database.get_connection()) as db:
            unlinked = db.execute("""INSERT INTO offers
                (product_id, merchant_name, price, currency, active, created_at, updated_at, merchant_id)
                VALUES (?, 'Legacy', 10, 'YER', 1, ?, ?, NULL)""", (unlinked_product, self.now, self.now)).lastrowid
            query = """SELECT o.offer_id FROM offers o
                JOIN products p ON p.product_id=o.product_id
                JOIN merchants m ON m.merchant_id=o.merchant_id
                WHERE o.offer_id=? AND o.active=1 AND p.active=1
                  AND o.merchant_id IS NOT NULL AND m.status='active' AND o.currency='YER'"""
            accepted = {offer_id for offer_id in (eligible, bad_status, bad_currency, inactive_offer, inactive_product, unlinked)
                        if db.execute(query, (offer_id,)).fetchone()}
        self.assertEqual(accepted, {eligible})
        with closing(self.connect_fk()) as db:
            db.execute("INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at) VALUES (?, ?, 1, ?, ?)", (cart_id, eligible, self.now, self.now))
            for offer_id in (bad_status, bad_currency, inactive_offer, inactive_product, unlinked):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "cart_offer_ineligible"):
                    db.execute("INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at) VALUES (?, ?, 1, ?, ?)", (cart_id, offer_id, self.now, self.now))

    def test_migration_audit_reports_clean_cart_relationships(self):
        report = audit_database(database.DB_PATH)
        self.assertEqual(report["user_version"], 7)
        self.assertEqual(report["foreign_key_violations"], [])
        self.assertEqual(report["orphaned_records"], [])
        for table in ("sessions", "delivery_zones", "merchant_delivery_policies", "carts", "cart_items"):
            self.assertEqual(report["row_counts"][table], 0)

    def test_only_approved_named_indexes_are_added(self):
        with closing(database.get_connection()) as db:
            cart_indexes = {r[1] for r in db.execute("PRAGMA index_list(carts)") if not r[1].startswith("sqlite_autoindex")}
            item_indexes = {r[1] for r in db.execute("PRAGMA index_list(cart_items)") if not r[1].startswith("sqlite_autoindex")}
        self.assertEqual(cart_indexes, {"ux_carts_active_session", "ux_carts_active_customer"})
        self.assertEqual(item_indexes, {"idx_cart_items_offer"})


if __name__ == "__main__":
    unittest.main()
