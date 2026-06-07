"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import RepoRegistry, Settings
from .routers import jobs, repos, worktrees
from .services.augment_runner import AugmentRunner, SubprocessAugmentRunner
from .services.git_service import GitService
from .services.job_store import JobStore


def create_app(
    settings: Settings | None = None,
    *,
    git: GitService | None = None,
    store: JobStore | None = None,
    runner: AugmentRunner | None = None,
    static_dir: Path | str | None = "static",
) -> FastAPI:
    settings = settings or Settings()
    store = store or JobStore()

    app = FastAPI(
        title="Pocket Dev Guild",
        version="0.1.0",
        summary="Manage git worktrees and run augment from a small web UI.",
    )

    app.state.settings = settings
    app.state.registry = RepoRegistry(settings.config_path)
    app.state.git = git or GitService()
    app.state.store = store
    app.state.runner = runner or SubprocessAugmentRunner(store=store)

    app.include_router(repos.router)
    app.include_router(worktrees.router)
    app.include_router(jobs.router)

    if static_dir is not None:
        path = Path(static_dir)
        if path.is_dir():
            app.mount("/", StaticFiles(directory=str(path), html=True), name="static")

    return app
