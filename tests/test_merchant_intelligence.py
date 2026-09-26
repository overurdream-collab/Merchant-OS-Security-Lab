import unittest
from src.merchant_os.merchant_intelligence import MerchantIntelligenceEngine

class TestMerchantIntelligence(unittest.TestCase):
    def test_rank_is_explainable_and_ordered(self):
        engine = MerchantIntelligenceEngine()
        evidence = [
            {"source":"https://a.example","data":{"name":"A"}},
            {"source":"https://b.example","data":{"name":"B"}},
        ]
        merchants = [
            {"name":"A","url":"https://a.example","city":"Sanaa","category":"fashion","channels":["facebook","whatsapp"],"phone":"1","captured_at":"2026-09-19"},
            {"name":"B","url":"https://b.example","city":"Other","category":"other"},
        ]
        ranked = engine.rank(merchants,evidence,{"city":"Sanaa","category":"fashion"})
        self.assertEqual(ranked[0]["merchant"]["name"],"A")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])
        self.assertEqual(set(ranked[0]["factors"]), set(engine.WEIGHTS))

if __name__=="__main__": unittest.main()
