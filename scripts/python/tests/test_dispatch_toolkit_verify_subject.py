#!/usr/bin/env python3
"""G-N1: bin/dispatch-toolkit-verify.sh must judge the toolkit it verifies.

The verifier used to read shared/dispatch-toolkit.sh as prose only: an awk
sweep over the source text for the "Expected Model Lane Tool Surface" block.
Nothing ever asked bash whether that file parses, and nothing ever ran it. A
toolkit that cannot be sourced, and a toolkit that emits nothing at all, both
produced "PASS: all expected MCP enumerations verified across 5 model lanes."

The three controls below are the measured shapes of that hole:

  * an ``esac`` typo -- the toolkit exits non-zero for every lane, so
    send-task.sh appends a broken injection;
  * every heredoc redirected to /dev/null -- the toolkit runs clean and
    injects nothing, which no syntax check can see;
  * the bare ``case`` fragment with no surrounding script -- the shape the
    verifier's own prose parser cannot distinguish from a real toolkit.

Assertions are on exit code and operator-visible output, never on the
verifier's source text: a check that reads its subject's source is precisely
the defect under repair.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
VERIFY = ROOT / "bin" / "dispatch-toolkit-verify.sh"
TOOLKIT = ROOT / "shared" / "dispatch-toolkit.sh"


def verifier_lane_clis() -> dict[str, str]:
    """Read the lane-to-CLI pairing from the verifier's parallel arrays."""
    source = VERIFY.read_text(encoding="utf-8")
    arrays = {}
    for name in ("LANES", "CLIS"):
        match = re.search(rf"^{name}=\(([^)]*)\)", source, re.M)
        if match is None:
            raise RuntimeError(f"{name}=(...) not found in {VERIFY}")
        arrays[name] = match.group(1).split()
    if len(arrays["LANES"]) != len(arrays["CLIS"]):
        raise RuntimeError("verifier LANES and CLIS arrays are misaligned")
    return dict(zip(arrays["LANES"], arrays["CLIS"]))


LANE_CLIS = verifier_lane_clis()
LANES = tuple(LANE_CLIS)
# One expected MCP per lane, matched by the inventory fixtures below.
LANE_MCP = {
    "gpt-codex": "alpha",
    "claude": "bravo",
    "gemini": "charlie",
    "grok": "echo",
    "kimi": "delta",
}

SURFACE_HEADER = "## Expected Model Lane Tool Surface"


def healthy_toolkit_source() -> str:
    """A runnable stand-in shaped like the real toolkit.

    Same contract send-task.sh uses: ``bash <toolkit> <namespace> <to-model>``
    prints the markdown block for that lane on stdout.
    """
    branches = "".join(
        f"    {lane})\n"
        "        cat <<'EOF'\n"
        "\n"
        f"{SURFACE_HEADER}\n"
        "\n"
        f"This lane expects `{mcp}`. Later tools include `not_a_server`.\n"
        "EOF\n"
        "        ;;\n"
        for lane, mcp in LANE_MCP.items()
    )
    return '#!/bin/bash\nTO_MODEL="${2:-}"\ncase "${TO_MODEL}" in\n' + branches + "esac\n"


