import unittest
from src.merchant_os.source_discovery import SourceDiscoveryPlanner, classify_source, MerchantEntityResolver

class TestSourceDiscovery(unittest.TestCase):
    def test_facebook_gets_many_surfaces(self):
        planned = SourceDiscoveryPlanner().plan("spare parts", "Sana'a", max_queries=40)
        types = {x.source_type for x in planned}
        self.assertIn("facebook_page", types)
        self.assertIn("facebook_group", types)
        self.assertIn("facebook_marketplace", types)
        self.assertIn("facebook_post", types)
        self.assertIn("facebook_ad", types)
        self.assertIn("facebook_reel", types)
        self.assertTrue(all(x.priority == 0 for x in planned if x.source_type.startswith("facebook_")))

    def test_source_classification(self):
        self.assertEqual(classify_source("https://www.facebook.com/marketplace/item/1"), "facebook_marketplace")
        self.assertEqual(classify_source("https://www.facebook.com/groups/yemen-shop"), "facebook_group")
        self.assertEqual(classify_source("https://chat.whatsapp.com/ABC"), "whatsapp_group")
        self.assertEqual(classify_source("https://t.me/example"), "telegram_group")

    def test_repeated_merchant_is_merged(self):
        rows = [
            {"name":"ABC Store","city":"Sana'a","phone":"+967771234567","url":"https://facebook.com/p/abc","source_type":"facebook_page"},
            {"name":"ABC Store","city":"Sana'a","phone":"+967771234567","url":"https://facebook.com/marketplace/item/1","source_type":"facebook_marketplace"},
        ]
        merged = MerchantEntityResolver().resolve(rows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["occurrences"], 2)
        self.assertEqual(len(merged[0]["source_types"]), 2)

if __name__ == "__main__":
    unittest.main()
