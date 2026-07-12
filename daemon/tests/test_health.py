from fastapi.testclient import TestClient
from daemon.tests.conftest import AUTH_HEADERS  # noqa: F401 sets env
from daemon.main import app

def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
