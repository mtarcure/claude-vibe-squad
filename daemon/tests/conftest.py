"""Test fixtures — sets required env before app import."""
import os

# Auth middleware requires VIBESQUAD_DAEMON_TOKEN at app construction time.
# Set a test token BEFORE any test module imports daemon.main.
os.environ.setdefault("VIBESQUAD_DAEMON_TOKEN", "test-token-for-pytest-only")

TEST_TOKEN = os.environ["VIBESQUAD_DAEMON_TOKEN"]
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}
