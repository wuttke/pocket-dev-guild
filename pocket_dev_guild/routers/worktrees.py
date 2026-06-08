"""CRUD endpoints for git worktrees of a configured repo."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam

from ..deps import get_conversations, get_git, get_repo, get_repo_store, get_store
from ..schemas import (
    IDENT_PATTERN,
    Repo,
    WorktreeCreate,
    WorktreeCreated,
    WorktreeInfo,
    WorktreeRemoved,
)
from ..services.conversation_store import ConversationStore
from ..services.git_service import GitError, GitService
from ..services.job_store import JobStore
from ..services.repo_store import RepoStore

router = APIRouter(prefix="/repos/{repo_id}/worktrees", tags=["worktrees"])


@router.get("", response_model=list[WorktreeInfo], summary="List worktrees")
async def list_worktrees(
    repo: Repo = Depends(get_repo),
    store: RepoStore = Depends(get_repo_store),
    git: GitService = Depends(get_git),
) -> list[WorktreeInfo]:
    try:
        raw = await git.list_worktrees(Path(repo.path))
    except GitError as exc:
        raise HTTPException(500, str(exc))
    return store.classify_worktrees(repo, raw)


@router.post("", response_model=WorktreeCreated, summary="Create a worktree")
async def create_worktree(
    body: WorktreeCreate,
    existing: bool = False,
    repo: Repo = Depends(get_repo),
    store: RepoStore = Depends(get_repo_store),
    git: GitService = Depends(get_git),
) -> WorktreeCreated:
    # Worktree directory mirrors the branch, lower-cased with `/` and
    # `.` replaced by `_`. This both satisfies `IDENT_PATTERN` for use
    # in URL segments and makes `Feature/Foo` collide with `feature/foo`
    # on the filesystem, so we never end up with two case-only-distinct
    # worktrees.
    name = body.branch.lower().replace("/", "_").replace(".", "_")
    target = store.worktree_path(repo, name)
    try:
        if existing:
            # Check out an existing branch (local or remote tracking).
            await git.add_worktree(
                Path(repo.path), target, branch=body.branch
            )
        else:
            # Create a fresh branch off the remote default tip.
            start_point = await git.default_remote_branch(Path(repo.path))
            await git.add_worktree(
                Path(repo.path),
                target,
                branch=body.branch,
                start_point=start_point,
            )
    except GitError as exc:
        raise HTTPException(400, str(exc))
    return WorktreeCreated(name=name, path=str(target))


@router.delete("/{name}", response_model=WorktreeRemoved, summary="Remove a worktree")
async def delete_worktree(
    name: Annotated[str, PathParam(pattern=IDENT_PATTERN)],
    repo: Repo = Depends(get_repo),
    store: RepoStore = Depends(get_repo_store),
    git: GitService = Depends(get_git),
    conversations: ConversationStore = Depends(get_conversations),
    jobs: JobStore = Depends(get_store),
) -> WorktreeRemoved:
    # Guard against silently orphaning bound state. Unarchived
    # conversations would survive as zombies (their session can't be
    # resumed because the cwd is gone); active jobs would die mid-write
    # to a directory we're about to delete.
    active_conversations = await conversations.count(
        repo_id=repo.id, worktree=name, include_archived=False
    )
    active_jobs = await jobs.count(
        repo_id=repo.id, worktree=name, status="running"
    ) + await jobs.count(
        repo_id=repo.id, worktree=name, status="queued"
    )
    if active_conversations or active_jobs:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "worktree_has_active_resources",
                "worktree": name,
                "conversations": active_conversations,
                "active_jobs": active_jobs,
                "hint": (
                    "Archive the conversations and wait for/cancel "
                    "active jobs before removing this worktree."
                ),
            },
        )

    target = store.worktree_path(repo, name)
    try:
        await git.remove_worktree(Path(repo.path), target)
    except GitError as exc:
        raise HTTPException(400, str(exc))
    return WorktreeRemoved(removed=name)
