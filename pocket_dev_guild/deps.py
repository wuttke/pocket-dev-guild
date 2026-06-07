"""FastAPI dependency providers.

Tests override these with `app.dependency_overrides[...] = ...`.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from .config import RepoRegistry
from .schemas import Repo
from .services.augment_runner import AugmentRunner
from .services.git_service import GitService
from .services.job_store import JobStore


def get_registry(request: Request) -> RepoRegistry:
    return request.app.state.registry


def get_git(request: Request) -> GitService:
    return request.app.state.git


def get_store(request: Request) -> JobStore:
    return request.app.state.store


def get_runner(request: Request) -> AugmentRunner:
    return request.app.state.runner


def get_repo(
    repo_id: str, registry: RepoRegistry = Depends(get_registry)
) -> Repo:
    repo = registry.get(repo_id)
    if repo is None:
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    return repo
