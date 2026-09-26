import os
import gc
import sqlite3
import tempfile
import unittest
from contextlib import closing

from src.merchant_os import catalog, database, merchants, operations, orders
from src.merchant_os.migrations import apply_migrations


class TestCatalogFoundation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "catalog.sqlite3")
        database.ensure_schema()
        merchants.ensure_merchant_schema()
        catalog.ensure_catalog_schema()
        orders.ensure_order_schema()
        operations.ensure_operations_schema()
        apply_migrations(database.DB_PATH)
        self.merchant_a = merchants.create_merchant("Merchant A")
        self.merchant_b = merchants.create_merchant("Merchant B")
        self.product_id = catalog.create_product("Shared Product", sku="GLOBAL-1")

    def tearDown(self):
        gc.collect()
        self.tmp.cleanup()

    def test_one_product_can_have_offers_from_two_merchants(self):
        offer_a = catalog.add_offer(self.product_id, self.merchant_a, 10)
        offer_b = catalog.add_offer(self.product_id, self.merchant_b, 12)
        with closing(database.get_connection()) as db:
            rows = db.execute(
                "SELECT offer_id, product_id, merchant_id FROM offers ORDER BY offer_id"
            ).fetchall()
        self.assertEqual([tuple(row) for row in rows], [
            (offer_a, self.product_id, self.merchant_a),
            (offer_b, self.product_id, self.merchant_b),
        ])

    def test_merchant_id_is_authoritative_for_display_identity(self):
        offer_id = catalog.add_offer(self.product_id, self.merchant_a, 10)
        with closing(database.get_connection()) as db:
            db.execute("UPDATE offers SET merchant_name='Legacy conflicting label' WHERE offer_id=?", (offer_id,))
            db.commit()
        product = catalog.find_products("Shared Product")[0]
        self.assertEqual(product["merchant_id"], self.merchant_a)
        self.assertEqual(product["merchant_name"], "Merchant A")

    def test_unknown_merchant_is_rejected_and_fk_enforcement_rejects_raw_invalid_id(self):
        with self.assertRaisesRegex(ValueError, "merchant_not_found"):
            catalog.add_offer(self.product_id, 99999, 10)

        with closing(database.get_connection()) as db:
            db.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """INSERT INTO offers
                    (product_id, merchant_name, price, created_at, updated_at, merchant_id)
                    VALUES (?, 'invalid', 10, 'a', 'b', 99999)""",
                    (self.product_id,),
                )

    def test_inventory_mode_check_and_unmanaged_offer_without_stock(self):
        unmanaged = catalog.add_offer(self.product_id, self.merchant_a, 10, stock=None, inventory_managed=0)
        managed = catalog.add_offer(self.product_id, self.merchant_b, 12, stock=0, inventory_managed=1)
        with closing(database.get_connection()) as db:
            for bad_value in (-1, 2):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        """INSERT INTO offers
                        (product_id, merchant_name, price, created_at, updated_at,
                         merchant_id, inventory_managed)
                        VALUES (?, 'invalid mode', 10, 'a', 'b', ?, ?)""",
                        (self.product_id, self.merchant_a, bad_value),
                    )
            rows = db.execute(
                "SELECT offer_id, stock, inventory_managed FROM offers ORDER BY offer_id"
            ).fetchall()
        self.assertEqual([tuple(row) for row in rows], [
            (unmanaged, None, 0),
            (managed, 0.0, 1),
        ])

    def test_offer_indexes_exist_with_expected_columns(self):
        with closing(database.get_connection()) as db:
            indexes = {
                row["name"]: [column["name"] for column in db.execute(
                    f"PRAGMA index_info('{row['name']}')"
                )]
                for row in db.execute("PRAGMA index_list('offers')")
            }
        self.assertEqual(indexes["idx_offers_product_active"], ["product_id", "active"])
        self.assertEqual(indexes["idx_offers_merchant_active"], ["merchant_id", "active"])


if __name__ == "__main__":
    unittest.main()
