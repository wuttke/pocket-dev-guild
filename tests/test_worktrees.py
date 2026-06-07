from fastapi.testclient import TestClient

from pocket_dev_guild.schemas import WorktreeInfo


def test_create_list_delete_worktree(client: TestClient) -> None:
    create = client.post(
        "/repos/demo/worktrees",
        json={"branch": "feature/persistence"},
    )
    assert create.status_code == 200, create.text
    assert create.json()["name"] == "feature_persistence"

    listed = client.get("/repos/demo/worktrees")
    assert listed.status_code == 200
    items = listed.json()
    by_name = {w["name"]: w for w in items}
    assert "feature_persistence" in by_name
    assert by_name["feature_persistence"]["is_primary"] is False

    delete = client.delete("/repos/demo/worktrees/feature_persistence")
    assert delete.status_code == 200
    assert delete.json() == {"removed": "feature_persistence"}


def test_create_passes_branch_and_start_point_to_git(
    app_factory, tmp_config
) -> None:
    from .conftest import FakeGit  # type: ignore[import-not-found]

    _config, repo_path = tmp_config
    git = FakeGit(default_branch="origin/develop")
    app = app_factory(git=git)
    with TestClient(app) as client:
        resp = client.post(
            "/repos/demo/worktrees",
            json={"branch": "bugfix/issue-42"},
        )
    assert resp.status_code == 200, resp.text
    assert len(git.added) == 1
    _repo, target, branch, start_point = git.added[0]
    assert target.endswith("/demo-worktrees/bugfix_issue-42")
    assert branch == "bugfix/issue-42"
    assert start_point == "origin/develop"


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


def test_rejects_invalid_repo_id_in_path(client: TestClient) -> None:
    for repo_id in ("..", ".", "demo/..", "with space", ""):
        response = client.get(f"/repos/{repo_id}/worktrees")
        assert response.status_code in (404, 422), (repo_id, response.text)


def test_rejects_invalid_branch_pattern_on_create(client: TestClient) -> None:
    # Branch names must look like `kind/slug[/slug...]` with kind in
    # lowercase letters and slugs in lowercase + digits + dashes.
    for branch in (
        "",                    # empty
        "feature",             # missing kind separator
        "feature/",            # empty slug
        "/persistence",        # missing kind
        "Feature/Foo",         # uppercase
        "feature/foo_bar",     # underscore in slug
        "feature/foo bar",     # whitespace
        "feature//bar",        # empty inner segment
        "feature/..",          # path traversal
    ):
        response = client.post(
            "/repos/demo/worktrees", json={"branch": branch}
        )
        assert response.status_code == 422, (branch, response.text)


def test_accepts_nested_branch_segments(client: TestClient) -> None:
    resp = client.post(
        "/repos/demo/worktrees",
        json={"branch": "feature/team/foo-bar"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "feature_team_foo-bar"


def test_rejects_invalid_worktree_name_on_delete(client: TestClient) -> None:
    # "." and ".." get normalised away by the HTTP client before they reach
    # the server, so we only assert on names that survive URL normalisation.
    for name in ("with%20space", "a%2Eb%2Ec", "a%3Bb"):
        response = client.delete(f"/repos/demo/worktrees/{name}")
        assert response.status_code == 422, (name, response.text)
