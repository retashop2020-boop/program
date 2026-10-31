
import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch

from saloon_web_v4 import Member, collect_member_events


class ContextLengthErrorTests(unittest.TestCase):

    def test_context_length_error_does_not_block_next_member(self):

        error_body = json.dumps({
            "error": {
                "message": "The input exceeds the maximum context length.",
                "type": "invalid_request_error",
                "code": "context_length_exceeded"
            }
        }).encode("utf-8")

        context_error = HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(error_body)
        )

        response_data = {
            "choices": [
                {
                    "message": {
                        "content": "Second member succeeded."
                    },
                    "finish_reason": "stop"
                }
            ]
        }

        successful_response = MagicMock()
        successful_response.__enter__.return_value = successful_response
        successful_response.status = 200
        successful_response.read.return_value = json.dumps(
            response_data
        ).encode("utf-8")

        members = [
            Member(
                name="FirstMember",
                model="test/model-a",
                role="First role"
            ),
            Member(
                name="SecondMember",
                model="test/model-b",
                role="Second role"
            )
        ]

        with patch(
            "saloon_web_v4.urllib.request.urlopen",
            side_effect=[context_error, successful_response]
        ) as mocked_urlopen:

            events, context = collect_member_events(
                "test-key",
                members,
                []
            )

        # دو عضو، دو درخواست؛ بدون تلاش مجدد برای عضو اول
        self.assertEqual(mocked_urlopen.call_count, 2)

        # عضو اول باید با خطا ثبت شده باشد
        self.assertEqual(events[0]["kind"], "error")
        self.assertIn(
            "context_length_exceeded",
            events[0]["text"]
        )

        # عضو دوم باید بتواند پاسخ دهد
        self.assertEqual(events[1]["kind"], "reply")
        self.assertIn(
            "Second member succeeded.",
            events[1]["text"]
        )

        # خطای عضو اول باید در context نهایی ثبت شده باشد
        self.assertEqual(len(context), 2)
        self.assertEqual(context[0]["kind"], "error")

        # درخواست عضو دوم باید حاوی اطلاع از خطای عضو اول باشد
        second_request = mocked_urlopen.call_args_list[1].args[0]
        second_payload = json.loads(
            second_request.data.decode("utf-8")
        )

        second_messages = "\n".join(
            str(message.get("content", ""))
            for message in second_payload["messages"]
        )

        self.assertIn(
            "context_length_exceeded",
            second_messages
        )


if __name__ == "__main__":
    unittest.main()
