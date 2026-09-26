import unittest
from src.merchant_os.customer_discovery import CustomerDiscoveryAgent, DemandSupplyMatcher
from src.merchant_os.research_tools import StaticResearchProvider, ResearchResult

class TestCustomerDiscovery(unittest.TestCase):
    def test_customer_intent_is_separate(self):
        provider = StaticResearchProvider([
            ResearchResult("مطلوب iPhone 15", "https://facebook.com/post/1", "أبحث عن iPhone 15 في صنعاء", captured_at="2026-09-19T00:00:00Z")
        ])
        out = CustomerDiscoveryAgent(provider).run({
            "subject": {"category":"phones","city":"Sana'a","source_types":["facebook_post"],"max_discovery_queries":2}
        })
        self.assertTrue(out["customer_research"])
        self.assertGreater(out["customer_research"][0]["customer_intent_score"], 0)

    def test_demand_supply_match(self):
        customers=[{"category":"phones","city":"Sana'a","customer_intent_score":1}]
        merchants=[{"name":"Phone Store","category":"phones","city":"Sana'a","phone":"777","occurrences":3}]
        out=DemandSupplyMatcher().match(customers,merchants)
        self.assertEqual(out[0]["matches"][0]["merchant"]["name"],"Phone Store")
        self.assertGreater(out[0]["matches"][0]["match_score"],0.7)

if __name__=="__main__":
    unittest.main()
