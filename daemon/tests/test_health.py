import time

from fastapi.testclient import TestClient
from daemon.tests.conftest import AUTH_HEADERS  # noqa: F401 sets env
from daemon.main import app

def test_health_returns_ok(tmp_path, monkeypatch):
    # /health now reflects the outbox watcher's real state (was a hardcoded
    # "ok"), so the watcher must actually start: run inside the TestClient
    # context manager so the app's lifespan executes, and give it a scratch
    # VIBESQUAD_STATE_DIR to watch. The watcher task is scheduled, not run,
    # by the time the context manager returns, so poll briefly instead of
    # asserting on the first response.
    monkeypatch.setenv("VIBESQUAD_STATE_DIR", str(tmp_path))
    with TestClient(app) as client:
        response = None
        for _ in range(50):
            response = client.get("/health")
            if response.json().get("status") == "ok":
                break
            time.sleep(0.02)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
