import os
import tempfile
import unittest

from src.merchant_os import database, operations
from src.merchant_os.creative import ProductCreativeEngine
from src.merchant_os.customer_voice import CustomerVoiceEngine


class TestV1RealCore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "db.sqlite")
        database.ensure_schema()
        operations.ensure_operations_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_delivery_lifecycle_and_collection_reconciliation(self):
        delivery_id = operations.create_delivery(101, "Sana'a", "courier", 12000)
        self.assertEqual(operations.update_delivery_status(delivery_id, "assigned")["status"], "assigned")
        self.assertEqual(operations.update_delivery_status(delivery_id, "out_for_delivery")["status"], "out_for_delivery")
        self.assertEqual(operations.update_delivery_status(delivery_id, "delivered")["status"], "delivered")
        result = operations.reconcile_collection(delivery_id, 12000)
        self.assertEqual(result["status"], "delivered")
        self.assertEqual(result["collection_status"], "reconciled")
        self.assertEqual(result["collected_amount"], 12000)

    def test_return_lifecycle(self):
        delivery_id = operations.create_delivery(102, "Sana'a", "courier", 9000)
        operations.update_delivery_status(delivery_id, "assigned")
        return_id = operations.request_return(102, "customer rejected at delivery")
        self.assertEqual(operations.update_return_status(return_id, "approved")["status"], "approved")
        self.assertEqual(operations.update_return_status(return_id, "received")["status"], "received")
        self.assertEqual(operations.update_return_status(return_id, "closed")["status"], "closed")

    def test_settlement_requires_verified_delivery_and_collection(self):
        delivery_id = operations.create_delivery(103, "Sana'a", "courier", 10000)
        settlement_id = operations.create_settlement(103, "Merchant A", 10000, 0.10)
        approved = operations.approve_order_commission(103)
        self.assertEqual(approved["status"], "due")
        self.assertEqual(approved["commission_amount"], 1000)
        operations.update_delivery_status(delivery_id, "assigned")
        operations.update_delivery_status(delivery_id, "out_for_delivery")
        operations.update_delivery_status(delivery_id, "delivered")
        operations.reconcile_collection(delivery_id, 10000)
        finalized = operations.finalize_settlement(103, settlement_id)
        self.assertEqual(finalized["status"], "due")
        self.assertEqual(finalized["commission_amount"], 1000)

    def test_settlement_confirmation_and_payment(self):
        delivery_id = operations.create_delivery(104, "Sana'a", "courier", 5000)
        for status in ("assigned", "out_for_delivery", "delivered"):
            operations.update_delivery_status(delivery_id, status)
        operations.reconcile_collection(delivery_id, 5000)
        sid = operations.create_settlement(104, "Merchant B", 5000, 0.10)
        operations.finalize_settlement(104, sid)
        self.assertEqual(operations.confirm_settlement(sid)["status"], "confirmed")
        self.assertEqual(operations.mark_settlement_paid(sid)["status"], "paid")

    def test_creative_package_has_multiple_realizable_formats(self):
        package = ProductCreativeEngine().build({
            "name": "عطر يمني",
            "price": 25000,
            "description": "رائحة ثابتة"
        }, audience="عطور", objective="conversion")
        types = {v["type"] for v in package["variants"]}
        self.assertEqual(types, {"image", "short_video", "social_post", "product_card"})
        self.assertEqual(package["status"], "draft")
        self.assertIn("external_media_provider_required", package["variants"][1]["asset_generation"])

    def test_customer_voice_extracts_actionable_market_signals(self):
        summary = CustomerVoiceEngine().summarize([
            {"text": "هل يوجد اللون الأسود والمقاس 42؟"},
            {"text": "السعر غالي، هل يوجد خصم؟"},
            {"text": "التوصيل متأخر"},
        ])
        self.assertGreaterEqual(summary["theme_counts"]["availability"], 1)
        self.assertGreaterEqual(summary["theme_counts"]["price"], 1)
        self.assertGreaterEqual(summary["theme_counts"]["delivery"], 1)


if __name__ == "__main__":
    unittest.main()


    def test_commission_is_not_reversed_until_return_is_approved(self):
        operations.create_settlement(105, "Merchant C", 20000, 0.10)
        due = operations.approve_order_commission(105)
        self.assertEqual(due["commission_amount"], 2000)
        rid = operations.request_return(105, "customer returned")
        with self.assertRaises(ValueError):
            operations.reverse_commission_for_approved_return(105)
        operations.update_return_status(rid, "approved")
        reversed_settlement = operations.reverse_commission_for_approved_return(105)
        self.assertEqual(reversed_settlement["status"], "reversed")
        self.assertEqual(reversed_settlement["commission_amount"], 0)


    def test_daily_statement_reflects_due_and_reversed_commission(self):
        operations.create_settlement(106, "Merchant D", 30000, 0.10)
        operations.approve_order_commission(106)
        operations.create_settlement(107, "Merchant D", 20000, 0.10)
        operations.approve_order_commission(107)
        rid = operations.request_return(107, "returned")
        operations.update_return_status(rid, "approved")
        operations.reverse_commission_for_approved_return(107)
        statement = operations.merchant_daily_statement("Merchant D")
        self.assertEqual(statement["totals"]["commission_due"], 3000)
        self.assertEqual(len(statement["items"]), 2)
