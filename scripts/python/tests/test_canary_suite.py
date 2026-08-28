#!/usr/bin/env python3
"""bin/canary.sh — the properties that make it a gate rather than decoration.

WHY THIS FILE EXISTS
  This suite is in the awkward position of being a unit test for a program
  whose entire premise is that unit tests cannot measure capability. It does
  not try to. It pins the four properties that decide whether the live probes
  are worth believing, every one of them learned from a green-but-broken case:

    1. Every probe demonstrably FAILS when its capability is broken. Four
       capabilities shipped green and dead in one build -- board fan-out,
       swarm, the notification spine, anti-affinity review -- and one of them
       still passed a 35-test suite with its enforcement replaced by
       ``if False:``. A canary that cannot fail is not a gate.
    2. Every probe demonstrably PASSES on a working fixture. A probe stuck at
       FAIL satisfies every inversion above while measuring nothing.
    3. NOT MEASURED is never scored as a pass, and never collapses to a
       boolean. Same reason doctor.sh carries COULD NOT DETERMINE.
    4. The skills oracle is not quotable from the packet. If the packet
       contained the sentinel, a lane could echo it back without ever loading
       the skill -- and the probe would certify "fired" for a projection.
    5. The expected MCP surface is not quotable from the packet. The worker
       must enumerate and exercise its own live runtime namespaces; a config
       read or echoed allowlist is not capability evidence.

SAFETY
  No test here writes to the live private vault. Every invocation either
  passes ``--no-memory-write`` or runs with ``CHRONO_VAULT_ROOT`` unset, and
  the write path is refused before ``notes.record`` is reached. Registry probes
  run against ``CANARY_ROOT_UNDER_TEST`` fixtures in a temp directory; the only
  live-tree assertions read the probe-canary skill, canary expectation, and its
  canonical documentation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
CANARY = REPO_ROOT / "bin" / "canary.sh"
SKILL_FILE = REPO_ROOT / ".claude" / "skills" / "probe-canary" / "SKILL.md"
MCP_SURFACE_DOC = REPO_ROOT / "docs" / "board-mcp-surface.md"
MCP_MARKER = "MCP_SURFACE_JSON:"
CONTEXT_SCHEMA = "go-live-trusted-context/v1"

# Duplicated from canary.sh on purpose, and the duplication is the point: if
# either copy drifts, test_sentinel_is_live_in_the_skill_file below goes red
# and names the drift. An oracle nobody notices going stale is how a probe
# starts reporting on nothing.
SENTINEL = "project-scoped skill loading works"


def expected_mcp_surface() -> list[str]:
    """Read the executable expectation without maintaining a third copy."""
    prefix = "MCP_SURFACE_EXPECTED_JSON="
    declaration = next(
        line for line in CANARY.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    )
    return json.loads(declaration.removeprefix(prefix).strip("'"))


def _codex_apps_measurement_errors(document: str) -> list[str]:
    """Pin the measured override/control pair and its interpretation."""
    marker = "## Per-server disable experiment"
    if marker not in document:
        return [marker]
    section = document.split(marker, 1)[1].split("\n## ", 1)[0]
    required = (
        "Status: **MEASURED — the override suppresses the bridge.**",
        "| with `-c 'mcp_servers.codex_apps="
        "{enabled=false,command=\"/usr/bin/false\"}'` | **0** (`[]`) |",
        "| **positive control** — same command, override removed | **125** |",
        "an empty array means the existing override\nsuppresses the bridge.",
    )
    errors = [value for value in required if value not in section]
    if "override does not suppress the bridge" in section:
        errors.append("inverted suppression verdict")
    return errors


def run_canary(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke canary.sh with the live vault write path disabled."""
    env = dict(os.environ)
    env.pop("CHRONO_VAULT_ROOT", None)
    if root is not None:
        env["CANARY_ROOT_UNDER_TEST"] = str(root)
    return subprocess.run(
        ["bash", str(CANARY), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=300,
    )


def status_of(output: str, probe: str) -> str:
    """Return PASS / FAIL / NOT MEASURED for one probe, or '' if absent."""
    for line in output.splitlines():
        if not line.startswith("["):
            continue
        status, _, rest = line[1:].partition("]")
        if rest.split() and rest.split()[0] == probe:
            return status.strip()
    return ""


def write_fixture(root: Path, entry: dict, task_id: str) -> None:
    (root / "_state").mkdir(parents=True, exist_ok=True)
    (root / "_state" / "active-tasks.json").write_text(
        json.dumps({task_id: entry}), encoding="utf-8"
    )


def write_persisted_prompt(
    root: Path, entry: dict, task_id: str, prompt: str
) -> None:
    """Write the controller-built brief that remains after inbox consumption."""
    attempt_id = entry["delivery_attempt_id"]
    generation = entry["delivery_generation"]
    context_dir = root / "_state" / "board-dispatch"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / f"{task_id}.{attempt_id}.context.json").write_text(
        json.dumps(
            {
                "schema": CONTEXT_SCHEMA,
                "authority": {
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "generation": generation,
                },
                "task_prompt": prompt,
            }
        ),
        encoding="utf-8",
    )


