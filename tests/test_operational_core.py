import os
import tempfile
import unittest

from src.merchant_os import database, operations, outreach, catalog, merchants
from src.merchant_os.action_engine import ActionEngine
from src.merchant_os.human_approval import HumanApprovalGate


class TestOperationalCore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "db.sqlite")
        database.ensure_schema()
        catalog.ensure_catalog_schema()
        operations.ensure_operations_schema()
        outreach.ensure_outreach_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_delivery_and_settlement_are_persisted(self):
        delivery_id = operations.create_delivery(7, "Sana'a", "test-courier", 2500)
        settlement_id = operations.create_settlement(7, "Merchant A", 10000, 0.10)
        self.assertIsInstance(delivery_id, int)
        self.assertIsInstance(settlement_id, int)

        with database.get_connection() as db:
            delivery = db.execute("SELECT * FROM deliveries WHERE delivery_id=?", (delivery_id,)).fetchone()
            settlement = db.execute("SELECT * FROM settlements WHERE settlement_id=?", (settlement_id,)).fetchone()
        self.assertEqual(delivery["collection_amount"], 2500)
        self.assertEqual(delivery["status"], "pending")
        self.assertEqual(settlement["commission_amount"], 1000)
        self.assertEqual(settlement["merchant_amount"], 9000)

    def test_outreach_defaults_to_draft(self):
        merchants.ensure_merchant_schema()
        merchant_id = merchants.create_merchant("Merchant A", phone="967700000001")
        outreach_id = outreach.create_outreach(merchant_id, "whatsapp", "عرض تجريبي")
        with database.get_connection() as db:
            row = db.execute("SELECT * FROM outreach WHERE outreach_id=?", (outreach_id,)).fetchone()
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["direction"], "outbound")

    def test_action_engine_requires_approval(self):
        engine = ActionEngine()
        engine.register("send_message", lambda payload: {"sent": payload["text"]})
        blocked = engine.execute("send_message", {"text": "x"})
        self.assertEqual(blocked["status"], "blocked")
        forged = engine.execute("send_message", {"text": "x"}, approved=True)
        self.assertEqual(forged["status"], "blocked")
        engine = ActionEngine(approval_verifier=lambda action, payload, record: record == "verified-approval")
        engine.register("send_message", lambda payload: {"sent": payload["text"]})
        executed = engine.execute("send_message", {"text": "x"}, approval_record="verified-approval")
        self.assertEqual(executed["status"], "executed")
        self.assertTrue(executed["result"]["sent"] == "x")

    def test_human_approval_state_transition(self):
        gate = HumanApprovalGate()
        request = gate.request("m1", "send_message", "medium")
        self.assertEqual(request["status"], "pending")
        self.assertEqual(gate.approve(request)["status"], "approved")
        self.assertEqual(gate.reject(request)["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
