import os
import tempfile
import unittest

from src.merchant_os import database
from src.merchant_os.customer_interest import CustomerInterestEngine


class TestCustomerInterest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "db.sqlite")
        database.ensure_schema()
        database.ensure_interest_schema()
        self.engine = CustomerInterestEngine(database)
        self.customer = database.upsert_customer("967700000001", "Test Customer")

    def tearDown(self):
        self.tmp.cleanup()

    def test_tracks_behavior_and_ranks_interest(self):
        cid = self.customer["customer_id"]
        self.engine.record_event(cid, "view", "shoe-1", "shoes")
        self.engine.record_event(cid, "click", "shoe-1", "shoes")
        self.engine.record_event(cid, "search", None, "shoes")
        self.engine.record_event(cid, "order_started", "shoe-1", "shoes")
        profile = self.engine.profile(cid)
        self.assertEqual(profile["top_categories"], ["shoes"])
        self.assertEqual(profile["top_products"], ["shoe-1"])
        self.assertEqual(profile["purchase_readiness"], "medium_high")
        self.assertEqual(profile["event_count"], 4)

    def test_purchase_and_return_are_observable(self):
        cid = self.customer["customer_id"]
        self.engine.record_event(cid, "purchase", "bag-1", "bags")
        self.engine.record_event(cid, "return", "bag-1", "bags")
        profile = self.engine.profile(cid)
        self.assertEqual(profile["purchase_readiness"], "high")
        self.assertEqual(profile["category_scores"]["bags"], 4)

    def test_duplicate_event_id_is_idempotent(self):
        cid = self.customer["customer_id"]
        event1 = self.engine.record_event(cid, "view", "p1", "electronics", {"event_id": "evt-1"})
        event2 = self.engine.record_event(cid, "view", "p1", "electronics", {"event_id": "evt-1"})
        self.assertEqual(event1["event_id"], event2["event_id"])
        self.assertEqual(len(database.get_interest_events(cid)), 1)
