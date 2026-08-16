#!/usr/bin/env python3
"""The weekly review must not fabricate a week that did not happen.

The runner shipped on a Sunday launchd schedule with both collectors wired to
paths that never yielded anything, so it POSTed a 52-byte payload -- two section
headers and nothing else -- to /summarize along with an order to produce six
named sections. Given no evidence and an instruction to produce sections, the
model invented them: the 2026-W32 output describes a cloud migration, a Redis
incident and handoffs between four named engineers, none of which occurred.

The guard asserted here is structural. No evidence must be incapable of
producing a document, which means no HTTP request and no output file -- and it
must stay that way even if the collectors are repointed at nothing again.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PYTHON_SCRIPTS = ROOT / "scripts/python"
if str(PYTHON_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS))

# weekly_review_runner imports httpx at module scope, and the interpreter
# bin/test falls back to inside a board worktree does not have it: .venv is
# gitignored, so the repo-local venv exists only in the primary checkout. A bare
# `import` here would skip this test in all 44 worktrees -- the ones where a
# dispatched worker is asked to verify against it.
#
# The stub does not weaken the assertion. What is asserted is that no request is
# issued, and the recording client below replaces AsyncClient either way; against
# the unfixed runner the stub records the call and this test fails exactly as it
# should.
try:  # pragma: no cover - depends on the host interpreter, not on the branch
    import httpx  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - see above
    _stub = types.ModuleType("httpx")
    _stub.AsyncClient = None
    sys.modules["httpx"] = _stub

import weekly_review_runner as runner  # noqa: E402


class WeeklyReviewWrapperTest(unittest.TestCase):
    """The scheduled wrapper is runnable without private clone-local files."""

    def test_sealed_home_uses_locked_project_environment(self):
        with tempfile.TemporaryDirectory(prefix="weekly-review-wrapper-") as temp:
            home = Path(temp) / "home"
            local_bin = home / ".local/bin"
            local_bin.mkdir(parents=True)
            uv_log = Path(temp) / "uv-args.log"
            fake_uv = local_bin / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf '%s\\n' \"$@\" > \"${WEEKLY_UV_LOG:?}\"\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin",
                "WEEKLY_UV_LOG": str(uv_log),
            }
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "bin/weekly-review.sh")],
                cwd=Path(temp),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            args = uv_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(args[:5], ["run", "--quiet", "--locked", "--project", str(ROOT)])
        self.assertEqual(args[5], "python")
        self.assertEqual(
            args[6], str(ROOT / "scripts/python/weekly_review_runner.py")
        )

    def test_default_installer_includes_weekly_review_as_optional(self):
        installer = (ROOT / "bin/install-routines.sh").read_text(encoding="utf-8")
        assignment = re.search(
            r"^OPTIONAL_AGENTS=\(([^)]*)\)", installer, flags=re.MULTILINE
        )
        self.assertIsNotNone(assignment, "installer must declare OPTIONAL_AGENTS")
        assert assignment is not None
        optional_agents = shlex.split(assignment.group(1))

        self.assertIn("com.vibesquad.weekly-review", optional_agents)

    def test_missing_locked_environment_runner_is_indeterminate(self):
        with tempfile.TemporaryDirectory(prefix="weekly-review-missing-uv-") as temp:
            home = Path(temp) / "home"
            home.mkdir()
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "bin/weekly-review.sh")],
                cwd=Path(temp),
                env={
                    **os.environ,
                    "HOME": str(home),
                    "PATH": "/usr/bin:/bin",
                    "WEEKLY_UV_UNDER_TEST": "/definitely/missing/uv",
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("COULD NOT DETERMINE", result.stderr)


class FakeResponse:
    """A successful /summarize reply, so an unguarded run completes.

    Deliberately not an error: if a request slips past the guard, the run should
    carry on and write its file, so the test reports *both* things that went
    wrong rather than masking the second behind an exception from the first.
    """

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"summary": "SECTIONS THE MODEL INVENTED"}


class RecordingClient:
    """Stands in for httpx.AsyncClient and records every request attempted."""

    calls: list[str] = []
    payloads: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "RecordingClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, **kwargs) -> FakeResponse:
        RecordingClient.calls.append(url)
        RecordingClient.payloads.append(kwargs.get("json") or {})
        return FakeResponse()


class WeeklyReviewGuardTest(unittest.TestCase):
    """No evidence -> no request, no file. And a control proving we can see both."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="weekly-review-guard-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)

        RecordingClient.calls = []
        RecordingClient.payloads = []

        # REPO is a module-level constant bound at import, but the collectors
        # read it at call time, so patching the global redirects them without
        # the subprocess dance test_deperson_python_root.py needs.
        for patcher in (
            mock.patch.object(runner, "REPO", self.vault),
            mock.patch.object(runner.httpx, "AsyncClient", RecordingClient, create=True),
            mock.patch.dict(os.environ, {"VIBESQUAD_DAEMON_TOKEN": "test-token"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def written_reviews(self) -> list[Path]:
        return sorted(self.vault.rglob("docs/reviews/weekly/*.md"))

    def seed_handoff(self, name: str, body: str) -> None:
        """Write a handoff under its real naming convention: <date>-<slug>.md."""
        handoffs = self.vault / "docs" / "handoffs"
        handoffs.mkdir(parents=True, exist_ok=True)
        (handoffs / name).write_text(body, encoding="utf-8")

    def seed_envelope(self, namespace: str, name: str, body: str) -> None:
        """Write a board response envelope where the live mailboxes keep them."""
        outbox = self.vault / "departments" / namespace / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / name).write_text(body, encoding="utf-8")

    def test_empty_week_issues_no_request_and_writes_no_file(self):
        """The regression. An empty vault must not reach /summarize at all."""
        exit_code = asyncio.run(runner.main())

        self.assertEqual(
            RecordingClient.calls,
            [],
            "the runner POSTed to /summarize with no evidence collected; "
            "a model asked for six sections over an empty corpus invents them",
        )
        self.assertEqual(
            self.written_reviews(),
            [],
            "the runner wrote a weekly review for a week it collected no evidence for",
        )
        self.assertEqual(exit_code, 0, "an empty week is not an error; it must exit 0")

    def test_evidence_below_the_floor_is_treated_as_empty(self):
        """Paths that resolve but hold nothing of substance are still no evidence."""
        self.seed_handoff("2026-08-05-empty.md", "\n\n   \n")
        self.seed_envelope("coding", "TASK-blank-response.md", "")

        exit_code = asyncio.run(runner.main())

        self.assertEqual(RecordingClient.calls, [], "whitespace is not evidence")
        self.assertEqual(self.written_reviews(), [])
        self.assertEqual(exit_code, 0)

    def test_positive_control_real_evidence_does_reach_summarize(self):
        """Proves the harness can observe a request and a file.

        Without this, the two assertions above would pass just as happily if the
        client were never wired up or main() died before reaching it -- a silent
        no-op and a working guard print the same empty output.
        """
        today = runner.datetime.date.today()
        week_start = today - runner.datetime.timedelta(days=today.weekday())

        self.seed_handoff(
            f"{week_start.isoformat()}-tmux-ux-polish-handoff.md",
            "# Handoff\n\n" + "Reworked the tmux status line. " * 20,
        )
        self.seed_envelope(
            "coding",
            "TASK-2026-08-09-1045-weekly-review-guard-response.md",
            "---\nstatus: complete\n---\n\n" + "Repointed the collectors. " * 20,
        )

        exit_code = asyncio.run(runner.main())

        self.assertEqual(
            len(RecordingClient.calls), 1, "real evidence must reach /summarize"
        )
        self.assertEqual(len(self.written_reviews()), 1, "a real week gets a document")
        self.assertEqual(exit_code, 0)

        payload = RecordingClient.payloads[0]

        # Requirement 2: both collectors point at sources that carry data.
        self.assertIn("tmux-ux-polish-handoff", payload["text"])
        self.assertIn("Repointed the collectors.", payload["text"])

        # Requirement 3: the instructions forbid inventing what is not supplied.
        instructions = payload["instructions"].lower()
        self.assertIn("only", instructions)
        self.assertIn("no evidence", instructions)


if __name__ == "__main__":
    unittest.main()
