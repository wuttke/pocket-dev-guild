"""CRUD endpoints for git worktrees of a configured repo."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..config import RepoRegistry
from ..deps import get_git, get_registry, get_repo
from ..schemas import (
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
    repo: Repo = Depends(get_repo),
    registry: RepoRegistry = Depends(get_registry),
    git: GitService = Depends(get_git),
) -> WorktreeCreated:
    target = registry.worktree_path(repo, body.name)
    try:
        await git.add_worktree(Path(repo.path), target, body.base_branch)
    except GitError as exc:
        raise HTTPException(400, str(exc))
    return WorktreeCreated(name=body.name, path=str(target))


@router.delete("/{name}", response_model=WorktreeRemoved, summary="Remove a worktree")
async def delete_worktree(
    name: str,
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
