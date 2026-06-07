"""Shared fixtures: tmp config, fake git, fake augment runner, test client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pytest
import yaml
from fastapi.testclient import TestClient

from pocket_dev_guild import create_app
from pocket_dev_guild.config import Settings
from pocket_dev_guild.schemas import LogLine, WorktreeInfo
from pocket_dev_guild.services.augment_runner import AugmentRunner
from pocket_dev_guild.services.git_service import GitService
from pocket_dev_guild.services.job_store import JobStore


@dataclass
class FakeGit(GitService):
    """In-memory git stand-in. Tracks calls and serves canned data."""

    worktrees: dict[str, list[WorktreeInfo]] = field(default_factory=dict)
    added: list[tuple[str, str, str | None]] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)

    async def list_worktrees(self, repo_path: Path) -> list[WorktreeInfo]:
        return list(self.worktrees.get(str(repo_path), []))

    async def add_worktree(
        self, repo_path: Path, target: Path, base_branch: str | None = None
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(exist_ok=True)
        self.added.append((str(repo_path), str(target), base_branch))
        self.worktrees.setdefault(str(repo_path), []).append(
            WorktreeInfo(path=str(target), branch=base_branch)
        )

    async def remove_worktree(self, repo_path: Path, target: Path) -> None:
        self.removed.append((str(repo_path), str(target)))


@dataclass
class FakeRunner:
    """Replays a scripted sequence of log lines + exit code into JobStore.

    Also satisfies the conversation-aware parts of the runner protocol so
    tests can exercise orchestration: `request_id` is patched onto the
    job during `run` (to mimic the real runner capturing it from
    stdout), and `discover_session`/`summarize` return canned values.
    """

    store: JobStore
    script: list[LogLine] = field(default_factory=list)
    returncode: int = 0
    delay: float = 0.0
    captured_request_id: str | None = None
    discovered_session_id: str | None = None
    summary_text: str | None = None
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    async def run(
        self,
        job_id: str,
        cwd: Path,
        prompt: str,
        *,
        session_id: str | None = None,
    ) -> None:
        self.calls.append(("run", session_id))
        await self.store.set_status(job_id, "running")
        if session_id is not None:
            await self.store.set_session_meta(job_id, session_id=session_id)
        for line in self.script:
            if self.delay:
                await asyncio.sleep(self.delay)
            await self.store.append_log(job_id, line)
        if self.captured_request_id is not None:
            await self.store.set_session_meta(
                job_id, request_id=self.captured_request_id
            )
        await self.store.set_status(
            job_id,
            "finished" if self.returncode == 0 else "failed",
            returncode=self.returncode,
        )

    async def discover_session(self, request_id: str) -> str | None:
        self.calls.append(("discover_session", request_id))
        return self.discovered_session_id

    async def summarize(self, session_id: str, prompt: str = "") -> str | None:
        self.calls.append(("summarize", session_id))
        return self.summary_text


@pytest.fixture()
def tmp_config(tmp_path: Path) -> tuple[Path, Path]:
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"repos": [{"id": "demo", "name": "demo", "path": str(repo_path)}]}
        )
    )
    return config, repo_path


@pytest.fixture()
def app_factory(tmp_config):
    config, _repo_path = tmp_config

    def _build(*, runner: AugmentRunner | None = None, git: GitService | None = None):
        return create_app(
            Settings(config_path=config),
            git=git or FakeGit(),
            store=JobStore(),
            runner=runner,
            static_dir=None,
        )

    return _build


@pytest.fixture()
def client(app_factory) -> Iterator[TestClient]:
    app = app_factory()
    with TestClient(app) as c:
        yield c
