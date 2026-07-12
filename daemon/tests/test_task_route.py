from fastapi.testclient import TestClient
from daemon.tests.conftest import AUTH_HEADERS  # noqa: F401 sets env

from daemon.main import app

def test_post_task_writes_to_inbox(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBESQUAD_STATE_DIR", str(tmp_path))
    client = TestClient(app)
    packet = {
        "specialist": "researcher",
        "specialist_file": "specialists/researcher.md",
        "lane": "kimi",
        "model": "kimi-k2.7-code",
        "model_key": "default",
        "prompt": "Research topic X",
    }
    response = client.post("/task", json=packet, headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert "task_id" in body
    inbox_files = list((tmp_path / "inbox" / "kimi").glob("*.md"))
    assert len(inbox_files) == 1
