"""MongoDB-backed job store.

Persists jobs and logs to MongoDB while maintaining the same interface as
the in-memory JobStore.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..schemas import JobInfo, JobLog, JobStatus, LogLine
from .notification_hub import NotificationHub


class MongoJobStore:
    """MongoDB job store. Thread-unsafe by design — runs on asyncio event loop."""

    def __init__(
        self, db: AsyncIOMotorDatabase, notifications: NotificationHub | None = None
    ) -> None:
        self._db = db
        self._jobs = db["jobs"]
        self._logs = db["job_logs"]
        self._notifications = notifications or NotificationHub()

    async def _ensure_indexes(self) -> None:
        """Create MongoDB indexes for efficient queries."""
        await self._jobs.create_index("id", unique=True)
        await self._jobs.create_index("conversation_id")
        await self._jobs.create_index("created_at")
        await self._logs.create_index([("job_id", 1), ("seq", 1)], unique=True)

    def create(
        self,
        repo_id: str,
        worktree: str | None,
        prompt: str,
        *,
        conversation_id: str | None = None,
    ) -> JobInfo:
        job_id = uuid.uuid4().hex
        info = JobInfo(
            id=job_id,
            repo_id=repo_id,
            worktree=worktree,
            prompt=prompt,
            status="queued",
            returncode=None,
            created_at=datetime.now(timezone.utc),
            conversation_id=conversation_id,
        )
        # Store in MongoDB (fire and forget for sync create)
        asyncio.create_task(self._jobs.insert_one(info.model_dump(mode="json")))
        return info

    async def get(self, job_id: str) -> JobInfo | None:
        doc = await self._jobs.find_one({"id": job_id}, {"_id": 0})
        if not doc:
            return None
        return JobInfo(**doc)

    async def snapshot(self, job_id: str) -> JobLog | None:
        job_doc = await self._jobs.find_one({"id": job_id}, {"_id": 0})
        if not job_doc:
            return None

        log_docs = await self._logs.find(
            {"job_id": job_id}, {"_id": 0, "job_id": 0, "seq": 0}
        ).sort("seq", 1).to_list(None)
        log = [LogLine(**doc) for doc in log_docs]

        return JobLog(**job_doc, log=log)

    async def log_slice(self, job_id: str, start: int) -> list[LogLine]:
        log_docs = await self._logs.find(
            {"job_id": job_id, "seq": {"$gte": start}},
            {"_id": 0, "job_id": 0, "seq": 0}
        ).sort("seq", 1).to_list(None)
        return [LogLine(**doc) for doc in log_docs]

    async def append_log(self, job_id: str, line: LogLine) -> None:
        # Get current log count for seq number
        seq = await self._logs.count_documents({"job_id": job_id})
        doc = {"job_id": job_id, "seq": seq, **line.model_dump()}
        await self._logs.insert_one(doc)
        await self._notifications.notify(f"job:{job_id}")

    async def set_status(
        self, job_id: str, status: JobStatus, returncode: int | None = None
    ) -> None:
        update: dict[str, object] = {"status": status, "returncode": returncode}
        if status in ("finished", "failed"):
            update["finished_at"] = datetime.now(timezone.utc)

        await self._jobs.update_one(
            {"id": job_id},
            {"$set": update}
        )
        await self._notifications.notify(f"job:{job_id}")

    async def set_session_meta(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Patch agent-side ids onto the job. Only non-None values overwrite."""
        update: dict[str, object] = {}
        if request_id is not None:
            update["request_id"] = request_id
        if session_id is not None:
            update["session_id"] = session_id
        if not update:
            return

        await self._jobs.update_one(
            {"id": job_id},
            {"$set": update}
        )
        await self._notifications.notify(f"job:{job_id}")

    async def wait_for_update(self, job_id: str, timeout: float = 5.0) -> None:
        await self._notifications.wait(f"job:{job_id}", timeout=timeout)
