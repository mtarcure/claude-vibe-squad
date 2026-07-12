"""Bearer token auth tests."""
from fastapi.testclient import TestClient
from daemon.tests.conftest import AUTH_HEADERS  # noqa: F401 sets env
from daemon.main import app


def test_task_without_auth_returns_401():
    client = TestClient(app)
    response = client.post("/task", json={
        "specialist": "x", "specialist_file": "x", "lane": "kimi",
        "model": "kimi-k2.7-code", "model_key": "default", "prompt": "test",
    })
    assert response.status_code == 401


def test_task_with_bad_token_returns_403():
    client = TestClient(app)
    response = client.post("/task", json={
        "specialist": "x", "specialist_file": "x", "lane": "kimi",
        "model": "kimi-k2.7-code", "model_key": "default", "prompt": "test",
    }, headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 403


def test_health_no_auth_needed():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
