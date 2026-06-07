"""In-memory job store with asyncio.Condition push semantics."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from ..schemas import JobInfo, JobLog, JobStatus, LogLine


@dataclass
class _JobRecord:
    info: JobInfo
    log: list[LogLine] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)


class JobStore:
    """Thread-unsafe by design — runs entirely on the asyncio event loop."""

    def __init__(self) -> None:
        self._jobs: dict[str, _JobRecord] = {}

    def create(self, repo_id: str, worktree: str | None, prompt: str) -> JobInfo:
        job_id = uuid.uuid4().hex
        info = JobInfo(
            id=job_id,
            repo_id=repo_id,
            worktree=worktree,
            prompt=prompt,
            status="queued",
            returncode=None,
        )
        self._jobs[job_id] = _JobRecord(info=info)
        return info

    def get(self, job_id: str) -> JobInfo | None:
        record = self._jobs.get(job_id)
        return record.info if record else None

    def snapshot(self, job_id: str) -> JobLog | None:
        record = self._jobs.get(job_id)
        if not record:
            return None
        return JobLog(**record.info.model_dump(), log=list(record.log))

    def log_slice(self, job_id: str, start: int) -> list[LogLine]:
        record = self._jobs.get(job_id)
        if not record:
            return []
        return record.log[start:]

    async def append_log(self, job_id: str, line: LogLine) -> None:
        record = self._jobs[job_id]
        record.log.append(line)
        async with record.condition:
            record.condition.notify_all()

    async def set_status(
        self, job_id: str, status: JobStatus, returncode: int | None = None
    ) -> None:
        record = self._jobs[job_id]
        record.info = record.info.model_copy(
            update={"status": status, "returncode": returncode}
        )
        async with record.condition:
            record.condition.notify_all()

    async def wait_for_update(self, job_id: str, timeout: float = 5.0) -> None:
        record = self._jobs.get(job_id)
        if not record:
            return
        async with record.condition:
            try:
                await asyncio.wait_for(record.condition.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
