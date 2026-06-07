from fastapi.testclient import TestClient


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
