"""In-memory job store."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..schemas import JobInfo, JobLog, JobStatus, LogLine
from .notification_hub import NotificationHub


@dataclass
class _JobRecord:
    info: JobInfo
    log: list[LogLine] = field(default_factory=list)


class JobStore:
    """Thread-unsafe by design — runs entirely on the asyncio event loop."""

    def __init__(self, notifications: NotificationHub | None = None) -> None:
        self._jobs: dict[str, _JobRecord] = {}
        self._notifications = notifications or NotificationHub()

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
        self._jobs[job_id] = _JobRecord(info=info)
        return info

    async def get(self, job_id: str) -> JobInfo | None:
        record = self._jobs.get(job_id)
        return record.info if record else None

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
        infos = [r.info for r in self._jobs.values()]
        if repo_id is not None:
            infos = [i for i in infos if i.repo_id == repo_id]
        if worktree is not None:
            infos = [i for i in infos if i.worktree == worktree]
        if status is not None:
            infos = [i for i in infos if i.status == status]
        if conversation_id is not None:
            infos = [i for i in infos if i.conversation_id == conversation_id]

        sort_spec = sort or [("created_at", -1)]
        for field, direction in reversed(sort_spec):
            infos.sort(
                key=lambda i: (getattr(i, field) is None, getattr(i, field, "")),
                reverse=(direction == -1),
            )
        return infos[offset : offset + limit]

    async def count(
        self,
        *,
        repo_id: str | None = None,
        worktree: str | None = None,
        status: JobStatus | None = None,
        conversation_id: str | None = None,
    ) -> int:
        n = 0
        for r in self._jobs.values():
            i = r.info
            if repo_id is not None and i.repo_id != repo_id:
                continue
            if worktree is not None and i.worktree != worktree:
                continue
            if status is not None and i.status != status:
                continue
            if conversation_id is not None and i.conversation_id != conversation_id:
                continue
            n += 1
        return n

    async def snapshot(self, job_id: str) -> JobLog | None:
        record = self._jobs.get(job_id)
        if not record:
            return None
        return JobLog(**record.info.model_dump(), log=list(record.log))

    async def log_slice(self, job_id: str, start: int) -> list[LogLine]:
        record = self._jobs.get(job_id)
        if not record:
            return []
        return record.log[start:]

    async def append_log(self, job_id: str, line: LogLine) -> None:
        record = self._jobs[job_id]
        record.log.append(line)
        await self._notifications.notify(f"job:{job_id}")

    async def set_status(
        self, job_id: str, status: JobStatus, returncode: int | None = None
    ) -> None:
        record = self._jobs[job_id]
        # cancelled is terminal alongside finished/failed — stamp finished_at
        # so the UI can render an end time and the SSE loop exits.
        update: dict[str, object] = {"status": status, "returncode": returncode}
        if status in ("finished", "failed", "cancelled"):
            update["finished_at"] = datetime.now(timezone.utc)
        record.info = record.info.model_copy(update=update)
        await self._notifications.notify(f"job:{job_id}")

    async def set_session_meta(
        self,
        job_id: str,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Patch agent-side ids onto the job. Only non-None values overwrite."""
        record = self._jobs.get(job_id)
        if record is None:
            return
        update: dict[str, object] = {}
        if request_id is not None:
            update["request_id"] = request_id
        if session_id is not None:
            update["session_id"] = session_id
        if not update:
            return
        record.info = record.info.model_copy(update=update)
        await self._notifications.notify(f"job:{job_id}")

    async def wait_for_update(self, job_id: str, timeout: float = 5.0) -> None:
        await self._notifications.wait(f"job:{job_id}", timeout=timeout)
