"""Conversations: CRUD, turn binding, session discovery and summary."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from pocket_dev_guild.schemas import LogLine
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
        info = client.get(f"/conversations/{conv_id}").json()
        if predicate(info):
            return info
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting on conversation {conv_id}: {info}")


def test_conversation_crud(client: TestClient, tmp_config) -> None:
    _ensure_worktree(tmp_config)

    create = client.post(
        "/conversations",
        json={"repo_id": "demo", "worktree": "feature-a", "title": "t1"},
    )
    assert create.status_code == 200, create.text
    info = create.json()
    assert info["repo_id"] == "demo"
    assert info["worktree"] == "feature-a"
    assert info["title"] == "t1"
    assert info["session_id"] is None
    assert info["turns"] == []

    listing = client.get("/conversations").json()
    assert [c["id"] for c in listing] == [info["id"]]

    detail = client.get(f"/conversations/{info['id']}").json()
    assert detail["id"] == info["id"]

    assert client.get("/conversations/does-not-exist").status_code == 404


def test_conversation_rejects_unknown_repo_or_worktree(client: TestClient) -> None:
    assert (
        client.post("/conversations", json={"repo_id": "demo", "worktree": "nope"}).status_code
        == 404
    )
    assert client.post("/conversations", json={"repo_id": "missing"}).status_code == 404


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
            "/conversations",
            json={"repo_id": "demo", "worktree": "feature-a"},
        ).json()
        turn1 = client.post(
            f"/conversations/{conv['id']}/turns", json={"prompt": "p1"}
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
            f"/conversations/{conv['id']}/turns", json={"prompt": "p2"}
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
            "/conversations",
            json={"repo_id": "demo", "worktree": "feature-a"},
        ).json()
        first = client.post(
            f"/conversations/{conv['id']}/turns", json={"prompt": "p1"}
        )
        assert first.status_code == 200, first.text
        second = client.post(
            f"/conversations/{conv['id']}/turns", json={"prompt": "p2"}
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
            "/conversations",
            json={"repo_id": "demo", "worktree": "feature-a"},
        ).json()
        # Mismatched worktree → 409.
        bad = client.post(
            "/jobs",
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
            "/jobs",
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
        job = client.get(f"/jobs/{job_id}").json()
        assert job["conversation_id"] == conv["id"]
        assert job["session_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert job["request_id"] == "11111111-2222-3333-4444-555555555555"
