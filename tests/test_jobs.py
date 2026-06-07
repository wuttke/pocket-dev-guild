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
