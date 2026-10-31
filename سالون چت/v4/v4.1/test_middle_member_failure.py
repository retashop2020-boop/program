
import unittest
from unittest.mock import patch

from saloon_web_v4 import Member, collect_member_events


class MiddleMemberFailureTests(unittest.TestCase):

    def test_middle_failure_preserves_first_reply_and_runs_third(self):
        members = [
            Member("Skeptic", "model-a", "role"),
            Member("Analyst", "model-b", "role"),
            Member("Builder", "model-c", "role"),
        ]

        responses = [
            ("First reply", False),
            OSError("middle member failed"),
            ("Third reply", False),
        ]

        received_contexts = []

        def fake_call_model(api_key, member, context):
            # Save a snapshot of context at call time.
            received_contexts.append([
                dict(event) for event in context
            ])

            result = responses.pop(0)

            if isinstance(result, Exception):
                raise result

            return result

        with patch(
            "saloon_web_v4.call_model",
            side_effect=fake_call_model,
        ) as mocked_call:

            events, context = collect_member_events(
                "test-key",
                members,
                []
            )

        # All three members should have been attempted.
        self.assertEqual(mocked_call.call_count, 3)

        # First member: successful reply.
        self.assertEqual(events[0]["kind"], "reply")
        self.assertEqual(events[0]["member"], "Skeptic")
        self.assertEqual(events[0]["text"], "First reply")

        # Second member: failure.
        self.assertEqual(events[1]["kind"], "error")
        self.assertEqual(events[1]["member"], "Analyst")

        # Third member: successful reply.
        self.assertEqual(events[2]["kind"], "reply")
        self.assertEqual(events[2]["member"], "Builder")
        self.assertEqual(events[2]["text"], "Third reply")

        # Check the actual context received at the third call.
        third_call_context = received_contexts[2]

        self.assertEqual(len(third_call_context), 2)
        self.assertEqual(third_call_context[0]["kind"], "reply")
        self.assertEqual(third_call_context[0]["text"], "First reply")
        self.assertEqual(third_call_context[1]["kind"], "error")
        self.assertEqual(third_call_context[1]["member"], "Analyst")

        # Final context should contain all three events.
        self.assertEqual(len(context), 3)
        self.assertEqual(context[0]["kind"], "reply")
        self.assertEqual(context[1]["kind"], "error")
        self.assertEqual(context[2]["kind"], "reply")


if __name__ == "__main__":
    unittest.main()
