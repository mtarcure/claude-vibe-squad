#!/usr/bin/env python3
"""Plan D Task 5: doctor's findings have to be worth reading.

Doctor reported five warnings and zero issues on a healthy host, and several of
those warnings had been unchanged for days. A finding that fires permanently and
tells nobody what to do trains the reader to ignore the whole channel -- which is
how the four real failures of 2026-08-16 went unnoticed next to a green report.

Three calibrations are pinned here:

  * 5.1 the inbox backlog measures AGE, not only depth. Depth cannot tell eleven
    packets queued thirty seconds ago from eleven queued since Tuesday; on the
    maintainer's tree the old gate PASSED ten packets whose oldest was eleven
    days abandoned.
  * 5.2 instruction drift scans the surfaces the runtime reads, and a checkably
    false claim there is an ISSUE rather than a yellow line nobody acts on.
  * 5.3 the process audit names the PIDs it found. "extra non-squad CLI sessions
    detected" fired on every terminal the operator had open and named none of
    them.

SAFETY, read before touching anything here
------------------------------------------
No test in this file may reach the operator's live tmux session, processes or
doctor logs. Doctor prepends ``$HOME/.local/bin`` to PATH, so the ``ps``, ``tmux``
and ``stat`` stubs placed there WIN over the real binaries and doctor's whole view
of the machine comes from environment variables. No test starts a tmux server on
any socket, and none sends a signal to any process.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402
import doctor_fixture  # noqa: E402

ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])

DAY = 86400

# A ps whose entire process table is DOCTOR_TEST_PROC_ROWS: one
# `pid ppid etime pcpu argv...` record per line. It answers every format doctor
# asks for, including the `-o pid= -p $$` liveness canary, and reports nothing
# else -- so no test here can observe, or report on, the host's real processes.
PS_SCRIPTED = r"""#!/bin/bash
fmt=""
want=""
prev=""
for argument in "$@"; do
    case "$prev" in
        -o|-eo) fmt="$argument" ;;
        -p) want="$argument" ;;
    esac
    prev="$argument"
done
if [[ -n "$want" ]]; then
    if [[ "$fmt" == "args=" ]]; then
        printf '%s\n' "${DOCTOR_TEST_PROC_ROWS:-}" \
            | awk -v want="$want" '$1 == want { $1=""; $2=""; $3=""; $4="";
                sub(/^ +/, ""); print }'
        exit 0
    fi
    printf '%s\n' "$want"
    exit 0
fi
printf '%s\n' "${DOCTOR_TEST_PROC_ROWS:-}" | awk -v fmt="$fmt" '
    NF == 0 { next }
    {
        args = ""
        for (i = 5; i <= NF; i++) args = args (i > 5 ? " " : "") $i
        n = split($5, parts, "/")
        comm = parts[n]
        if (fmt == "pid=,ppid=,etime=,args=") print $1, $2, $3, args
        else if (fmt == "pid=,comm=") print $1, comm
        else if (fmt == "pid,ppid,etime,pcpu,comm") print $1, $2, $3, $4, comm
        else if (fmt == "pid,etime,pcpu,comm") print $1, $3, $4, comm
        else if (fmt == "pid,ppid,etime,pcpu,command") print $1, $2, $3, $4, args
    }
