import concurrent.futures
import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

from src.merchant_os import catalog, database, merchants, operations, orders
from src.merchant_os.cart_service import (
    CartNotFound,
    CartService,
    IdentityVerificationRequired,
    InvalidQuantity,
    OfferUnavailable,
    SessionInvalid,
    VerifiedIdentityContext,
)
from src.merchant_os.migrations import apply_migrations


class TestCartService(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "cart-service.sqlite3")
        self.original_db = database.DB_PATH
        database.DB_PATH = self.path
        database.ensure_schema()
        merchants.ensure_merchant_schema()
        catalog.ensure_catalog_schema()
        orders.ensure_order_schema()
        operations.ensure_operations_schema()
        apply_migrations(self.path)
        self.now = datetime(2026, 9, 24, tzinfo=timezone.utc)
        self.service = CartService(self.path, clock=lambda: self.now)

    def tearDown(self):
        database.DB_PATH = self.original_db
        self.temp.cleanup()

    def new_session(self, *, https=False):
        result = self.service.get_or_create_session(is_https=https)
        parsed = SimpleCookie()
        parsed.load(result.set_cookie)
        token = parsed["merchant_os_session"].value
        return result, token, f"merchant_os_session={token}"

    def merchant(self, name, status="active"):
        merchant_id = merchants.create_merchant(name)
        with database.get_connection() as db:
            db.execute("UPDATE merchants SET status=? WHERE merchant_id=?", (status, merchant_id))
            db.commit()
        return merchant_id

    def offer(self, merchant_id, *, currency="YER", product_active=1, offer_active=1, price=10):
        product_id = catalog.create_product(f"Product {merchant_id}", sku=f"SKU-{uuid.uuid4()}")
        with database.get_connection() as db:
            db.execute("UPDATE products SET active=? WHERE product_id=?", (product_active, product_id))
            db.commit()
        offer_id = catalog.add_offer(product_id, merchant_id, price, currency=currency)
        with database.get_connection() as db:
            db.execute("UPDATE offers SET active=? WHERE offer_id=?", (offer_active, offer_id))
            db.commit()
        return offer_id, product_id

    def cart_row(self, cart_id):
        with database.get_connection() as db:
            return dict(db.execute("SELECT * FROM carts WHERE cart_id=?", (cart_id,)).fetchone())

    def test_session_token_is_random_hashed_and_cookie_is_protected(self):
        access, token, cookie_header = self.new_session(https=True)
        with database.get_connection() as db:
            row = db.execute("SELECT token_hash FROM sessions WHERE session_id=?", (access.session_id,)).fetchone()
        self.assertNotEqual(row["token_hash"], token)
        self.assertEqual(len(row["token_hash"]), 64)
        self.assertIn("HttpOnly", access.set_cookie)
        self.assertIn("SameSite=Lax", access.set_cookie)
        self.assertIn("Secure", access.set_cookie)
        self.assertNotIn(token, str(dict(row)))
        self.assertEqual(self.service.get_or_create_session(cookie_header).session_id, access.session_id)

    def test_http_cookie_is_not_secure_and_session_expiry_is_rolling(self):
        access, _, cookie = self.new_session(https=False)
        cart_id = self.service.get_cart(cookie)["cart_id"]
        self.assertNotIn("Secure", access.set_cookie)
        initial_expiry = datetime.fromisoformat(access.expires_at)
        self.now += timedelta(days=29)
        refreshed = self.service.get_or_create_session(cookie)
        self.assertEqual(refreshed.session_id, access.session_id)
        self.assertGreater(datetime.fromisoformat(refreshed.expires_at), initial_expiry)
        self.now += timedelta(days=31)
        replacement = self.service.get_or_create_session(cookie)
        self.assertNotEqual(replacement.session_id, access.session_id)
        with database.get_connection() as db:
            old = db.execute("SELECT revoked_at FROM sessions WHERE session_id=?", (access.session_id,)).fetchone()
            cart_status = db.execute("SELECT status FROM carts WHERE cart_id=?", (cart_id,)).fetchone()[0]
        self.assertIsNotNone(old["revoked_at"])
        self.assertEqual(cart_status, "expired")

    def test_session_token_rotation_invalidates_old_cookie(self):
        access, old_token, old_cookie = self.new_session()
        identity = VerifiedIdentityContext(123, "verification-1", "trusted-adapter", self.now.isoformat())
        with self.assertRaises(IdentityVerificationRequired):
            self.service.rotate_session_token(old_cookie, identity)
        rejecting = CartService(
            self.path, clock=lambda: self.now,
            identity_verifier=type("Verifier", (), {"verify": lambda _self, _context: False})(),
        )
        with self.assertRaises(IdentityVerificationRequired):
            rejecting.rotate_session_token(old_cookie, identity)
        verified = CartService(
            self.path, clock=lambda: self.now,
            identity_verifier=type("Verifier", (), {"verify": lambda _self, context: context.customer_id == 123})(),
        )
        rotated = verified.rotate_session_token(old_cookie, identity)
        parsed = SimpleCookie()
        parsed.load(rotated.set_cookie)
        new_token = parsed["merchant_os_session"].value
        self.assertNotEqual(new_token, old_token)
        self.assertEqual(rotated.session_id, access.session_id)
        with self.assertRaises(SessionInvalid):
            self.service.get_cart(old_cookie)
        self.assertEqual(self.service.get_cart(f"merchant_os_session={new_token}")["cart_id"] > 0, True)

    def test_sessions_are_isolated_and_cart_idor_fails_closed(self):
        _, _, cookie_a = self.new_session()
        _, _, cookie_b = self.new_session()
        cart_a = self.service.get_cart(cookie_a)["cart_id"]
        cart_b = self.service.get_cart(cookie_b)["cart_id"]
        self.assertNotEqual(cart_a, cart_b)
        with self.assertRaises(CartNotFound):
            self.service.get_cart(cookie_a, cart_id=cart_b)
        with self.assertRaises(CartNotFound):
            self.service.clear_cart(cookie_a, cart_id=cart_b)
        with self.assertRaises(TypeError):
            self.service.get_cart(cookie_a, customer_id=123)

    def test_linked_customer_active_cart_is_not_revealed_to_second_session(self):
        customer_id = database.upsert_customer("verified-customer")['customer_id']
        _, _, cookie_a = self.new_session()
        _, _, cookie_b = self.new_session()
        with database.get_connection() as db:
            db.execute("UPDATE sessions SET customer_id=? WHERE token_hash IS NOT NULL", (customer_id,))
            # Assign only the first session; the second remains anonymous until
            # after its active cart is established for the ownership check.
            rows = db.execute("SELECT session_id FROM sessions ORDER BY rowid").fetchall()
            db.execute("UPDATE sessions SET customer_id=NULL WHERE session_id=?", (rows[1]["session_id"],))
            db.commit()
        cart_a = self.service.get_cart(cookie_a)
        with database.get_connection() as db:
            db.execute("UPDATE sessions SET customer_id=? WHERE session_id=(SELECT session_id FROM sessions WHERE token_hash IS NOT NULL ORDER BY rowid DESC LIMIT 1)", (customer_id,))
            db.commit()
        with self.assertRaises(CartNotFound):
            self.service.get_cart(cookie_b)
        with database.get_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM carts WHERE customer_id=? AND status='active'", (customer_id,)).fetchone()[0], 1)

    def test_cart_expires_after_30_days_inactive_without_deleting_history(self):
        _, _, cookie = self.new_session()
        first = self.service.get_cart(cookie)
        merchant_id = self.merchant("Expiry merchant")
        offer_id, _ = self.offer(merchant_id)
        self.service.add_item(cookie, offer_id)
        self.now += timedelta(days=29)
        self.service.get_or_create_session(cookie)
        self.now += timedelta(days=1, seconds=1)
        second = self.service.get_cart(cookie)
        self.assertNotEqual(first["cart_id"], second["cart_id"])
        self.assertEqual(self.cart_row(first["cart_id"])["status"], "expired")
        with database.get_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM carts").fetchone()[0], 2)

    def test_add_duplicate_update_remove_and_clear(self):
        _, _, cookie = self.new_session()
        merchant_id = self.merchant("Mutation merchant")
        offer_id, _ = self.offer(merchant_id)
        added = self.service.add_item(cookie, offer_id, 2)
        duplicate = self.service.add_item(cookie, offer_id, 3)
        self.assertEqual(duplicate["merchant_groups"][0]["items"][0]["quantity"], 5)
        self.assertEqual(duplicate["products_total"], 50)
        updated = self.service.update_quantity(cookie, offer_id, 4)
        self.assertEqual(updated["merchant_groups"][0]["items"][0]["quantity"], 4)
        removed = self.service.remove_item(cookie, offer_id)
        self.assertEqual(removed["merchant_groups"], [])
        cleared = self.service.add_item(cookie, offer_id)
        empty = self.service.clear_cart(cookie)
        self.assertEqual(empty["products_total"], 0)
        self.assertEqual(empty["unavailable_items"], [])

    def test_quantity_requires_positive_integer_and_rejects_injection_style_input(self):
        _, _, cookie = self.new_session()
        merchant_id = self.merchant("Quantity merchant")
        offer_id, _ = self.offer(merchant_id)
        for bad in (0, -1, 1.5, True, "2"):
            with self.subTest(quantity=bad), self.assertRaises(InvalidQuantity):
                self.service.add_item(cookie, offer_id, bad)
        with self.assertRaises(OfferUnavailable):
            self.service.add_item(cookie, "1 OR 1=1", 1)
        self.assertEqual(self.service.get_cart(cookie)["merchant_groups"], [])

    def test_eligibility_requires_active_offer_product_merchant_link_and_yer(self):
        active = self.merchant("Active seller", "active")
        lead = self.merchant("Lead seller", "lead")
        suspended = self.merchant("Suspended seller", "suspended")
        valid, _ = self.offer(active)
        invalid = [
            self.offer(lead)[0], self.offer(suspended)[0],
            self.offer(active, product_active=0)[0],
            self.offer(active, offer_active=0)[0],
        ]
        usd_offer = self.offer(active)[0]
        negative_offer = self.offer(active)[0]
        with database.get_connection() as db:
            db.execute("UPDATE offers SET currency='USD' WHERE offer_id=?", (usd_offer,))
            db.execute("UPDATE offers SET price=-1 WHERE offer_id=?", (negative_offer,))
            db.commit()
        invalid.extend([usd_offer, negative_offer])
        _, _, cookie = self.new_session()
        self.service.add_item(cookie, valid)
        for offer_id in invalid:
            with self.subTest(offer_id=offer_id), self.assertRaises(OfferUnavailable):
                self.service.add_item(cookie, offer_id)
        with database.get_connection() as db:
            product_id = catalog.create_product("Legacy unlinked")
            now = self.now.isoformat()
            unlinked = db.execute(
                """INSERT INTO offers(product_id, merchant_name, price, currency, created_at, updated_at)
                   VALUES (?, 'Legacy', 3, 'YER', ?, ?)""", (product_id, now, now)
            ).lastrowid
        with self.assertRaises(OfferUnavailable):
            self.service.add_item(cookie, unlinked)
        groups = self.service.get_cart(cookie)["merchant_groups"]
        self.assertEqual([g["merchant_id"] for g in groups], [active])

    def test_grouping_uses_server_merchant_identity_and_current_prices(self):
        merchant_a = self.merchant("Merchant A")
        merchant_b = self.merchant("Merchant B")
        offer_a1, _ = self.offer(merchant_a, price=7)
        offer_a2, _ = self.offer(merchant_a, price=9)
        offer_b, _ = self.offer(merchant_b, price=11)
        _, _, cookie = self.new_session()
        self.service.add_item(cookie, offer_a1, 2)
        self.service.add_item(cookie, offer_a2, 1)
        self.service.add_item(cookie, offer_b, 3)
        cart = self.service.get_cart(cookie)
        self.assertEqual({group["merchant_id"] for group in cart["merchant_groups"]}, {merchant_a, merchant_b})
        totals = {group["merchant_id"]: group["products_subtotal"] for group in cart["merchant_groups"]}
        self.assertEqual(totals, {merchant_a: 23.0, merchant_b: 33.0})
        self.assertEqual(cart["products_total"], 56.0)
        with database.get_connection() as db:
            db.execute("UPDATE offers SET price=13 WHERE offer_id=?", (offer_a1,))
            db.commit()
        repriced = self.service.get_cart(cookie)
        self.assertEqual(repriced["products_total"], 68.0)

    def test_stale_offer_is_reported_unavailable_on_cart_read(self):
        merchant_id = self.merchant("Stale merchant")
        offer_id, _ = self.offer(merchant_id)
        _, _, cookie = self.new_session()
        self.service.add_item(cookie, offer_id)
        with database.get_connection() as db:
            db.execute("UPDATE merchants SET status='inactive' WHERE merchant_id=?", (merchant_id,))
            db.commit()
        cart = self.service.get_cart(cookie)
        self.assertEqual(cart["merchant_groups"], [])
        self.assertEqual(cart["unavailable_items"][0]["offer_id"], offer_id)
        self.assertEqual(cart["unavailable_items"][0]["reason"], "offer_unavailable")

    def test_concurrent_adds_are_serialized_without_lost_updates(self):
        merchant_id = self.merchant("Concurrent seller")
        offer_id, _ = self.offer(merchant_id)
        _, _, cookie = self.new_session()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.service.add_item(cookie, offer_id), range(8)))
        cart = self.service.get_cart(cookie)
        self.assertEqual(cart["merchant_groups"][0]["items"][0]["quantity"], 8)
        with database.get_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM carts WHERE status='active'").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_foreign_keys_are_enabled_per_cart_connection_only(self):
        _, _, cookie = self.new_session()
        self.service.get_cart(cookie)
        with database.get_connection() as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 0)
        with self.service._connection() as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
