"""Repositories resource: list, create, and clone repositories."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_git, get_repo_store
from ..schemas import Repo, RepoClone, RepoCreate
from ..services.git_service import GitError, GitService
from ..services.repo_store import RepoStore

router = APIRouter(prefix="/repos", tags=["repos"])


@router.get("", response_model=list[Repo], summary="List all repositories")
async def list_repos(store: RepoStore = Depends(get_repo_store)) -> list[Repo]:
    """List all registered repositories."""
    return await store.list()


@router.post("", response_model=Repo, summary="Register an existing repository")
async def create_repo(
    body: RepoCreate,
    store: RepoStore = Depends(get_repo_store),
) -> Repo:
    """Register a repository that already exists on disk.

    The repository must already be a valid git repository at the specified path.
    This endpoint does not clone or initialize repositories - it only registers
    them in the database.

    Args:
        body: Repository details (id, name, path)

    Returns:
        The created repository record

    Raises:
        400: If the path does not exist or is not a git repository
        409: If a repository with the same ID already exists
    """
    repo_path = Path(body.path)

    # Verify path exists
    if not repo_path.exists():
        raise HTTPException(400, f"Path does not exist: {body.path}")

    # Verify it's a git repository
    if not (repo_path / ".git").exists():
        raise HTTPException(400, f"Path is not a git repository: {body.path}")

    try:
        repo = await store.create(id=body.id, name=body.name, path=body.path)
        return repo
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/clone", response_model=Repo, summary="Clone a repository from URL")
async def clone_repo(
    body: RepoClone,
    store: RepoStore = Depends(get_repo_store),
    git: GitService = Depends(get_git),
) -> Repo:
    """Clone a repository from a URL and register it.

    Clones the repository to {parent_path}/{name} where name is derived from
    the repository URL if not explicitly provided.

    Args:
        body: Clone details (url, parent_path, optional id and name)

    Returns:
        The created repository record

    Raises:
        400: If clone fails or parent path is invalid
        409: If a repository with the same ID already exists
    """
    parent_path = Path(body.parent_path)

    # Verify parent path exists
    if not parent_path.exists():
        raise HTTPException(400, f"Parent path does not exist: {body.parent_path}")

    if not parent_path.is_dir():
        raise HTTPException(400, f"Parent path is not a directory: {body.parent_path}")

    # Derive repository name from URL if not provided
    repo_name = body.name
    if repo_name is None:
        # Extract name from URL (e.g., "https://github.com/user/repo.git" -> "repo")
        url_parts = body.url.rstrip("/").split("/")
        repo_name = url_parts[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

    # Use provided ID or derive from name
    repo_id = body.id if body.id is not None else repo_name

    # Target path for clone
    target_path = parent_path / repo_name

    # Check if target already exists
    if target_path.exists():
        raise HTTPException(400, f"Target path already exists: {target_path}")

    # Perform the clone
    try:
        await git.clone(body.url, target_path)
    except GitError as exc:
        raise HTTPException(400, f"Clone failed: {exc}")

    # Register the cloned repository
    try:
        repo = await store.create(id=repo_id, name=repo_name, path=str(target_path))
        return repo
    except ValueError as e:
        # Clean up cloned repository if registration fails
        import shutil
        shutil.rmtree(target_path, ignore_errors=True)
        raise HTTPException(409, str(e))


@router.delete("/{repo_id}", status_code=204, summary="Deactivate a repository")
async def delete_repo(
    repo_id: str,
    store: RepoStore = Depends(get_repo_store),
) -> None:
    """Mark a repository as inactive (soft delete).

    The repository files on disk are NOT deleted - only the database record
    is marked as inactive. This hides the repository from listings and
    prevents new operations, but preserves the record so existing jobs and
    conversations can still resolve their repo_id.

    To fully remove a repository:
    1. Call this endpoint to deactivate it
    2. Manually delete the repository directory from disk if desired

    Args:
        repo_id: Repository ID to deactivate

    Raises:
        404: If repository not found
    """
    result = await store.mark_inactive(repo_id)
    if result is None:
        raise HTTPException(404, f"Repository '{repo_id}' not found")
