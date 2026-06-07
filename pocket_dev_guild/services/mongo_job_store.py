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

    def _build_filter(
        self,
        *,
        repo_id: str | None,
        worktree: str | None,
        status: JobStatus | None,
        conversation_id: str | None,
    ) -> dict[str, object]:
        f: dict[str, object] = {}
        if repo_id is not None:
            f["repo_id"] = repo_id
        if worktree is not None:
            f["worktree"] = worktree
        if status is not None:
            f["status"] = status
        if conversation_id is not None:
            f["conversation_id"] = conversation_id
        return f

    async def list(
        self,
        *,
        repo_id: str | None = None,
        worktree: str | None = None,
        status: JobStatus | None = None,
        conversation_id: str | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobInfo]:
        try:
            query = self._build_filter(
                repo_id=repo_id, worktree=worktree,
                status=status, conversation_id=conversation_id,
            )
            cursor = self._jobs.find(query, {"_id": 0})
            cursor = cursor.sort(sort or [("created_at", -1)])
            if offset:
                cursor = cursor.skip(offset)
            cursor = cursor.limit(limit)
            docs = await cursor.to_list(None)
            return [JobInfo(**_attach_utc(d)) for d in docs]
        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            return []

    async def count(
        self,
        *,
        repo_id: str | None = None,
        worktree: str | None = None,
        status: JobStatus | None = None,
        conversation_id: str | None = None,
    ) -> int:
        try:
            query = self._build_filter(
                repo_id=repo_id, worktree=worktree,
                status=status, conversation_id=conversation_id,
            )
            return await self._jobs.count_documents(query)
        except Exception as e:
            logger.error(f"Failed to count jobs: {e}")
            return 0

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
            if status in ("finished", "failed", "cancelled"):
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

    async def fail_orphans(self, *, reason: str = "server restart") -> int:
        """Mark any queued/running job in Mongo as failed.

        Called from app lifespan startup to clean up jobs whose
        subprocess died with the previous server instance. Appends a
        log line per orphaned job and flips status to failed with
        returncode=-2.

        Single-instance only. With multiple instances behind a load
        balancer this would clobber jobs still running on peers — see
        MULTIPLE_INSTANCES.md.
        """
        try:
            cursor = self._jobs.find(
                {"status": {"$in": ["queued", "running"]}}, {"_id": 0, "id": 1}
            )
            ids = [doc["id"] for doc in await cursor.to_list(None)]
        except Exception as e:
            logger.error(f"Failed to scan for orphaned jobs: {e}")
            return 0

        for jid in ids:
            await self.append_log(
                jid, LogLine(stream="stderr", line=f"-- {reason}, job orphaned --\n")
            )
            await self.set_status(jid, "failed", returncode=-2)
        return len(ids)
