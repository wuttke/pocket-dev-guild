"""Configuration loading: settings and the repository registry."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .schemas import Repo


class Settings:
    """App-level settings, kept tiny on purpose."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        if config_path is None:
            config_path = os.environ.get("POCKET_DEV_GUILD_CONFIG", "config.yaml")
        self.config_path = Path(config_path)


class RepoRegistry:
    """Reads the YAML repo list. Re-reads on every access so edits to
    `config.yaml` show up without restart, but stays trivial to test by
    pointing at a tmp_path file."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    @property
    def config_path(self) -> Path:
        return self._config_path

    def list(self) -> list[Repo]:
        if not self._config_path.exists():
            return []
        data = yaml.safe_load(self._config_path.read_text()) or {}
        return [Repo(**item) for item in data.get("repos", [])]

    def get(self, repo_id: str) -> Repo | None:
        for repo in self.list():
            if repo.id == repo_id:
                return repo
        return None

    def worktree_root(self, repo: Repo) -> Path:
        repo_path = Path(repo.path)
        return repo_path.parent / f"{repo_path.name}-worktrees"

    def worktree_path(self, repo: Repo, name: str) -> Path:
        return self.worktree_root(repo) / name
