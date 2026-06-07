"""MongoDB-backed conversation store.

Persists conversations to MongoDB while maintaining the same interface as
the in-memory ConversationStore. Uses asyncio.Condition for notifications.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..schemas import ConversationInfo


@dataclass
class _ConversationCondition:
    """In-memory notification state and busy flag for a conversation."""

    busy: bool = False
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)


class MongoConversationStore:
    """MongoDB conversation store. Thread-unsafe by design."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self._conversations = db["conversations"]
        # In-memory state for busy tracking and notifications
        self._conditions: dict[str, _ConversationCondition] = {}

    async def _ensure_indexes(self) -> None:
        """Create MongoDB indexes for efficient queries."""
        await self._conversations.create_index("id", unique=True)
        await self._conversations.create_index("repo_id")
        await self._conversations.create_index("updated_at")

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
        # Store in MongoDB (fire and forget for sync create)
        asyncio.create_task(self._conversations.insert_one(info.model_dump(mode="json")))
        # Create condition for notifications
        self._conditions[conv_id] = _ConversationCondition()
        return info

    async def get(self, conv_id: str) -> ConversationInfo | None:
        doc = await self._conversations.find_one({"id": conv_id}, {"_id": 0})
        if not doc:
            return None
        # Ensure condition exists for this conversation
        if conv_id not in self._conditions:
            self._conditions[conv_id] = _ConversationCondition()
        return ConversationInfo(**doc)

    async def list(self, repo_id: str | None = None) -> list[ConversationInfo]:
        query = {"repo_id": repo_id} if repo_id is not None else {}
        docs = await self._conversations.find(query, {"_id": 0}).sort("updated_at", -1).to_list(None)
        return [ConversationInfo(**doc) for doc in docs]

    def is_busy(self, conv_id: str) -> bool:
        cond = self._conditions.get(conv_id)
        return bool(cond and cond.busy)

    async def mark_busy(self, conv_id: str, busy: bool) -> None:
        cond = self._conditions.get(conv_id)
        if cond is None:
            # Create condition if it doesn't exist
            self._conditions[conv_id] = _ConversationCondition(busy=busy)
            cond = self._conditions[conv_id]
        else:
            cond.busy = busy
        
        async with cond.condition:
            cond.condition.notify_all()

    async def append_turn(self, conv_id: str, job_id: str) -> None:
        # Get current conversation
        doc = await self._conversations.find_one({"id": conv_id})
        if doc is None:
            return
        
        turns = doc.get("turns", []) + [job_id]
        update = {
            "turns": turns,
            "updated_at": datetime.now(timezone.utc),
        }
        
        await self._conversations.update_one(
            {"id": conv_id},
            {"$set": update}
        )
        
        # Notify subscribers
        cond = self._conditions.get(conv_id)
        if cond:
            async with cond.condition:
                cond.condition.notify_all()

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
        
        await self._conversations.update_one(
            {"id": conv_id},
            {"$set": update}
        )
        
        # Notify subscribers
        cond = self._conditions.get(conv_id)
        if cond:
            async with cond.condition:
                cond.condition.notify_all()
