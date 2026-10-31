from __future__ import annotations

import threading
import unittest

from saloon_v5 import (
    ConversationEvent,
    MemberReply,
    MemberSpec,
    MemoryUpdate,
    MemoryVersion,
    RoundOrchestrator,
    SlotMemory,
)


class RoundIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = RoundOrchestrator()
        self.members = (
            MemberSpec("analyst", "model-a", "Analyst"),
            MemberSpec("critic", "model-b", "Critic"),
        )
        self.context = (
            ConversationEvent(
                event_id="old-1",
                round_index=0,
                kind="user",
                content="Earlier question",
            ),
            ConversationEvent(
                event_id="old-2",
                round_index=0,
                kind="member",
                content="Earlier answer",
                slot_id="analyst",
            ),
        )
        self.memories = (
            SlotMemory("analyst", (MemoryVersion(1, "add", "Analyst-only note"),)),
            SlotMemory("critic", (MemoryVersion(1, "add", "Critic-only note"),)),
        )

    def test_every_member_gets_same_pre_round_context(self) -> None:
        seen = {}

        def invoke(request):
            seen[request.slot_id] = request.shared_context
            return MemberReply(f"reply from {request.slot_id}")

        result = self.orchestrator.run_round(
            round_index=1,
            current_user_message="Current question",
            shared_context=self.context,
            members=self.members,
            slot_memories=self.memories,
            invoke_member=invoke,
        )

        self.assertEqual(seen["analyst"], self.context)
        self.assertEqual(seen["critic"], self.context)
        self.assertIs(seen["analyst"], seen["critic"])
        self.assertEqual(result.shared_context[-1].content, "reply from critic")
        self.assertEqual(len(result.shared_context), len(self.context) + 3)

    def test_each_member_receives_only_its_own_slot_memory(self) -> None:
        seen = {}

        def invoke(request):
            seen[request.slot_id] = request.slot_memory
            return MemberReply("ok")

        self.orchestrator.run_round(
            round_index=1,
            current_user_message="Question",
            shared_context=self.context,
            members=self.members,
            slot_memories=self.memories,
            invoke_member=invoke,
        )

        self.assertEqual(seen["analyst"].slot_id, "analyst")
        self.assertEqual(seen["critic"].slot_id, "critic")
        self.assertNotEqual(seen["analyst"].slot_id, seen["critic"].slot_id)
        self.assertEqual(seen["analyst"].latest.content, "Analyst-only note")
        self.assertEqual(seen["critic"].latest.content, "Critic-only note")

    def test_current_round_outputs_are_not_visible_to_other_members(self) -> None:
        barrier = threading.Barrier(2)
        seen_context_lengths = []

        def invoke(request):
            barrier.wait(timeout=2)
            seen_context_lengths.append(len(request.shared_context))
            return MemberReply(f"reply-{request.slot_id}")

        result = self.orchestrator.run_round(
            round_index=1,
            current_user_message="Question",
            shared_context=self.context,
            members=self.members,
            slot_memories=self.memories,
            invoke_member=invoke,
        )

        self.assertEqual(seen_context_lengths, [len(self.context), len(self.context)])
        self.assertEqual(
            [event.content for event in result.shared_context[-2:]],
            ["reply-analyst", "reply-critic"],
        )

    def test_one_member_failure_does_not_block_another(self) -> None:
        def invoke(request):
            if request.slot_id == "analyst":
                raise RuntimeError("temporary failure")
            return MemberReply(
                "critic response",
                MemoryUpdate("revise", "updated critic inference"),
            )

        result = self.orchestrator.run_round(
            round_index=1,
            current_user_message="Question",
            shared_context=self.context,
            members=self.members,
            slot_memories=self.memories,
            invoke_member=invoke,
        )

        by_slot = {outcome.slot_id: outcome for outcome in result.outcomes}
        self.assertIn("RuntimeError", by_slot["analyst"].error)
        self.assertEqual(by_slot["critic"].response, "critic response")
        self.assertEqual(result.shared_context[-1].content, "critic response")
        updated = {memory.slot_id: memory for memory in result.slot_memories}
        self.assertEqual(updated["analyst"].latest.content, "Analyst-only note")
        self.assertEqual(updated["critic"].latest.revision, 2)
        self.assertEqual(updated["critic"].latest.content, "updated critic inference")

    def test_memory_history_is_append_only_and_no_change_is_noop(self) -> None:
        original = SlotMemory("analyst", (MemoryVersion(1, "add", "v1"),))
        revised = original.apply(MemoryUpdate("redefine", "v2"))
        unchanged = revised.apply(MemoryUpdate("no_change", ""))

        self.assertEqual(len(original.versions), 1)
        self.assertEqual(len(revised.versions), 2)
        self.assertEqual(revised.versions[0].content, "v1")
        self.assertEqual(revised.latest.content, "v2")
        self.assertIs(unchanged, revised)

    def test_disabled_member_is_not_invoked(self) -> None:
        calls = []

        def invoke(request):
            calls.append(request.slot_id)
            return MemberReply("ok")

        result = self.orchestrator.run_round(
            round_index=1,
            current_user_message="Question",
            shared_context=self.context,
            members=(self.members[0], MemberSpec("off", "model-x", "Inactive", False)),
            slot_memories=self.memories,
            invoke_member=invoke,
        )

        self.assertEqual(calls, ["analyst"])
        self.assertEqual([item.slot_id for item in result.outcomes], ["analyst"])


if __name__ == "__main__":
    unittest.main()
