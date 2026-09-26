import os
import tempfile
import unittest

from src.merchant_os import database
from src.merchant_os.intelligence.hermes_scout import HermesScoutAgent, ScoutRequest
from src.merchant_os.intelligence.signals import signal_from_item


class FakeCollector:
    def collect(self, query, context):
        self.query = query
        self.context = context
        return [
            {
                "source": "reddit",
                "id": "r1",
                "type": "demand",
                "content": "Looking for Hilux brake pads in Sanaa",
                "category": "auto_parts",
                "location": "Sanaa",
                "intent": "looking_to_buy",
                "confidence": 0.91,
            },
            {
                "source": "reddit",
                "id": "r1",
                "type": "demand",
                "content": "Looking for Hilux brake pads in Sanaa",
            },
            {
                "source": "facebook",
                "id": "f1",
                "type": "complaint",
                "content": "Hard to find this part locally",
                "confidence": 0.8,
            },
        ]


class TestHermesScout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.tmp.name, "db.sqlite")
        database.ensure_intelligence_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalization_and_deduplication(self):
        collector = FakeCollector()
        agent = HermesScoutAgent(collector)

        signals = agent.collect(
            ScoutRequest(
                query="Hilux brake pads",
                sources=("reddit", "facebook"),
                category="auto_parts",
                location="Sanaa",
            )
        )

        self.assertEqual(len(signals), 2)
        self.assertEqual(signals[0].source, "reddit")
        self.assertEqual(signals[0].signal_type, "demand")
        self.assertEqual(signals[0].confidence, 0.91)
        self.assertTrue(signals[0].signal_id)

    def test_store_is_idempotent(self):
        collector = FakeCollector()
        agent = HermesScoutAgent(collector)
        request = ScoutRequest(query="Hilux brake pads")

        first = agent.collect_and_store(request)
        second = agent.collect_and_store(request)

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)

        with database.get_connection() as db:
            count = db.execute("SELECT COUNT(*) FROM market_signals").fetchone()[0]

        self.assertEqual(count, 2)

    def test_invalid_signal_is_rejected(self):
        with self.assertRaises(ValueError):
            signal_from_item({"source": "reddit", "type": "unknown_type", "content": "x"})


if __name__ == "__main__":
    unittest.main()
