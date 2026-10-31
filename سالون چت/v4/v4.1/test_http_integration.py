
import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from saloon_web_v4 import Member, collect_member_events


class HttpIntegrationTests(unittest.TestCase):

    def test_http_error_does_not_block_next_member(self):
        members = [
            Member("Skeptic", "model-a", "role"),
            Member("Analyst", "model-b", "role"),
        ]

        # Simulate an HTTP 429 response for the first member.
        http_error = HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"rate limit exceeded"}'),
        )

        # Simulate a successful HTTP response for the second member.
        success_data = {
            "choices": [
                {
                    "message": {
                        "content": "Analyst successful reply"
                    },
                    "finish_reason": "stop",
                }
            ]
        }

        successful_response = MagicMock()
        successful_response.__enter__.return_value = successful_response
        successful_response.status = 200
        successful_response.read.return_value = json.dumps(
            success_data
        ).encode("utf-8")

        with patch(
            "saloon_web_v4.urllib.request.urlopen",
            side_effect=[http_error, successful_response],
        ) as mocked_urlopen:

            events, context = collect_member_events(
                "test-key",
                members,
                [],
            )

        # Both real call_model executions should reach urlopen.
        self.assertEqual(mocked_urlopen.call_count, 2)

        # First member should receive an HTTP 429 error.
        self.assertEqual(events[0]["kind"], "error")
        self.assertEqual(events[0]["member"], "Skeptic")
        self.assertIn("HTTP 429", events[0]["text"])

        # Second member should still receive a successful reply.
        self.assertEqual(events[1]["kind"], "reply")
        self.assertEqual(events[1]["member"], "Analyst")
        self.assertEqual(
            events[1]["text"],
            "Analyst successful reply",
        )

        # Verify the second API request contains the first member's error.
        second_request = mocked_urlopen.call_args_list[1].args[0]
        second_payload = json.loads(second_request.data.decode("utf-8"))

        second_messages = second_payload["messages"]

        self.assertTrue(
            any(
                message["role"] == "user"
                and "[اطلاع فنی:" in message["content"]
                for message in second_messages
            )
        )

        # Final context should preserve both events.
        self.assertEqual(len(context), 2)
        self.assertEqual(context[0]["kind"], "error")
        self.assertEqual(context[1]["kind"], "reply")


if __name__ == "__main__":
    unittest.main()
