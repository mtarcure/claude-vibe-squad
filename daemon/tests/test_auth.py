"""Bearer token auth tests."""
import pytest
from fastapi.testclient import TestClient
from daemon.tests.conftest import AUTH_HEADERS  # noqa: F401 sets env
from daemon.main import app
from starlette.websockets import WebSocketDisconnect


def test_tasks_without_auth_returns_401():
    client = TestClient(app)
    response = client.get("/tasks")
    assert response.status_code == 401


def test_tasks_with_bad_token_returns_403():
    client = TestClient(app)
    response = client.get(
        "/tasks", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 403


def test_health_no_auth_needed():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_events_without_auth_is_rejected():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/events"):
            pass
    assert exc_info.value.code == 1008


def test_events_with_bad_token_is_rejected():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/events", headers={"Authorization": "Bearer wrong-token"}
        ):
            pass
    assert exc_info.value.code == 1008


def test_events_with_good_token_connects():
    client = TestClient(app)
    with client.websocket_connect("/events", headers=AUTH_HEADERS):
        pass
