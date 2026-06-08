"""Conversation store with pluggable storage backend.

A `Conversation` groups successive jobs that share an agent-side session.
Thread-unsafe on purpose, lives entirely on the asyncio event loop.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..schemas import ConversationInfo
from .notification_hub import NotificationHub
from .storage_backend import InMemoryBackend, StorageBackend

if TYPE_CHECKING:
    from .job_store import JobStore
    from .mongo_job_store import MongoJobStore

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
        # NOTE: use model_dump() (not mode="json") so datetimes stay as
        # datetime objects. MongoBackend then stores them as BSON dates,
        # matching what update()/append_turn()/patch() write.
        await self._backend.insert("conversations", info.model_dump())
        return info

    async def get(self, conv_id: str) -> ConversationInfo | None:
        doc = await self._backend.get("conversations", conv_id)
        if not doc:
            return None
        return ConversationInfo(**doc)

    def _build_filter(
        self,
        *,
        repo_id: str | None,
        worktree: str | None,
        include_archived: bool,
        updated_since: datetime | None = None,
    ) -> dict[str, object]:
        f: dict[str, object] = {}
        if repo_id is not None:
            f["repo_id"] = repo_id
        if worktree is not None:
            f["worktree"] = worktree
        if not include_archived:
            # `$ne: True` matches docs missing the field as well — covers
            # pre-archive records that never had `archived` written.
            f["archived"] = {"$ne": True}
        if updated_since is not None:
            # Normalize naive datetimes to UTC. `updated_at` is always
            # stored tz-aware, and naive-vs-aware comparison crashes the
            # in-memory matcher.
            since = updated_since
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            f["updated_at"] = {"$gte": since}
        return f

    async def list(
        self,
        repo_id: str | None = None,
        *,
        worktree: str | None = None,
        include_archived: bool = False,
        updated_since: datetime | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationInfo]:
        filter_dict = self._build_filter(
            repo_id=repo_id,
            worktree=worktree,
            include_archived=include_archived,
            updated_since=updated_since,
        )
        docs = await self._backend.find(
            "conversations",
            filter=filter_dict or None,
            sort=sort or [("updated_at", -1)],
            limit=limit,
            offset=offset,
        )
        return [ConversationInfo(**doc) for doc in docs]

    async def list_with_turn_status(
        self,
        job_store: JobStore | MongoJobStore,
        repo_id: str | None = None,
        *,
        worktree: str | None = None,
        include_archived: bool = False,
        updated_since: datetime | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationInfo]:
        """List conversations with last_turn_status populated.

        Fetches job statuses for the last turn of each conversation in a
        single batched query for efficiency.
        """
        convs = await self.list(
            repo_id=repo_id,
            worktree=worktree,
            include_archived=include_archived,
            updated_since=updated_since,
            sort=sort,
            limit=limit,
            offset=offset,
        )

        # Extract last job IDs (if any)
        job_ids = [c.turns[-1] for c in convs if c.turns]

        if not job_ids:
            return convs

        # Batch fetch job statuses
        jobs = await job_store.get_many(job_ids)
        job_status_map = {j.id: j.status for j in jobs}

        # Populate last_turn_status
        enriched = []
        for conv in convs:
            last_job_id = conv.turns[-1] if conv.turns else None
            last_status = job_status_map.get(last_job_id) if last_job_id else None
            enriched.append(conv.model_copy(update={"last_turn_status": last_status}))

        return enriched

    async def count(
        self,
        *,
        repo_id: str | None = None,
        worktree: str | None = None,
        include_archived: bool = False,
        updated_since: datetime | None = None,
    ) -> int:
        filter_dict = self._build_filter(
            repo_id=repo_id,
            worktree=worktree,
            include_archived=include_archived,
            updated_since=updated_since,
        )
        return await self._backend.count(
            "conversations", filter=filter_dict or None
        )

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
        title: str | None = None,
    ) -> None:
        """Update mutable fields. Only non-None values overwrite."""
        try:
            update: dict[str, object] = {"updated_at": datetime.now(timezone.utc)}
            if session_id is not None:
                update["session_id"] = session_id
            if summary is not None:
                update["summary"] = summary
            if title is not None:
                update["title"] = title

            await self._backend.update("conversations", conv_id, update)
            await self._notifications.notify(f"conversation:{conv_id}")
        except Exception as e:
            logger.error(f"Failed to patch conversation {conv_id}: {e}")
            raise

    async def archive(self, conv_id: str) -> bool:
        """Mark a conversation as archived. Returns False if not found.

        Soft delete: the record stays so historical jobs still resolve
        their conversation_id. Archived conversations are hidden from
        `list()` by default and reject new turns at the router level.
        """
        doc = await self._backend.get("conversations", conv_id)
        if doc is None:
            return False
        await self._backend.update(
            "conversations",
            conv_id,
            {"archived": True, "updated_at": datetime.now(timezone.utc)},
        )
        await self._notifications.notify(f"conversation:{conv_id}")
        return True
