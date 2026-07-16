"""Lazy summarizer startup and scoped failure tests."""
from fastapi.testclient import TestClient

from daemon.main import app
from daemon.tests.conftest import AUTH_HEADERS  # noqa: F401 sets env


def test_missing_gemini_key_returns_scoped_503(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post(
        "/summarize", json={"text": "hello"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "summarization unavailable: GEMINI_API_KEY not set"
    }


def test_summarizer_is_constructed_on_request(monkeypatch):
    class StubSummarizer:
        async def summarize(self, text, instructions=None):
            return f"{instructions or 'default'}: {text}"

    monkeypatch.setattr("daemon.routes.summarize.FlashSummarizer", StubSummarizer)
    client = TestClient(app)

    response = client.post(
        "/summarize",
        json={"text": "hello", "instructions": "brief"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"summary": "brief: hello"}
