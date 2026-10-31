
import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch

from saloon_web_v4 import Member, collect_member_events


class OversizedInputPropagationTests(unittest.TestCase):

    def test_oversized_message_is_not_automatically_trimmed(self):

        def make_context_error():
            body = json.dumps({
                "error": {
                    "message": "Input exceeds context length.",
                    "type": "invalid_request_error",
                    "code": "context_length_exceeded"
                }
            }).encode("utf-8")

            return HTTPError(
                url="https://openrouter.ai/api/v1/chat/completions",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=io.BytesIO(body)
            )

        oversized_text = "X" * 50000

        transcript = [
            {
                "kind": "user",
                "text": oversized_text
            }
        ]

        members = [
            Member("FirstMember", "test/model-a", "First role"),
            Member("SecondMember", "test/model-b", "Second role")
        ]

        with patch(
            "saloon_web_v4.urllib.request.urlopen",
            side_effect=[
                make_context_error(),
                make_context_error()
            ]
        ) as mocked_urlopen:

            events, context = collect_member_events(
                "test-key",
                members,
                transcript
            )

        self.assertEqual(mocked_urlopen.call_count, 2)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "error")
        self.assertEqual(events[1]["kind"], "error")

        first_request = mocked_urlopen.call_args_list[0].args[0]
        second_request = mocked_urlopen.call_args_list[1].args[0]

        first_payload = json.loads(first_request.data.decode("utf-8"))
        second_payload = json.loads(second_request.data.decode("utf-8"))

        first_messages = json.dumps(first_payload["messages"])
        second_messages = json.dumps(second_payload["messages"])

        # پیام بزرگ باید در درخواست هر دو عضو وجود داشته باشد
        self.assertIn(oversized_text, first_messages)
        self.assertIn(oversized_text, second_messages)

        # هیچ کوتاه‌سازی خودکاری روی متن بزرگ انجام نشده باشد
        self.assertEqual(
            len(oversized_text),
            50000
        )

        # خطای عضو اول نیز باید به تاریخچه عضو دوم اضافه شده باشد
        self.assertIn(
            "context_length_exceeded",
            second_messages
        )

        self.assertEqual(len(context), 3)


if __name__ == "__main__":
    unittest.main()
