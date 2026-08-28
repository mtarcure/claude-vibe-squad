"""Consumer oracle for universal rails in the assembled dispatch brief."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLKIT = ROOT / "shared" / "dispatch-toolkit.sh"

# These are deliberately the review's observable markers, not source-line
# locations. The oracle below renders the same toolkit output that send-task.sh
# appends to every packet, so a marker that remains in a dead source branch does
# not satisfy the test.
REQUIRED_BRIEF_MARKERS = (
    "single digits",
    "target allowlist",
    "dry_run status",
    "only writer",
    "Kimi subagents",
    "sole writer",
    "COORDINATION REQUESTED",
    "OPERATOR DECISION REQUIRED",
    "residue your own run generated",
)


def render_assembled_brief() -> str:
    """Render the production toolkit contribution for an ordinary dispatch."""

    result = subprocess.run(
        [
            "bash",
            str(TOOLKIT),
            "coding",
            "gpt-codex",
            "project",
            "systems-engineer",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"dispatch brief render failed: {result.stderr}")
    return result.stdout


def assert_required_brief_markers(brief: str) -> None:
    """Fail closed when any universal worker rail is absent from delivery."""

    missing = [marker for marker in REQUIRED_BRIEF_MARKERS if marker not in brief]
    if missing:
        raise AssertionError(
            "assembled dispatch brief missing required rail marker(s): "
            + ", ".join(missing)
        )


class DispatchToolkitRailTests(unittest.TestCase):
    def test_required_rails_reach_the_assembled_brief(self) -> None:
        assert_required_brief_markers(render_assembled_brief())


if __name__ == "__main__":
    unittest.main()
