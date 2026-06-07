from fastapi.testclient import TestClient


def test_create_list_delete_worktree(client: TestClient) -> None:
    create = client.post(
        "/repos/demo/worktrees",
        json={"name": "feature-a", "base_branch": "main"},
    )
    assert create.status_code == 200, create.text
    assert create.json()["name"] == "feature-a"

    listed = client.get("/repos/demo/worktrees")
    assert listed.status_code == 200
    names = [w["path"].split("/")[-1] for w in listed.json()]
    assert "feature-a" in names

    delete = client.delete("/repos/demo/worktrees/feature-a")
    assert delete.status_code == 200
    assert delete.json() == {"removed": "feature-a"}


def test_unknown_repo_returns_404(client: TestClient) -> None:
    response = client.get("/repos/nope/worktrees")
    assert response.status_code == 404
