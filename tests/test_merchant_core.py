import os
import gc
import tempfile
import unittest

from src.merchant_os import database, catalog, orders, merchants, operations
from src.merchant_os.migrations import apply_migrations
from src.merchant_os.agents import run_agent


class TestMerchantCore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "db.sqlite")
        database.ensure_schema()
        merchants.ensure_merchant_schema()
        catalog.ensure_catalog_schema()
        orders.ensure_order_schema()
        operations.ensure_operations_schema()
        apply_migrations(database.DB_PATH)

    def tearDown(self):
        gc.collect()
        self.tmp.cleanup()

    def test_agent_routing(self):
        result = run_agent("بكم السعر؟")
        self.assertEqual(result["intent"], "price_request")
        self.assertEqual(result["agent"], "sales_agent")

    def test_catalog_and_order(self):
        product_id = catalog.create_product("منتج تجريبي", sku="TEST-1")
        merchant_id = merchants.create_merchant("Merchant A")
        catalog.add_offer(product_id, merchant_id, 1000, stock=5)
        customer = database.upsert_customer("967700000001", "Test")
        result = orders.create_order(
            customer["customer_id"],
            [{"product_id": product_id, "quantity": 2, "unit_price": 1000}],
        )
        self.assertEqual(result["total"], 2000)
        self.assertEqual(result["status"], "pending")


if __name__ == "__main__":
    unittest.main()
