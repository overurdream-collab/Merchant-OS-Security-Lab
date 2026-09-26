import os
import unittest
from unittest.mock import patch, Mock

from src.merchant_os import whatsapp


class TestWhatsApp(unittest.TestCase):
    def test_config_status_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            status = whatsapp.whatsapp_config_status()
        self.assertFalse(status["configured"])
        self.assertFalse(status["access_token_present"])
        self.assertFalse(status["phone_number_id_present"])

    def test_send_text_uses_runtime_environment(self):
        response = Mock()
        response.ok = True
        response.json.return_value = {"messages": [{"id": "wamid.test"}]}

        with patch.dict(
            os.environ,
            {
                "WHATSAPP_ACCESS_TOKEN": "test-token",
                "WHATSAPP_PHONE_NUMBER_ID": "123456",
                "META_GRAPH_VERSION": "v23.0",
            },
            clear=True,
        ), patch("src.merchant_os.whatsapp.requests.post", return_value=response) as post:
            result = whatsapp.send_text("967700000001", "hello")

        self.assertEqual(result["messages"][0]["id"], "wamid.test")
        post.assert_called_once()
        self.assertIn("/v23.0/123456/messages", post.call_args.args[0])
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-token",
        )


if __name__ == "__main__":
    unittest.main()
