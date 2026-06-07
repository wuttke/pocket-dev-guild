"""GET /repos — list configured repositories."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import RepoRegistry
from ..deps import get_registry
from ..schemas import Repo

router = APIRouter(prefix="/repos", tags=["repos"])


@router.get("", response_model=list[Repo], summary="List configured repos")
def list_repos(registry: RepoRegistry = Depends(get_registry)) -> list[Repo]:
    return registry.list()
