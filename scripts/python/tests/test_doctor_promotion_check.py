#!/usr/bin/env python3
"""Task 10: the promotion-throughput doctor check.

Spec §11 item 4. A sweep that stops is invisible -- curation and usage
telemetry both stopped 2026-07-25 and nobody noticed for 23 days, by which
point 94.6% of notes were stuck at `candidate`. This check asserts
"promotion has fired at least once in the trailing window" so the next
stall is loud instead of silent.

Deliberately WARN, never ISSUE (bin/doctor.sh: note_warn, not note_issue).
A quiet promotion pipeline is not a broken installation, and ISSUE gates
`squad up` exit 1 (SQUAD_UNSAFE_AUTONOMY defaults to 1). A check that
cannot fire is exactly the defect this whole design exists to remove, so
these tests prove it can: one case drives it to WARN, one to OK, one to
the fail-closed UNKNOWN paths.

SAFETY, read before touching anything here
------------------------------------------
No test here reaches ``~/Obsidian-Chrono`` or any other real vault.
Every fixture vault lives under ``tempfile.TemporaryDirectory`` and is
torn down with it. ``CHRONO_VAULT_ROOT`` is explicitly popped from the
inherited environment before each run and only ever re-set to a fixture
path, so a host that happens to export it cannot leak into these tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402
import doctor_fixture  # noqa: E402

ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])

DAY_NS = 86400 * 10**9


# The promotion check needs vaultroot.py and memory_metrics.py, and nothing
# doctor_fixture.install_doctor_helpers() already copies: neither is one of
# DOCTOR_HELPERS. Both are stdlib-only (sqlite3, json, os, pathlib) so no
# venv or third-party package is required to exercise them.
def install_promotion_check_deps(repo_root: Path, fixture_root: Path) -> None:
    vault_pkg = fixture_root / "plugins" / "chrono-vault"
    vault_pkg.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repo_root / "plugins" / "chrono-vault" / "vaultroot.py",
        vault_pkg / "vaultroot.py",
    )
    scripts_pkg = fixture_root / "scripts" / "python"
    scripts_pkg.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repo_root / "scripts" / "python" / "memory_metrics.py",
        scripts_pkg / "memory_metrics.py",
    )


def write_private_vault(
    path: Path,
    *,
    rows: tuple = (),
    with_verified_at_column: bool = True,
    with_index: bool = True,
) -> Path:
    """Build a minimal but vaultroot.resolve_vault_root()-valid private vault.

    ``rows`` are (docid, id, status, note_type, mtime_ns, verified_at_ns)
    tuples when with_verified_at_column, else the same without the last
    column -- mirroring test_memory_metrics.py's two fixture shapes.
    """
    path.mkdir(parents=True, exist_ok=True)
    (path / ".chrono-vault").write_text(
        json.dumps({"vault_id": "doctor-promotion-fixture", "schema_version": 1}),
        encoding="utf-8",
    )
    if with_index:
        index_dir = path / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(index_dir / "kg.db")
        if with_verified_at_column:
            con.execute(
                "CREATE TABLE meta (docid INTEGER, id TEXT, status TEXT, "
                "note_type TEXT, mtime_ns INTEGER, verified_at_ns INTEGER)"
            )
            con.executemany("INSERT INTO meta VALUES (?,?,?,?,?,?)", rows)
        else:
            con.execute(
                "CREATE TABLE meta (docid INTEGER, id TEXT, status TEXT, "
                "note_type TEXT, mtime_ns INTEGER)"
            )
            con.executemany("INSERT INTO meta VALUES (?,?,?,?,?)", rows)
        con.execute(
            "CREATE TABLE usage (recall_id TEXT, note_id TEXT, outcome TEXT, "
            "source_task TEXT, ts TEXT)"
        )
        con.commit()
        con.close()
    return path


def _promotion_line(offset: float, index: int, status: str) -> str:
    stamp = (datetime.now(timezone.utc) - timedelta(days=offset)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    summary = (
        "promoted 1 memory note(s) to verified: mem-fixture"
        if status == "MEMORY-PROMOTION"
        else "memory promotion skipped: CHRONO_VAULT_ROOT is unset"
        if status.endswith("SKIPPED")
        else "memory promotion failed: memory index is missing"
    )
    return f"{stamp} | {status} | coding/TASK-{index} | {summary}"


def write_chrono_queue(
    repo_root: Path,
    days_ago: tuple[float, ...],
    *,
    archived_days_ago: tuple[float, ...] = (),
    non_promotion_days_ago: tuple[tuple[float, str], ...] = (),
) -> Path:
    """Seed the repo's Chrono queue -- both halves -- with promotion events.

    This -- not a `verified_at` stamp on a note -- is what the doctor check
    keys on. A stamp says a note carries a promotion time; it does not say
    the handler produced it, because `notes._normalize` stamps a note
    recorded straight to `verified` and `lifecycle.set_status` stamps any
    manual promotion during curation.

    `archived_days_ago` writes into `chrono-queue-handled.md`, where
    `bin/chrono-queue-backfill.sh` moves every line whose task is no longer
    open -- which is every promotion line, since promotion happens at
    settlement. `non_promotion_days_ago` writes the handler's OTHER two
    statuses, which must never satisfy this check.
    """
    state = repo_root / "_state"
    state.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Chrono Queue",
        "# timestamp | status | namespace/task-id | summary",
        "",
    ]
    for index, offset in enumerate(days_ago):
        lines.append(_promotion_line(offset, index, "MEMORY-PROMOTION"))
    for index, (offset, status) in enumerate(non_promotion_days_ago):
        lines.append(_promotion_line(offset, 900 + index, status))
    queue = state / "chrono-queue.md"
    queue.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if archived_days_ago:
        archived = [
            _promotion_line(offset, 500 + index, "MEMORY-PROMOTION")
            for index, offset in enumerate(archived_days_ago)
        ]
        (state / "chrono-queue-handled.md").write_text(
            "\n".join(archived)
            + "\n<!-- chrono-queue-backfill:batch=" + "0" * 64 + " -->\n",
            encoding="utf-8",
        )
    return queue


class DoctorPromotionCheckRunner(unittest.TestCase):
    """Runs a real bin/doctor.sh against a throwaway repo and fixture vault."""

    def run_doctor(
        self,
        *,
        vault_root: Path | None,
        env: dict | None = None,
        promotion_events_days_ago: tuple[float, ...] = (),
        archived_promotion_days_ago: tuple[float, ...] = (),
        non_promotion_days_ago: tuple[tuple[float, str], ...] = (),
    ):
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-check-") as temp:
            fixture = Path(temp)
            root = fixture / "root"
            doctor_fixture.install_doctor_helpers(ROOT, root)
            install_promotion_check_deps(ROOT, root)
            write_chrono_queue(
                root,
                promotion_events_days_ago,
                archived_days_ago=archived_promotion_days_ago,
                non_promotion_days_ago=non_promotion_days_ago,
            )
            subprocess.run(
                ["git", "init", "-q"], cwd=root, check=True, capture_output=True
            )

            home = fixture / "home"
            local_bin = home / ".local" / "bin"
            doctor_fixture.write_stub(local_bin, "ps", doctor_fixture.EMPTY_PS)
            doctor_fixture.stub_launch_dependencies(local_bin, ROOT)
            doctor_fixture.write_stub(local_bin, "launchctl", "#!/bin/bash\nexit 64\n")
            doctor_fixture.write_stub(
                local_bin,
                "curl",
                '#!/bin/bash\nprintf \'{"Browser": "test"}\\n\'\nexit 0\n',
            )

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
            if vault_root is not None:
                environment["CHRONO_VAULT_ROOT"] = str(vault_root)
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


class PromotionThroughputWarnsWhenZero(DoctorPromotionCheckRunner):
    """The check must be able to FIRE -- a check that cannot fail is the
    exact defect memory_metrics.promotion_throughput's docstring describes
    (mtime_ns read 99 promotions on a vault that never promoted anything)."""

    def test_zero_throughput_is_warn_not_issue_and_names_the_window(self):
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-vault-") as vtemp:
            vault = write_private_vault(Path(vtemp) / "vault", rows=())
            _result, summary, _report = self.run_doctor(vault_root=vault)

        matches = [w for w in summary["warnings"] if "promotion throughput" in w]
        self.assertEqual(len(matches), 1, summary["warnings"])
        self.assertIn("30", matches[0], "warning must name the window")
        self.assertIn("ZERO", matches[0])
        self.assertFalse(
            [i for i in summary["issues"] if "promotion" in i],
            "a quiet promotion pipeline must be a WARNING, never an ISSUE "
            f"(issues={summary['issues']!r})",
        )

    def test_zero_throughput_also_warns_before_verified_at_ns_exists(self):
        """Today's live schema (pre-Task-8-stamping everywhere) has no
        verified_at_ns column at all; memory_metrics.promotion_throughput
        returns 0 rather than falling back to mtime, and doctor must warn."""
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-vault-") as vtemp:
            vault = write_private_vault(
                Path(vtemp) / "vault",
                rows=((1, "mem-a", "verified", "finding", 0),),
                with_verified_at_column=False,
            )
            _result, summary, _report = self.run_doctor(vault_root=vault)

        matches = [w for w in summary["warnings"] if "promotion throughput" in w]
        self.assertEqual(len(matches), 1, summary["warnings"])


class PromotionThroughputStaysQuietOnRecentPromotion(DoctorPromotionCheckRunner):
    def test_a_recent_handler_event_is_not_a_warning(self):
        now_ns = time.time_ns()
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-vault-") as vtemp:
            vault = write_private_vault(
                Path(vtemp) / "vault",
                rows=((1, "mem-a", "verified", "finding", 0, now_ns),),
            )
            _result, summary, report = self.run_doctor(
                vault_root=vault, promotion_events_days_ago=(1,)
            )

        self.assertFalse(
            [w for w in summary["warnings"] if "promotion throughput" in w],
            summary["warnings"],
        )
        self.assertFalse(
            [i for i in summary["issues"] if "promotion" in i], summary["issues"]
        )
        self.assertIn("chrono-vault promotion", report)
        self.assertIn("MEMORY-PROMOTION", report)

    def test_a_stamped_note_alone_does_not_silence_the_alarm(self):
        """I1: `verified_at` has three provenances; only one is promotion.

        `notes._normalize` stamps a note recorded straight to `verified`,
        and `lifecycle.set_status` stamps any manual promotion -- which
        `shared/curation-protocol.md` §3 has Chrono doing at every session
        boundary. One such note used to silence "the handler stopped
        firing" for a full 30-day window.
        """
        now_ns = time.time_ns()
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-vault-") as vtemp:
            vault = write_private_vault(
                Path(vtemp) / "vault",
                rows=((1, "mem-a", "verified", "finding", 0, now_ns),),
            )
            _result, summary, report = self.run_doctor(
                vault_root=vault, promotion_events_days_ago=()
            )

        matches = [w for w in summary["warnings"] if "promotion throughput" in w]
        self.assertEqual(len(matches), 1, summary["warnings"])
        # The stamped count is still reported -- as context, labelled as the
        # upper bound it is, never as the alarm's number.
        self.assertIn('"stamped_notes": 1', report)

    def test_an_old_handler_event_outside_the_window_still_warns(self):
        """An event 40 days ago does not satisfy a 30-day window."""
        old_ns = time.time_ns() - 40 * DAY_NS
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-vault-") as vtemp:
            vault = write_private_vault(
                Path(vtemp) / "vault",
                rows=((1, "mem-a", "verified", "finding", 0, old_ns),),
            )
            _result, summary, _report = self.run_doctor(
                vault_root=vault, promotion_events_days_ago=(40,)
            )

        matches = [w for w in summary["warnings"] if "promotion throughput" in w]
        self.assertEqual(len(matches), 1, summary["warnings"])


class PromotionEventStatusIsExact(DoctorPromotionCheckRunner):
    """N1/N2: the alarm must not answer for the handler's failures, and must
    not go blind when the queue is archived."""

    def test_only_skipped_and_failed_lines_still_warn(self) -> None:
        """N1, end to end through the real doctor.

        `MEMORY-PROMOTION-SKIPPED` is what a settlement writes when
        `CHRONO_VAULT_ROOT` is unset in the settling shell -- a recurring
        condition on this machine. While all three outcomes shared one
        status, this fixture reported OK: the loudest alarm in the design
        counting its own failures as successes.
        """
        now_ns = time.time_ns()
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-vault-") as vtemp:
            vault = write_private_vault(
                Path(vtemp) / "vault",
                rows=((1, "mem-a", "verified", "finding", 0, now_ns),),
            )
            _result, summary, _report = self.run_doctor(
                vault_root=vault,
                promotion_events_days_ago=(),
                non_promotion_days_ago=(
                    (1, "MEMORY-PROMOTION-SKIPPED"),
                    (2, "MEMORY-PROMOTION-FAILED"),
                ),
            )

        matches = [w for w in summary["warnings"] if "promotion throughput" in w]
        self.assertEqual(len(matches), 1, summary["warnings"])
        self.assertIn("ZERO", matches[0])

    def test_an_archived_promotion_line_keeps_the_alarm_quiet(self) -> None:
        """N2: `bin/chrono-queue-backfill.sh` moves settled lines out.

        Every promotion line is written at settlement, so its task is
        `complete` and the backfill archives it. Live state proves the
        backfill runs: `chrono-queue-handled.md` held 110 `REVIEW-SETTLED`
        lines while `chrono-queue.md` held 0. Reading only the live queue
        made the doctor WARN on a machine that had been promoting normally.
        """
        now_ns = time.time_ns()
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-vault-") as vtemp:
            vault = write_private_vault(
                Path(vtemp) / "vault",
                rows=((1, "mem-a", "verified", "finding", 0, now_ns),),
            )
            _result, summary, report = self.run_doctor(
                vault_root=vault,
                promotion_events_days_ago=(),
                archived_promotion_days_ago=(1,),
            )

        self.assertFalse(
            [w for w in summary["warnings"] if "promotion throughput" in w],
            summary["warnings"],
        )
        self.assertIn("chrono-vault promotion", report)


class PromotionThroughputStaysFailClosed(DoctorPromotionCheckRunner):
    """CHRONO_VAULT_ROOT unset or an unreadable index must report UNKNOWN,
    never OK -- doctor's fail-closed vocabulary, never invented status
    words."""

    def test_unset_vault_root_is_absent_input_not_ok(self):
        result, summary, _report = self.run_doctor(vault_root=None)

        matches = [u for u in summary["absent_inputs"] if "promotion throughput" in u]
        self.assertEqual(len(matches), 1, summary["absent_inputs"])
        self.assertFalse(
            [w for w in summary["warnings"] if "promotion throughput" in w],
            "absent input is not a measured zero and must not warn",
        )
        # Absent inputs are non-gating: a fresh clone with no vault configured
        # yet must still be able to launch.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unreadable_index_is_gate_unknown_not_ok(self):
        with tempfile.TemporaryDirectory(prefix="doctor-memloop-vault-") as vtemp:
            # Valid sentinel, but no index/kg.db at all -- an operator who
            # configured a vault whose index this check genuinely cannot read.
            vault = write_private_vault(Path(vtemp) / "vault", with_index=False)
            _result, summary, _report = self.run_doctor(vault_root=vault)

        matches = [g for g in summary["gate_unknowns"] if "promotion throughput" in g]
        self.assertEqual(len(matches), 1, summary["gate_unknowns"])
        self.assertFalse(
            [w for w in summary["warnings"] if "promotion throughput" in w],
            "an unreadable index is UNKNOWN, not a measured zero",
        )


if __name__ == "__main__":
    unittest.main()
