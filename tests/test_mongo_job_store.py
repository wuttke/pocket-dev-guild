"""Integration tests for MongoJobStore.

Skipped if no MongoDB is reachable (see `mongo_db` fixture).
"""

from __future__ import annotations

import asyncio

import pytest

from pocket_dev_guild.schemas import LogLine
from pocket_dev_guild.services.mongo_job_store import MongoJobStore


@pytest.mark.asyncio
async def test_create_and_get(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    info = await store.create(repo_id="demo", worktree="feature-a", prompt="hi")

    persisted = await store.get(info.id)
    assert persisted is not None
    assert persisted.repo_id == "demo"
    assert persisted.worktree == "feature-a"
    assert persisted.prompt == "hi"
    assert persisted.status == "queued"
    assert persisted.returncode is None
    assert persisted.conversation_id is None


@pytest.mark.asyncio
async def test_create_with_conversation_id(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    info = await store.create(
        repo_id="demo", worktree=None, prompt="x", conversation_id="conv-1"
    )
    persisted = await store.get(info.id)
    assert persisted is not None
    assert persisted.conversation_id == "conv-1"
    assert persisted.worktree is None


@pytest.mark.asyncio
async def test_get_missing_returns_none(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    assert await store.get("does-not-exist") is None


@pytest.mark.asyncio
async def test_snapshot_includes_log(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    info = await store.create(repo_id="demo", worktree="wt", prompt="p")

    await store.append_log(info.id, LogLine(stream="stdout", line="hello\n"))
    await store.append_log(info.id, LogLine(stream="stderr", line="warn\n"))

    snap = await store.snapshot(info.id)
    assert snap is not None
    assert [l.line for l in snap.log] == ["hello\n", "warn\n"]
    assert [l.stream for l in snap.log] == ["stdout", "stderr"]
    assert snap.status == "queued"


@pytest.mark.asyncio
async def test_snapshot_missing_returns_none(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    assert await store.snapshot("nope") is None


@pytest.mark.asyncio
async def test_log_slice_starts_at_offset(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    info = await store.create(repo_id="demo", worktree="wt", prompt="p")
    for i in range(4):
        await store.append_log(info.id, LogLine(stream="stdout", line=f"{i}\n"))

    sliced = await store.log_slice(info.id, start=2)
    assert [l.line for l in sliced] == ["2\n", "3\n"]


@pytest.mark.asyncio
async def test_set_status_writes_finished_at(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    info = await store.create(repo_id="demo", worktree="wt", prompt="p")

    await store.set_status(info.id, "running")
    running = await store.get(info.id)
    assert running.status == "running"
    assert running.finished_at is None

    await store.set_status(info.id, "finished", returncode=0)
    finished = await store.get(info.id)
    assert finished.status == "finished"
    assert finished.returncode == 0
    assert finished.finished_at is not None
    # finished_at must be tz-aware (BSON roundtrip normalized to UTC)
    assert finished.finished_at.tzinfo is not None


@pytest.mark.asyncio
async def test_set_session_meta_only_overwrites_non_none(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    info = await store.create(repo_id="demo", worktree="wt", prompt="p")

    await store.set_session_meta(info.id, request_id="req-1", session_id="s-1")
    after = await store.get(info.id)
    assert after.request_id == "req-1"
    assert after.session_id == "s-1"

    # request_id None must not clobber the existing value
    await store.set_session_meta(info.id, session_id="s-2")
    after2 = await store.get(info.id)
    assert after2.request_id == "req-1"
    assert after2.session_id == "s-2"

    # All-None is a no-op (no error, no write)
    await store.set_session_meta(info.id)
    after3 = await store.get(info.id)
    assert after3.request_id == "req-1"
    assert after3.session_id == "s-2"


@pytest.mark.asyncio
async def test_fail_orphans_marks_inflight_jobs_failed(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    queued = await store.create(repo_id="demo", worktree=None, prompt="p1")
    running = await store.create(repo_id="demo", worktree=None, prompt="p2")
    await store.set_status(running.id, "running")
    done = await store.create(repo_id="demo", worktree=None, prompt="p3")
    await store.set_status(done.id, "finished", returncode=0)

    count = await store.fail_orphans()
    assert count == 2

    q = await store.get(queued.id)
    r = await store.get(running.id)
    d = await store.get(done.id)
    assert q.status == "failed" and q.returncode == -2 and q.finished_at is not None
    assert r.status == "failed" and r.returncode == -2 and r.finished_at is not None
    assert d.status == "finished" and d.returncode == 0

    # Second call must be a no-op.
    assert await store.fail_orphans() == 0

    snap = await store.snapshot(running.id)
    assert any("orphaned" in line.line for line in snap.log)


@pytest.mark.asyncio
async def test_wait_for_update_unblocks_on_append_log(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    info = await store.create(repo_id="demo", worktree="wt", prompt="p")

    async def producer():
        await asyncio.sleep(0.01)
        await store.append_log(info.id, LogLine(stream="stdout", line="x\n"))

    task = asyncio.create_task(producer())
    await store.wait_for_update(info.id, timeout=1.0)
    await task


@pytest.mark.asyncio
async def test_ensure_indexes_idempotent(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    await store._ensure_indexes()
    await store._ensure_indexes()  # second call must not raise


@pytest.mark.asyncio
async def test_list_and_count_with_filters(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    a1 = await store.create(repo_id="demo", worktree="wt-a", prompt="p")
    await asyncio.sleep(0.01)
    a2 = await store.create(repo_id="demo", worktree="wt-a", prompt="p")
    await asyncio.sleep(0.01)
    b1 = await store.create(repo_id="demo", worktree="wt-b", prompt="p")
    await store.set_status(a1.id, "running")
    await store.set_status(a2.id, "finished", returncode=0)

    # No filter, default sort (-created_at) → newest first.
    listed = await store.list()
    assert [j.id for j in listed] == [b1.id, a2.id, a1.id]
    assert await store.count() == 3

    # Filter by worktree.
    wt_a = await store.list(worktree="wt-a")
    assert {j.id for j in wt_a} == {a1.id, a2.id}
    assert await store.count(worktree="wt-a") == 2

    # Filter by status.
    fin = await store.list(status="finished")
    assert [j.id for j in fin] == [a2.id]
    assert await store.count(status="finished") == 1

    # Sort ascending.
    asc = await store.list(sort=[("created_at", 1)])
    assert [j.id for j in asc] == [a1.id, a2.id, b1.id]

    # Pagination: skip 1, take 1 under default sort.
    page = await store.list(limit=1, offset=1)
    assert [j.id for j in page] == [a2.id]


@pytest.mark.asyncio
async def test_list_filter_by_conversation_id(mongo_db) -> None:
    store = MongoJobStore(mongo_db)
    a = await store.create(
        repo_id="demo", worktree=None, prompt="p", conversation_id="conv-1"
    )
    await store.create(
        repo_id="demo", worktree=None, prompt="p", conversation_id="conv-2"
    )
    listed = await store.list(conversation_id="conv-1")
    assert [j.id for j in listed] == [a.id]
    assert await store.count(conversation_id="conv-1") == 1


@pytest.mark.asyncio
async def test_set_status_on_orphaned_running_job(mongo_db) -> None:
    """Test canceling an orphaned job (running status but no process).

    This simulates the bug scenario: a job is stuck in "running" state
    (e.g., after server restart killed the subprocess), and we try to
    cancel it via set_status("cancelled").
    """
    store = MongoJobStore(mongo_db)
    info = await store.create(repo_id="demo", worktree="wt", prompt="p")

    # Simulate the job reaching "running" state
    await store.set_status(info.id, "running")
    running = await store.get(info.id)
    assert running is not None
    assert running.status == "running"
    assert running.finished_at is None

    # Now cancel it (as the DELETE endpoint would do for an orphaned job)
    await store.set_status(info.id, "cancelled", returncode=None)

    # Verify the status was actually updated
    cancelled = await store.get(info.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.finished_at is not None
    assert cancelled.returncode is None
