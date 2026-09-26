import unittest
from src.merchant_os.customer_intelligence import CustomerIntentEngine, CustomerEntityResolver

class TestCustomerIntelligence(unittest.TestCase):
    def test_intent_extracts_purchase_and_budget(self):
        x=CustomerIntentEngine().extract("أريد هاتف ايفون بميزانيتي 500000 وأحتاجه اليوم", "phones", "Sana'a")
        self.assertEqual(x["intent"], "purchase")
        self.assertGreater(x["intent_score"], 0.4)
        self.assertEqual(x["budget"]["value"], 500000)

    def test_resolver_does_not_merge_names(self):
        out=CustomerEntityResolver().resolve([
            {"name":"Ahmed","url":"https://facebook.com/p/1"},
            {"name":"Ahmed","url":"https://facebook.com/p/2"},
        ])
        self.assertEqual(len(out),2)

    def test_resolver_merges_public_phone(self):
        out=CustomerEntityResolver().resolve([
            {"name":"A","url":"https://facebook.com/post/1","phone":"00967777123456"},
            {"name":"B","url":"https://facebook.com/post/2","phone":"777123456"},
        ])
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["demand_events"],2)

if __name__=="__main__":
    unittest.main()