'
exit 0
"""

# An MCP audit that completes with per-server rows and a real finding: one
# REQUIRED server that will not initialize, one OPTIONAL one. Exit 1 is its
# documented "found issues" code.
MCP_AUDIT_WITH_FINDINGS = """#!/bin/bash
cat <<'ROWS'
## claude
- chrono-vault: tier=required registered=true reachable=true usable=false initialize_response=false
- chrono-recon: tier=optional registered=true reachable=true usable=false initialize_response=false
- chrono-research-arsenal: tier=optional registered=true reachable=true usable=true
ROWS
printf 'summary: issues=2 warnings=0 log=/tmp/doctor-fixture-mcp-audit.md\\n'
exit 1
"""

# stat is installed and answers nothing, for either flavour's spelling: the
# "packets are right here and doctor cannot date them" case.
STAT_DENIED = """#!/bin/bash
exit 1
"""


class DoctorCalibrationRunner(unittest.TestCase):
    """Shared throwaway-tree runner. Subclasses supply the state under test."""

    def run_doctor(self, *, env: dict[str, str] | None = None, setup=None):
        with tempfile.TemporaryDirectory(prefix="doctor-severity-") as temp:
            fixture = Path(temp)
            root = fixture / "root"
            doctor_fixture.install_doctor_helpers(ROOT, root)
            subprocess.run(
                ["git", "init", "-q"], cwd=root, check=True, capture_output=True
            )

            home = fixture / "home"
            local_bin = home / ".local" / "bin"
            doctor_fixture.write_stub(local_bin, "ps", doctor_fixture.EMPTY_PS)
            doctor_fixture.stub_launch_dependencies(local_bin, ROOT)

            environment = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "VAULT_ROOT": str(root),
                "TERM": "dumb",
                "LANG": "C",
                "TMPDIR": str(fixture),
            }
            environment.pop("CHRONO_DOCTOR_LOG_DIR", None)
            environment.pop("CHRONO_VAULT_ROOT", None)
            if setup is not None:
                setup(root, local_bin, environment)
            environment.update(env or {})

            result = subprocess.run(
                ["/bin/bash", str(root / "bin" / "doctor.sh")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            log_dir = home / ".local/state/chrono-vault/doctor-logs"
            summaries = sorted(log_dir.glob("*-summary.json"))
            self.assertEqual(
                len(summaries),
                1,
                f"doctor did not emit one summary: {result.stdout}{result.stderr}",
            )
            summary = json.loads(summaries[0].read_text(encoding="utf-8"))
            reports = sorted(log_dir.glob("[0-9]*.md"))
            self.assertEqual(len(reports), 1, "doctor did not emit one report")
            return result, summary, reports[0].read_text(encoding="utf-8")


def write_inbox_packets(root: Path, count: int, *, age_days: float) -> list[Path]:
    """Drop `count` inbox packets whose mtime is `age_days` in the past."""
    inbox = root / "departments" / "shared" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    when = time.time() - age_days * DAY
    written = []
    for index in range(count):
        packet = inbox / f"TASK-2026-08-0{index % 9 + 1}-000{index}-fixture.md"
        packet.write_text("---\nid: fixture\n---\n", encoding="utf-8")
        os.utime(packet, (when, when))
        written.append(packet)
    return written


def archive_packet(root: Path, packet: Path, *, namespace: str = "security") -> Path:
    """Complete a task: put a copy of its packet under a department archive.

    The namespace defaults to a DIFFERENT one from the inbox the packet sits in,
    because that is what the maintainer's tree actually looked like -- the copy
    was in security/archive while the residue sat in shared/inbox -- so a
    same-namespace test would pass against a check that cannot see it.
    """
    archive = root / "departments" / namespace / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    archived = archive / packet.name
    archived.write_text(packet.read_text(encoding="utf-8"), encoding="utf-8")
    return archived


class InboxBacklogAgeTest(DoctorCalibrationRunner):
    """5.1 -- queue state is reported, never gated.

    Every outcome here is a WARNING. `SQUAD_UNSAFE_AUTONOMY` defaults to 1, so a
    normal `squad up` runs this gate and any non-zero exit blocks the launch --
    and an unacknowledged work item is queue state, not installation breakage.
    Blocking would also invert the remedy: doctor gates the very launch the
    operator would use to work the queue.
    """

    def test_deep_but_fresh_backlog_is_a_warning_not_an_issue(self):
        """A wide fan-out publishes many packets at once and answers them."""

        def setup(root, _local_bin, _environment):
            write_inbox_packets(root, 15, age_days=0)

        result, summary, _report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            any("inbox backlog: 15" in warning for warning in summary["warnings"]),
            summary["warnings"],
        )
        self.assertEqual(
            [issue for issue in summary["issues"] if "inbox" in issue or "dispatch" in issue],
            [],
            summary["issues"],
        )

    def test_old_packet_under_the_depth_limit_is_a_warning(self):
        """The state the depth gate PASSED: two packets, eleven days abandoned.

        Reported in full — name, age, limit — and it does NOT block the launch.
        """

        def setup(root, _local_bin, _environment):
            write_inbox_packets(root, 2, age_days=11)

        result, summary, report = self.run_doctor(setup=setup)
        self.assertTrue(
            any(
                "abandoned dispatch" in warning and "11d" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )
        # It must name the packet, or the operator cannot act on it.
        self.assertIn("fixture.md", " ".join(summary["warnings"]))
        self.assertIn("bin/send-task.sh", report)
        # Queue state is not installation breakage.
        self.assertEqual(summary["issues"], [], summary["issues"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_age_escalates_an_abandoned_dispatch_to_a_launch_blocker(self):
        """There is deliberately no second, harsher threshold.

        A ninety-day-old packet is a bigger cleanup job than a four-day-old one,
        not a broken installation, so nothing here may reach exit 1.
        """

        def setup(root, _local_bin, _environment):
            write_inbox_packets(root, 2, age_days=90)

        result, summary, _report = self.run_doctor(setup=setup)
        self.assertEqual(summary["issues"], [], summary["issues"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            any("abandoned dispatch" in warning for warning in summary["warnings"]),
            summary["warnings"],
        )

    def test_a_task_with_an_archive_copy_is_not_abandoned(self):
        """THE regression that matters: today's live state.

        The flagged packet existed in BOTH departments/shared/inbox and
        departments/security/archive -- completed, archived, and its inbox copy
        left behind. It was the oldest file in any inbox, so it drove the
        headline finding, and "waited 10d unacknowledged" about a finished task
        was simply false.
        """

        def setup(root, _local_bin, _environment):
            packets = write_inbox_packets(root, 1, age_days=11)
            archive_packet(root, packets[0])

        result, summary, _report = self.run_doctor(setup=setup)
        self.assertEqual(
            [w for w in summary["warnings"] if "abandoned dispatch" in w],
            [],
            summary["warnings"],
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_archived_inbox_copy_is_reported_as_residue(self):
        """Excluded from abandonment, but not swept under the rug."""

        def setup(root, _local_bin, _environment):
            packets = write_inbox_packets(root, 1, age_days=11)
            archive_packet(root, packets[0])

        _result, summary, report = self.run_doctor(setup=setup)
        self.assertTrue(
            any(
                "1 handled task(s) still have an inbox copy" in warning
                and "fixture.md" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )
        self.assertIn("Fix: remove the inbox copy", report)

    def test_residue_does_not_hide_a_genuinely_abandoned_packet(self):
        """The archived one is older, so a naive fix would report only it.

        Age is measured over the unacknowledged packets alone, so the younger
        genuine one still surfaces with its own name.
        """

        def setup(root, _local_bin, _environment):
            old = write_inbox_packets(root, 1, age_days=30)[0]
            archive_packet(root, old)
            genuine = root / "departments" / "shared" / "inbox" / "TASK-2026-08-09-live.md"
            genuine.write_text("---\nid: live\n---\n", encoding="utf-8")
            when = time.time() - 7 * DAY
            os.utime(genuine, (when, when))

        _result, summary, _report = self.run_doctor(setup=setup)
        abandoned = [w for w in summary["warnings"] if "abandoned dispatch" in w]
        self.assertEqual(len(abandoned), 1, summary["warnings"])
        self.assertIn("TASK-2026-08-09-live.md", abandoned[0])
        self.assertIn("7d", abandoned[0])

    def test_shallow_and_fresh_backlog_is_healthy(self):
        """Positive control -- without it an always-failing check would pass."""

        def setup(root, _local_bin, _environment):
            write_inbox_packets(root, 2, age_days=0)

        result, summary, report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Inbox backlog: 2 unacknowledged (depth limit 10)", report)
        self.assertIn("age limit", report)
        self.assertEqual(
            [issue for issue in summary["issues"] if "dispatch" in issue],
            [],
            summary["issues"],
        )

    def test_age_threshold_is_configurable(self):
        """A 11-day packet passes a 30-day limit; the bound is not baked in."""

        def setup(root, _local_bin, _environment):
            write_inbox_packets(root, 2, age_days=11)

        result, summary, report = self.run_doctor(
            env={"DOCTOR_INBOX_MAX_AGE_DAYS": "30"}, setup=setup
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [issue for issue in summary["issues"] if "abandoned" in issue],
            [],
            summary["issues"],
        )
        # The clean line has to state the bound it cleared, or "healthy" is an
        # unfalsifiable claim -- and this assertion is what makes the test fail
        # when the age dimension is removed rather than merely widened.
        self.assertIn(f"age limit {30 * DAY}s", report)

    def test_undatable_packets_are_unknown_not_a_pass(self):
        """Packets present and undatable is not "backlog within threshold".

        Loud and never a pass — but not gate-blocking either: an unmeasured
        queue must not block a launch harder than a measured one would, and the
        strongest finding this check can now produce is a warning.
        """

        def setup(root, local_bin, _environment):
            write_inbox_packets(root, 2, age_days=0)
            doctor_fixture.write_stub(local_bin, "stat", STAT_DENIED)

        result, summary, _report = self.run_doctor(setup=setup)
        self.assertTrue(
            any(
                "inbox backlog age could not be measured" in entry
                for entry in summary["unknowns"]
            ),
            summary["unknowns"],
        )
        # The whole point: this entry is not in the exit-2 list. The process
        # exit code cannot be asserted here, because the `stat` stub that makes
        # the packets undatable also breaks the status-file and browser-summary
        # age checks, and those are gate-blocking for reasons of their own.
        self.assertEqual(
            [e for e in summary["gate_unknowns"] if "inbox backlog" in e],
            [],
            summary["gate_unknowns"],
        )
        del result


def seed_instruction_surfaces(root: Path, *, specialists: int = 4) -> None:
    """Give the fixture the four live surfaces and a registry of known size."""
    (root / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# Fixture root instructions\n", encoding="utf-8")
    (root / "chrono").mkdir(parents=True, exist_ok=True)
    (root / "chrono" / "CLAUDE.md").write_text("# Chrono\n", encoding="utf-8")
    registry = root / "shared" / "specialist-runtime-map.tsv"
    registry.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"spec-{index}\tclaude" for index in range(specialists))
    registry.write_text(f"specialist\tto_model\n{rows}\n", encoding="utf-8")


class InstructionDriftSeverityTest(DoctorCalibrationRunner):
    """5.2 -- a checkably false claim on a live surface is a defect."""

    def test_clean_live_surfaces_are_healthy(self):
        """Positive control -- without it an always-failing check would pass."""

        def setup(root, _local_bin, _environment):
            seed_instruction_surfaces(root)

        result, summary, report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No stale roster count, unfilled template", report)
        self.assertEqual(
            [issue for issue in summary["issues"] if "drift" in issue],
            [],
            summary["issues"],
        )

    def test_stale_roster_count_on_a_live_surface_is_an_issue(self):
        """README claiming 73 specialists over a 4-row registry is false."""

        def setup(root, _local_bin, _environment):
            seed_instruction_surfaces(root, specialists=4)
            (root / "README.md").write_text(
                "# Fixture\n\nShips 73 specialists across four lanes.\n",
                encoding="utf-8",
            )

        result, summary, _report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any("checkably false" in issue for issue in summary["issues"]),
            summary["issues"],
        )

    def test_unfilled_template_marker_on_a_live_surface_is_an_issue(self):
        def setup(root, _local_bin, _environment):
            seed_instruction_surfaces(root)
            (root / "shared" / "routing.md").write_text(
                "Route to <FILL:lane> for this class of work.\n", encoding="utf-8"
            )

        result, summary, _report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any("checkably false" in issue for issue in summary["issues"]),
            summary["issues"],
        )

    def test_self_declared_archive_is_not_a_live_surface(self):
        """chrono/current.md's own title says ARCHIVE, NOT LIVE STATE."""

        def setup(root, _local_bin, _environment):
            seed_instruction_surfaces(root, specialists=4)
            (root / "chrono" / "current.md").write_text(
                "# Chrono Current State — ARCHIVE, NOT LIVE STATE\n"
                "\n"
                "As of July this repo shipped 73 specialists.\n",
                encoding="utf-8",
            )

        result, summary, report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [issue for issue in summary["issues"] if "drift" in issue],
            [],
            summary["issues"],
        )
        # Not merely "not an issue": the scan has to reach its CLEAN line, or a
        # scope narrowing would be indistinguishable from a demotion.
        self.assertIn("No stale roster count, unfilled template", report)

    def test_dated_documents_under_docs_are_out_of_scope(self):
        """A July audit saying 73 specialists is an accurate record."""

        def setup(root, _local_bin, _environment):
            seed_instruction_surfaces(root, specialists=4)
            audit = root / "docs" / "2026-07-26-audit.md"
            audit.parent.mkdir(parents=True, exist_ok=True)
            audit.write_text("At the time: 73 specialists.\n", encoding="utf-8")

        result, summary, report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [issue for issue in summary["issues"] if "drift" in issue],
            [],
            summary["issues"],
        )
        # Not merely "not an issue": the scan has to reach its CLEAN line, or a
        # scope narrowing would be indistinguishable from a demotion.
        self.assertIn("No stale roster count, unfilled template", report)

    def test_partition_claim_is_not_a_roster_total(self):
        """"20 of 73 specialists are content specialists" states no total."""

        def setup(root, _local_bin, _environment):
            seed_instruction_surfaces(root, specialists=4)
            (root / "README.md").write_text(
                "# Fixture\n\n20 of 73 specialists are content specialists.\n",
                encoding="utf-8",
            )

        result, summary, report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            [issue for issue in summary["issues"] if "drift" in issue],
            [],
            summary["issues"],
        )
        # Not merely "not an issue": the scan has to reach its CLEAN line, or a
        # scope narrowing would be indistinguishable from a demotion.
        self.assertIn("No stale roster count, unfilled template", report)

    def test_dated_doc_pointer_is_a_warning_not_an_issue(self):
        """A pointer to a handoff is stale, not false. It may even resolve."""

        def setup(root, _local_bin, _environment):
            seed_instruction_surfaces(root)
            (root / "CLAUDE.md").write_text(
                "# Fixture\n\nResume from docs/handoffs/2026-07-12-tmux-handoff.md.\n",
                encoding="utf-8",
            )

        result, summary, _report = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "dated handoffs/specs/plans" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )
        self.assertEqual(
            [issue for issue in summary["issues"] if "drift" in issue],
            [],
            summary["issues"],
        )


