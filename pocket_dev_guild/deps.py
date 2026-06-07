"""FastAPI dependency providers.

Tests override these with `app.dependency_overrides[...] = ...`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request

from .schemas import IDENT_PATTERN, Repo
from .services.augment_runner import AugmentRunner
from .services.conversation_store import ConversationStore
from .services.git_service import GitService
from .services.job_store import JobStore
from .services.repo_store import RepoStore


def get_repo_store(request: Request) -> RepoStore:
    return request.app.state.repo_store


def get_git(request: Request) -> GitService:
    return request.app.state.git


def get_store(request: Request) -> JobStore:
    return request.app.state.store


def get_runner(request: Request) -> AugmentRunner:
    return request.app.state.runner


def get_conversations(request: Request) -> ConversationStore:
    return request.app.state.conversations


async def get_repo(
    repo_id: Annotated[str, Path(pattern=IDENT_PATTERN)],
    store: RepoStore = Depends(get_repo_store),
) -> Repo:
    repo = await store.get(repo_id)
    if repo is None or repo.inactive:
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    return repo
