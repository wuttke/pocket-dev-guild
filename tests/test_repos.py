from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from pocket_dev_guild.config import Settings


def test_list_repos(client: TestClient) -> None:
    response = client.get("/repos")
    assert response.status_code == 200
    data = response.json()
    assert data == [{"id": "demo", "name": "demo", "path": data[0]["path"]}]


def test_openapi_contains_typed_models(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "Repo" in schema["components"]["schemas"]
    assert "JobLog" in schema["components"]["schemas"]
    assert "WorktreeInfo" in schema["components"]["schemas"]


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
