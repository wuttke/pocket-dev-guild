import json

from fastapi.testclient import TestClient

from pocket_dev_guild.schemas import LogLine
from tests.conftest import FakeRunner


def _make_client(app_factory, tmp_config, runner_script, returncode=0):
    _, repo_path = tmp_config
    # ensure a worktree dir exists so the job endpoint accepts it
    worktree_dir = repo_path.parent / "demo-worktrees" / "feature-a"
    worktree_dir.mkdir(parents=True, exist_ok=True)

    app = app_factory()
    # swap in fake runner that shares the app's JobStore
    runner = FakeRunner(
        store=app.state.store, script=runner_script, returncode=returncode
    )
    app.state.runner = runner
    return TestClient(app)


def test_job_lifecycle(app_factory, tmp_config) -> None:
    script = [
        LogLine(stream="stdout", line="hello\n"),
        LogLine(stream="stdout", line="world\n"),
    ]
    with _make_client(app_factory, tmp_config, script) as client:
        create = client.post(
            "/jobs",
            json={"repo_id": "demo", "worktree": "feature-a", "prompt": "do it"},
        )
        assert create.status_code == 200, create.text
        job_id = create.json()["job_id"]

        # SSE stream consumes log + status events
        with client.stream("GET", f"/jobs/{job_id}/events") as stream:
            events: list[tuple[str, str]] = []
            current_event = "message"
            for raw in stream.iter_lines():
                if raw.startswith("event:"):
                    current_event = raw.split(":", 1)[1].strip()
                elif raw.startswith("data:"):
                    data = raw.split(":", 1)[1].strip()
                    events.append((current_event, data))
                    if current_event == "status":
                        break

        log_events = [json.loads(d) for ev, d in events if ev == "log"]
        status_events = [json.loads(d) for ev, d in events if ev == "status"]
        assert [e["line"] for e in log_events] == ["hello\n", "world\n"]
        final = status_events[-1]
        assert final["status"] == "finished"
        assert final["returncode"] == 0
        assert final["finished_at"] is not None

        snapshot = client.get(f"/jobs/{job_id}/log").json()
        assert snapshot["status"] == "finished"
        assert len(snapshot["log"]) == 2
        assert snapshot["created_at"] is not None
        assert snapshot["finished_at"] is not None


def test_job_unknown_worktree(client: TestClient) -> None:
    response = client.post(
        "/jobs",
        json={"repo_id": "demo", "worktree": "missing", "prompt": "x"},
    )
    assert response.status_code == 404


def test_job_rejects_invalid_identifiers(client: TestClient) -> None:
    for body in (
        {"repo_id": "..", "prompt": "x"},
        {"repo_id": "demo", "worktree": "..", "prompt": "x"},
        {"repo_id": "demo", "worktree": "a/b", "prompt": "x"},
        {"repo_id": "with space", "prompt": "x"},
    ):
        response = client.post("/jobs", json=body)
        assert response.status_code == 422, (body, response.text)


def test_job_primary_repo(app_factory, tmp_config) -> None:
    script = [LogLine(stream="stdout", line="ok\n")]
    with _make_client(app_factory, tmp_config, script) as client:
        # worktree omitted → runs in the primary repo checkout
        create = client.post(
            "/jobs", json={"repo_id": "demo", "prompt": "do it"}
        )
        assert create.status_code == 200, create.text
        job_id = create.json()["job_id"]
        info = client.get(f"/jobs/{job_id}").json()
        assert info["worktree"] is None


def _wait_finished(client: TestClient, job_id: str, timeout: float = 2.0) -> None:
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        info = client.get(f"/jobs/{job_id}").json()
        if info["status"] in ("finished", "failed"):
            return
        _time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {info}")


def test_list_jobs_empty(client: TestClient) -> None:
    resp = client.get("/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_list_jobs_filter_sort_paginate(app_factory, tmp_config) -> None:
    script = [LogLine(stream="stdout", line="ok\n")]
    with _make_client(app_factory, tmp_config, script) as client:
        # Three jobs on the same worktree, finished sequentially so
        # `created_at` is monotonic in insertion order.
        ids: list[str] = []
        for _ in range(3):
            r = client.post(
                "/jobs",
                json={"repo_id": "demo", "worktree": "feature-a", "prompt": "p"},
            )
            assert r.status_code == 200
            jid = r.json()["job_id"]
            _wait_finished(client, jid)
            ids.append(jid)

        # And one queued job that we never let finish, on a different worktree.
        (tmp_config[1].parent / "demo-worktrees" / "feature-b").mkdir(
            parents=True, exist_ok=True
        )
        # No runner script branch: reuse same FakeRunner — it will finish
        # quickly. Filter by worktree below anyway.
        other = client.post(
            "/jobs",
            json={"repo_id": "demo", "worktree": "feature-b", "prompt": "p"},
        ).json()["job_id"]
        _wait_finished(client, other)

        # Default: newest first, all four jobs visible.
        body = client.get("/jobs").json()
        assert body["total"] == 4
        assert body["items"][0]["id"] == other  # last created
        assert body["items"][-1]["id"] == ids[0]  # first created

        # Filter by worktree drops `other`.
        wt = client.get("/jobs?worktree=feature-a").json()
        assert wt["total"] == 3
        assert {j["id"] for j in wt["items"]} == set(ids)

        # status=finished matches everything in this run.
        fin = client.get("/jobs?status=finished").json()
        assert fin["total"] == 4

        # Status passthrough validation.
        bad = client.get("/jobs?status=nonsense")
        assert bad.status_code == 400, bad.text

        # Sort ascending by created_at flips order.
        asc = client.get("/jobs?sort=created_at").json()
        assert [j["id"] for j in asc["items"]] == ids + [other]

        # Invalid sort field rejected.
        assert client.get("/jobs?sort=prompt").status_code == 400

        # Pagination: limit=2 + offset=2 returns the 3rd/4th item under
        # default sort (newest first → ids[1], ids[0]).
        page = client.get("/jobs?limit=2&offset=2").json()
        assert page["total"] == 4
        assert page["limit"] == 2
        assert page["offset"] == 2
        assert [j["id"] for j in page["items"]] == [ids[1], ids[0]]

        # limit out of range → 422 from FastAPI Query validation.
        assert client.get("/jobs?limit=0").status_code == 422
        assert client.get("/jobs?limit=999").status_code == 422
        assert client.get("/jobs?offset=-1").status_code == 422
