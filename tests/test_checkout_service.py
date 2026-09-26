import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.merchant_os import catalog, database, merchants, operations, orders
from src.merchant_os.cart_service import CartService
from src.merchant_os.checkout_service import CheckoutError, CheckoutService
from src.merchant_os.migrations import apply_migrations
from src.merchant_os.quote_service import QuoteService


SECRET = "checkout-test-secret-that-is-long-enough-32+"


class TestCheckoutService(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "checkout.sqlite3")
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
        self.checkout_service = CheckoutService(self.path, clock=lambda: self.now)
        with database.get_connection() as db:
            self.zone_id = db.execute(
                "INSERT INTO delivery_zones(zone_code,city_name,display_name,active) "
                "VALUES (?,?,?,1)", (f"Z-{uuid.uuid4()}", "Sanaa", "Sanaa")
            ).lastrowid
            db.commit()

    def tearDown(self):
        database.DB_PATH = self.original_db
        self.temp.cleanup()

    def merchant(self, name=None, status="active"):
        merchant_id = merchants.create_merchant(name or f"Merchant-{uuid.uuid4()}")
        with database.get_connection() as db:
            db.execute("UPDATE merchants SET status=? WHERE merchant_id=?", (status, merchant_id))
            db.commit()
        return merchant_id

    def offer(self, merchant_id, *, price=10, currency="YER", active=1, product_active=1,
              managed=0, stock=None, name=None):
        product_id = catalog.create_product(name or f"Product-{uuid.uuid4()}", sku=f"SKU-{uuid.uuid4()}")
        offer_id = catalog.add_offer(product_id, merchant_id, price, currency=currency)
        with database.get_connection() as db:
            db.execute("UPDATE products SET active=? WHERE product_id=?", (product_active, product_id))
            db.execute("UPDATE offers SET active=?, inventory_managed=?, stock=? WHERE offer_id=?",
                       (active, managed, stock, offer_id))
            db.execute("INSERT INTO merchant_delivery_policies "
                       "(merchant_id,zone_id,delivery_fee,currency,active,updated_at,delivery_fee_minor) "
                       "VALUES (?,?,3,'YER',1,?,3)", (merchant_id, self.zone_id, self.now.isoformat()))
            db.commit()
        return offer_id, product_id

    def session_cart(self, offer_quantities):
        access = self.carts.get_or_create_session()
        cookie = access.set_cookie.split(";", 1)[0]
        cart = self.carts.get_cart(cookie)
        self.carts.set_delivery_zone(cookie, self.zone_id, cart_id=cart["cart_id"])
        for offer_id, quantity in offer_quantities:
            self.carts.add_item(cookie, offer_id, quantity)
        return cookie, cart["cart_id"]

    def quote(self, cookie):
        return self.quotes.quote(cookie)

    def submit(self, cookie, revision, *, key="key-1", name="Buyer Name", phone="967 700-123-456",
               address="Sanaa, Street 1", payment="cod", **kwargs):
        return self.checkout_service.checkout(
            cookie, idempotency_key=key, quote_revision_value=revision,
            recipient_name=name, recipient_phone=phone, delivery_address=address,
            payment_method=payment, **kwargs,
        )

    def counts(self):
        with database.get_connection() as db:
            return {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    for name in ("customers", "orders", "order_items", "merchant_orders",
                                 "fulfillments", "deliveries", "settlements", "checkout_idempotency")}

    def test_single_merchant_guest_cod_snapshots_and_replay(self):
        merchant_id = self.merchant("Seller A")
        offer_id, product_id = self.offer(merchant_id, price=12, name="Tea")
        with database.get_connection() as db:
            original_sku = db.execute("SELECT sku FROM products WHERE product_id=?", (product_id,)).fetchone()[0]
        cookie, cart_id = self.session_cart([(offer_id, 2)])
        revision = self.quote(cookie)["quote_revision"]
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            result = self.submit(cookie, revision)
            # A successful replay is resolved before mutable catalog state is read.
            with database.get_connection() as db:
                db.execute("UPDATE products SET active=0 WHERE product_id=?", (product_id,))
                db.commit()
            replay = self.submit(cookie, revision)
        with database.get_connection() as db:
            db.execute("UPDATE products SET name='Renamed Tea',sku='RENAMED' WHERE product_id=?", (product_id,))
            db.execute("UPDATE merchants SET name='Renamed Seller' WHERE merchant_id=?", (merchant_id,))
            db.execute("UPDATE offers SET price=99 WHERE offer_id=?", (offer_id,))
            db.commit()
        self.assertEqual(result["total"], "27")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["payment_method"], "cod")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["order_id"], result["order_id"])
        with database.get_connection() as db:
            root = db.execute("SELECT * FROM orders WHERE order_id=?", (result["order_id"],)).fetchone()
            self.assertEqual((root["payment_status"], root["recipient_name_snapshot"],
                              root["recipient_phone_snapshot"]), ("unpaid", "Buyer Name", "967700123456"))
            self.assertEqual(db.execute("SELECT wa_id FROM customers WHERE customer_id=?",
                                        (root["customer_id"],)).fetchone()[0], None)
            item = db.execute("SELECT * FROM order_items WHERE order_id=?", (result["order_id"],)).fetchone()
            self.assertEqual((item["offer_id"], item["merchant_id"], item["product_id"],
                              item["quantity"], item["line_total"], item["product_name_snapshot"],
                              item["sku_snapshot"], item["merchant_name_snapshot"], item["unit_price"]),
                             (offer_id, merchant_id, product_id, 2, 24, "Tea", original_sku, "Seller A", 12))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fulfillments").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM settlements").fetchone()[0], 0)
            cart = db.execute("SELECT status,checkout_order_id FROM carts WHERE cart_id=?", (cart_id,)).fetchone()
            self.assertEqual(tuple(cart), ("checked_out", result["order_id"]))

    def test_multi_merchant_groups_root_and_merchant_totals(self):
        ma, mb = self.merchant("A"), self.merchant("B")
        oa, _ = self.offer(ma, price=10)
        ob, _ = self.offer(mb, price=7)
        cookie, _ = self.session_cart([(oa, 2), (ob, 3)])
        revision = self.quote(cookie)["quote_revision"]
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            result = self.submit(cookie, revision)
        self.assertEqual(result["total"], "47")
        groups = {row["merchant_id"]: row for row in result["merchant_orders"]}
        self.assertEqual(groups[ma]["products_subtotal"], 20)
        self.assertEqual(groups[mb]["products_subtotal"], 21)
        self.assertEqual(groups[ma]["delivery_fee"], 3)
        self.assertEqual(len(groups), 2)
        with database.get_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fulfillments").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_items WHERE order_id=?",
                                        (result["order_id"],)).fetchone()[0], 2)

    def test_managed_inventory_decrements_and_unmanaged_inventory_is_untouched(self):
        m = self.merchant()
        managed, _ = self.offer(m, managed=1, stock=5)
        unmanaged, _ = self.offer(self.merchant(), managed=0, stock=None)
        cookie, _ = self.session_cart([(managed, 2), (unmanaged, 4)])
        revision = self.quote(cookie)["quote_revision"]
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            self.submit(cookie, revision)
        with database.get_connection() as db:
            stock = {r["offer_id"]: r["stock"] for r in db.execute(
                "SELECT offer_id,stock FROM offers WHERE offer_id IN (?,?)", (managed, unmanaged))}
        self.assertEqual(stock[managed], 3)
        self.assertIsNone(stock[unmanaged])

    def test_bad_managed_stock_fails_without_partial_customer_or_order(self):
        for stock in (None, -1, 1.5, 1):
            with self.subTest(stock=stock):
                m = self.merchant()
                offer, _ = self.offer(m, managed=1, stock=stock)
                cookie, _ = self.session_cart([(offer, 2)])
                revision = self.quote(cookie)["quote_revision"]
                before = self.counts()
                with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
                    with self.assertRaises(CheckoutError) as raised:
                        self.submit(cookie, revision, key=f"bad-{stock}")
                self.assertEqual(raised.exception.code, "insufficient_stock")
                self.assertEqual(self.counts(), before)

    def test_exact_stock_depletion(self):
        m = self.merchant()
        offer, _ = self.offer(m, managed=1, stock=2)
        cookie, _ = self.session_cart([(offer, 2)])
        revision = self.quote(cookie)["quote_revision"]
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            self.submit(cookie, revision)
        with database.get_connection() as db:
            self.assertEqual(db.execute("SELECT stock FROM offers WHERE offer_id=?", (offer,)).fetchone()[0], 0)

    def test_stale_price_policy_or_eligibility_fails_before_writes(self):
        changes = (
            ("UPDATE offers SET price=price+1,price_minor=price_minor+1 WHERE offer_id=?", False, "quote_changed"),
            ("UPDATE merchant_delivery_policies SET delivery_fee=delivery_fee+1,delivery_fee_minor=delivery_fee_minor+1 WHERE merchant_id=?", False, "quote_changed"),
            ("UPDATE offers SET active=0 WHERE offer_id=?", False, "offer_unavailable"),
            ("UPDATE products SET active=0 WHERE product_id=?", True, "offer_unavailable"),
            ("UPDATE merchants SET status='inactive' WHERE merchant_id=?", True, "offer_unavailable"),
        )
        for sql, uses_product, expected in changes:
            with self.subTest(sql=sql):
                merchant_id = self.merchant()
                offer, product = self.offer(merchant_id)
                cookie, _ = self.session_cart([(offer, 1)])
                revision = self.quote(cookie)["quote_revision"]
                with database.get_connection() as db:
                    db.execute(sql, (product if uses_product else merchant_id if "policies" in sql else offer,))
                    db.commit()
                before = self.counts()
                with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
                    with self.assertRaises(CheckoutError) as raised:
                        self.submit(cookie, revision, key=f"stale-{uuid.uuid4()}")
                self.assertEqual(raised.exception.code, expected)
                self.assertEqual(self.counts(), before)

    def test_idempotency_conflicts_and_different_key_same_request(self):
        m = self.merchant()
        offer, _ = self.offer(m)
        cookie, _ = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            first = self.submit(cookie, revision, key="same")
            self.assertTrue(self.submit(cookie, revision, key="same")["replayed"])
            with self.assertRaises(CheckoutError) as changed:
                self.submit(cookie, revision, key="same", phone="967700000000")
            self.assertEqual(changed.exception.code, "idempotency_conflict")
            self.assertTrue(self.submit(cookie, revision, key="different")["replayed"])
            with self.assertRaises(CheckoutError) as conflict:
                self.submit(cookie, revision, key="different-2", address="Other address")
            self.assertEqual(conflict.exception.code, "already_checked_out_conflict")
        self.assertEqual(self.counts()["orders"], 1)
        self.assertEqual(first["order_id"], 1)

    def test_quote_change_and_invalid_payment_fail_without_writes(self):
        m = self.merchant()
        offer, _ = self.offer(m)
        cookie, _ = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        before = self.counts()
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with self.assertRaises(CheckoutError) as stale:
                self.submit(cookie, "forged-revision")
            self.assertEqual(stale.exception.code, "quote_changed")
            with self.assertRaises(CheckoutError) as payment:
                self.submit(cookie, revision, payment="card")
            self.assertEqual(payment.exception.code, "invalid_payment_method")
        self.assertEqual(self.counts(), before)

    def test_expired_revoked_idor_and_bad_session(self):
        m = self.merchant()
        offer, _ = self.offer(m)
        cookie_a, cart_a = self.session_cart([(offer, 1)])
        cookie_b, _ = self.session_cart([])
        revision = self.quote(cookie_a)["quote_revision"]
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with self.assertRaises(CheckoutError) as idor:
                self.submit(cookie_b, revision, cart_id=cart_a)
            self.assertEqual(idor.exception.code, "cart_not_found")
            with self.assertRaises(CheckoutError) as invalid:
                self.submit("", revision)
            self.assertEqual(invalid.exception.code, "session_invalid")
            self.now += timedelta(days=31)
            with self.assertRaises(CheckoutError) as expired:
                self.submit(cookie_a, revision)
            self.assertEqual(expired.exception.code, "session_invalid")

    def test_missing_hmac_secret_fails_closed(self):
        m = self.merchant()
        offer, _ = self.offer(m)
        cookie, _ = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        with patch.dict(os.environ, {}, clear=True):
            before = self.counts()
            with self.assertRaises(CheckoutError) as raised:
                self.submit(cookie, revision)
        self.assertEqual(raised.exception.code, "checkout_configuration_error")
        self.assertEqual(self.counts(), before)

    def test_transaction_failure_after_stock_decrement_rolls_back_everything(self):
        m = self.merchant()
        offer, _ = self.offer(m, managed=1, stock=5)
        cookie, _ = self.session_cart([(offer, 2)])
        revision = self.quote(cookie)["quote_revision"]
        with database.get_connection() as db:
            db.execute("CREATE TRIGGER fail_checkout_event BEFORE INSERT ON order_events "
                       "BEGIN SELECT RAISE(ABORT,'forced test failure'); END")
            db.commit()
        before = self.counts()
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with self.assertRaises(CheckoutError) as raised:
                self.submit(cookie, revision)
        self.assertEqual(raised.exception.code, "checkout_failed")
        self.assertEqual(self.counts(), before)
        with database.get_connection() as db:
            self.assertEqual(db.execute("SELECT stock FROM offers WHERE offer_id=?", (offer,)).fetchone()[0], 5)
            self.assertEqual(db.execute("SELECT status FROM carts").fetchone()[0], "active")

    def test_concurrent_same_and_different_key_requests_do_not_duplicate_order(self):
        m = self.merchant()
        offer, _ = self.offer(m, managed=1, stock=1)
        cookie, _ = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        service = CheckoutService(self.path, clock=lambda: self.now)
        def run(key):
            try:
                return ("ok", service.checkout(cookie, idempotency_key=key,
                    quote_revision_value=revision, recipient_name="Buyer Name",
                    recipient_phone="967700123456", delivery_address="Sanaa"))
            except CheckoutError as exc:
                return (exc.code, None)
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(run, ("parallel-a", "parallel-b")))
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 2, outcomes)
        self.assertEqual(self.counts()["orders"], 1)
        with database.get_connection() as db:
            self.assertGreaterEqual(db.execute("SELECT stock FROM offers WHERE offer_id=?", (offer,)).fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_same_key_concurrent_retry_returns_same_order(self):
        m = self.merchant()
        offer, _ = self.offer(m)
        cookie, _ = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        service = CheckoutService(self.path, clock=lambda: self.now)
        def run():
            return service.checkout(cookie, idempotency_key="same-parallel",
                quote_revision_value=revision, recipient_name="Buyer Name",
                recipient_phone="967700123456", delivery_address="Sanaa")
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(first["order_id"], second["order_id"])
        self.assertEqual(self.counts()["orders"], 1)

    def test_concurrent_independent_carts_cannot_buy_last_stock_twice(self):
        merchant_id = self.merchant()
        offer, _ = self.offer(merchant_id, managed=1, stock=1)
        cookie_a, _ = self.session_cart([(offer, 1)])
        cookie_b, _ = self.session_cart([(offer, 1)])
        revision_a = self.quote(cookie_a)["quote_revision"]
        revision_b = self.quote(cookie_b)["quote_revision"]
        service = CheckoutService(self.path, clock=lambda: self.now)
        def run(args):
            cookie, revision, key = args
            try:
                return service.checkout(cookie, idempotency_key=key, quote_revision_value=revision,
                    recipient_name="Buyer Name", recipient_phone="967700123456",
                    delivery_address="Sanaa")
            except CheckoutError as exc:
                return exc.code
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(run, ((cookie_a, revision_a, "stock-a"),
                                               (cookie_b, revision_b, "stock-b"))))
        self.assertEqual(sum(isinstance(value, dict) for value in outcomes), 1)
        # If the other checkout has already depleted inventory, its stock
        # change invalidates this cart's quote first; that safe stale-quote
        # conflict is also valid, and a refreshed attempt reports stock loss.
        self.assertTrue(any(value in ("insufficient_stock", "quote_changed")
                            for value in outcomes if isinstance(value, str)))
        self.assertEqual(self.counts()["orders"], 1)
        with database.get_connection() as db:
            self.assertEqual(db.execute("SELECT stock FROM offers WHERE offer_id=?", (offer,)).fetchone()[0], 0)
        for (cookie, _, _), outcome in zip(((cookie_a, revision_a, "stock-a"),
                                           (cookie_b, revision_b, "stock-b")), outcomes):
            if outcome == "quote_changed":
                current_revision = self.quote(cookie)["quote_revision"]
                with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
                    with self.assertRaises(CheckoutError) as retry:
                        self.submit(cookie, current_revision, key=f"refreshed-{uuid.uuid4()}")
                self.assertEqual(retry.exception.code, "insufficient_stock")

    def test_empty_cart_inactive_zone_missing_policy_and_non_yer_fail(self):
        cookie, _ = self.session_cart([])
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with self.assertRaises(CheckoutError) as empty:
                self.submit(cookie, "unused")
            self.assertEqual(empty.exception.code, "cart_empty")

        merchant_id = self.merchant()
        offer, _ = self.offer(merchant_id)
        cookie, cart_id = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        with database.get_connection() as db:
            db.execute("UPDATE delivery_zones SET active=0 WHERE zone_id=?", (self.zone_id,))
            db.commit()
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with self.assertRaises(CheckoutError) as inactive_zone:
                self.submit(cookie, revision)
        self.assertEqual(inactive_zone.exception.code, "delivery_zone_unavailable")

    def test_missing_policy_and_unsupported_currency_fail(self):
        merchant_id = self.merchant()
        offer, _ = self.offer(merchant_id)
        cookie, _ = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        with database.get_connection() as db:
            db.execute("DELETE FROM merchant_delivery_policies WHERE merchant_id=?", (merchant_id,))
            db.commit()
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with self.assertRaises(CheckoutError) as no_policy:
                self.submit(cookie, revision)
        self.assertEqual(no_policy.exception.code, "delivery_policy_unavailable")

        merchant_id = self.merchant()
        offer, _ = self.offer(merchant_id)
        cookie, _ = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        with database.get_connection() as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute("UPDATE offers SET currency='USD' WHERE offer_id=?", (offer,))
            db.commit()
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with self.assertRaises(CheckoutError) as currency:
                self.submit(cookie, revision, key="non-yer")
        self.assertEqual(currency.exception.code, "unsupported_currency")

    def test_invalid_quantity_currency_and_forged_financial_inputs_fail_closed(self):
        merchant_id = self.merchant()
        offer, _ = self.offer(merchant_id)
        cookie, _ = self.session_cart([(offer, 1)])
        revision = self.quote(cookie)["quote_revision"]
        with database.get_connection() as db:
            db.execute("PRAGMA ignore_check_constraints=ON")
            db.execute("UPDATE cart_items SET quantity=1.5 WHERE offer_id=?", (offer,))
            db.commit()
        with patch.dict(os.environ, {"CHECKOUT_FINGERPRINT_SECRET": SECRET}):
            with self.assertRaises(CheckoutError) as invalid_quantity:
                self.submit(cookie, revision)
        self.assertEqual(invalid_quantity.exception.code, "invalid_quantity")

        # Caller-supplied prices/totals/fees are not accepted by the service contract.
        with self.assertRaises(TypeError):
            self.checkout_service.checkout(cookie, idempotency_key="x", quote_revision_value=revision,
                recipient_name="Buyer", recipient_phone="12345678", delivery_address="Sanaa",
                price=0, total=0, delivery_fee=0)


if __name__ == "__main__":
    unittest.main()
