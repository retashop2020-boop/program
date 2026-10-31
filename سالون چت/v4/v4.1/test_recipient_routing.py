import unittest

from saloon_web_v4 import Member, resolve_recipients


class RecipientRoutingTests(unittest.TestCase):
    def setUp(self):
        self.members = [
            Member("Skeptic", "model-a", "role"),
            Member("Analyst", "model-b", "role"),
            Member("Disabled", "model-c", "role", enabled=False),
        ]

    def test_no_mention_selects_all_enabled_members(self):
        self.assertEqual([m.name for m in resolve_recipients("سلام", self.members)],
                         ["Skeptic", "Analyst"])

    def test_single_mention_selects_only_named_member(self):
        self.assertEqual([m.name for m in resolve_recipients("@Analyst بررسی کن", self.members)],
                         ["Analyst"])

    def test_multiple_mentions_select_only_mentioned_members(self):
        self.assertEqual([m.name for m in resolve_recipients("@Analyst @Skeptic", self.members)],
                         ["Skeptic", "Analyst"])

    def test_quoted_name_with_spaces(self):
        members = [Member("Red Team", "model", "role")]
        self.assertEqual([m.name for m in resolve_recipients('@"Red Team" سلام', members)],
                         ["Red Team"])

    def test_unknown_target_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "ناشناخته"):
            resolve_recipients("@Ghost", self.members)

    def test_disabled_target_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "غیرفعال"):
            resolve_recipients("@Disabled", self.members)

    def test_duplicate_names_are_ambiguous(self):
        members = self.members + [Member("Analyst", "model-d", "role")]
        with self.assertRaisesRegex(ValueError, "مبهم"):
            resolve_recipients("@Analyst", members)

    def test_repeated_mentions_are_deduplicated(self):
        self.assertEqual([m.name for m in resolve_recipients("@Analyst دوباره @Analyst", self.members)],
                         ["Analyst"])


if __name__ == "__main__":
    unittest.main()
