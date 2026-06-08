from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from pocket_dev_guild.config import Settings


def test_list_repos(client: TestClient) -> None:
    response = client.get("/api/repos")
    assert response.status_code == 200
    data = response.json()
    assert data == [
        {"id": "demo", "name": "demo", "path": data[0]["path"], "inactive": False}
    ]


def test_openapi_contains_typed_models(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    assert "Repo" in schema["components"]["schemas"]
    assert "JobLog" in schema["components"]["schemas"]
    assert "WorktreeInfo" in schema["components"]["schemas"]


def test_list_repos_include_inactive_filter(client: TestClient) -> None:
    """Test that include_inactive parameter correctly filters repos."""
    # First, verify we have the demo repo
    response = client.get("/api/repos")
    assert response.status_code == 200
    initial_repos = response.json()
    assert len(initial_repos) == 1
    assert initial_repos[0]["id"] == "demo"
    assert initial_repos[0]["inactive"] is False

    # Mark the demo repo as inactive
    response = client.delete("/api/repos/demo")
    assert response.status_code == 204

    # List repos without include_inactive (default False) - should be empty
    response = client.get("/api/repos")
    assert response.status_code == 200
    active_repos = response.json()
    assert len(active_repos) == 0

    # List repos with include_inactive=False - should also be empty
    response = client.get("/api/repos?include_inactive=false")
    assert response.status_code == 200
    active_repos_explicit = response.json()
    assert len(active_repos_explicit) == 0

    # List repos with include_inactive=True - should show the inactive repo
    response = client.get("/api/repos?include_inactive=true")
    assert response.status_code == 200
    all_repos = response.json()
    assert len(all_repos) == 1
    assert all_repos[0]["id"] == "demo"
    assert all_repos[0]["inactive"] is True


def test_settings_defaults_and_overrides(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("repos: []\n")
    s = Settings(config_path=empty)
    assert s.agent_binary == "auggie"
    assert s.agent_prompt_param == "--print"

    custom = tmp_path / "custom.yaml"
    custom.write_text(
        yaml.safe_dump(
            {
                "agent_binary": "/usr/local/bin/foo-agent",
                "agent_prompt_param": "-p",
                "repos": [],
            }
        )
    )
    s = Settings(config_path=custom)
    assert s.agent_binary == "/usr/local/bin/foo-agent"
    assert s.agent_prompt_param == "-p"
