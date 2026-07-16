from fastapi.testclient import TestClient
from daemon.tests.conftest import AUTH_HEADERS  # noqa: F401 sets env

from daemon.main import app


def test_dispatch_and_project_routes_are_not_mounted():
    client = TestClient(app)
    assert client.post("/task", json={}, headers=AUTH_HEADERS).status_code == 404
    assert client.get("/projects", headers=AUTH_HEADERS).status_code == 404
    assert client.post("/projects", json={}, headers=AUTH_HEADERS).status_code == 404
    assert client.get("/projects/example", headers=AUTH_HEADERS).status_code == 404


def test_tasks_status_route_remains_available(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBESQUAD_STATE_DIR", str(tmp_path))
    lane_dir = tmp_path / "active" / "kimi"
    lane_dir.mkdir(parents=True)
    (lane_dir / "TASK-status.md").write_text("started_at_epoch: 123\ntokens_used: 7\n")

    client = TestClient(app)
    response = client.get("/tasks", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "tasks": [
            {
                "task_id": "TASK-status",
                "lane": "kimi",
                "state": "running",
                "tokens_used": 7,
                "started_at_epoch": 123,
            }
        ]
    }
