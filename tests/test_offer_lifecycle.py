import unittest
from src.merchant_os.offer_lifecycle import OfferLifecycle

class TestOfferLifecycle(unittest.TestCase):
    def test_valid_flow(self):
        x = OfferLifecycle()
        x.create("o1", 1, "p1")
        for state in ("approved","ready","sent","delivered","read","clicked","ordered","purchased"):
            x.transition("o1", state)
        self.assertEqual(x.get("o1")["state"], "purchased")

    def test_invalid_transition_is_rejected(self):
        x = OfferLifecycle()
        x.create("o1", 1, "p1")
        with self.assertRaises(ValueError):
            x.transition("o1", "sent")
