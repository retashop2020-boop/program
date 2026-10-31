"""Round orchestration with shared-context snapshots and slot isolation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4
from typing import Callable, Iterable

from .models import (
    ConversationEvent,
    MemberOutcome,
    MemberReply,
    MemberRequest,
    MemberSpec,
    RoundResult,
    SlotMemory,
)


MemberInvoker = Callable[[MemberRequest], MemberReply]


class RoundOrchestrator:
    """Run all enabled slots against one pre-round snapshot.

    The executor may finish members in any order. Results are reassembled in
    configuration order and are committed to shared context only after every
    enabled member has completed. The invoker must not be given access to the
    mutable orchestration state.
    """

    def run_round(
        self,
        *,
        round_index: int,
        current_user_message: str,
        shared_context: Iterable[ConversationEvent],
        members: Iterable[MemberSpec],
        slot_memories: Iterable[SlotMemory],
        invoke_member: MemberInvoker,
    ) -> RoundResult:
        context_snapshot = tuple(shared_context)
        enabled_members = tuple(member for member in members if member.enabled)
        memory_by_slot = {memory.slot_id: memory for memory in slot_memories}

        if len({member.slot_id for member in enabled_members}) != len(enabled_members):
            raise ValueError("Enabled member slot_id values must be unique.")

        requests: dict[str, MemberRequest] = {}
        for member in enabled_members:
            requests[member.slot_id] = MemberRequest(
                round_index=round_index,
                slot_id=member.slot_id,
                model=member.model,
                role=member.role,
                current_user_message=current_user_message,
                shared_context=context_snapshot,
                slot_memory=memory_by_slot.get(
                    member.slot_id, SlotMemory(slot_id=member.slot_id)
                ),
            )

        outcomes_by_slot: dict[str, MemberOutcome] = {}
        if enabled_members:
            with ThreadPoolExecutor(max_workers=len(enabled_members)) as executor:
                future_to_slot = {
                    executor.submit(invoke_member, requests[member.slot_id]): member.slot_id
                    for member in enabled_members
                }
                for future in as_completed(future_to_slot):
                    slot_id = future_to_slot[future]
                    try:
                        reply = future.result()
                        if not isinstance(reply, MemberReply):
                            raise TypeError("Member invoker must return MemberReply.")
                        outcomes_by_slot[slot_id] = MemberOutcome(
                            slot_id=slot_id,
                            response=reply.response,
                            memory_update=reply.memory_update,
                        )
                    except Exception as exc:  # isolate a single member failure
                        outcomes_by_slot[slot_id] = MemberOutcome(
                            slot_id=slot_id,
                            error=f"{type(exc).__name__}: {exc}",
                        )

        # Stable presentation/commit order; execution completion order is irrelevant.
        outcomes = tuple(
            outcomes_by_slot[member.slot_id] for member in enabled_members
        )

        user_event = ConversationEvent(
            event_id=str(uuid4()),
            round_index=round_index,
            kind="user",
            content=current_user_message,
        )
        committed_events = [user_event]
        updated_memories = dict(memory_by_slot)

        for outcome in outcomes:
            if outcome.error is not None:
                continue
            if outcome.response is not None:
                committed_events.append(
                    ConversationEvent(
                        event_id=str(uuid4()),
                        round_index=round_index,
                        kind="member",
                        content=outcome.response,
                        slot_id=outcome.slot_id,
                    )
                )
            if outcome.memory_update is not None:
                prior = updated_memories.get(
                    outcome.slot_id, SlotMemory(slot_id=outcome.slot_id)
                )
                updated_memories[outcome.slot_id] = prior.apply(
                    outcome.memory_update
                )

        return RoundResult(
            round_index=round_index,
            shared_context=context_snapshot + tuple(committed_events),
            outcomes=outcomes,
            slot_memories=tuple(
                updated_memories[key] for key in sorted(updated_memories)
            ),
        )
