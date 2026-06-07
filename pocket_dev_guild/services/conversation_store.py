"""Conversation store with pluggable storage backend.

A `Conversation` groups successive jobs that share an agent-side session.
Thread-unsafe on purpose, lives entirely on the asyncio event loop.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from ..schemas import ConversationInfo
from .notification_hub import NotificationHub
from .storage_backend import InMemoryBackend, StorageBackend

logger = logging.getLogger(__name__)


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

    async def create(
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
        await self._backend.insert("conversations", info.model_dump(mode="json"))
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

    async def state(self, conv_id: str) -> tuple[ConversationInfo, bool] | None:
        """Snapshot info and busy flag atomically."""
        info = await self.get(conv_id)
        if info is None:
            return None
        busy = self.is_busy(conv_id)
        return info, busy

    async def wait_for_update(self, conv_id: str, timeout: float = 5.0) -> None:
        """Wait for an update notification on this conversation."""
        await self._notifications.wait(f"conversation:{conv_id}", timeout=timeout)

    async def mark_busy(self, conv_id: str, busy: bool) -> None:
        self._busy[conv_id] = busy
        await self._notifications.notify(f"conversation:{conv_id}")

    async def append_turn(self, conv_id: str, job_id: str) -> None:
        """Append a job_id to the conversation's turn list.

        Note: Reads entire turns list and rewrites it. Consider using backend's
        append_to_list for better efficiency with large turn counts.
        """
        try:
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
        except Exception as e:
            logger.error(f"Failed to append turn to conversation {conv_id}: {e}")
            raise

    async def patch(
        self,
        conv_id: str,
        *,
        session_id: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Update mutable fields. Only non-None values overwrite."""
        try:
            update: dict[str, object] = {"updated_at": datetime.now(timezone.utc)}
            if session_id is not None:
                update["session_id"] = session_id
            if summary is not None:
                update["summary"] = summary

            await self._backend.update("conversations", conv_id, update)
            await self._notifications.notify(f"conversation:{conv_id}")
        except Exception as e:
            logger.error(f"Failed to patch conversation {conv_id}: {e}")
            raise
