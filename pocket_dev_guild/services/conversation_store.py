"""In-memory conversation store.

A `Conversation` groups successive jobs that share an agent-side session.
Mirrors the in-memory `JobStore`: thread-unsafe on purpose, lives entirely
on the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..schemas import ConversationInfo


@dataclass
class _ConversationRecord:
    info: ConversationInfo
    # set while a turn (job + post-processing) is in flight, so the
    # router can reject parallel turns with 409.
    busy: bool = False
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)


class ConversationStore:
    def __init__(self) -> None:
        self._items: dict[str, _ConversationRecord] = {}

    def create(
        self,
        repo_id: str,
        worktree: str | None,
        agent_id: str | None,
        title: str | None,
    ) -> ConversationInfo:
        conv_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        info = ConversationInfo(
            id=conv_id,
            repo_id=repo_id,
            worktree=worktree,
            agent_id=agent_id,
            title=title,
            session_id=None,
            summary=None,
            created_at=now,
            updated_at=now,
            turns=[],
        )
        self._items[conv_id] = _ConversationRecord(info=info)
        return info

    def get(self, conv_id: str) -> ConversationInfo | None:
        record = self._items.get(conv_id)
        return record.info if record else None

    def list(self, repo_id: str | None = None) -> list[ConversationInfo]:
        items = [r.info for r in self._items.values()]
        if repo_id is not None:
            items = [c for c in items if c.repo_id == repo_id]
        items.sort(key=lambda c: c.updated_at, reverse=True)
        return items

    def is_busy(self, conv_id: str) -> bool:
        record = self._items.get(conv_id)
        return bool(record and record.busy)

    def state(self, conv_id: str) -> tuple[ConversationInfo, bool] | None:
        """Snapshot info and busy flag atomically (single dict lookup)."""
        record = self._items.get(conv_id)
        if record is None:
            return None
        return record.info, record.busy

    async def wait_for_update(self, conv_id: str, timeout: float = 5.0) -> None:
        record = self._items.get(conv_id)
        if record is None:
            return
        async with record.condition:
            try:
                await asyncio.wait_for(record.condition.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    async def mark_busy(self, conv_id: str, busy: bool) -> None:
        record = self._items.get(conv_id)
        if record is None:
            return
        record.busy = busy
        async with record.condition:
            record.condition.notify_all()

    async def append_turn(self, conv_id: str, job_id: str) -> None:
        record = self._items.get(conv_id)
        if record is None:
            return
        turns = list(record.info.turns) + [job_id]
        record.info = record.info.model_copy(
            update={"turns": turns, "updated_at": datetime.now(timezone.utc)}
        )
        async with record.condition:
            record.condition.notify_all()

    async def patch(
        self,
        conv_id: str,
        *,
        session_id: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Update mutable fields. Only non-None values overwrite."""
        record = self._items.get(conv_id)
        if record is None:
            return
        update: dict[str, object] = {"updated_at": datetime.now(timezone.utc)}
        if session_id is not None:
            update["session_id"] = session_id
        if summary is not None:
            update["summary"] = summary
        record.info = record.info.model_copy(update=update)
        async with record.condition:
            record.condition.notify_all()
