"""Immutable data contracts for Saloon V5's round-based architecture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EventKind = Literal["user", "member"]


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    """A committed event in the shared conversation stream."""

    event_id: str
    round_index: int
    kind: EventKind
    content: str
    slot_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryVersion:
    """An immutable version in one slot's private memory history."""

    revision: int
    action: str
    content: str


@dataclass(frozen=True, slots=True)
class SlotMemory:
    """Memory belonging to a discussion slot, not to a model identity."""

    slot_id: str
    versions: tuple[MemoryVersion, ...] = ()

    @property
    def latest(self) -> MemoryVersion | None:
        return self.versions[-1] if self.versions else None

    def apply(self, update: MemoryUpdate | None) -> SlotMemory:
        """Append a new version without destroying prior memory history."""
        if update is None or update.action == "no_change":
            return self
        version = MemoryVersion(
            revision=len(self.versions) + 1,
            action=update.action,
            content=update.content,
        )
        return SlotMemory(
            slot_id=self.slot_id,
            versions=self.versions + (version,),
        )


@dataclass(frozen=True, slots=True)
class MemberSpec:
    """A configured discussion slot and its currently assigned model."""

    slot_id: str
    model: str
    role: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class MemoryUpdate:
    """A model-produced, evaluable memory change; not private chain of thought."""

    action: str
    content: str = ""


@dataclass(frozen=True, slots=True)
class MemberRequest:
    """The complete, isolated input supplied to one member for one round."""

    round_index: int
    slot_id: str
    model: str
    role: str
    current_user_message: str
    shared_context: tuple[ConversationEvent, ...]
    slot_memory: SlotMemory


@dataclass(frozen=True, slots=True)
class MemberReply:
    """Parsed public response and optional concise memory update."""

    response: str
    memory_update: MemoryUpdate | None = None


@dataclass(frozen=True, slots=True)
class MemberOutcome:
    """Operational result for one slot; failures remain local to that slot."""

    slot_id: str
    response: str | None = None
    memory_update: MemoryUpdate | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RoundResult:
    """Committed shared context and per-slot outcomes after a round completes."""

    round_index: int
    shared_context: tuple[ConversationEvent, ...]
    outcomes: tuple[MemberOutcome, ...]
    slot_memories: tuple[SlotMemory, ...]
