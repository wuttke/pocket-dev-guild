"""Repository store with pluggable storage backend.

Persists repository records to a database instead of config.yaml.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..schemas import Repo, WorktreeInfo
from .storage_backend import InMemoryBackend, StorageBackend

logger = logging.getLogger(__name__)


class RepoStore:
    """Repository store with pluggable backend."""

    def __init__(self, backend: StorageBackend | None = None) -> None:
        self._backend = backend or InMemoryBackend()

    async def _ensure_indexes(self) -> None:
        """Create backend indexes if supported (MongoDB only)."""
        from .storage_backend import MongoBackend

        if isinstance(self._backend, MongoBackend):
            await self._backend.ensure_indexes(
                "repos",
                [
                    {"fields": "id", "unique": True},
                    {"fields": "name"},
                ],
            )

    async def create(self, id: str, name: str, path: str) -> Repo:
        """Create a new repository record.

        Args:
            id: Repository ID (must match IDENT_PATTERN)
            name: Display name
            path: Absolute path to the repository on disk

        Returns:
            The created Repo object

        Raises:
            ValueError: If a repository with the same ID already exists
        """
        # Check if ID already exists (including inactive repos)
        existing = await self._backend.get("repos", id)
        if existing is not None:
            raise ValueError(f"Repository with id '{id}' already exists")

        repo = Repo(id=id, name=name, path=path, inactive=False)
        await self._backend.insert("repos", repo.model_dump())
        return repo

    async def get(self, repo_id: str) -> Repo | None:
        """Get a repository by ID."""
        doc = await self._backend.get("repos", repo_id)
        if doc is None:
            return None
        return Repo(**doc)

    async def list(
        self,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
        offset: int = 0,
        include_inactive: bool = False,
    ) -> list[Repo]:
        """List repositories with optional sorting and pagination.

        Args:
            sort: Sort specification (field, direction) tuples
            limit: Maximum number of results
            offset: Number of results to skip
            include_inactive: If False (default), only return active repos

        Returns:
            List of repository objects
        """
        filter_dict = None if include_inactive else {"inactive": {"$ne": True}}
        docs = await self._backend.find(
            "repos",
            filter=filter_dict,
            sort=sort or [("name", 1)],
            limit=limit,
            offset=offset,
        )
        return [Repo(**doc) for doc in docs]

    async def count(self) -> int:
        """Count total number of repositories."""
        return await self._backend.count("repos")

    async def update(self, repo_id: str, name: str | None = None, path: str | None = None) -> Repo | None:
        """Update a repository's name and/or path.

        Args:
            repo_id: Repository ID
            name: New name (optional)
            path: New path (optional)

        Returns:
            Updated Repo object or None if not found
        """
        doc = await self._backend.get("repos", repo_id)
        if doc is None:
            return None

        updates: dict[str, str] = {}
        if name is not None:
            updates["name"] = name
        if path is not None:
            updates["path"] = path

        if updates:
            await self._backend.update("repos", repo_id, updates)

        # Return updated repo
        updated_doc = await self._backend.get("repos", repo_id)
        return Repo(**updated_doc) if updated_doc else None

    async def mark_inactive(self, repo_id: str) -> Repo | None:
        """Mark a repository as inactive (soft delete).

        The repository record is preserved so existing jobs/conversations
        can still resolve their repo_id, but it's hidden from listings
        and rejects new operations.

        Args:
            repo_id: Repository ID to mark as inactive

        Returns:
            Updated Repo object or None if not found
        """
        doc = await self._backend.get("repos", repo_id)
        if doc is None:
            return None

        await self._backend.update("repos", repo_id, {"inactive": True})

        # Return updated repo
        updated_doc = await self._backend.get("repos", repo_id)
        return Repo(**updated_doc) if updated_doc else None

    def worktree_root(self, repo: Repo) -> Path:
        """Compute worktree root directory for a repository."""
        repo_path = Path(repo.path)
        return repo_path.parent / f"{repo_path.name}-worktrees"

    def worktree_path(self, repo: Repo, name: str) -> Path:
        """Compute path for a specific worktree."""
        return self.worktree_root(repo) / name


    def classify_worktrees(
        self, repo: Repo, items: list[WorktreeInfo]
    ) -> list[WorktreeInfo]:
        """Annotate worktrees with `name` / `is_primary` and drop any
        whose path does not match our convention."""
        repo_resolved = Path(repo.path).resolve(strict=False)
        wt_root = self.worktree_root(repo).resolve(strict=False)
        out: list[WorktreeInfo] = []
        for w in items:
            if not w.path:
                continue
            p = Path(w.path).resolve(strict=False)
            if p == repo_resolved:
                out.append(w.model_copy(update={"is_primary": True}))
                continue
            try:
                rel = p.relative_to(wt_root)
            except ValueError:
                continue
            if not rel.parts:
                continue
            out.append(w.model_copy(update={"name": rel.parts[0]}))
        return out