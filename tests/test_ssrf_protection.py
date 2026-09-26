import unittest
from unittest.mock import patch

from src.merchant_os.research_tools import (
    ResearchResult,
    WebPageEnricher,
    _validate_public_url,
)


class TestResearchEnrichmentSecurity(unittest.TestCase):
    def test_rejects_loopback_ip(self):
        with self.assertRaises(ValueError):
            _validate_public_url("http://127.0.0.1:8765/")

    def test_rejects_localhost(self):
        with self.assertRaises(ValueError):
            _validate_public_url("http://localhost:8765/")

    def test_rejects_private_ip(self):
        with self.assertRaises(ValueError):
            _validate_public_url("http://192.168.1.10/")

    def test_allows_public_https_host(self):
        self.assertEqual(
            _validate_public_url("https://example.com/"),
            "https://example.com/",
        )

    def test_enricher_does_not_open_blocked_url(self):
        enricher = WebPageEnricher()
        with patch("src.merchant_os.research_tools._validate_public_url", side_effect=ValueError("blocked")),              patch.object(enricher._opener, "open") as opener:
            result = enricher.enrich(ResearchResult("x", "http://127.0.0.1:8765/"))
        opener.assert_not_called()
        self.assertFalse(result["fetch_ok"])

    def test_redirect_handler_rejects_loopback_target(self):
        handler = WebPageEnricher()._opener.handlers[0]
        # The actual request is never made: redirect validation happens first.
        class Req:
            full_url = "https://example.com/start"
        with self.assertRaises(ValueError):
            handler.redirect_request(
                Req(), None, 302, "Found",
                {"Location": "http://127.0.0.1:8765/"},
                "http://127.0.0.1:8765/",
            )


if __name__ == "__main__":
    unittest.main()
