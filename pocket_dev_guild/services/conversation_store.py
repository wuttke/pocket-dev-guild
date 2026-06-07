"""Conversation store with pluggable storage backend.

A `Conversation` groups successive jobs that share an agent-side session.
Thread-unsafe on purpose, lives entirely on the asyncio event loop.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..schemas import ConversationInfo
from .notification_hub import NotificationHub
from .storage_backend import InMemoryBackend, StorageBackend


class ConversationStore:
    """Conversation store with pluggable backend."""

    def __init__(
        self,
        backend: StorageBackend | None = None,
        notifications: NotificationHub | None = None,
    ) -> None:
        self._backend = backend or InMemoryBackend()
        self._notifications = notifications or NotificationHub()
        # In-memory busy state (not persisted)
        self._busy: dict[str, bool] = {}

    async def _ensure_indexes(self) -> None:
        """Create backend indexes if supported (MongoDB only)."""
        from .storage_backend import MongoBackend

        if isinstance(self._backend, MongoBackend):
            await self._backend.ensure_indexes(
                "conversations",
                [
                    {"fields": "id", "unique": True},
                    {"fields": "repo_id"},
                    {"fields": "updated_at"},
                ],
            )

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
        # Store in backend (fire and forget for sync create)
        import asyncio
        asyncio.create_task(self._backend.insert("conversations", info.model_dump(mode="json")))
        return info

    async def get(self, conv_id: str) -> ConversationInfo | None:
        doc = await self._backend.get("conversations", conv_id)
        if not doc:
            return None
        return ConversationInfo(**doc)

    async def list(self, repo_id: str | None = None) -> list[ConversationInfo]:
        filter_dict = {"repo_id": repo_id} if repo_id is not None else None
        docs = await self._backend.find(
            "conversations",
            filter=filter_dict,
            sort=[("updated_at", -1)],
        )
        return [ConversationInfo(**doc) for doc in docs]

    def is_busy(self, conv_id: str) -> bool:
        return self._busy.get(conv_id, False)

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
        self._busy[conv_id] = busy
        await self._notifications.notify(f"conversation:{conv_id}")

    async def append_turn(self, conv_id: str, job_id: str) -> None:
        # Get current turns
        doc = await self._backend.get("conversations", conv_id)
        if doc is None:
            return

        turns = doc.get("turns", []) + [job_id]
        await self._backend.update(
            "conversations",
            conv_id,
            {"turns": turns, "updated_at": datetime.now(timezone.utc)},
        )
        await self._notifications.notify(f"conversation:{conv_id}")

    async def patch(
        self,
        conv_id: str,
        *,
        session_id: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Update mutable fields. Only non-None values overwrite."""
        update: dict[str, object] = {"updated_at": datetime.now(timezone.utc)}
        if session_id is not None:
            update["session_id"] = session_id
        if summary is not None:
            update["summary"] = summary

        await self._backend.update("conversations", conv_id, update)
        await self._notifications.notify(f"conversation:{conv_id}")
