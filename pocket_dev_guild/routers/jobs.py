"""Jobs resource: create augment runs, inspect them, stream logs via SSE."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typing import Annotated, get_args

from fastapi import APIRouter, Depends, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from ..config import RepoRegistry
from ..deps import get_conversations, get_registry, get_runner, get_store
from ..schemas import (
    IDENT_PATTERN,
    JobCreate,
    JobCreated,
    JobInfo,
    JobListResponse,
    JobLog,
    JobStatus,
)
from ..services.augment_runner import AugmentRunner
from ..services.conversation_orchestrator import run_conversation_turn
from ..services.conversation_store import ConversationStore
from ..services.job_store import JobStore
from ._pagination import DEFAULT_LIMIT, MAX_LIMIT, parse_sort

_JOB_SORT_FIELDS = {"created_at", "finished_at", "status"}
_JOB_STATUS_VALUES = set(get_args(JobStatus))

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def start_job(
    *,
    repo_id: str,
    worktree: str | None,
    prompt: str,
    conversation_id: str | None,
    registry: RepoRegistry,
    store: JobStore,
    runner: AugmentRunner,
    conversations: ConversationStore,
) -> JobCreated:
    """Validate inputs, persist the job, and schedule its background run.

    Shared between `POST /jobs` and `POST /conversations/{id}/turns`. When
    `conversation_id` is set, the job is bound to the conversation and the
    orchestrator handles session discovery + summary; otherwise it's a
    plain one-shot run.
    """
    repo = registry.get(repo_id)
    if repo is None:
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    if worktree is None:
        target = Path(repo.path)
    else:
        target = registry.worktree_path(repo, worktree)
    if not target.exists():
        label = worktree if worktree is not None else "<primary>"
        raise HTTPException(404, f"Worktree '{label}' not found at {target}")

    if conversation_id is not None:
        conv = await conversations.get(conversation_id)
        if conv is None:
            raise HTTPException(404, f"Conversation '{conversation_id}' not found")
        if conv.repo_id != repo_id or conv.worktree != worktree:
            raise HTTPException(
                409,
                "Job repo/worktree does not match the conversation",
            )
        if conversations.is_busy(conversation_id):
            raise HTTPException(
                409, "Conversation already has a turn in flight"
            )

    info = await store.create(
        repo_id, worktree, prompt, conversation_id=conversation_id
    )

    if conversation_id is not None:
        await conversations.append_turn(conversation_id, info.id)
        asyncio.create_task(
            run_conversation_turn(
                conversation_id=conversation_id,
                job_id=info.id,
                cwd=target,
                prompt=prompt,
                conversations=conversations,
                jobs=store,
                runner=runner,
            )
        )
    else:
        asyncio.create_task(runner.run(info.id, target, prompt))
    return JobCreated(job_id=info.id)


@router.post("", response_model=JobCreated, summary="Start an augment run")
async def create_job(
    body: JobCreate,
    registry: RepoRegistry = Depends(get_registry),
    store: JobStore = Depends(get_store),
    runner: AugmentRunner = Depends(get_runner),
    conversations: ConversationStore = Depends(get_conversations),
) -> JobCreated:
    return await start_job(
        repo_id=body.repo_id,
        worktree=body.worktree,
        prompt=body.prompt,
        conversation_id=body.conversation_id,
        registry=registry,
        store=store,
        runner=runner,
        conversations=conversations,
    )


@router.get(
    "",
    response_model=JobListResponse,
    summary="List jobs with filters, sort and pagination",
)
async def list_jobs(
    repo_id: Annotated[str | None, Query(pattern=IDENT_PATTERN)] = None,
    worktree: Annotated[str | None, Query(pattern=IDENT_PATTERN)] = None,
    status: str | None = None,
    conversation_id: Annotated[str | None, Query(min_length=1)] = None,
    sort: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    store: JobStore = Depends(get_store),
) -> JobListResponse:
    if status is not None and status not in _JOB_STATUS_VALUES:
        raise HTTPException(
            400,
            f"Invalid status '{status}'. Allowed: {sorted(_JOB_STATUS_VALUES)}",
        )
    sort_spec = parse_sort(
        sort, allowed=_JOB_SORT_FIELDS, default=[("created_at", -1)]
    )
    items = await store.list(
        repo_id=repo_id,
        worktree=worktree,
        status=status,
        conversation_id=conversation_id,
        sort=sort_spec,
        limit=limit,
        offset=offset,
    )
    total = await store.count(
        repo_id=repo_id,
        worktree=worktree,
        status=status,
        conversation_id=conversation_id,
    )
    return JobListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobInfo, summary="Job metadata")
async def get_job(job_id: str, store: JobStore = Depends(get_store)) -> JobInfo:
    info = await store.get(job_id)
    if info is None:
        raise HTTPException(404, "Job not found")
    return info


@router.delete("/{job_id}", response_model=JobInfo, summary="Cancel a job")
async def cancel_job(
    job_id: str,
    store: JobStore = Depends(get_store),
    runner: AugmentRunner = Depends(get_runner),
) -> JobInfo:
    info = await store.get(job_id)
    if info is None:
        raise HTTPException(404, "Job not found")
    if info.status in ("finished", "failed", "cancelled"):
        raise HTTPException(
            409, f"Job already terminal: status={info.status}"
        )
    # `runner.cancel` records the cancellation intent and SIGTERMs the
    # live subprocess (if any). For queued jobs there is no process yet,
    # so we also flip the store-side status here. If a process was
    # signalled, the runner's `run` finishes the transition to
    # `cancelled` once the subprocess exits.
    signalled = await runner.cancel(job_id)
    if not signalled:
        await store.set_status(job_id, "cancelled", returncode=None)
    updated = await store.get(job_id)
    return updated if updated is not None else info


@router.get("/{job_id}/log", response_model=JobLog, summary="Full log snapshot")
async def get_job_log(job_id: str, store: JobStore = Depends(get_store)) -> JobLog:
    snap = await store.snapshot(job_id)
    if snap is None:
        raise HTTPException(404, "Job not found")
    return snap


@router.get("/{job_id}/events", summary="SSE stream of log lines + status")
async def stream_job_events(
    job_id: str, store: JobStore = Depends(get_store)
) -> EventSourceResponse:
    if await store.get(job_id) is None:
        raise HTTPException(404, "Job not found")

    async def gen():
        position = 0
        while True:
            info = await store.get(job_id)
            if info is None:
                yield {"event": "error", "data": "Job not found"}
                return

            new_lines = await store.log_slice(job_id, position)
            for line in new_lines:
                yield {"event": "log", "data": line.model_dump_json()}
            position += len(new_lines)

            if info.status in ("finished", "failed", "cancelled"):
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {
                            "status": info.status,
                            "returncode": info.returncode,
                            "finished_at": (
                                info.finished_at.isoformat()
                                if info.finished_at is not None
                                else None
                            ),
                        }
                    ),
                }
                return

            await store.wait_for_update(job_id, timeout=5.0)

    return EventSourceResponse(gen())
