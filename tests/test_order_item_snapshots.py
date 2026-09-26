import os
import gc
import sqlite3
import tempfile
import unittest
from contextlib import closing

from src.merchant_os import catalog, database, merchants, operations, orders
from src.merchant_os.migrations import apply_migrations


class TestOrderItemHistoricalFoundation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "orders.sqlite3")
        database.ensure_schema()
        merchants.ensure_merchant_schema()
        catalog.ensure_catalog_schema()
        orders.ensure_order_schema()
        operations.ensure_operations_schema()
        apply_migrations(database.DB_PATH)
        self.merchant_id = merchants.create_merchant("Merchant Snapshot")
        self.product_id = catalog.create_product("Product Snapshot", sku="SNAP-1")
        self.offer_id = catalog.add_offer(self.product_id, self.merchant_id, 12, currency="YER")
        customer = database.upsert_customer("snapshot-customer", "Snapshot Customer")
        self.order_id = orders.create_order(customer["customer_id"], [], currency="YER")["order_id"]

    def tearDown(self):
        # Release SQLite connections left by legacy `with connection` call sites
        # before TemporaryDirectory removes the database on Windows.
        gc.collect()
        self.tmp.cleanup()

    def test_offer_backed_line_derives_relationships_and_preserves_snapshots(self):
        item_id = orders._persist_offer_order_item(self.order_id, self.offer_id, 3)

        with database.get_connection() as db:
            db.execute("""UPDATE products SET name='Renamed product', sku='RENAMED-1'
                          WHERE product_id=?""", (self.product_id,))
            db.execute("UPDATE merchants SET name='Renamed merchant' WHERE merchant_id=?", (self.merchant_id,))
            db.execute("UPDATE offers SET price=99 WHERE offer_id=?", (self.offer_id,))
            db.commit()
        with database.get_connection() as db:
            row = db.execute("SELECT * FROM order_items WHERE order_item_id=?", (item_id,)).fetchone()

        self.assertEqual(row["offer_id"], self.offer_id)
        self.assertEqual(row["product_id"], self.product_id)
        self.assertEqual(row["merchant_id"], self.merchant_id)
        self.assertEqual(row["unit_price"], 12)
        self.assertEqual(row["currency"], "YER")
        self.assertEqual(row["line_total"], 36)
        self.assertEqual(row["product_name_snapshot"], "Product Snapshot")
        self.assertEqual(row["sku_snapshot"], "SNAP-1")
        self.assertEqual(row["merchant_name_snapshot"], "Merchant Snapshot")

    def test_line_total_is_computed_by_persistence_path(self):
        item_id = orders._persist_offer_order_item(self.order_id, self.offer_id, 4)
        with database.get_connection() as db:
            row = db.execute("SELECT quantity, unit_price, line_total FROM order_items WHERE order_item_id=?", (item_id,)).fetchone()
        self.assertEqual(row["line_total"], row["quantity"] * row["unit_price"])

    def test_legacy_order_item_without_offer_and_snapshots_remains_readable(self):
        item = orders.create_order(
            database.upsert_customer("legacy-customer")["customer_id"],
            [{"product_id": self.product_id, "quantity": 1, "unit_price": 7}],
        )
        with database.get_connection() as db:
            row = db.execute("SELECT * FROM order_items WHERE order_id=?", (item["order_id"],)).fetchone()
        self.assertIsNone(row["offer_id"])
        self.assertIsNone(row["merchant_id"])
        self.assertIsNone(row["product_name_snapshot"])
        self.assertIsNone(row["sku_snapshot"])
        self.assertIsNone(row["merchant_name_snapshot"])

    def test_fk_enabled_connection_rejects_deleting_referenced_offer(self):
        orders._persist_offer_order_item(self.order_id, self.offer_id, 1)
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM offers WHERE offer_id=?", (self.offer_id,))

    def test_fk_enabled_connection_rejects_deleting_referenced_merchant(self):
        orders._persist_offer_order_item(self.order_id, self.offer_id, 1)
        # Clear the offer's merchant link on this FK-disabled temporary connection
        # to isolate the order item's own merchant reference for the constraint check.
        with database.get_connection() as db:
            db.execute("UPDATE offers SET merchant_id=NULL WHERE offer_id=?", (self.offer_id,))
            db.commit()
        with database.get_connection() as db:
            db.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM merchants WHERE merchant_id=?", (self.merchant_id,))


if __name__ == "__main__":
    unittest.main()
