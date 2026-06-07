"""CRUD endpoints for git worktrees of a configured repo."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam

from ..config import RepoRegistry
from ..deps import get_git, get_registry, get_repo
from ..schemas import (
    IDENT_PATTERN,
    Repo,
    WorktreeCreate,
    WorktreeCreated,
    WorktreeInfo,
    WorktreeRemoved,
)
from ..services.git_service import GitError, GitService

router = APIRouter(prefix="/repos/{repo_id}/worktrees", tags=["worktrees"])


@router.get("", response_model=list[WorktreeInfo], summary="List worktrees")
async def list_worktrees(
    repo: Repo = Depends(get_repo),
    registry: RepoRegistry = Depends(get_registry),
    git: GitService = Depends(get_git),
) -> list[WorktreeInfo]:
    try:
        raw = await git.list_worktrees(Path(repo.path))
    except GitError as exc:
        raise HTTPException(500, str(exc))
    return registry.classify_worktrees(repo, raw)


@router.post("", response_model=WorktreeCreated, summary="Create a worktree")
async def create_worktree(
    body: WorktreeCreate,
    existing: bool = False,
    repo: Repo = Depends(get_repo),
    registry: RepoRegistry = Depends(get_registry),
    git: GitService = Depends(get_git),
) -> WorktreeCreated:
    # Worktree directory mirrors the branch, lower-cased with `/` and
    # `.` replaced by `_`. This both satisfies `IDENT_PATTERN` for use
    # in URL segments and makes `Feature/Foo` collide with `feature/foo`
    # on the filesystem, so we never end up with two case-only-distinct
    # worktrees.
    name = body.branch.lower().replace("/", "_").replace(".", "_")
    target = registry.worktree_path(repo, name)
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
    registry: RepoRegistry = Depends(get_registry),
    git: GitService = Depends(get_git),
) -> WorktreeRemoved:
    target = registry.worktree_path(repo, name)
    try:
        await git.remove_worktree(Path(repo.path), target)
    except GitError as exc:
        raise HTTPException(400, str(exc))
    return WorktreeRemoved(removed=name)
