import unittest
from src.merchant_os.offer_learning import OfferLearningEngine

class TestOfferLearning(unittest.TestCase):
    def test_learning_loop_records_and_classifies_outcomes(self):
        e = OfferLearningEngine()
        e.record(1, "o1", "p1", "impression")
        e.record(1, "o1", "p1", "click")
        e.record(1, "o1", "p1", "order_started")
        result = e.outcome(1, "o1")
        self.assertEqual(result["status"], "high_intent")
        self.assertEqual(result["outcome_score"], 7)
        self.assertEqual(result["event_counts"]["click"], 1)

    def test_purchase_becomes_conversion_and_return_reduces_learning(self):
        e = OfferLearningEngine()
        e.record(2, "o2", "p2", "purchase")
        self.assertEqual(e.outcome(2, "o2")["status"], "converted")
        e.record(2, "o2", "p2", "return")
        self.assertEqual(e.product_learning("p2")["learning_score"], 2)

    def test_unsupported_event_is_rejected(self):
        e = OfferLearningEngine()
        with self.assertRaises(ValueError):
            e.record(3, "o3", "p3", "random_event")
