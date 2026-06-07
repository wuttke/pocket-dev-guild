"""Pydantic models for requests, responses and SSE payloads.

Centralised here so that every router can declare `response_model=` and
the generated OpenAPI document is fully typed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "finished", "failed"]
LogStream = Literal["stdout", "stderr"]


class Repo(BaseModel):
    id: str
    name: str
    path: str


class WorktreeInfo(BaseModel):
    """Subset of `git worktree list --porcelain` we expose.

    `name` is derived from the path when it sits under the conventional
    `{repo_parent}/{repo_name}-worktrees/` prefix, otherwise `None`.
    `is_primary` is true for the repo's main checkout.
    """

    name: str | None = None
    is_primary: bool = False
    path: str | None = None
    branch: str | None = None
    head: str | None = Field(default=None, alias="HEAD")
    bare: bool = False
    detached: bool = False

    model_config = {"populate_by_name": True}


class WorktreeCreate(BaseModel):
    name: str
    base_branch: str | None = None


class WorktreeCreated(BaseModel):
    name: str
    path: str


class WorktreeRemoved(BaseModel):
    removed: str


class JobCreate(BaseModel):
    repo_id: str
    worktree: str
    prompt: str


class JobCreated(BaseModel):
    job_id: str


class JobInfo(BaseModel):
    id: str
    repo_id: str
    worktree: str
    prompt: str
    status: JobStatus
    returncode: int | None = None


class LogLine(BaseModel):
    stream: LogStream
    line: str


class JobLog(JobInfo):
    log: list[LogLine] = Field(default_factory=list)


class JobStatusEvent(BaseModel):
    status: JobStatus
    returncode: int | None = None
