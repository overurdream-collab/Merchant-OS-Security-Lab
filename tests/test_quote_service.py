import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone

from src.merchant_os import catalog, database, merchants, operations, orders
from src.merchant_os.cart_service import (
    CartNotFound,
    CartService,
    DeliveryZoneUnavailable,
    InvalidQuantity,
    SessionInvalid,
)
from src.merchant_os.migrations import apply_migrations
from src.merchant_os.quote_service import (
    DeliveryPolicyUnavailable,
    DeliveryZoneRequired,
    QuoteCurrencyInvalid,
    QuoteDeliveryZoneUnavailable,
    QuoteOfferUnavailable,
    QuoteService,
)


class TestQuoteService(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "quote.sqlite3")
        self.original_db = database.DB_PATH
        database.DB_PATH = self.path
        database.ensure_schema()
        merchants.ensure_merchant_schema()
        catalog.ensure_catalog_schema()
        orders.ensure_order_schema()
        operations.ensure_operations_schema()
        apply_migrations(self.path)
        self.now = datetime(2026, 9, 24, tzinfo=timezone.utc)
        self.carts = CartService(self.path, clock=lambda: self.now)
        self.quotes = QuoteService(self.path, clock=lambda: self.now)
        self.zone_id = self.add_zone()

    def tearDown(self):
        database.DB_PATH = self.original_db
        self.temp.cleanup()

    def add_zone(self, *, active=1):
        with database.get_connection() as db:
            zone_id = db.execute(
                "INSERT INTO delivery_zones(zone_code, city_name, display_name, active) "
                "VALUES (?, 'Sanaa', 'Sanaa', ?)", (f"Z-{uuid.uuid4()}", active)
            ).lastrowid
            db.commit()
        return zone_id

    def add_merchant(self, *, name=None, status="active"):
        merchant_id = merchants.create_merchant(name or f"Merchant {uuid.uuid4()}")
        with database.get_connection() as db:
            db.execute("UPDATE merchants SET status=? WHERE merchant_id=?", (status, merchant_id))
            db.commit()
        return merchant_id

    def add_offer(self, merchant_id, *, price=10, currency="YER", offer_active=1, product_active=1):
        product_id = catalog.create_product(f"Product {uuid.uuid4()}", sku=f"SKU-{uuid.uuid4()}")
        with database.get_connection() as db:
            db.execute("UPDATE products SET active=? WHERE product_id=?", (product_active, product_id))
            db.commit()
        offer_id = catalog.add_offer(product_id, merchant_id, price, currency=currency)
        with database.get_connection() as db:
            db.execute("UPDATE offers SET active=? WHERE offer_id=?", (offer_active, offer_id))
            db.commit()
        return offer_id, product_id

    def add_policy(self, merchant_id, *, fee=5, zone_id=None, active=1, currency="YER"):
        with database.get_connection() as db:
            policy_id = db.execute(
                """INSERT INTO merchant_delivery_policies
                   (merchant_id, zone_id, delivery_fee, currency, active, updated_at, delivery_fee_minor)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (merchant_id, zone_id or self.zone_id, fee, currency, active, self.now.isoformat(), fee),
            ).lastrowid
            db.commit()
        return policy_id

    def session(self):
        access = self.carts.get_or_create_session()
        cookie = access.set_cookie.split(";", 1)[0]
        return access, cookie

    def set_zone(self, cookie, *, cart_id=None, zone_id=None):
        cart = self.carts.get_cart(cookie, cart_id=cart_id)
        return self.carts.set_delivery_zone(cookie, zone_id or self.zone_id, cart_id=cart["cart_id"])

    def test_single_merchant_quote_and_server_totals(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id, price=12)
        self.add_policy(merchant_id, fee=3)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id, 2)
        self.set_zone(cookie)

        quote = self.quotes.quote(cookie)

        self.assertEqual(quote["currency"], "YER")
        self.assertEqual(quote["merchant_groups"][0]["merchant_id"], merchant_id)
        self.assertEqual(quote["merchant_groups"][0]["products_subtotal"], "24")
        self.assertEqual(quote["merchant_groups"][0]["delivery_fee"], "3")
        self.assertEqual(quote["merchant_groups"][0]["merchant_total"], "27")
        self.assertEqual(quote["product_total"], "24")
        self.assertEqual(quote["delivery_total"], "3")
        self.assertEqual(quote["grand_total"], "27")

    def test_multi_merchant_fees_are_charged_once_and_grand_total_is_sum(self):
        merchant_a = self.add_merchant()
        merchant_b = self.add_merchant()
        offer_a, _ = self.add_offer(merchant_a, price=10)
        offer_b, _ = self.add_offer(merchant_b, price=7)
        self.add_policy(merchant_a, fee=2)
        self.add_policy(merchant_b, fee=4)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_a, 2)
        self.carts.add_item(cookie, offer_b, 3)
        self.set_zone(cookie)

        quote = self.quotes.quote(cookie)

        groups = {group["merchant_id"]: group for group in quote["merchant_groups"]}
        self.assertEqual(groups[merchant_a]["products_subtotal"], "20")
        self.assertEqual(groups[merchant_a]["delivery_fee"], "2")
        self.assertEqual(groups[merchant_b]["products_subtotal"], "21")
        self.assertEqual(groups[merchant_b]["delivery_fee"], "4")
        self.assertEqual(quote["product_total"], "41")
        self.assertEqual(quote["delivery_total"], "6")
        self.assertEqual(quote["grand_total"], "47")

    def test_missing_or_inactive_policy_fails_closed(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id)
        self.set_zone(cookie)
        with self.assertRaises(DeliveryPolicyUnavailable):
            self.quotes.quote(cookie)
        self.add_policy(merchant_id, active=0)
        with self.assertRaises(DeliveryPolicyUnavailable):
            self.quotes.quote(cookie)

    def test_missing_and_inactive_zones_are_rejected(self):
        _, cookie = self.session()
        cart = self.carts.get_cart(cookie)
        with self.assertRaises(DeliveryZoneRequired):
            self.quotes.quote(cookie)
        inactive_zone = self.add_zone(active=0)
        with self.assertRaises(DeliveryZoneUnavailable):
            self.carts.set_delivery_zone(cookie, inactive_zone, cart_id=cart["cart_id"])
        self.carts.set_delivery_zone(cookie, self.zone_id, cart_id=cart["cart_id"])
        with database.get_connection() as db:
            db.execute("UPDATE delivery_zones SET active=0 WHERE zone_id=?", (self.zone_id,))
            db.commit()
        with self.assertRaises(QuoteDeliveryZoneUnavailable):
            self.quotes.quote(cookie)

    def test_ineligible_stale_items_are_rejected_at_quote(self):
        cases = [
            {"offer_active": 0},
            {"product_active": 0},
            {"status": "inactive"},
            {"currency": "USD"},
        ]
        for case in cases:
            with self.subTest(case=case):
                merchant_id = self.add_merchant()
                offer_id, product_id = self.add_offer(merchant_id)
                self.add_policy(merchant_id)
                _, cookie = self.session()
                self.carts.add_item(cookie, offer_id)
                self.set_zone(cookie)
                # Eligibility may change after insertion; Quote re-reads source data.
                with database.get_connection() as db:
                    if "status" in case:
                        db.execute("UPDATE merchants SET status=? WHERE merchant_id=?", (case["status"], merchant_id))
                    if "offer_active" in case:
                        db.execute("UPDATE offers SET active=? WHERE offer_id=?", (case["offer_active"], offer_id))
                    if "product_active" in case:
                        db.execute("UPDATE products SET active=? WHERE product_id=?", (case["product_active"], product_id))
                    if "currency" in case:
                        db.execute("UPDATE offers SET currency=? WHERE offer_id=?", (case["currency"], offer_id))
                    db.commit()
                with self.assertRaises((QuoteOfferUnavailable, QuoteCurrencyInvalid)):
                    self.quotes.quote(cookie)

    def test_offer_without_merchant_is_rejected_even_if_legacy_cart_line_exists(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id)
        _, cookie = self.session()
        cart = self.carts.get_cart(cookie)
        self.carts.set_delivery_zone(cookie, self.zone_id, cart_id=cart["cart_id"])
        with database.get_connection() as db:
            db.execute("DROP TRIGGER cart_items_require_eligible_offer_insert")
            db.execute(
                "INSERT INTO cart_items(cart_id, offer_id, quantity, created_at, updated_at) "
                "VALUES (?, ?, 1, ?, ?)", (cart["cart_id"], offer_id, self.now.isoformat(), self.now.isoformat())
            )
            db.execute("UPDATE offers SET merchant_id=NULL WHERE offer_id=?", (offer_id,))
            db.commit()
        with self.assertRaises(QuoteOfferUnavailable):
            self.quotes.quote(cookie)

    def test_current_offer_price_is_used_after_price_change(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id, price=10)
        self.add_policy(merchant_id, fee=1)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id, 2)
        self.set_zone(cookie)
        with database.get_connection() as db:
            db.execute("UPDATE offers SET price=15,price_minor=15 WHERE offer_id=?", (offer_id,))
            db.commit()
        quote = self.quotes.quote(cookie)
        self.assertEqual(quote["merchant_groups"][0]["items"][0]["unit_price"], "15")
        self.assertEqual(quote["product_total"], "30")
        self.assertEqual(quote["grand_total"], "31")

    def test_invalid_quantity_is_revalidated(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id)
        self.add_policy(merchant_id)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id)
        self.set_zone(cookie)
        with database.get_connection() as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute("UPDATE cart_items SET quantity=1.5 WHERE offer_id=?", (offer_id,))
            db.commit()
        with self.assertRaises(InvalidQuantity):
            self.quotes.quote(cookie)

    def test_delivery_policy_currency_is_revalidated(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id)
        self.add_policy(merchant_id)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id)
        self.set_zone(cookie)
        with database.get_connection() as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute("UPDATE merchant_delivery_policies SET currency='USD' WHERE merchant_id=?", (merchant_id,))
            db.commit()
        with self.assertRaises(QuoteCurrencyInvalid):
            self.quotes.quote(cookie)

    def test_cross_session_cart_idor_is_rejected(self):
        _, cookie_a = self.session()
        _, cookie_b = self.session()
        cart_a = self.carts.get_cart(cookie_a)
        self.carts.get_cart(cookie_b)
        with self.assertRaises(CartNotFound):
            self.quotes.quote(cookie_b, cart_id=cart_a["cart_id"])

    def test_zone_assignment_rejects_another_sessions_cart(self):
        _, cookie_a = self.session()
        _, cookie_b = self.session()
        cart_a = self.carts.get_cart(cookie_a)
        cart_b = self.carts.get_cart(cookie_b)
        with self.assertRaises(CartNotFound):
            self.carts.set_delivery_zone(cookie_a, self.zone_id, cart_id=cart_b["cart_id"])
        with database.get_connection() as db:
            self.assertIsNone(db.execute(
                "SELECT delivery_zone_id FROM carts WHERE cart_id=?", (cart_b["cart_id"],)
            ).fetchone()[0])

    def test_expired_session_cannot_receive_quote(self):
        _, cookie = self.session()
        cart = self.carts.get_cart(cookie)
        self.carts.set_delivery_zone(cookie, self.zone_id, cart_id=cart["cart_id"])
        self.now += timedelta(days=31)
        with self.assertRaises(SessionInvalid):
            self.quotes.quote(cookie)

    def test_empty_cart_returns_zero_totals_for_selected_zone(self):
        _, cookie = self.session()
        cart = self.carts.get_cart(cookie)
        self.carts.set_delivery_zone(cookie, self.zone_id, cart_id=cart["cart_id"])
        quote = self.quotes.quote(cookie)
        self.assertEqual(quote["merchant_groups"], [])
        self.assertEqual(quote["product_total"], "0")
        self.assertEqual(quote["delivery_total"], "0")
        self.assertEqual(quote["grand_total"], "0")

    def test_duplicate_offer_quantity_is_quoted_as_combined_quantity(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id, price=4)
        self.add_policy(merchant_id, fee=2)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id, 2)
        self.carts.add_item(cookie, offer_id, 3)
        self.set_zone(cookie)
        quote = self.quotes.quote(cookie)
        item = quote["merchant_groups"][0]["items"][0]
        self.assertEqual(item["quantity"], 5)
        self.assertEqual(item["line_total"], "20")
        self.assertEqual(quote["grand_total"], "22")

    def test_quote_is_read_only_and_creates_no_commerce_records(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id)
        self.add_policy(merchant_id)
        _, cookie = self.session()
        cart = self.carts.add_item(cookie, offer_id)
        self.carts.set_delivery_zone(cookie, self.zone_id, cart_id=cart["cart_id"])
        with database.get_connection() as db:
            before = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("sessions", "carts", "cart_items", "orders", "order_items",
                              "deliveries", "settlements")
            }
            timestamps = tuple(db.execute(
                "SELECT s.last_seen_at, c.updated_at FROM sessions s JOIN carts c "
                "ON c.session_id=s.session_id WHERE c.cart_id=?", (cart["cart_id"],)
            ).fetchone())
        self.quotes.quote(cookie)
        with database.get_connection() as db:
            after = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before
            }
            timestamps_after = tuple(db.execute(
                "SELECT s.last_seen_at, c.updated_at FROM sessions s JOIN carts c "
                "ON c.session_id=s.session_id WHERE c.cart_id=?", (cart["cart_id"],)
            ).fetchone())
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(before, after)
        self.assertEqual(timestamps, timestamps_after)

    def test_quote_rejects_unrecognized_or_injected_ids_safely(self):
        _, cookie = self.session()
        with self.assertRaises(CartNotFound):
            self.quotes.quote(cookie, cart_id="1 OR 1=1")
        with self.assertRaises(CartNotFound):
            self.quotes.quote(cookie, cart_id=999999)

    def test_active_cart_must_belong_to_cookie_session(self):
        _, cookie_a = self.session()
        _, cookie_b = self.session()
        cart_a = self.carts.get_cart(cookie_a)
        self.carts.set_delivery_zone(cookie_a, self.zone_id, cart_id=cart_a["cart_id"])
        with self.assertRaises(CartNotFound):
            self.quotes.quote(cookie_b, cart_id=cart_a["cart_id"])

    def test_quote_service_does_not_change_global_foreign_key_default(self):
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 0)

    def test_quote_revision_is_deterministic_for_unchanged_server_state(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id, price=10)
        self.add_policy(merchant_id, fee=2)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id, 2)
        self.set_zone(cookie)
        first = self.quotes.quote(cookie)["quote_revision"]
        second = self.quotes.quote(cookie)["quote_revision"]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_quote_revision_changes_with_quantity_price_and_policy(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id, price=10)
        self.add_policy(merchant_id, fee=2)
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id, 1)
        self.set_zone(cookie)
        revisions = [self.quotes.quote(cookie)["quote_revision"]]
        self.carts.update_quantity(cookie, offer_id, 2)
        revisions.append(self.quotes.quote(cookie)["quote_revision"])
        with database.get_connection() as db:
            db.execute("UPDATE offers SET price=11,price_minor=11 WHERE offer_id=?", (offer_id,))
            db.commit()
        revisions.append(self.quotes.quote(cookie)["quote_revision"])
        with database.get_connection() as db:
            db.execute("UPDATE merchant_delivery_policies SET delivery_fee=3,delivery_fee_minor=3 WHERE merchant_id=?",
                       (merchant_id,))
            db.commit()
        revisions.append(self.quotes.quote(cookie)["quote_revision"])
        self.assertEqual(len(set(revisions)), len(revisions))

    def test_quote_revision_changes_with_zone_or_relevant_eligibility(self):
        merchant_id = self.add_merchant()
        offer_id, product_id = self.add_offer(merchant_id)
        self.add_policy(merchant_id, fee=2)
        _, cookie = self.session()
        cart = self.carts.add_item(cookie, offer_id)
        self.carts.set_delivery_zone(cookie, self.zone_id, cart_id=cart["cart_id"])
        first = self.quotes.quote(cookie)["quote_revision"]
        other_zone = self.add_zone()
        self.add_policy(merchant_id, fee=2, zone_id=other_zone)
        self.carts.set_delivery_zone(cookie, other_zone, cart_id=cart["cart_id"])
        second = self.quotes.quote(cookie)["quote_revision"]
        self.assertNotEqual(first, second)
        with database.get_connection() as db:
            db.execute("UPDATE products SET name='Changed Product' WHERE product_id=?", (product_id,))
            db.commit()
        third = self.quotes.quote(cookie)["quote_revision"]
        self.assertNotEqual(second, third)

    def test_quote_revision_changes_when_managed_inventory_eligibility_changes(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id)
        self.add_policy(merchant_id)
        with database.get_connection() as db:
            db.execute("UPDATE offers SET inventory_managed=1,stock=5 WHERE offer_id=?", (offer_id,))
            db.commit()
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id, 1)
        self.set_zone(cookie)
        before = self.quotes.quote(cookie)["quote_revision"]
        with database.get_connection() as db:
            db.execute("UPDATE offers SET stock=4 WHERE offer_id=?", (offer_id,))
            db.commit()
        after = self.quotes.quote(cookie)["quote_revision"]
        self.assertNotEqual(before, after)

    def test_unmanaged_stock_does_not_change_quote_revision(self):
        merchant_id = self.add_merchant()
        offer_id, _ = self.add_offer(merchant_id)
        self.add_policy(merchant_id)
        with database.get_connection() as db:
            db.execute("UPDATE offers SET inventory_managed=0,stock=5 WHERE offer_id=?", (offer_id,))
            db.commit()
        _, cookie = self.session()
        self.carts.add_item(cookie, offer_id, 1)
        self.set_zone(cookie)
        before = self.quotes.quote(cookie)["quote_revision"]
        with database.get_connection() as db:
            db.execute("UPDATE offers SET stock=4 WHERE offer_id=?", (offer_id,))
            db.commit()
        after = self.quotes.quote(cookie)["quote_revision"]
        self.assertEqual(before, after)
        _, cookie = self.session()
        cart = self.carts.get_cart(cookie)
        self.carts.set_delivery_zone(cookie, self.zone_id, cart_id=cart["cart_id"])
        self.quotes.quote(cookie)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
