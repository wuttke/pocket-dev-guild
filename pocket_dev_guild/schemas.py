"""Pydantic models for requests, responses and SSE payloads.

Centralised here so that every router can declare `response_model=` and
the generated OpenAPI document is fully typed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "finished", "failed"]
LogStream = Literal["stdout", "stderr"]

# Repo IDs and worktree names flow into filesystem paths and URL segments.
# Restrict them to a conservative subset to rule out traversal, separators,
# whitespace and shell metacharacters.
IDENT_PATTERN = r"^[A-Za-z0-9_-]+$"


class Repo(BaseModel):
    id: str = Field(pattern=IDENT_PATTERN)
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
    name: str = Field(pattern=IDENT_PATTERN)
    base_branch: str | None = None


class WorktreeCreated(BaseModel):
    name: str
    path: str


class WorktreeRemoved(BaseModel):
    removed: str


class JobCreate(BaseModel):
    repo_id: str = Field(pattern=IDENT_PATTERN)
    worktree: str | None = Field(default=None, pattern=IDENT_PATTERN)
    prompt: str
    conversation_id: str | None = None


class JobCreated(BaseModel):
    job_id: str


class JobInfo(BaseModel):
    id: str
    repo_id: str
    worktree: str | None = None
    prompt: str
    status: JobStatus
    returncode: int | None = None
    created_at: datetime
    finished_at: datetime | None = None
    conversation_id: str | None = None
    # Populated by the runner while streaming `--print` output. `request_id`
    # is the per-turn id auggie prints to stdout; `session_id` is the
    # agent-side conversation id (only set for conversation-bound jobs).
    request_id: str | None = None
    session_id: str | None = None


class LogLine(BaseModel):
    stream: LogStream
    line: str


class JobLog(JobInfo):
    log: list[LogLine] = Field(default_factory=list)


class JobStatusEvent(BaseModel):
    status: JobStatus
    returncode: int | None = None
    finished_at: datetime | None = None


class ConversationCreate(BaseModel):
    repo_id: str = Field(pattern=IDENT_PATTERN)
    worktree: str | None = Field(default=None, pattern=IDENT_PATTERN)
    agent_id: str | None = None
    title: str | None = None


class ConversationTurnCreate(BaseModel):
    prompt: str


class ConversationInfo(BaseModel):
    id: str
    repo_id: str
    worktree: str | None = None
    agent_id: str | None = None
    title: str | None = None
    session_id: str | None = None
    summary: str | None = None
    created_at: datetime
    updated_at: datetime
    # job ids in turn order; in-flight turn (if any) is the last entry.
    turns: list[str] = Field(default_factory=list)