class SelfTestIsTheGate(unittest.TestCase):
    """canary.sh --self-test is the inverted-control suite; it must hold."""

    def test_every_inversion_and_control_holds(self) -> None:
        result = run_canary("--self-test")
        self.assertEqual(
            result.returncode,
            0,
            f"--self-test failed:\n{result.stdout}\n{result.stderr}",
        )
        self.assertNotIn("INVERSION FAILED", result.stdout)
        self.assertNotIn("CONTROL FAILED", result.stdout)
        # An empty self-test would pass both assertions above while proving
        # nothing -- the same silent-no-op shape the probes guard against.
        self.assertGreaterEqual(result.stdout.count("inversion holds"), 10)
        self.assertGreaterEqual(result.stdout.count("control holds"), 5)


class ThreeOutcomesNeverTwo(unittest.TestCase):
    """pass / fail / NOT MEASURED, and NOT MEASURED is never a pass."""

    def test_absent_registry_is_unmeasured_not_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_canary("--task", "TASK-X", "--no-memory-write", root=root)
        for probe in ("dispatch", "round_trip", "labelling", "mcp_surface"):
            self.assertEqual(
                status_of(result.stdout, probe),
                "NOT MEASURED",
                f"{probe} scored an unreadable registry:\n{result.stdout}",
            )
        # Exit 2, not 0: an unmeasured run must not read as a healthy one.
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_a_broken_capability_exits_one(self) -> None:
        task = "TASK-2099-01-01-0004-brk"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(
                root,
                {
                    "source_namespace": "coding",
                    "status": "complete",
                    "dispatched_at": "2099-01-01T00:00:00+00:00",
                    "return_artifact": f"departments/coding/outbox/{task}-response.md",
                    # Queued and never claimed: the shape a fan-out that was
                    # refused before host admission actually leaves behind.
                    "delivery_history": [{"event": "queued"}],
                },
                task,
            )
            result = run_canary("--task", task, "--no-memory-write", root=root)
        self.assertEqual(status_of(result.stdout, "dispatch"), "FAIL", result.stdout)
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_unknown_argument_is_refused(self) -> None:
        # Silently ignoring `--tsk` would run the default path while the caller
        # believed a task had been adjudicated. 64 is EX_USAGE, as in doctor.sh.
        result = run_canary("--tsk", "TASK-X")
        self.assertEqual(result.returncode, 64, result.stdout + result.stderr)