class StandingWarningActionabilityTest(DoctorCalibrationRunner):
    """5.3 -- every standing warning names what it found and what to do."""

    def test_unusable_mcps_are_named_with_their_tier(self):
        """"reported registered/unusable drift" named no server and no tier."""

        def setup(root, _local_bin, _environment):
            doctor_fixture.write_stub(
                root / "bin", "mcp-audit.sh", MCP_AUDIT_WITH_FINDINGS
            )

        _result, summary, _report = self.run_doctor(setup=setup)
        mcp_warnings = [w for w in summary["warnings"] if w.startswith("MCP ")]
        self.assertEqual(len(mcp_warnings), 1, summary["warnings"])
        self.assertIn("required: chrono-vault", mcp_warnings[0])
        self.assertIn("optional: chrono-recon", mcp_warnings[0])
        # The server that WORKS must not be listed as a finding.
        self.assertNotIn("chrono-research-arsenal", mcp_warnings[0])

    def test_vault_root_warning_points_at_the_doc_that_answers_it(self):
        """It pointed at the do-not-commit policy, which never names the var."""
        _result, summary, _report = self.run_doctor()
        vault_warnings = [
            warning
            for warning in summary["warnings"]
            if "CHRONO_VAULT_ROOT unset" in warning
        ]
        self.assertEqual(len(vault_warnings), 1, summary["warnings"])
        self.assertIn("docs/getting-started.md", vault_warnings[0])
        self.assertNotIn("private-config", vault_warnings[0])
        # And it states the consequence, which is the part a reader acts on.
        self.assertIn("record/recall are off", vault_warnings[0])

    def test_orphaned_lane_cli_is_warned_about_by_pid(self):
        """A `codex exec` reparented to init: nothing will ever reap it."""
        _result, summary, report = self.run_doctor(
            env={
                "DOCTOR_TEST_PROC_ROWS": (
                    "90307 1 07-23:14:20 0.0 node /opt/homebrew/bin/codex exec --sandbox\n"
                )
            },
            setup=lambda root, local_bin, _env: doctor_fixture.write_stub(
                local_bin, "ps", PS_SCRIPTED
            ),
        )
        orphan_warnings = [w for w in summary["warnings"] if "orphaned" in w]
        self.assertEqual(len(orphan_warnings), 1, summary["warnings"])
        self.assertIn("codex PID 90307", orphan_warnings[0])
        self.assertIn("will not reap", orphan_warnings[0])
        self.assertIn("Orphaned lane CLI processes", report)

    def test_attached_cli_session_is_information_not_a_warning(self):
        """The old check warned about every terminal the operator had open."""
        _result, summary, report = self.run_doctor(
            env={
                "DOCTOR_TEST_PROC_ROWS": (
                    "6116 6011 20:56:45 9.3 /opt/fixture/bin/claude\n"
                )
            },
            setup=lambda root, local_bin, _env: doctor_fixture.write_stub(
                local_bin, "ps", PS_SCRIPTED
            ),
        )
        self.assertEqual(
            [w for w in summary["warnings"] if "CLI" in w and "orphan" in w],
            [],
            summary["warnings"],
        )
        self.assertIn("Attached non-squad CLI sessions", report)
        self.assertIn("claude PID 6116", report)

    def test_unrelated_process_quoting_a_lane_name_is_not_a_finding(self):
        """The false positive that made the old line fire every day.

        bin/send-task.sh carries a lane name in its ARGUMENTS. Positional
        matching looks at argv[0] and argv[1] only, so it cannot see it.
        """
        _result, summary, report = self.run_doctor(
            env={
                "DOCTOR_TEST_PROC_ROWS": (
                    "19040 1 00:04 0.0 /bin/bash /repo/bin/send-task.sh --to-model claude\n"
                )
            },
            setup=lambda root, local_bin, _env: doctor_fixture.write_stub(
                local_bin, "ps", PS_SCRIPTED
            ),
        )
        self.assertEqual(
            [w for w in summary["warnings"] if "orphan" in w], [], summary["warnings"]
        )
        self.assertNotIn("19040", report)


if __name__ == "__main__":
    unittest.main()
