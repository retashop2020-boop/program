import unittest
from unittest.mock import patch

from saloon_web_v4 import Member, call_model, collect_member_events


class MemberFailureIsolationTests(unittest.TestCase):
    def setUp(self):
        self.members = [
            Member("Skeptic", "model-a", "role"),
            Member("Analyst", "model-b", "role"),
        ]

    def test_failure_of_first_member_does_not_block_second(self):
        def fake_call(_key, member, _context):
            if member.name == "Skeptic":
                raise ConnectionResetError(10054, "connection reset")
            return "Analyst reply", False

        with patch("saloon_web_v4.call_model", side_effect=fake_call):
            events, context = collect_member_events("test-key", self.members, [])

        self.assertEqual([e["kind"] for e in events], ["error", "reply"])
        self.assertEqual(events[1]["member"], "Analyst")
        self.assertEqual(events[1]["text"], "Analyst reply")
        self.assertEqual(context, events)

    def test_successful_reply_is_preserved_when_later_member_fails(self):
        def fake_call(_key, member, _context):
            if member.name == "Analyst":
                raise OSError("remote closed connection")
            return "Skeptic reply", False

        with patch("saloon_web_v4.call_model", side_effect=fake_call):
            events, context = collect_member_events("test-key", self.members, [])

        self.assertEqual([e["kind"] for e in events], ["reply", "error"])
        self.assertEqual(events[0]["text"], "Skeptic reply")
        self.assertEqual(context, events)

    def test_call_model_converts_raw_connection_reset_to_runtime_error(self):
        member = Member("Skeptic", "model-a", "role")
        with patch("saloon_web_v4.urllib.request.urlopen", side_effect=ConnectionResetError(10054, "reset")):
            with self.assertRaisesRegex(RuntimeError, "خطای ارتباط با سرویس"):
                call_model("test-key", member, [])

    def test_later_member_receives_prior_member_event_in_context(self):
        seen_context_lengths = []

        def fake_call(_key, member, context):
            seen_context_lengths.append((member.name, len(context)))
            return member.name + " reply", False

        with patch("saloon_web_v4.call_model", side_effect=fake_call):
            events, _ = collect_member_events("test-key", self.members, [{"kind": "user", "text": "hi"}])

        self.assertEqual(seen_context_lengths, [("Skeptic", 1), ("Analyst", 2)])
        self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
