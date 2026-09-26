import unittest
from src.merchant_os.data_intelligence import DataIntelligenceAgent
from src.merchant_os.strategist import StrategicDeveloperAgent

class TestDataIntelligence(unittest.TestCase):
    def test_market_gap(self):
        merchants=[{"taxonomy":{"primary_category":"fashion"}}]
        customers=[
            {"taxonomy":{"purchase_categories":["fashion"],"geography":{"city":"Sana'a"}}},
            {"taxonomy":{"purchase_categories":["fashion"],"geography":{"city":"Sana'a"}}},
            {"taxonomy":{"purchase_categories":["fashion"],"geography":{"city":"Sana'a"}}},
        ]
        out=DataIntelligenceAgent().analyze(merchants,customers)
        self.assertEqual(out["market_signals"]["demand_supply_gaps"][0]["category"],"fashion")

    def test_strategist_finds_missing_lifecycle(self):
        out=StrategicDeveloperAgent().analyze({
            "merchants":[{"name":"A"}],
            "customers":[{"name":"B"}],
            "data_intelligence":{"data_gaps":{"merchant_missing_city":0,"customer_missing_city":0,"customer_missing_age":1},
                                "market_signals":{"demand_supply_gaps":[]}}
        })
        codes={x["code"] for x in out["suggestions"]}
        self.assertIn("merchant_performance",codes)
        self.assertIn("customer_lifecycle",codes)

if __name__=="__main__":
    unittest.main()
