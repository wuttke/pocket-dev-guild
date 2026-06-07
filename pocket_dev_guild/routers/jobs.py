"""Jobs resource: create augment runs, inspect them, stream logs via SSE."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..config import RepoRegistry
from ..deps import get_registry, get_runner, get_store
from ..schemas import JobCreate, JobCreated, JobInfo, JobLog
from ..services.augment_runner import AugmentRunner
from ..services.job_store import JobStore

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobCreated, summary="Start an augment run")
async def create_job(
    body: JobCreate,
    registry: RepoRegistry = Depends(get_registry),
    store: JobStore = Depends(get_store),
    runner: AugmentRunner = Depends(get_runner),
) -> JobCreated:
    repo = registry.get(body.repo_id)
    if repo is None:
        raise HTTPException(404, f"Repo '{body.repo_id}' not found")
    target = registry.worktree_path(repo, body.worktree)
    if not target.exists():
        raise HTTPException(404, f"Worktree '{body.worktree}' not found at {target}")

    info = store.create(body.repo_id, body.worktree, body.prompt)
    asyncio.create_task(runner.run(info.id, target, body.prompt))
    return JobCreated(job_id=info.id)


@router.get("/{job_id}", response_model=JobInfo, summary="Job metadata")
def get_job(job_id: str, store: JobStore = Depends(get_store)) -> JobInfo:
    info = store.get(job_id)
    if info is None:
        raise HTTPException(404, "Job not found")
    return info


@router.get("/{job_id}/log", response_model=JobLog, summary="Full log snapshot")
def get_job_log(job_id: str, store: JobStore = Depends(get_store)) -> JobLog:
    snap = store.snapshot(job_id)
    if snap is None:
        raise HTTPException(404, "Job not found")
    return snap


@router.get("/{job_id}/events", summary="SSE stream of log lines + status")
async def stream_job_events(
    job_id: str, store: JobStore = Depends(get_store)
) -> EventSourceResponse:
    if store.get(job_id) is None:
        raise HTTPException(404, "Job not found")

    async def gen():
        position = 0
        while True:
            info = store.get(job_id)
            if info is None:
                yield {"event": "error", "data": "Job not found"}
                return

            new_lines = store.log_slice(job_id, position)
            for line in new_lines:
                yield {"event": "log", "data": line.model_dump_json()}
            position += len(new_lines)

            if info.status in ("finished", "failed"):
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {"status": info.status, "returncode": info.returncode}
                    ),
                }
                return

            await store.wait_for_update(job_id, timeout=5.0)

    return EventSourceResponse(gen())
