#!/usr/bin/env python3
"""The toolkit verifier must probe the CLI the dispatch rail actually launches.

`bin/dispatch-toolkit-verify.sh` probed the `gemini` binary while
`seatbelt_profile.LANE_CLI_PATHS` routes the gemini lane to `agy`. So the
verifier audited a CLI the squad stopped using: its six "gemini lists X but
does not enumerate it" warnings -- including one for perplexity -- described
the retired binary, while a live `agy mcp list` shows
chrono-research-arsenal enabled.

This is the same split-source-of-truth defect that took memory autocapture
down for 12 days and 73 notes (`4928b84b`): one fact, two homes, drifted.
Root CLAUDE.md Hard Rule 10.

The flag differs too, which is why this cannot be a blind rename: the old
`gemini mcp list` required `-d` to print, and `agy mcp list` REJECTS `-d`
("flags provided but not defined: -d") -- verified against the installed
binary.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFIER = REPO_ROOT / "bin" / "dispatch-toolkit-verify.sh"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "python"))
import seatbelt_profile  # noqa: E402


class ToolkitVerifyLaneAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = VERIFIER.read_text(encoding="utf-8")

    def _clis(self) -> list[str]:
        match = re.search(r"^CLIS=\(([^)]*)\)", self.source, re.M)
        self.assertIsNotNone(match, "CLIS=(...) not found in the verifier")
        return match.group(1).split()

    def _lanes(self) -> list[str]:
        match = re.search(r"^LANES=\(([^)]*)\)", self.source, re.M)
        self.assertIsNotNone(match, "LANES=(...) not found in the verifier")
        return match.group(1).split()

    def test_every_lane_probes_the_cli_dispatch_launches(self) -> None:
        """Catches: any lane's probe drifting from LANE_CLI_PATHS, in either
        direction. Not gemini-specific on purpose -- the next drift will be a
        different lane, and a gemini-only assertion would not see it."""
        lanes, clis = self._lanes(), self._clis()
        self.assertEqual(len(lanes), len(clis), "LANES and CLIS are misaligned")
        # The verifier's lane labels use the routing name; LANE_CLI_PATHS keys
        # on the same names except gpt-codex, whose routing key is `codex`.
        alias = {"gpt-codex": "codex"}
        for lane, cli in zip(lanes, clis):
            key = alias.get(lane, lane)
            expected = seatbelt_profile.LANE_CLI_PATHS.get(key)
            self.assertIsNotNone(expected, f"no LANE_CLI_PATHS entry for {key}")
            self.assertEqual(
                cli, expected.name,
                f"the verifier probes {cli!r} for lane {lane!r} but dispatch "
                f"launches {expected.name!r}; the verifier is auditing a CLI "
                "the squad does not use",
            )

    def test_the_retired_gemini_d_flag_is_gone(self) -> None:
        """`agy mcp list` rejects -d: 'flags provided but not defined: -d'.

        Catches: renaming the CLI without dropping the old binary's flag, which
        would make every gemini-lane probe fail rather than report an inventory.
        """
        listing = re.search(r"mcp_list_for_cli\(\) {(.*?)\n}", self.source, re.S)
        self.assertIsNotNone(listing, "mcp_list_for_cli() not found")
        # Strip comments first. The branch deliberately EXPLAINS the retired
        # flag in prose, and a naive scan matches that explanation rather than
        # the code -- the same trap that made three earlier tests in this repo
        # vacuous by matching the very comment their own fix had written.
        for line in listing.group(1).splitlines():
            code = line.split("#", 1)[0]
            if "mcp list" in code and re.search(r"(?<!-)-d\b", code):
                self.fail(f"a retired `-d` flag survives in: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