class SkillsProbeMeasuresFiringNotProjection(unittest.TestCase):
    def test_sentinel_is_live_in_the_skill_file(self) -> None:
        if not SKILL_FILE.is_file():
            self.skipTest(f"NOT MEASURED: skill oracle is absent: {SKILL_FILE}")

        # The oracle rots silently otherwise: reword the skill and the probe
        # keeps running while it can no longer detect anything.
        self.assertIn(
            SENTINEL,
            SKILL_FILE.read_text(encoding="utf-8"),
            "the probe-canary sentinel changed; canary.sh SKILL_SENTINEL and this "
            "test must be updated together or the skills probe measures nothing",
        )

    def test_emitted_packet_never_quotes_the_sentinel(self) -> None:
        # If it did, a lane could satisfy the probe by echoing the packet back
        # without loading the skill, and "projected" would certify as "fired".
        result = run_canary("--emit-packet", "TASK-2099-01-01-0005-pkt")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SENTINEL, result.stdout)
        self.assertIn("probe-canary", result.stdout)
        self.assertIn("run_id: TASK-2099-01-01-0005-pkt", result.stdout)
        self.assertIn("to_model: claude", result.stdout)
        self.assertIn("specialist: backend-engineer", result.stdout)
        self.assertNotIn(MCP_MARKER, result.stdout)

    def test_emitted_mcp_packet_never_quotes_expected_surface(self) -> None:
        result = run_canary(
            "--emit-mcp-packet", "TASK-2099-01-01-0008-mcp-pkt"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("to_model: gpt-codex", result.stdout)
        self.assertIn("specialist: systems-engineer", result.stdout)
        self.assertIn("run_id: TASK-2099-01-01-0008-mcp-pkt", result.stdout)
        self.assertIn(MCP_MARKER, result.stdout)
        self.assertIn("codex_apps_tools", result.stdout)
        self.assertIn("mcp__codex_apps__", result.stdout)
        self.assertNotIn(
            json.dumps(expected_mcp_surface(), separators=(",", ":")),
            result.stdout,
            "the MCP packet quoted the expected answer instead of asking for a probe",
        )

    def test_persisted_assembled_brief_can_reach_pass(self) -> None:
        """The ask oracle survives after the dispatcher consumes the inbox packet."""
        task = "TASK-2099-01-01-0009-persisted"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / ".claude" / "skills" / "probe-canary"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(f"**{SENTINEL}**\n", encoding="utf-8")
            outbox = root / "departments" / "coding" / "outbox"
            outbox.mkdir(parents=True)
            (outbox / f"{task}-response.md").write_text(
                f"The loaded skill says {SENTINEL}.\n", encoding="utf-8"
            )
            entry = {
                "source_namespace": "coding",
                "status": "complete",
                "dispatched_at": "2099-01-01T00:00:00+00:00",
                "delivery_attempt_id": "d-persisted",
                "delivery_generation": 1,
                "return_artifact": f"departments/coding/outbox/{task}-response.md",
                "delivery_history": [
                    {"event": "queued"},
                    {"event": "board-claimed"},
                    {"event": "terminal"},
                ],
            }
            write_fixture(root, entry, task)
            write_persisted_prompt(
                root,
                entry,
                task,
                "Invoke the project skill named probe-canary and quote it.",
            )
            self.assertFalse((root / "departments/coding/inbox" / f"{task}.md").exists())
            self.assertFalse((root / "departments/coding/archive" / f"{task}.md").exists())
            result = run_canary("--task", task, "--no-memory-write", root=root)
        self.assertEqual(status_of(result.stdout, "skills"), "PASS", result.stdout)

    def test_a_task_never_asked_is_unmeasured_not_failed(self) -> None:
        """An ordinary board task is not evidence about skills either way."""
        task = "TASK-2099-01-01-0006-ord"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / ".claude" / "skills" / "probe-canary"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(f"**{SENTINEL}**\n", encoding="utf-8")
            outbox = root / "departments" / "coding" / "outbox"
            outbox.mkdir(parents=True)
            # Deliberately quote both sentinels in the response: response text
            # is output, never proof the worker was asked to produce evidence.
            (outbox / f"{task}-response.md").write_text(
                f"ordinary work; {SENTINEL}; {MCP_MARKER}\n", encoding="utf-8"
            )
            entry = {
                "source_namespace": "coding",
                "status": "complete",
                "dispatched_at": "2099-01-01T00:00:00+00:00",
                "delivery_attempt_id": "d-ordinary",
                "delivery_generation": 1,
                "return_artifact": f"departments/coding/outbox/{task}-response.md",
                "delivery_history": [
                    {"event": "queued"},
                    {"event": "board-claimed"},
                    {"event": "terminal"},
                ],
            }
            write_fixture(root, entry, task)
            write_persisted_prompt(root, entry, task, "Perform ordinary work only.")
            result = run_canary("--task", task, "--no-memory-write", root=root)
        self.assertEqual(
            status_of(result.stdout, "skills"), "NOT MEASURED", result.stdout
        )
        self.assertEqual(
            status_of(result.stdout, "mcp_surface"), "NOT MEASURED", result.stdout
        )

    def test_malformed_persisted_brief_is_unmeasured_not_a_crash(self) -> None:
        task = "TASK-2099-01-01-0011-malformed"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / ".claude" / "skills" / "probe-canary"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(f"**{SENTINEL}**\n", encoding="utf-8")
            outbox = root / "departments" / "coding" / "outbox"
            outbox.mkdir(parents=True)
            (outbox / f"{task}-response.md").write_text(
                f"{SENTINEL}\n", encoding="utf-8"
            )
            entry = {
                "source_namespace": "coding",
                "status": "complete",
                "dispatched_at": "2099-01-01T00:00:00+00:00",
                "delivery_attempt_id": "d-malformed",
                "delivery_generation": 1,
                "return_artifact": f"departments/coding/outbox/{task}-response.md",
                "delivery_history": [
                    {"event": "queued"},
                    {"event": "board-claimed"},
                    {"event": "terminal"},
                ],
            }
            write_fixture(root, entry, task)
            write_persisted_prompt(root, entry, task, "Invoke probe-canary.")
            context = (
                root
                / "_state"
                / "board-dispatch"
                / f"{task}.d-malformed.context.json"
            )
            context.write_text("[]\n", encoding="utf-8")
            result = run_canary("--task", task, "--no-memory-write", root=root)
        self.assertEqual(
            status_of(result.stdout, "skills"), "NOT MEASURED", result.stdout
        )
        self.assertIn("failed task/attempt binding", result.stdout)


class McpSurfaceMeasuresTheWorkerNotConfig(unittest.TestCase):
    def run_surface_fixture(
        self,
        *,
        server_prefixes: list[str],
        successful_probes: list[str],
        codex_apps_tools: list[str] | None = None,
    ) -> subprocess.CompletedProcess:
        task = "TASK-2099-01-01-0007-mcp"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outbox = root / "departments" / "coding" / "outbox"
            outbox.mkdir(parents=True)
            report = {
                "codex_apps_tools": (
                    codex_apps_tools
                    if codex_apps_tools is not None
                    else ["mcp__codex_apps__fixture"]
                    if "codex_apps" in server_prefixes
                    else []
                ),
                "inventory_command": "fixture live tool manifest",
                "server_prefixes": server_prefixes,
                "successful_probes": successful_probes,
            }
            (outbox / f"{task}-response.md").write_text(
                f"{MCP_MARKER} {json.dumps(report, separators=(',', ':'))}\n",
                encoding="utf-8",
            )
            entry = {
                "source_namespace": "coding",
                "status": "complete",
                "dispatched_at": "2099-01-01T00:00:00+00:00",
                "delivery_attempt_id": "d-mcp",
                "delivery_generation": 1,
                "return_artifact": f"departments/coding/outbox/{task}-response.md",
                "delivery_history": [
                    {"event": "queued"},
                    {"event": "board-claimed"},
                    {"event": "terminal"},
                ],
            }
            write_fixture(root, entry, task)
            write_persisted_prompt(
                root,
                entry,
                task,
                f"Measure the live tool manifest and return {MCP_MARKER} evidence.",
            )
            return run_canary("--mcp-task", task, "--no-memory-write", root=root)

    def test_exact_live_surface_and_calls_pass(self) -> None:
        expected = expected_mcp_surface()
        result = self.run_surface_fixture(
            server_prefixes=expected,
            successful_probes=expected,
        )
        self.assertEqual(status_of(result.stdout, "mcp_surface"), "PASS", result.stdout)

    def test_missing_namespace_fails(self) -> None:
        expected = expected_mcp_surface()
        broken = expected[:-1]
        result = self.run_surface_fixture(
            server_prefixes=broken,
            successful_probes=broken,
        )
        self.assertEqual(status_of(result.stdout, "mcp_surface"), "FAIL", result.stdout)

    def test_visible_but_uncallable_namespace_fails(self) -> None:
        expected = expected_mcp_surface()
        result = self.run_surface_fixture(
            server_prefixes=expected,
            successful_probes=expected[:-1],
        )
        self.assertEqual(status_of(result.stdout, "mcp_surface"), "FAIL", result.stdout)

    def test_visible_bridge_without_tool_inventory_is_unmeasured(self) -> None:
        expected = expected_mcp_surface()
        result = self.run_surface_fixture(
            server_prefixes=expected,
            successful_probes=expected,
            codex_apps_tools=[],
        )
        self.assertEqual(
            status_of(result.stdout, "mcp_surface"), "NOT MEASURED", result.stdout
        )

    def test_documented_surface_matches_executable_expectation(self) -> None:
        self.assertTrue(MCP_SURFACE_DOC.is_file(), f"missing {MCP_SURFACE_DOC}")
        document = MCP_SURFACE_DOC.read_text(encoding="utf-8")
        encoded = json.dumps(expected_mcp_surface(), separators=(",", ":"))
        self.assertIn(
            f"Canary contract (runtime prefixes): `{encoded}`",
            document,
        )

    def test_document_records_complete_codex_apps_inventory(self) -> None:
        document = MCP_SURFACE_DOC.read_text(encoding="utf-8")
        documented_tools = re.findall(
            r"^mcp__codex_apps__[A-Za-z0-9_]+$", document, flags=re.MULTILINE
        )
        self.assertEqual(len(documented_tools), 125)
        self.assertEqual(documented_tools, sorted(set(documented_tools)))
        self.assertIn("mcp_servers.codex_apps={enabled=false", document)
        # The disable experiment was NOT MEASURED until 2026-08-28, when Chrono ran
        # it from the main checkout (a worker may not launch a second Codex CLI).
        # The guard's point survives the flip: a suppression verdict is only
        # meaningful alongside the positive control, because an empty array is
        # equally consistent with a probe that never had the bridge at all.
        self.assertEqual(_codex_apps_measurement_errors(document), [])

    def test_document_guard_rejects_an_inverted_measurement(self) -> None:
        document = MCP_SURFACE_DOC.read_text(encoding="utf-8")
        mutated = document.replace(
            "Status: **MEASURED — the override suppresses the bridge.**",
            "Status: **MEASURED — the override does not suppress the bridge.**",
            1,
        ).replace(
            "| with `-c 'mcp_servers.codex_apps="
            "{enabled=false,command=\"/usr/bin/false\"}'` | **0** (`[]`) |",
            "| with `-c 'mcp_servers.codex_apps="
            "{enabled=false,command=\"/usr/bin/false\"}'` | **125** |",
            1,
        ).replace(
            "| **positive control** — same command, override removed | **125** |",
            "| **positive control** — same command, override removed | **0** (`[]`) |",
            1,
        ).replace(
            "an empty array means the existing override\nsuppresses the bridge.",
            "an empty array means the existing override\ndoes not suppress the bridge.",
            1,
        )
        self.assertNotEqual(mutated, document, "measurement mutation did not apply")
        self.assertNotEqual(_codex_apps_measurement_errors(mutated), [])


class MemoryProbeFailsClosed(unittest.TestCase):
    def test_unset_vault_root_is_unmeasured(self) -> None:
        # Board spawns have shipped without CHRONO_VAULT_ROOT; the vault then
        # fails closed, and a failed-closed vault must not read as a live one.
        result = run_canary()
        self.assertEqual(
            status_of(result.stdout, "memory"), "NOT MEASURED", result.stdout
        )

    def test_read_only_mode_cannot_claim_a_round_trip(self) -> None:
        result = run_canary("--no-memory-write")
        self.assertEqual(
            status_of(result.stdout, "memory"), "NOT MEASURED", result.stdout
        )


if __name__ == "__main__":
    unittest.main()
