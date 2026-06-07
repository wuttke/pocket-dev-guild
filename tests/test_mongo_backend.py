"""Integration tests for MongoBackend.

Run against a real local MongoDB (see `mongo_db` fixture). Tests are
skipped if no Mongo is reachable on `POCKET_DEV_GUILD_MONGO_TEST_URL`
(default `mongodb://localhost:27017`).
"""

from __future__ import annotations

import pytest

from pocket_dev_guild.services.storage_backend import MongoBackend


@pytest.mark.asyncio
async def test_insert_and_get(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    doc = {"id": "a1", "name": "alice", "n": 1}

    await backend.insert("things", doc)

    got = await backend.get("things", "a1")
    assert got is not None
    assert got["id"] == "a1"
    assert got["name"] == "alice"
    assert "_id" not in got  # backend strips mongo _id


@pytest.mark.asyncio
async def test_get_missing_returns_none(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    assert await backend.get("things", "nope") is None


@pytest.mark.asyncio
async def test_update_only_specified_fields(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    await backend.insert("things", {"id": "a1", "name": "alice", "n": 1})

    await backend.update("things", "a1", {"n": 42})

    got = await backend.get("things", "a1")
    assert got["name"] == "alice"
    assert got["n"] == 42


@pytest.mark.asyncio
async def test_update_missing_is_silent(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    # No error, just a no-op
    await backend.update("things", "nope", {"x": 1})
    assert await backend.get("things", "nope") is None


@pytest.mark.asyncio
async def test_find_with_filter_sort_limit(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    for i, name in enumerate(["a", "b", "c"]):
        await backend.insert("things", {"id": name, "group": "x", "n": i})
    await backend.insert("things", {"id": "d", "group": "y", "n": 99})

    rows = await backend.find(
        "things", filter={"group": "x"}, sort=[("n", -1)], limit=2
    )
    assert [r["id"] for r in rows] == ["c", "b"]


@pytest.mark.asyncio
async def test_find_empty_filter_returns_all(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    for i in range(3):
        await backend.insert("things", {"id": f"x{i}", "n": i})

    rows = await backend.find("things")
    assert {r["id"] for r in rows} == {"x0", "x1", "x2"}


@pytest.mark.asyncio
async def test_append_to_list_creates_and_extends(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    await backend.insert("things", {"id": "a1", "name": "alice"})

    await backend.append_to_list("things", "a1", "tags", {"t": "first"})
    await backend.append_to_list("things", "a1", "tags", {"t": "second"})

    got = await backend.get("things", "a1")
    assert got["tags"] == [{"t": "first"}, {"t": "second"}]


@pytest.mark.asyncio
async def test_append_to_list_missing_is_silent(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    # Updates with no matching doc are silent in Mongo; we just check
    # it doesn't raise.
    await backend.append_to_list("things", "nope", "tags", {"t": "x"})
    assert await backend.get("things", "nope") is None


@pytest.mark.asyncio
async def test_ensure_indexes_is_idempotent(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    specs = [
        {"fields": "id", "unique": True},
        {"fields": "group"},
    ]
    await backend.ensure_indexes("things", specs)
    # Second call must be a no-op (not raise).
    await backend.ensure_indexes("things", specs)

    index_info = await mongo_db["things"].index_information()
    index_keys = {
        tuple(spec["key"]) for spec in index_info.values()
    }
    assert (("id", 1),) in index_keys
    assert (("group", 1),) in index_keys


@pytest.mark.asyncio
async def test_find_with_offset_and_count(mongo_db) -> None:
    backend = MongoBackend(mongo_db)
    for i in range(5):
        await backend.insert("things", {"id": f"x{i}", "n": i})

    assert await backend.count("things") == 5
    assert await backend.count("things", filter={"n": {"$gte": 3}}) == 2

    page = await backend.find(
        "things", sort=[("n", 1)], limit=2, offset=2
    )
    assert [r["id"] for r in page] == ["x2", "x3"]


@pytest.mark.asyncio
async def test_find_filter_ne_excludes_field_or_missing(mongo_db) -> None:
    """`$ne: True` must include docs where the field is missing — that's
    how `ConversationStore` hides only explicit archives without
    backfilling legacy records."""
    backend = MongoBackend(mongo_db)
    await backend.insert("things", {"id": "a", "archived": True})
    await backend.insert("things", {"id": "b", "archived": False})
    await backend.insert("things", {"id": "c"})  # archived field missing

    rows = await backend.find("things", filter={"archived": {"$ne": True}})
    assert {r["id"] for r in rows} == {"b", "c"}
    assert await backend.count("things", filter={"archived": {"$ne": True}}) == 2


@pytest.mark.asyncio
async def test_ensure_indexes_unique_enforced(mongo_db) -> None:
    from pymongo.errors import DuplicateKeyError

    backend = MongoBackend(mongo_db)
    await backend.ensure_indexes("things", [{"fields": "id", "unique": True}])

    await backend.insert("things", {"id": "dup", "n": 1})
    with pytest.raises(DuplicateKeyError):
        await backend.insert("things", {"id": "dup", "n": 2})
