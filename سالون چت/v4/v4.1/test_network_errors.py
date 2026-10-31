
import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from saloon_web_v4 import Member, call_model


class NetworkErrorTests(unittest.TestCase):
    def setUp(self):
        self.member = Member("Skeptic", "model-a", "role")

    def assert_network_error(self, error, expected_text):
        with patch(
            "saloon_web_v4.urllib.request.urlopen",
            side_effect=error
        ):
            with self.assertRaises(RuntimeError) as caught:
                call_model("test-key", self.member, [])

        self.assertIn(expected_text, str(caught.exception))

    def test_timeout_is_converted(self):
        self.assert_network_error(
            TimeoutError("request timed out"),
            "خطای ارتباط با سرویس"
        )

    def test_url_error_is_converted(self):
        self.assert_network_error(
            urllib.error.URLError("network unreachable"),
            "خطای ارتباط با سرویس"
        )

    def test_http_429_is_reported(self):
        error = urllib.error.HTTPError(
            "https://example.com",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b"rate limited")
        )
        self.assert_network_error(error, "HTTP 429")

    def test_http_500_is_reported(self):
        error = urllib.error.HTTPError(
            "https://example.com",
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b"server error")
        )
        self.assert_network_error(error, "HTTP 500")

    def test_invalid_json_is_converted(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b"not valid json"

        with patch(
            "saloon_web_v4.urllib.request.urlopen",
            return_value=response
        ):
            with self.assertRaises(RuntimeError) as caught:
                call_model("test-key", self.member, [])

        self.assertIn("خطای ارتباط با سرویس", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
