from fastapi.testclient import TestClient

from pocket_dev_guild.schemas import WorktreeInfo


def test_create_list_delete_worktree(client: TestClient) -> None:
    create = client.post(
        "/repos/demo/worktrees",
        json={"name": "feature-a", "base_branch": "main"},
    )
    assert create.status_code == 200, create.text
    assert create.json()["name"] == "feature-a"

    listed = client.get("/repos/demo/worktrees")
    assert listed.status_code == 200
    items = listed.json()
    by_name = {w["name"]: w for w in items}
    assert "feature-a" in by_name
    assert by_name["feature-a"]["is_primary"] is False

    delete = client.delete("/repos/demo/worktrees/feature-a")
    assert delete.status_code == 200
    assert delete.json() == {"removed": "feature-a"}


def test_list_marks_primary_and_hides_foreign(app_factory, tmp_config) -> None:
    from .conftest import FakeGit  # type: ignore[import-not-found]

    _config, repo_path = tmp_config
    git = FakeGit()
    git.worktrees[str(repo_path)] = [
        WorktreeInfo(path=str(repo_path), branch="refs/heads/main"),
        WorktreeInfo(path="/tmp/some-foreign-worktree", branch="refs/heads/x"),
    ]
    app = app_factory(git=git)
    with TestClient(app) as client:
        items = client.get("/repos/demo/worktrees").json()
    assert len(items) == 1
    assert items[0]["is_primary"] is True
    assert items[0]["name"] is None


def test_unknown_repo_returns_404(client: TestClient) -> None:
    response = client.get("/repos/nope/worktrees")
    assert response.status_code == 404
