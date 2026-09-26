import unittest
from src.merchant_os.delivery import MockDeliveryProvider, OfferDeliveryAdapter
from src.merchant_os.offer_guard import OfferFrequencyGuard

class TestOfferDeliveryAdapter(unittest.TestCase):
    def test_first_offer_is_sent_to_mock_provider(self):
        adapter = OfferDeliveryAdapter(OfferFrequencyGuard(), MockDeliveryProvider())
        result = adapter.send(1, "967700000000", "o1", "p1", {"status": "draft"})
        self.assertEqual(result.status, "queued")
        self.assertEqual(result.channel, "mock")

    def test_guard_blocks_repeated_offer(self):
        guard = OfferFrequencyGuard()
        adapter = OfferDeliveryAdapter(guard, MockDeliveryProvider())
        adapter.send(1, "967700000000", "o1", "p1", {"status": "draft"})
        result = adapter.send(1, "967700000000", "o2", "p2", {"status": "draft"})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "offer_cooldown")

    def test_prepare_does_not_send(self):
        provider = MockDeliveryProvider()
        adapter = OfferDeliveryAdapter(OfferFrequencyGuard(), provider)
        prepared = adapter.prepare(1, "967700000000", "o1", "p1", {"status": "draft"})
        self.assertEqual(prepared["status"], "ready")
        self.assertEqual(prepared["channel"], "mock")
