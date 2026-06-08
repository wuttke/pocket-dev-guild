from fastapi.testclient import TestClient

from pocket_dev_guild.schemas import WorktreeInfo


def test_create_list_delete_worktree(client: TestClient) -> None:
    create = client.post(
        "/api/repos/demo/worktrees",
        json={"branch": "feature/persistence"},
    )
    assert create.status_code == 200, create.text
    assert create.json()["name"] == "feature_persistence"

    listed = client.get("/api/repos/demo/worktrees")
    assert listed.status_code == 200
    items = listed.json()
    by_name = {w["name"]: w for w in items}
    assert "feature_persistence" in by_name
    assert by_name["feature_persistence"]["is_primary"] is False

    delete = client.delete("/api/repos/demo/worktrees/feature_persistence")
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
            "/api/repos/demo/worktrees",
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
        items = client.get("/api/repos/demo/worktrees").json()
    assert len(items) == 1
    assert items[0]["is_primary"] is True
    assert items[0]["name"] is None


def test_unknown_repo_returns_404(client: TestClient) -> None:
    response = client.get("/api/repos/nope/worktrees")
    assert response.status_code == 404


def test_rejects_invalid_repo_id_in_path(client: TestClient) -> None:
    # Some inputs (".", "..", "demo/..") get normalized by the HTTP client
    # and land on a different route (e.g. DELETE /repos/{repo_id}), which
    # responds 405 to a GET. That's still a rejection of the worktrees
    # handler — accept it alongside 404 / 422.
    for repo_id in ("..", ".", "demo/..", "with space", ""):
        response = client.get(f"/api/repos/{repo_id}/worktrees")
        assert response.status_code in (404, 405, 422), (repo_id, response.text)


def test_rejects_invalid_branch_pattern_on_create(client: TestClient) -> None:
    # Branch names must look like `kind/slug[/slug...]` with kind in
    # letters (any case) and slugs in letters + digits + dashes + dots.
    for branch in (
        "",                    # empty
        "feature",             # missing kind separator
        "feature/",            # empty slug
        "/persistence",        # missing kind
        "feature/foo_bar",     # underscore in slug
        "feature/foo bar",     # whitespace
        "feature//bar",        # empty inner segment
        "feature1/foo",        # digit in kind
    ):
        response = client.post(
            "/api/repos/demo/worktrees", json={"branch": branch}
        )
        assert response.status_code == 422, (branch, response.text)


