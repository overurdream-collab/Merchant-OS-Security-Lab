import unittest
from datetime import datetime, timedelta, timezone
from src.merchant_os.offer_guard import OfferFrequencyGuard

class TestOfferFrequencyGuard(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)

    def test_first_offer_is_allowed(self):
        self.assertTrue(OfferFrequencyGuard().check(1, self.now)["allowed"])

    def test_cooldown_blocks_repetition(self):
        g = OfferFrequencyGuard()
        g.record(1, "o1", "impression", self.now)
        r = g.check(1, self.now + timedelta(hours=2))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "offer_cooldown")

    def test_daily_limit_blocks_after_three(self):
        g = OfferFrequencyGuard(max_offers=3)
        for i in range(3):
            g.record(1, f"o{i}", "impression", self.now - timedelta(hours=i))
        r = g.check(1, self.now)
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "daily_offer_limit")

    def test_negative_signal_blocks_longer(self):
        g = OfferFrequencyGuard()
        g.record(1, "o1", "dismissed", self.now - timedelta(hours=12))
        r = g.check(1, self.now)
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "negative_signal_cooldown")