def rendered_expected_mcps(lane: str) -> set[str]:
    rendered = subprocess.run(
        ["/bin/bash", str(TOOLKIT), "", lane],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    block = rendered.split(SURFACE_HEADER, 1)[1].strip().split("\n\n", 1)[0]
    first_sentence = re.split(r"\.\s", block, maxsplit=1)[0]
    return set(re.findall(r"`([A-Za-z0-9][A-Za-z0-9._:-]*)`", first_sentence))


class DispatchToolkitSubjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="toolkit-subject-")
        self.root = Path(self.temporary.name)
        self.inventory = self.root / "inventory"
        self.inventory.mkdir()
        self.write_inventories()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_inventories(self) -> None:
        """Per-CLI fixtures whose contents exactly match LANE_MCP."""
        fixture_by_lane = {
            "gpt-codex": json.dumps([{"name": "alpha"}]),
            "claude": "Checking MCP server health…\nbravo: /bin/bravo - ✔ Connected\n",
            "gemini": (
                "NAME                     TYPE   STATUS   COMMAND/URL\n"
                "charlie                  stdio  enabled  /bin/charlie\n"
            ),
            "grok": "MCP Servers (1)\n└── echo (stdio)\n",
            "kimi": "delta /bin/delta enabled\n",
        }
        for lane, contents in fixture_by_lane.items():
            (self.inventory / f"{LANE_CLIS[lane]}.txt").write_text(
                contents, encoding="utf-8"
            )

    def write_toolkit(self, source: str) -> Path:
        toolkit = self.root / "dispatch-toolkit.sh"
        toolkit.write_text(source, encoding="utf-8")
        return toolkit

    def run_verify(self, toolkit: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(VERIFY)],
            cwd=ROOT,
            env={
                **os.environ,
                "DISPATCH_TOOLKIT_UNDER_TEST": str(toolkit),
                "DISPATCH_TOOLKIT_MCP_LIST_DIR_UNDER_TEST": str(self.inventory),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def assert_red(self, result: subprocess.CompletedProcess[str]) -> None:
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertNotIn("PASS:", result.stdout, combined)

    # --- positive control -------------------------------------------------

    def test_runnable_toolkit_still_passes(self) -> None:
        result = self.run_verify(self.write_toolkit(healthy_toolkit_source()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS:", result.stdout)

    def test_known_claude_first_party_name_is_safely_canonicalized(self) -> None:
        """Claude emits spaces/dots for reviewed first-party connectors.

        The verifier must compare their established shell-safe adapter name,
        not reject the entire Claude inventory or accept arbitrary free-form
        names.
        """
        (self.inventory / f"{LANE_CLIS['claude']}.txt").write_text(
            "Checking MCP server health…\n"
            "bravo: /bin/bravo - ✔ Connected\n"
            "claude.ai Google Drive: https://example.invalid/mcp - ✔ Connected\n",
            encoding="utf-8",
        )
        result = self.run_verify(self.write_toolkit(healthy_toolkit_source()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS:", result.stdout)
        self.assertIn("role-scoped optional/global MCP", result.stdout)

    def test_shell_unsafe_claude_name_remains_fail_closed(self) -> None:
        marker = self.root / "unsafe-name-executed"
        (self.inventory / f"{LANE_CLIS['claude']}.txt").write_text(
            "Checking MCP server health…\n"
            f"`touch {marker}`: /bin/tool - ✔ Connected\n",
            encoding="utf-8",
        )
        result = self.run_verify(self.write_toolkit(healthy_toolkit_source()))
        self.assert_red(result)
        self.assertIn("COULD NOT DETERMINE: claude MCP inventory", result.stdout)
        self.assertFalse(marker.exists(), "an inventory name was evaluated by a shell")

    # --- the three measured breakages -------------------------------------

    def test_esac_typo_that_makes_the_toolkit_unrunnable_is_red(self) -> None:
        broken = healthy_toolkit_source().replace("\nesac\n", "\nesacX\n")
        # Positive control: the subject really is unrunnable.
        toolkit = self.write_toolkit(broken)
        self.assertNotEqual(
            subprocess.run(
                ["/bin/bash", "-n", str(toolkit)], capture_output=True
            ).returncode,
            0,
        )
        self.assert_red(self.run_verify(toolkit))

    def test_toolkit_that_emits_nothing_is_red(self) -> None:
        muted = healthy_toolkit_source().replace(
            "        cat <<'EOF'\n", "        cat >/dev/null <<'EOF'\n"
        )
        toolkit = self.write_toolkit(muted)
        # Positive control: it parses and runs clean, and injects nothing --
        # so no syntax check alone can catch this one.
        parse = subprocess.run(["/bin/bash", "-n", str(toolkit)], capture_output=True)
        self.assertEqual(parse.returncode, 0, parse.stderr)
        rendered = subprocess.run(
            ["/bin/bash", str(toolkit), "", "gpt-codex"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertEqual(rendered.stdout, "")
        self.assert_red(self.run_verify(toolkit))

    def test_bare_case_fragment_with_no_script_is_red(self) -> None:
        source = healthy_toolkit_source()
        fragment = source.split("case \"${TO_MODEL}\" in\n", 1)[1].replace(
            "\nesac\n", "\n"
        )
        toolkit = self.write_toolkit(fragment)
        self.assertNotIn("case ", toolkit.read_text(encoding="utf-8"))
        self.assert_red(self.run_verify(toolkit))

    # --- healthy-subject guard --------------------------------------------

    def test_real_toolkit_parses_and_renders_every_lane(self) -> None:
        """The repo's own toolkit must survive both new checks.

        This is the over-tightening guard: whatever the verifier now demands
        of a subject, shared/dispatch-toolkit.sh has to satisfy it.
        """
        parse = subprocess.run(
            ["/bin/bash", "-n", str(TOOLKIT)], capture_output=True, text=True
        )
        self.assertEqual(parse.returncode, 0, parse.stderr)
        for lane in LANES:
            with self.subTest(lane=lane):
                rendered = subprocess.run(
                    ["/bin/bash", str(TOOLKIT), "", lane],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                self.assertIn(SURFACE_HEADER, rendered.stdout)

    def test_real_toolkit_matches_probed_active_mcp_contracts(self) -> None:
        """Pin expectation corrections supported by native probes + registry."""
        codex = rendered_expected_mcps("gpt-codex")
        gemini = rendered_expected_mcps("gemini")
        kimi = rendered_expected_mcps("kimi")

        self.assertTrue(
            {"chrono-dedup", "chrono-recon"}.issubset(codex),
            f"Codex omits active installed MCPs: {sorted(codex)}",
        )
        self.assertNotIn(
            "sequential-thinking",
            gemini,
            "agy's global MCP ceiling does not expose sequential-thinking",
        )
        self.assertIn(
            "chrono-recon",
            kimi,
            "Kimi installs the registry-supported all-lane recon MCP",
        )


if __name__ == "__main__":
    unittest.main()
