"""Shared fixtures: tmp config, fake git, fake augment runner, test client."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Iterator

import pytest
import pytest_asyncio
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
    added: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)
    default_branch: str = "origin/main"

    async def list_worktrees(self, repo_path: Path) -> list[WorktreeInfo]:
        return list(self.worktrees.get(str(repo_path), []))

    async def default_remote_branch(self, repo_path: Path) -> str:
        return self.default_branch

    async def add_worktree(
        self,
        repo_path: Path,
        target: Path,
        *,
        branch: str,
        start_point: str | None = None,
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(exist_ok=True)
        self.added.append((str(repo_path), str(target), branch, start_point))
        self.worktrees.setdefault(str(repo_path), []).append(
            WorktreeInfo(path=str(target), branch=f"refs/heads/{branch}")
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

    Mirrors `SubprocessAugmentRunner` cancellation: `cancel(job_id)`
    records the intent and the script loop checks the flag between
    lines, landing on `cancelled` instead of `finished`/`failed`.
    """

    store: JobStore
    script: list[LogLine] = field(default_factory=list)
    returncode: int = 0
    delay: float = 0.0
    captured_request_id: str | None = None
    discovered_session_id: str | None = None
    summary_text: str | None = None
    calls: list[tuple[str, str | None]] = field(default_factory=list)
    cancelled: set[str] = field(default_factory=set)
    running: set[str] = field(default_factory=set)

    async def run(
        self,
        job_id: str,
        cwd: Path,
        prompt: str,
        *,
        session_id: str | None = None,
    ) -> None:
        self.calls.append(("run", session_id))
        if job_id in self.cancelled:
            self.cancelled.discard(job_id)
            await self.store.set_status(job_id, "cancelled", returncode=None)
            return
        await self.store.set_status(job_id, "running")
        self.running.add(job_id)
        try:
            if session_id is not None:
                await self.store.set_session_meta(job_id, session_id=session_id)
            for line in self.script:
                if self.delay:
                    await asyncio.sleep(self.delay)
                if job_id in self.cancelled:
                    self.cancelled.discard(job_id)
                    await self.store.set_status(
                        job_id, "cancelled", returncode=None
                    )
                    return
                await self.store.append_log(job_id, line)
            if self.captured_request_id is not None:
                await self.store.set_session_meta(
                    job_id, request_id=self.captured_request_id
                )
            if job_id in self.cancelled:
                self.cancelled.discard(job_id)
                await self.store.set_status(job_id, "cancelled", returncode=None)
                return
            await self.store.set_status(
                job_id,
                "finished" if self.returncode == 0 else "failed",
                returncode=self.returncode,
            )
        finally:
            self.running.discard(job_id)

    async def cancel(self, job_id: str) -> bool:
        self.calls.append(("cancel", job_id))
        self.cancelled.add(job_id)
        return job_id in self.running

    async def discover_session(self, request_id: str) -> str | None:
        self.calls.append(("discover_session", request_id))
        return self.discovered_session_id

    async def summarize(self, session_id: str, prompt: str = "") -> str | None:
        self.calls.append(("summarize", session_id))
        return self.summary_text


@pytest.fixture()
def tmp_config(tmp_path: Path) -> tuple[Path, Path]:
    """Create a temporary repo directory.

    Note: config.yaml is no longer used for repos, but kept for settings.
    """
    repo_path = tmp_path / "demo"
    repo_path.mkdir()
    # Initialize as git repo
    (repo_path / ".git").mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({}))
    return config, repo_path


@pytest.fixture()
def app_factory(tmp_config):
    config, repo_path = tmp_config

    def _build(*, runner: AugmentRunner | None = None, git: GitService | None = None):
        from pocket_dev_guild.services.repo_store import RepoStore

        # Create in-memory repo store and pre-populate with demo repo
        repo_store = RepoStore()
        app = create_app(
            Settings(config_path=config),
            git=git or FakeGit(),
            store=JobStore(),
            repo_store=repo_store,
            runner=runner,
            static_dir=None,
        )

        # Pre-populate repo store with demo repo
        # Insert directly into backend to avoid async complications in sync fixture
        from pocket_dev_guild.schemas import Repo
        demo_repo = Repo(id="demo", name="demo", path=str(repo_path), inactive=False)
        import asyncio
        asyncio.run(repo_store._backend.insert("repos", demo_repo.model_dump()))

        return app

    return _build


@pytest.fixture()
def client(app_factory) -> Iterator[TestClient]:
    app = app_factory()
    with TestClient(app) as c:
        yield c


# -- MongoDB fixtures (skip if mongo not reachable) -------------------------

MONGO_TEST_URL = os.environ.get(
    "POCKET_DEV_GUILD_MONGO_TEST_URL", "mongodb://localhost:27017"
)


@pytest_asyncio.fixture()
async def mongo_db():
    """Per-test motor database against a real local MongoDB.

    Skips the test if no MongoDB is reachable. Uses a unique db name per
    test and drops it on teardown.
    """
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError:
        pytest.skip("motor not installed")

    client = AsyncIOMotorClient(MONGO_TEST_URL, serverSelectionTimeoutMS=500)
    try:
        await client.admin.command("ping")
    except Exception as exc:
        client.close()
        pytest.skip(f"MongoDB at {MONGO_TEST_URL} not reachable: {exc}")

    db_name = f"pocket_dev_guild_test_{uuid.uuid4().hex[:12]}"
    db = client[db_name]
    try:
        yield db
    finally:
        await client.drop_database(db_name)
        client.close()
