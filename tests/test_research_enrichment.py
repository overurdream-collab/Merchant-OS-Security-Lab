import unittest
from src.merchant_os.research_tools import ResearchResult, WebPageEnricher

class TestResearchEnrichment(unittest.TestCase):
    def test_enricher_has_public_signal_contract(self):
        self.assertTrue(hasattr(WebPageEnricher, "enrich"))
        result = ResearchResult(title="x", url="https://example.com")
        self.assertEqual(result.url, "https://example.com")

if __name__ == "__main__":
    unittest.main()
