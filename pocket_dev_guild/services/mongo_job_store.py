"""MongoDB-backed job store.

Persists jobs and logs to MongoDB while maintaining the same interface as
the in-memory JobStore.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..schemas import JobInfo, JobLog, JobStatus, LogLine
from .notification_hub import NotificationHub
from .storage_backend import _attach_utc

logger = logging.getLogger(__name__)


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
        """Create MongoDB indexes for efficient queries. Idempotent - safe to call multiple times."""
        try:
            # create_index is idempotent in MongoDB
            await self._jobs.create_index("id", unique=True)
            await self._jobs.create_index("conversation_id")
            await self._jobs.create_index("created_at")
            await self._logs.create_index([("job_id", 1), ("seq", 1)], unique=True)
        except Exception as e:
            logger.error(f"Failed to ensure indexes for jobs/logs: {e}")

    async def create(
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
        # model_dump() keeps datetimes native so motor stores them as BSON
        # dates, consistent with set_status()/set_session_meta().
        await self._jobs.insert_one(info.model_dump())
        return info

    async def get(self, job_id: str) -> JobInfo | None:
        try:
            doc = await self._jobs.find_one({"id": job_id}, {"_id": 0})
            if not doc:
                return None
            return JobInfo(**_attach_utc(doc))
        except Exception as e:
            logger.error(f"Failed to get job {job_id}: {e}")
            return None

    async def snapshot(self, job_id: str) -> JobLog | None:
        try:
            job_doc = await self._jobs.find_one({"id": job_id}, {"_id": 0})
            if not job_doc:
                return None

            log_docs = await self._logs.find(
                {"job_id": job_id}, {"_id": 0, "job_id": 0, "seq": 0}
            ).sort("seq", 1).to_list(None)
            log = [LogLine(**doc) for doc in log_docs]

            return JobLog(**_attach_utc(job_doc), log=log)
        except Exception as e:
            logger.error(f"Failed to get snapshot for job {job_id}: {e}")
            return None

    async def log_slice(self, job_id: str, start: int) -> list[LogLine]:
        try:
            log_docs = await self._logs.find(
                {"job_id": job_id, "seq": {"$gte": start}},
                {"_id": 0, "job_id": 0, "seq": 0}
            ).sort("seq", 1).to_list(None)
            return [LogLine(**doc) for doc in log_docs]
        except Exception as e:
            logger.error(f"Failed to get log slice for job {job_id}: {e}")
            return []

    async def append_log(self, job_id: str, line: LogLine) -> None:
        try:
            # Get current log count for seq number
            seq = await self._logs.count_documents({"job_id": job_id})
            doc = {"job_id": job_id, "seq": seq, **line.model_dump()}
            await self._logs.insert_one(doc)
            await self._notifications.notify(f"job:{job_id}")
        except Exception as e:
            logger.error(f"Failed to append log to job {job_id}: {e}")
            # Don't raise - log appending is best-effort
            # Still notify in case other updates succeeded
            await self._notifications.notify(f"job:{job_id}")

    async def set_status(
        self, job_id: str, status: JobStatus, returncode: int | None = None
    ) -> None:
        try:
            update: dict[str, object] = {"status": status, "returncode": returncode}
            if status in ("finished", "failed"):
                update["finished_at"] = datetime.now(timezone.utc)

            await self._jobs.update_one(
                {"id": job_id},
                {"$set": update}
            )
            await self._notifications.notify(f"job:{job_id}")
        except Exception as e:
            logger.error(f"Failed to set status for job {job_id}: {e}")
            raise

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

        try:
            await self._jobs.update_one(
                {"id": job_id},
                {"$set": update}
            )
            await self._notifications.notify(f"job:{job_id}")
        except Exception as e:
            logger.error(f"Failed to set session meta for job {job_id}: {e}")
            raise

    async def wait_for_update(self, job_id: str, timeout: float = 5.0) -> None:
        await self._notifications.wait(f"job:{job_id}", timeout=timeout)
