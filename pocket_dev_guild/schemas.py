"""Pydantic models for requests, responses and SSE payloads.

Centralised here so that every router can declare `response_model=` and
the generated OpenAPI document is fully typed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "finished", "failed", "cancelled"]
LogStream = Literal["stdout", "stderr"]

# Repo IDs and worktree names flow into filesystem paths and URL segments.
# Restrict them to a conservative subset to rule out traversal, separators,
# whitespace and shell metacharacters.
IDENT_PATTERN = r"^[A-Za-z0-9_-]+$"


class Repo(BaseModel):
    id: str = Field(pattern=IDENT_PATTERN)
    name: str
    path: str
    # Inactive repos are hidden from listings and reject operations.
    # The record is preserved so existing jobs/conversations can still
    # resolve their repo_id, but the repo is effectively soft-deleted.
    inactive: bool = False


class RepoCreate(BaseModel):
    """Request model for creating/registering an existing repository."""
    id: str = Field(pattern=IDENT_PATTERN)
    name: str
    path: str


class RepoClone(BaseModel):
    """Request model for cloning a repository from a URL."""
    url: str
    parent_path: str
    id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    name: str | None = None


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


# Branch names follow a `kind/slug[/slug...]` convention. The leading
# segment is letters only (e.g. `feature`, `Hotfix`); slug segments
# additionally allow digits, dashes and dots (e.g. `release/2.5.x`).
# Worktree directory names are derived from this by lowercasing and
# replacing `/` + `.` with `_`, which yields a string that satisfies
# `IDENT_PATTERN` without further validation.
BRANCH_PATTERN = r"^[A-Za-z]+(/[A-Za-z0-9.-]+)+$"


class WorktreeCreate(BaseModel):
    branch: str = Field(pattern=BRANCH_PATTERN)


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


class JobListResponse(BaseModel):
    """Paginated job listing.

    `total` is the count matching the filter, independent of `limit`/
    `offset` — clients use it to render page indicators without an extra
    round-trip.
    """

    items: list[JobInfo]
    total: int
    limit: int
    offset: int


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
    # Status of the most recent turn (last job in turns array). None if
    # turns is empty. Populated by list endpoint for efficient status
    # display in the UI; optional for backwards compatibility with single get.
    last_turn_status: JobStatus | None = None
    # Archived conversations are hidden from the default list and reject
    # new turns. The record is preserved (no physical delete) so existing
    # job rows still resolve their conversation_id.
    archived: bool = False


class ConversationListResponse(BaseModel):
    """Paginated conversation listing. See `JobListResponse` for the contract."""

    items: list[ConversationInfo]
    total: int
    limit: int
    offset: int
