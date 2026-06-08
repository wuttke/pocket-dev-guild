"""Conversations: CRUD, turn binding, session discovery and summary."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from pocket_dev_guild.routers.conversations import _conversation_event_stream
from pocket_dev_guild.schemas import LogLine
from pocket_dev_guild.services.conversation_store import ConversationStore
from tests.conftest import FakeRunner


def _ensure_worktree(tmp_config, name: str = "feature-a"):
    _, repo_path = tmp_config
    wt = repo_path.parent / "demo-worktrees" / name
    wt.mkdir(parents=True, exist_ok=True)
    return wt


def _make_app(app_factory, runner_kwargs):
    app = app_factory()
    runner = FakeRunner(store=app.state.store, **runner_kwargs)
    app.state.runner = runner
    return app, runner


def _wait_for(client: TestClient, conv_id: str, predicate, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = client.get(f"/api/conversations/{conv_id}").json()
        if predicate(info):
            return info
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting on conversation {conv_id}: {info}")


def test_conversation_crud(client: TestClient, tmp_config) -> None:
    _ensure_worktree(tmp_config)

    create = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "t1"},
    )
    assert create.status_code == 200, create.text
    info = create.json()
    assert info["repo_id"] == "demo"
    assert info["worktree"] == "feature-a"
    assert info["title"] == "t1"
    assert info["session_id"] is None
    assert info["turns"] == []

    listing = client.get("/api/conversations").json()
    assert [c["id"] for c in listing["items"]] == [info["id"]]
    assert listing["total"] == 1
    assert listing["limit"] == 50
    assert listing["offset"] == 0

    detail = client.get(f"/api/conversations/{info['id']}").json()
    assert detail["id"] == info["id"]

    assert client.get("/api/conversations/does-not-exist").status_code == 404


def test_conversation_rejects_unknown_repo_or_worktree(client: TestClient) -> None:
    assert (
        client.post("/api/conversations", json={"repo_id": "demo", "worktree": "nope"}).status_code
        == 404
    )
    assert client.post("/api/conversations", json={"repo_id": "missing"}).status_code == 404


def test_conversation_turn_discovers_session_and_summary(
    app_factory, tmp_config
) -> None:
    _ensure_worktree(tmp_config)
    app, runner = _make_app(
        app_factory,
        dict(
            script=[LogLine(stream="stdout", line="ok\n")],
            captured_request_id="11111111-2222-3333-4444-555555555555",
            discovered_session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            summary_text="Did the thing.",
        ),
    )
    with TestClient(app) as client:
        conv = client.post(
            "/api/conversations",
            json={"repo_id": "demo", "worktree": "feature-a"},
        ).json()
        turn1 = client.post(
            f"/api/conversations/{conv['id']}/turns", json={"prompt": "p1"}
        )
        assert turn1.status_code == 200, turn1.text
        job1_id = turn1.json()["job_id"]

        info = _wait_for(
            client,
            conv["id"],
            lambda c: c["session_id"] is not None and c["summary"] is not None,
        )
        assert info["session_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert info["summary"] == "Did the thing."
        assert info["turns"] == [job1_id]

        # Second turn resumes the discovered session.
        runner.calls.clear()
        turn2 = client.post(
            f"/api/conversations/{conv['id']}/turns", json={"prompt": "p2"}
        )
        assert turn2.status_code == 200, turn2.text
        _wait_for(
            client,
            conv["id"],
            lambda c: len(c["turns"]) == 2 and c["session_id"] is not None,
        )
        run_calls = [c for c in runner.calls if c[0] == "run"]
        assert run_calls == [("run", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")]
        assert not any(c[0] == "discover_session" for c in runner.calls)


def test_conversation_turn_rejects_parallel(app_factory, tmp_config) -> None:
    _ensure_worktree(tmp_config)
    app, _runner = _make_app(
        app_factory,
        dict(
            script=[LogLine(stream="stdout", line="ok\n")],
            captured_request_id="11111111-2222-3333-4444-555555555555",
            discovered_session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            summary_text="x",
            delay=0.05,
        ),
    )
    with TestClient(app) as client:
        conv = client.post(
            "/api/conversations",
            json={"repo_id": "demo", "worktree": "feature-a"},
        ).json()
        first = client.post(
            f"/api/conversations/{conv['id']}/turns", json={"prompt": "p1"}
        )
        assert first.status_code == 200, first.text
        second = client.post(
            f"/api/conversations/{conv['id']}/turns", json={"prompt": "p2"}
        )
        assert second.status_code == 409, second.text


def test_jobs_endpoint_accepts_conversation_id(app_factory, tmp_config) -> None:
    _ensure_worktree(tmp_config)
    app, _runner = _make_app(
        app_factory,
        dict(
            script=[LogLine(stream="stdout", line="ok\n")],
            captured_request_id="11111111-2222-3333-4444-555555555555",
            discovered_session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            summary_text="x",
        ),
    )
    with TestClient(app) as client:
        conv = client.post(
            "/api/conversations",
            json={"repo_id": "demo", "worktree": "feature-a"},
        ).json()
        # Mismatched worktree → 409.
        bad = client.post(
            "/api/jobs",
            json={
                "repo_id": "demo",
                "worktree": None,
                "prompt": "p",
                "conversation_id": conv["id"],
            },
        )
        assert bad.status_code == 409, bad.text
        # Correct binding works and the job carries conversation_id.
        ok = client.post(
            "/api/jobs",
            json={
                "repo_id": "demo",
                "worktree": "feature-a",
                "prompt": "p",
                "conversation_id": conv["id"],
            },
        )
        assert ok.status_code == 200, ok.text
        job_id = ok.json()["job_id"]
        _wait_for(
            client,
            conv["id"],
            lambda c: c["turns"] == [job_id] and c["session_id"] is not None,
        )
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["conversation_id"] == conv["id"]
        assert job["session_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert job["request_id"] == "11111111-2222-3333-4444-555555555555"



async def _collect_events(
    conversations: ConversationStore,
    conv_id: str,
    *,
    stop: callable,
    timeout: float = 3.0,
):
    """Drive `_conversation_event_stream` until `stop(events)` is true.

    Bypasses `TestClient` because `httpx.ASGITransport` buffers the entire
    response before returning, which deadlocks an infinite SSE generator.
    """
    events: list[tuple[str, dict]] = []
    agen = _conversation_event_stream(conversations, conv_id)
    deadline = asyncio.get_event_loop().time() + timeout
    try:
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise AssertionError(f"SSE timeout; got {events}")
            msg = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
            events.append((msg["event"], json.loads(msg["data"])))
            if stop(events):
                return events
    finally:
        await agen.aclose()


@pytest.mark.asyncio
async def test_conversation_events_initial_snapshot() -> None:
    """The stream emits a `snapshot` event on connect carrying the
    current `ConversationInfo` plus a `busy` flag."""
    store = ConversationStore()
    info = await store.create(
        repo_id="demo", worktree="feature-a", agent_id=None, title="t"
    )

    events = await _collect_events(store, info.id, stop=lambda evs: len(evs) >= 1)

    assert events[0][0] == "snapshot"
    payload = events[0][1]
    assert payload["busy"] is False
    assert payload["conversation"]["id"] == info.id
    assert payload["conversation"]["title"] == "t"
    assert payload["conversation"]["summary"] is None


@pytest.mark.asyncio
async def test_conversation_events_full_flow() -> None:
    """A busy toggle + summary patch produces snapshot + update events
    in order, with the final update carrying busy=False + summary."""
    store = ConversationStore()
    info = await store.create(
        repo_id="demo", worktree="feature-a", agent_id=None, title=None
    )

    async def mutate() -> None:
        await asyncio.sleep(0.01)
        await store.mark_busy(info.id, True)
        await asyncio.sleep(0.01)
        await store.patch(
            info.id, session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        await asyncio.sleep(0.01)
        await store.patch(info.id, summary="Did the thing.")
        await asyncio.sleep(0.01)
        await store.mark_busy(info.id, False)

    mutator = asyncio.create_task(mutate())
    try:
        events = await _collect_events(
            store,
            info.id,
            stop=lambda evs: (
                evs[-1][1]["conversation"]["summary"] is not None
                and not evs[-1][1]["busy"]
            ),
        )
    finally:
        await mutator

    assert events[0][0] == "snapshot"
    updates = [(ev, p) for ev, p in events[1:] if ev == "update"]
    assert updates, "expected at least one update event"
    assert any(p["busy"] for _, p in updates)
    last = updates[-1][1]
    assert last["conversation"]["summary"] == "Did the thing."
    assert last["conversation"]["session_id"] == (
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    assert last["busy"] is False


def test_conversation_events_404_for_missing(client: TestClient) -> None:
    resp = client.get("/api/conversations/does-not-exist/events")
    assert resp.status_code == 404


def test_archive_hides_conversation_and_blocks_turns(
    client: TestClient, tmp_config
) -> None:
    _ensure_worktree(tmp_config)
    a = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "keep"},
    ).json()
    b = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "gone"},
    ).json()

    # Archive `b`.
    resp = client.delete(f"/api/conversations/{b['id']}")
    assert resp.status_code == 204, resp.text

    # Default list excludes archived; include_archived returns both.
    visible = client.get("/api/conversations").json()
    assert [c["id"] for c in visible["items"]] == [a["id"]]
    assert visible["total"] == 1
    all_ = client.get("/api/conversations?include_archived=true").json()
    assert {c["id"] for c in all_["items"]} == {a["id"], b["id"]}
    assert all_["total"] == 2
    archived_doc = next(c for c in all_["items"] if c["id"] == b["id"])
    assert archived_doc["archived"] is True

    # GET still works (job rows may still reference it).
    assert client.get(f"/api/conversations/{b['id']}").status_code == 200

    # New turns are rejected.
    turn = client.post(
        f"/api/conversations/{b['id']}/turns", json={"prompt": "p"}
    )
    assert turn.status_code == 409, turn.text

    # Archiving a missing conversation is a 404.
    assert client.delete("/api/conversations/does-not-exist").status_code == 404


def test_list_conversations_filter_sort_paginate(
    client: TestClient, tmp_config
) -> None:
    _ensure_worktree(tmp_config, "feature-a")
    _ensure_worktree(tmp_config, "feature-b")

    # Create five conversations, alternating worktrees. Insertion order
    # determines created_at/updated_at because nothing else mutates them.
    created: list[dict] = []
    for i in range(5):
        wt = "feature-a" if i % 2 == 0 else "feature-b"
        c = client.post(
            "/api/conversations",
            json={"repo_id": "demo", "worktree": wt, "title": f"c{i}"},
        ).json()
        created.append(c)

    # Default sort is `-updated_at` → newest first.
    body = client.get("/api/conversations").json()
    assert body["total"] == 5
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert [c["id"] for c in body["items"]] == [
        c["id"] for c in reversed(created)
    ]

    # Filter by worktree.
    feat_a = client.get("/api/conversations?worktree=feature-a").json()
    assert feat_a["total"] == 3
    assert {c["worktree"] for c in feat_a["items"]} == {"feature-a"}

    # Combined filter + ascending sort.
    asc = client.get(
        "/api/conversations?worktree=feature-b&sort=created_at"
    ).json()
    assert [c["id"] for c in asc["items"]] == [
        created[1]["id"], created[3]["id"]
    ]

    # Pagination: limit=2, offset=2 with default sort returns items[2:4].
    page = client.get("/api/conversations?limit=2&offset=2").json()
    assert page["limit"] == 2
    assert page["offset"] == 2
    assert page["total"] == 5
    expected = list(reversed(created))[2:4]
    assert [c["id"] for c in page["items"]] == [c["id"] for c in expected]

    # Invalid sort field → 400.
    assert client.get("/api/conversations?sort=title").status_code == 400

    # limit/offset bounds.
    assert client.get("/api/conversations?limit=0").status_code == 422
    assert client.get("/api/conversations?limit=999").status_code == 422
    assert client.get("/api/conversations?offset=-1").status_code == 422


@pytest.mark.asyncio
async def test_list_conversations_updated_since_filter(tmp_config) -> None:
    """`updated_since` returns only conversations touched at-or-after the
    threshold. The cutoff is taken from a freshly-created record's
    `updated_at` so the comparison is `>=` inclusive."""
    store = ConversationStore()

    a = await store.create(
        repo_id="demo", worktree=None, agent_id=None, title="a"
    )
    await asyncio.sleep(0.01)
    b = await store.create(
        repo_id="demo", worktree=None, agent_id=None, title="b"
    )
    await asyncio.sleep(0.01)
    c = await store.create(
        repo_id="demo", worktree=None, agent_id=None, title="c"
    )

    # Inclusive cutoff at b → b and c remain (default sort: newest first).
    items = await store.list(repo_id="demo", updated_since=b.updated_at)
    assert [x.id for x in items] == [c.id, b.id]
    assert await store.count(repo_id="demo", updated_since=b.updated_at) == 2

    # Cutoff after the newest record → empty result.
    after_c = c.updated_at.replace(microsecond=c.updated_at.microsecond)
    items = await store.list(
        repo_id="demo",
        updated_since=after_c.replace(year=after_c.year + 1),
    )
    assert items == []


def test_list_conversations_updated_since_query(
    client: TestClient, tmp_config
) -> None:
    """The `updated_since` query parameter accepts ISO 8601 (incl. naive)
    and threads through to the store filter."""
    _ensure_worktree(tmp_config)

    first = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "old"},
    ).json()
    time.sleep(0.01)
    second = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "new"},
    ).json()

    # ISO 8601 with Z suffix: only `second` (created strictly after first).
    cutoff = second["updated_at"]
    body = client.get(f"/api/conversations?updated_since={cutoff}").json()
    assert [c["id"] for c in body["items"]] == [second["id"]]
    assert body["total"] == 1

    # Cutoff at/before first → both rows match.
    body = client.get(
        f"/api/conversations?updated_since={first['updated_at']}"
    ).json()
    assert {c["id"] for c in body["items"]} == {first["id"], second["id"]}
    assert body["total"] == 2

    # Garbage value → 422 from FastAPI.
    assert (
        client.get("/api/conversations?updated_since=not-a-date").status_code
        == 422
    )


def test_update_conversation_title(client: TestClient, tmp_config) -> None:
    """PUT /api/conversations/{id} updates the conversation title."""
    _ensure_worktree(tmp_config)

    # Create a conversation
    create_resp = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "Original Title"},
    )
    assert create_resp.status_code == 200
    conv = create_resp.json()
    conv_id = conv["id"]
    assert conv["title"] == "Original Title"

    # Update the title
    update_resp = client.put(
        f"/api/conversations/{conv_id}",
        json={"title": "Updated Title"},
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["id"] == conv_id
    assert updated["title"] == "Updated Title"
    assert updated["repo_id"] == "demo"
    assert updated["worktree"] == "feature-a"

    # Verify the update persisted
    get_resp = client.get(f"/api/conversations/{conv_id}")
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["title"] == "Updated Title"


def test_update_conversation_with_null_preserves_existing(
    client: TestClient, tmp_config
) -> None:
    """PUT with title=null does not change the existing title.

    The patch method only updates non-None values, so sending null
    is equivalent to not sending the field at all.
    """
    _ensure_worktree(tmp_config)

    # Create a conversation with a title
    create_resp = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "Initial Title"},
    )
    assert create_resp.status_code == 200
    conv_id = create_resp.json()["id"]

    # Send null - should not change the title
    update_resp = client.put(
        f"/api/conversations/{conv_id}",
        json={"title": None},
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["title"] == "Initial Title"  # Should remain unchanged

    # Verify the title is still there
    get_resp = client.get(f"/api/conversations/{conv_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Initial Title"


def test_update_conversation_not_found(client: TestClient) -> None:
    """PUT returns 404 for non-existent conversation."""
    resp = client.put(
        "/api/conversations/does-not-exist",
        json={"title": "New Title"},
    )
    assert resp.status_code == 404


def test_update_conversation_updates_timestamp(client: TestClient, tmp_config) -> None:
    """PUT updates the updated_at timestamp."""
    _ensure_worktree(tmp_config)

    # Create a conversation
    create_resp = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "Original"},
    )
    assert create_resp.status_code == 200
    conv = create_resp.json()
    conv_id = conv["id"]
    original_updated_at = conv["updated_at"]

    # Wait a bit to ensure timestamp difference
    time.sleep(0.05)

    # Update the title
    update_resp = client.put(
        f"/api/conversations/{conv_id}",
        json={"title": "Updated"},
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()

    # Verify updated_at changed
    assert updated["updated_at"] != original_updated_at
    assert updated["updated_at"] > original_updated_at
