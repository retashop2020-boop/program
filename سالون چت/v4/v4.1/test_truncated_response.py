
import json
import unittest
from unittest.mock import MagicMock, patch

from saloon_web_v4 import Member, collect_member_events


class TruncatedResponseTests(unittest.TestCase):

    def test_length_finish_reason_preserves_answer_and_adds_warning(self):
        response_data = {
            "choices": [
                {
                    "message": {
                        "content": "Partial answer"
                    },
                    "finish_reason": "length"
                }
            ]
        }

        successful_response = MagicMock()
        successful_response.__enter__.return_value = successful_response
        successful_response.status = 200
        successful_response.read.return_value = json.dumps(
            response_data
        ).encode("utf-8")

        member = Member(
            name="TestMember",
            model="test/model",
            role="Test role",
            max_tokens=1200
        )

        with patch(
            "saloon_web_v4.urllib.request.urlopen",
            return_value=successful_response
        ) as mocked_urlopen:

            events, context = collect_member_events(
                "test-key",
                [member],
                []
            )

        self.assertEqual(mocked_urlopen.call_count, 1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "reply")

        self.assertIn("Partial answer", events[0]["text"])
        self.assertIn(
            "[هشدار: احتمال دارد پاسخ به‌دلیل رسیدن به سقف توکن ناقص باشد.]",
            events[0]["text"]
        )

        self.assertEqual(context, events)

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))

        self.assertEqual(payload["max_tokens"], 1200)


if __name__ == "__main__":
    unittest.main()
