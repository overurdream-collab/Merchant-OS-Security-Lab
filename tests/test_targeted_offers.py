import os
import tempfile
import unittest

from src.merchant_os import database
from src.merchant_os.customer_interest import CustomerInterestEngine
from src.merchant_os.creative import ProductCreativeEngine
from src.merchant_os.targeted_offers import TargetedOfferEngine


class TestTargetedOffers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "db.sqlite")
        database.ensure_schema()
        database.ensure_interest_schema()
        self.interest = CustomerInterestEngine(database)
        self.engine = TargetedOfferEngine(self.interest, ProductCreativeEngine())
        self.customer = database.upsert_customer("967700000002", "Offer Customer")

    def tearDown(self):
        self.tmp.cleanup()

    def test_recommends_relevant_products_and_changes_objective_with_readiness(self):
        cid = self.customer["customer_id"]
        self.interest.record_event(cid, "view", "shoe-1", "shoes")
        self.interest.record_event(cid, "click", "shoe-1", "shoes")
        self.interest.record_event(cid, "order_started", "shoe-1", "shoes")
        products = [
            {"product_id": "shoe-1", "name": "Black Shoe", "category": "shoes", "price": 100},
            {"product_id": "bag-1", "name": "Bag", "category": "bags", "price": 80},
        ]
        offers = self.engine.recommend(cid, products)
        self.assertEqual(offers[0]["product_id"], "shoe-1")
        self.assertEqual(offers[0]["objective"], "engage")
        self.assertEqual(offers[0]["creative"]["status"], "draft")
        self.assertEqual(len(offers), 1)
