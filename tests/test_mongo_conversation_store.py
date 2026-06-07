"""Integration tests for ConversationStore wired with MongoBackend.

Skipped if no MongoDB is reachable (see `mongo_db` fixture).
"""

from __future__ import annotations

import asyncio

import pytest

from pocket_dev_guild.services.conversation_store import ConversationStore
from pocket_dev_guild.services.storage_backend import MongoBackend


@pytest.mark.asyncio
async def test_create_persists_and_get_round_trip(mongo_db) -> None:
    store = ConversationStore(backend=MongoBackend(mongo_db))

    info = await store.create(
        repo_id="demo", worktree="wt", agent_id=None, title="t1"
    )
    assert info.id

    got = await store.get(info.id)
    assert got is not None
    assert got.id == info.id
    assert got.title == "t1"
    assert got.repo_id == "demo"
    assert got.worktree == "wt"
    assert got.turns == []
    assert got.session_id is None
    assert got.summary is None


@pytest.mark.asyncio
async def test_get_missing_returns_none(mongo_db) -> None:
    store = ConversationStore(backend=MongoBackend(mongo_db))
    assert await store.get("nope") is None


@pytest.mark.asyncio
async def test_list_sorts_by_updated_at_desc_and_filters(mongo_db) -> None:
    store = ConversationStore(backend=MongoBackend(mongo_db))

    a = await store.create(
        repo_id="demo", worktree=None, agent_id=None, title="a"
    )
    await asyncio.sleep(0.01)
    b = await store.create(
        repo_id="demo", worktree=None, agent_id=None, title="b"
    )
    await asyncio.sleep(0.01)
    other = await store.create(
        repo_id="other", worktree=None, agent_id=None, title="o"
    )

    # Newest first; cross-repo entries excluded when repo_id given
    listed = await store.list(repo_id="demo")
    assert [c.id for c in listed] == [b.id, a.id]

    # No filter → everything
    all_ = await store.list()
    assert {c.id for c in all_} == {a.id, b.id, other.id}


@pytest.mark.asyncio
async def test_append_turn_updates_list_and_timestamp(mongo_db) -> None:
    store = ConversationStore(backend=MongoBackend(mongo_db))
    info = await store.create(
        repo_id="demo", worktree=None, agent_id=None, title=None
    )
    pre = await store.get(info.id)
    await asyncio.sleep(0.01)

    await store.append_turn(info.id, "job-1")
    await store.append_turn(info.id, "job-2")

    got = await store.get(info.id)
    assert got.turns == ["job-1", "job-2"]
    assert got.updated_at > pre.updated_at
    # Both timestamps must be tz-aware after the BSON-roundtrip normalization.
    assert pre.updated_at.tzinfo is not None
    assert got.updated_at.tzinfo is not None


@pytest.mark.asyncio
async def test_append_turn_on_missing_is_silent(mongo_db) -> None:
    store = ConversationStore(backend=MongoBackend(mongo_db))
    # Must not raise.
    await store.append_turn("does-not-exist", "job-1")


@pytest.mark.asyncio
async def test_patch_session_id_and_summary(mongo_db) -> None:
    store = ConversationStore(backend=MongoBackend(mongo_db))
    info = await store.create(
        repo_id="demo", worktree=None, agent_id=None, title=None
    )

    await store.patch(info.id, session_id="sess-1")
    after = await store.get(info.id)
    assert after.session_id == "sess-1"
    assert after.summary is None

    await store.patch(info.id, summary="brief")
    after2 = await store.get(info.id)
    assert after2.session_id == "sess-1"  # not clobbered
    assert after2.summary == "brief"


@pytest.mark.asyncio
async def test_ensure_indexes_idempotent(mongo_db) -> None:
    store = ConversationStore(backend=MongoBackend(mongo_db))
    await store._ensure_indexes()
    await store._ensure_indexes()  # second call must not raise

    info = await mongo_db["conversations"].index_information()
    keys = {tuple(spec["key"]) for spec in info.values()}
    assert (("id", 1),) in keys
    assert (("repo_id", 1),) in keys
    assert (("updated_at", 1),) in keys


@pytest.mark.asyncio
async def test_state_returns_info_and_busy_flag(mongo_db) -> None:
    store = ConversationStore(backend=MongoBackend(mongo_db))
    info = await store.create(
        repo_id="demo", worktree=None, agent_id=None, title=None
    )

    state = await store.state(info.id)
    assert state is not None
    snap, busy = state
    assert snap.id == info.id
    assert busy is False

    await store.mark_busy(info.id, True)
    snap2, busy2 = await store.state(info.id)
    assert busy2 is True

    assert await store.state("nope") is None
