"""Consumer oracle for universal rails in the assembled dispatch brief."""

from __future__ import annotations

import csv
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLKIT = ROOT / "shared" / "dispatch-toolkit.sh"
RUNTIME_MAP = ROOT / "shared" / "specialist-runtime-map.tsv"

UNIVERSAL_EVIDENCE_RAIL_MARKER = "The packet's premise is a claim, not a fact"
UNIVERSAL_EVIDENCE_RAIL_ITEMS = (
    UNIVERSAL_EVIDENCE_RAIL_MARKER,
    "A null, absent, or negative result needs a positive control",
    "Report what you measured and what you could not measure",
)
SECURITY_ONLY_DOCTRINE_MARKER = "## Verdict discipline"

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
    *UNIVERSAL_EVIDENCE_RAIL_ITEMS,
)


def render_assembled_brief(specialist: str) -> str:
    """Render the production toolkit contribution for an ordinary dispatch."""

    result = subprocess.run(
        [
            "bash",
            str(TOOLKIT),
            "coding",
            "gpt-codex",
            "project",
            specialist,
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


def specialist_safety(specialist: str) -> tuple[str, str]:
    """Resolve the fixture's real safety semantics from the production map."""

    with RUNTIME_MAP.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        row = next(item for item in rows if item["specialist"] == specialist)
    return row["safety_level"], row["heightened_risk"]


def assert_required_brief_markers(brief: str) -> None:
    """Fail closed when any universal worker rail is absent from delivery."""

    missing = [marker for marker in REQUIRED_BRIEF_MARKERS if marker not in brief]
    if missing:
        raise AssertionError(
            "assembled dispatch brief missing required rail marker(s): "
            + ", ".join(missing)
        )


class DispatchToolkitRailTests(unittest.TestCase):
    def test_required_rails_reach_medium_specialist_without_security_doctrine(
        self,
    ) -> None:
        self.assertEqual(specialist_safety("systems-engineer"), ("medium", "false"))
        brief = render_assembled_brief("systems-engineer")
        assert_required_brief_markers(brief)
        self.assertIn(UNIVERSAL_EVIDENCE_RAIL_MARKER, brief)
        self.assertNotIn(SECURITY_ONLY_DOCTRINE_MARKER, brief)

    def test_universal_rail_still_reaches_high_safety_specialist(self) -> None:
        self.assertEqual(specialist_safety("architect"), ("high", "false"))
        brief = render_assembled_brief("architect")
        assert_required_brief_markers(brief)
        self.assertIn(UNIVERSAL_EVIDENCE_RAIL_MARKER, brief)
        self.assertIn(SECURITY_ONLY_DOCTRINE_MARKER, brief)


if __name__ == "__main__":
    unittest.main()
