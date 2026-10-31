
import unittest
from unittest.mock import patch

from saloon_web_v4 import Member, collect_member_events


class UnexpectedErrorTests(unittest.TestCase):

    def test_unexpected_error_does_not_block_next_member(self):
        members = [
            Member("Skeptic", "model-a", "role"),
            Member("Analyst", "model-b", "role"),
        ]

        with patch(
            "saloon_web_v4.call_model",
            side_effect=[
    		    ValueError("unexpected test error"),
    		    ("Analyst reply", False),
	        ],
        ) as mocked_call:

            events, context = collect_member_events(
                "test-key",
                members,
                []
            )

        # Both members should have been attempted.
        self.assertEqual(mocked_call.call_count, 2)

        # The first member should have failed.
        self.assertEqual(events[0]["kind"], "error")
        self.assertEqual(events[0]["member"], "Skeptic")

        # The second member should still have replied.
        self.assertEqual(events[1]["kind"], "reply")
        self.assertEqual(events[1]["member"], "Analyst")
        self.assertEqual(events[1]["text"], "Analyst reply")


if __name__ == "__main__":
    unittest.main()
