"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient

from .config import RepoRegistry, Settings
from .routers import conversations, jobs, repos, worktrees
from .services.augment_runner import AugmentRunner, SubprocessAugmentRunner
from .services.conversation_store import ConversationStore
from .services.git_service import GitService
from .services.job_store import JobStore
from .services.mongo_job_store import MongoJobStore
from .services.notification_hub import NotificationHub
from .services.storage_backend import InMemoryBackend, MongoBackend


def create_app(
    settings: Settings | None = None,
    *,
    git: GitService | None = None,
    store: JobStore | None = None,
    conversations_store: ConversationStore | None = None,
    runner: AugmentRunner | None = None,
    static_dir: Path | str | None = "static",
) -> FastAPI:
    settings = settings or Settings()

    # Shared notification hub for real-time SSE updates
    notifications = NotificationHub()

    # Initialize storage backend and stores
    mongo_store = None
    mongo_backend = None

    if settings.mongodb_url:
        mongo_client = AsyncIOMotorClient(settings.mongodb_url)
        # Use database from URL, or default to "pocket_dev_guild"
        mongo_db = mongo_client.get_default_database() or mongo_client["pocket_dev_guild"]
        mongo_backend = MongoBackend(mongo_db)

    # Initialize job store (still has MongoDB-specific implementation)
    if store is None and mongo_backend:
        mongo_store = MongoJobStore(mongo_db, notifications=notifications)
        store = mongo_store
    else:
        store = store or JobStore(notifications=notifications)

    # Initialize conversation store with pluggable backend
    if conversations_store is None:
        backend = mongo_backend if mongo_backend else InMemoryBackend()
        conversations_store = ConversationStore(
            backend=backend, notifications=notifications
        )

    # Store mongo_backend reference for index creation
    if mongo_backend:
        mongo_conversations = conversations_store

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: ensure MongoDB indexes
        if mongo_store:
            await mongo_store._ensure_indexes()
        if mongo_backend:
            await conversations_store._ensure_indexes()
        yield
        # Shutdown: nothing to clean up for now

    app = FastAPI(
        title="Pocket Dev Guild",
        version="0.1.0",
        summary="Manage git worktrees and run augment from a small web UI.",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.registry = RepoRegistry(settings.config_path)
    app.state.git = git or GitService()
    app.state.store = store
    app.state.conversations = conversations_store
    app.state.runner = runner or SubprocessAugmentRunner(
        store=store,
        binary=settings.agent_binary,
        prompt_param=settings.agent_prompt_param,
    )

    app.include_router(repos.router)
    app.include_router(worktrees.router)
    app.include_router(jobs.router)
    app.include_router(conversations.router)

    if static_dir is not None:
        path = Path(static_dir)
        if path.is_dir():
            app.mount("/", StaticFiles(directory=str(path), html=True), name="static")

    return app
