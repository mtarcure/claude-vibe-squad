#!/usr/bin/env python3
"""Phase 1a: the distiller must resolve its CLI from the same authority as dispatch.

Memory autocapture stopped writing notes on 2026-08-29 and stayed down: 73 lost
notes in seven days, and doctor has warned on every run since. The cause is a
split source of truth, not a broken distiller.

`scripts/python/seatbelt_profile.py` holds `LANE_CLI_PATHS`, which maps the
`gemini` ROUTING identifier to the `agy` executable -- Antigravity's CLI
replaced the retired `gemini` binary for that lane, and the dispatch rail moved
with it. Autocapture did not: it calls `shutil.which("gemini")`, which still
resolves the retired binary, and that binary now fails every call with
`IneligibleTierError` because Google discontinued the tier.

So the two paths disagreed, and nothing enforced their agreement -- exactly the
"one fact, one home" failure in root CLAUDE.md Hard Rule 10.

These tests pin the agreement and the flag shape. They are static: running the
real distiller would make a live model call.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTOCAPTURE = REPO_ROOT / "plugins" / "chrono-vault" / "autocapture.py"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "python"))
import seatbelt_profile  # noqa: E402


class AutocaptureLaneAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = AUTOCAPTURE.read_text(encoding="utf-8")

    def test_distiller_resolves_the_gemini_lane_to_agy(self) -> None:
        """Whatever autocapture launches must be what dispatch launches."""
        expected = seatbelt_profile.LANE_CLI_PATHS["gemini"]
        self.assertEqual(
            expected.name,
            "agy",
            "seatbelt_profile is the authority for lane executables; if this "
            "changed, update the distiller with it rather than around it.",
        )
        # Assert the POSITIVE: the distiller consults the authority. Asserting
        # the absence of a literal `shutil.which("gemini")` passed vacuously --
        # the helper is generic (`shutil.which(cli)`) and the lane name only
        # appears at the call site, so the string never existed to be absent.
        self.assertIn(
            "LANE_CLI_PATHS",
            self.source,
            "the distiller resolves its CLI independently of "
            "seatbelt_profile.LANE_CLI_PATHS, so the two can drift -- and did, "
            "for 12 days and 73 lost notes. Resolve through the authority.",
        )

    def test_distill_command_carries_no_retired_flags(self) -> None:
        """agy rejects the old gemini CLI's flags.

        Verified against the installed binary: agy exposes --model, --effort
        (low|medium|high), --mode (accept-edits|plan), --output-format and
        --print. It has no -m, no -e, and no --approval-mode.
        `test_lane_agy_repoint.py:60-65` pins the same retired list for the
        dispatch rail.
        """
        match = re.search(r"command = \[(.*?)\n    \]", self.source, re.S)
        self.assertIsNotNone(match, "distill command list not found")
        command = match.group(1)
        for retired in ('"--approval-mode"', '"-e"', '"-m"'):
            self.assertNotIn(
                retired,
                command,
                f"{retired} is a retired gemini-CLI flag; agy does not accept it.",
            )

    def test_distill_command_uses_agy_flag_names(self) -> None:
        match = re.search(r"command = \[(.*?)\n    \]", self.source, re.S)
        self.assertIsNotNone(match, "distill command list not found")
        command = match.group(1)
        for required in ('"--model"', '"--print"'):
            self.assertIn(
                required,
                command,
                f"{required} is agy's flag name for this argument.",
            )

    def test_distiller_does_not_export_retired_gemini_cli_config(self) -> None:
        self.assertNotIn(
            "GEMINI_CLI_TRUST_WORKSPACE",
            self.source,
            "agy exposes no such environment contract; this setting belonged "
            "to the retired standalone Gemini CLI",
        )


if __name__ == "__main__":
    unittest.main()