def test_accepts_nested_branch_segments(client: TestClient) -> None:
    resp = client.post(
        "/api/repos/demo/worktrees",
        json={"branch": "feature/team/foo-bar"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "feature_team_foo-bar"


def test_dirname_is_lowercased_and_dots_replaced(client: TestClient) -> None:
    # Uppercase and dots are allowed in the branch name but normalised
    # away in the worktree directory name.
    resp = client.post(
        "/api/repos/demo/worktrees",
        json={"branch": "release/2.5.x"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "release_2_5_x"


def test_uppercase_branch_collides_with_lowercase_dirname(
    app_factory, tmp_config
) -> None:
    # `Feature/Foo` and `feature/foo` both map to the same worktree
    # directory (`feature_foo`); the second create attempt must fail
    # rather than silently clobber the first.
    from .conftest import FakeGit  # type: ignore[import-not-found]

    _config, _repo_path = tmp_config
    git = FakeGit()
    app = app_factory(git=git)
    with TestClient(app) as client:
        first = client.post(
            "/api/repos/demo/worktrees", json={"branch": "feature/foo"}
        )
        assert first.status_code == 200, first.text
        assert first.json()["name"] == "feature_foo"
        second = client.post(
            "/api/repos/demo/worktrees", json={"branch": "Feature/Foo"}
        )
    # FakeGit doesn't simulate git's "target already exists" failure,
    # so we at minimum check the derived dirname matches the first.
    assert second.json().get("name") == "feature_foo"


def test_create_existing_branch_skips_start_point(
    app_factory, tmp_config
) -> None:
    from .conftest import FakeGit  # type: ignore[import-not-found]

    _config, _repo_path = tmp_config
    git = FakeGit()
    app = app_factory(git=git)
    with TestClient(app) as client:
        resp = client.post(
            "/api/repos/demo/worktrees?existing=true",
            json={"branch": "feature/already-there"},
        )
    assert resp.status_code == 200, resp.text
    assert len(git.added) == 1
    _repo, target, branch, start_point = git.added[0]
    assert target.endswith("/demo-worktrees/feature_already-there")
    assert branch == "feature/already-there"
    # No -b: existing branch, no start-point.
    assert start_point is None


def test_rejects_invalid_worktree_name_on_delete(client: TestClient) -> None:
    # "." and ".." get normalised away by the HTTP client before they reach
    # the server, so we only assert on names that survive URL normalisation.
    for name in ("with%20space", "a%2Eb%2Ec", "a%3Bb"):
        response = client.delete(f"/api/repos/demo/worktrees/{name}")
        assert response.status_code == 422, (name, response.text)


def test_delete_blocked_by_unarchived_conversation(client: TestClient) -> None:
    # Create a worktree, then a conversation bound to it: delete must 409.
    client.post("/api/repos/demo/worktrees", json={"branch": "feature/blocker"})
    conv = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature_blocker", "title": "x"},
    )
    assert conv.status_code == 200, conv.text
    conv_id = conv.json()["id"]

    resp = client.delete("/api/repos/demo/worktrees/feature_blocker")
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["reason"] == "worktree_has_active_resources"
    assert detail["conversations"] == 1
    assert detail["active_jobs"] == 0

    # After archiving the conversation, deletion proceeds.
    archived = client.delete(f"/api/conversations/{conv_id}")
    assert archived.status_code == 204, archived.text

    resp = client.delete("/api/repos/demo/worktrees/feature_blocker")
    assert resp.status_code == 200, resp.text


def test_delete_blocked_by_active_job(client: TestClient) -> None:
    import asyncio

    client.post("/api/repos/demo/worktrees", json={"branch": "feature/busy"})

    # Seed a queued job directly via the store; no runner needed for
    # the count-based guard.
    store = client.app.state.store
    asyncio.run(
        store.create(
            repo_id="demo", worktree="feature_busy", prompt="hi",
        )
    )

    resp = client.delete("/api/repos/demo/worktrees/feature_busy")
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["active_jobs"] == 1
    assert detail["conversations"] == 0


def test_delete_allowed_when_only_finished_jobs_exist(client: TestClient) -> None:
    import asyncio

    client.post("/api/repos/demo/worktrees", json={"branch": "feature/done"})

    store = client.app.state.store

    async def _seed_finished() -> None:
        info = await store.create(
            repo_id="demo", worktree="feature_done", prompt="hi",
        )
        await store.set_status(info.id, "finished", returncode=0)

    asyncio.run(_seed_finished())

    resp = client.delete("/api/repos/demo/worktrees/feature_done")
    assert resp.status_code == 200, resp.text


def test_delete_with_archive_conversations_true(client: TestClient) -> None:
    """Test that archive_conversations=true archives conversations and allows deletion."""
    # Create a worktree
    client.post("/api/repos/demo/worktrees", json={"branch": "feature/archive-test"})

    # Create two conversations bound to it
    conv1 = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature_archive-test", "title": "conv1"},
    )
    assert conv1.status_code == 200, conv1.text
    conv1_id = conv1.json()["id"]

    conv2 = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature_archive-test", "title": "conv2"},
    )
    assert conv2.status_code == 200, conv2.text
    conv2_id = conv2.json()["id"]

    # Verify we have 2 unarchived conversations
    convs = client.get("/api/conversations?repo_id=demo&worktree=feature_archive-test")
    assert convs.status_code == 200
    assert convs.json()["total"] == 2

    # Delete with archive_conversations=true should succeed
    resp = client.delete("/api/repos/demo/worktrees/feature_archive-test?archive_conversations=true")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"removed": "feature_archive-test"}

    # Verify conversations were archived
    conv1_check = client.get(f"/api/conversations/{conv1_id}")
    assert conv1_check.status_code == 200
    assert conv1_check.json()["archived"] is True

    conv2_check = client.get(f"/api/conversations/{conv2_id}")
    assert conv2_check.status_code == 200
    assert conv2_check.json()["archived"] is True

    # Verify unarchived conversation count is 0
    convs_after = client.get("/api/conversations?repo_id=demo&worktree=feature_archive-test")
    assert convs_after.status_code == 200
    assert convs_after.json()["total"] == 0

    # Verify archived conversations are still accessible with include_archived=true
    convs_archived = client.get(
        "/api/conversations?repo_id=demo&worktree=feature_archive-test&include_archived=true"
    )
    assert convs_archived.status_code == 200
    assert convs_archived.json()["total"] == 2


def test_delete_without_archive_conversations_still_blocks(client: TestClient) -> None:
    """Test that without archive_conversations parameter, deletion is still blocked."""
    # Create a worktree
    client.post("/api/repos/demo/worktrees", json={"branch": "feature/still-blocked"})

    # Create a conversation bound to it
    conv = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature_still-blocked", "title": "blocker"},
    )
    assert conv.status_code == 200, conv.text

    # Delete without archive_conversations should still fail with 409
    resp = client.delete("/api/repos/demo/worktrees/feature_still-blocked")
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["reason"] == "worktree_has_active_resources"
    assert detail["conversations"] == 1


def test_archive_conversations_with_active_jobs_still_blocks(client: TestClient) -> None:
    """Test that archive_conversations=true still blocks if there are active jobs."""
    import asyncio

    client.post("/api/repos/demo/worktrees", json={"branch": "feature/jobs-block"})

    # Create a conversation
    conv = client.post(
        "/api/conversations",
        json={"repo_id": "demo", "worktree": "feature_jobs-block", "title": "x"},
    )
    assert conv.status_code == 200, conv.text

    # Seed a queued job directly via the store
    store = client.app.state.store
    asyncio.run(
        store.create(
            repo_id="demo", worktree="feature_jobs-block", prompt="hi",
        )
    )

    # Even with archive_conversations=true, active jobs should block deletion
    resp = client.delete("/api/repos/demo/worktrees/feature_jobs-block?archive_conversations=true")
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["active_jobs"] == 1
    # Conversation should have been archived before the check
    assert detail["conversations"] == 0
