#!/usr/bin/env python3
"""The doctor token has one home and one mirror; this pins them together.

`bin/doctor-state.sh` is the canonical definition (CLAUDE.md rule 10 names it as
the winner). `bin/vs-lane-status.sh` carries a Python mirror inside its poller
heredoc so that the once-a-second loop does not shell out to jq. A mirror is
only legitimate while a validator enforces the identity -- this is that
validator. Every fixture below is fed to BOTH and the answers must match.

Nothing here launches a session, touches the operator's status files, or reads
the operator's real doctor logs: the poller is run with VS_STATUS_ONCE=1 against
a temporary VAULT_ROOT, a temporary status directory, a temporary activity
directory, and an explicit CHRONO_DOCTOR_LOG_DIR.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
DOCTOR_STATE = ROOT / "bin" / "doctor-state.sh"
POLLER = ROOT / "bin" / "vs-lane-status.sh"

# The poller takes an injectable clock (VS_STATUS_NOW), so its lookup date is
# pinned. doctor_state() reads the wall clock and has no such hook, so the same
# fixture is written under today's and tomorrow's UTC date as well -- otherwise
# a run that straddles UTC midnight would read a file that is not there.
FIXED_EPOCH = 1_775_000_000
FIXED_DATE = datetime.fromtimestamp(FIXED_EPOCH, timezone.utc).strftime("%Y-%m-%d")


def fixture_dates() -> list[str]:
    today = datetime.now(timezone.utc)
    return sorted(
        {
            FIXED_DATE,
            today.strftime("%Y-%m-%d"),
            (today + timedelta(days=1)).strftime("%Y-%m-%d"),
        }
    )


def write_fixture(logs: Path, content: str | None) -> None:
    if content is None:
        return
    for date in fixture_dates():
        (logs / f"{date}-summary.json").write_text(content, encoding="utf-8")

# (label, summary file content or None for "no file", expected canonical token)
FIXTURES: list[tuple[str, str | None, str]] = [
    ("no summary for today", None, ""),
    ("clean run", json.dumps({"issue_count": 0, "warning_count": 0}), "healthy"),
    ("warnings only", json.dumps({"issue_count": 0, "warning_count": 3}), "warn:3"),
    ("issues win over warnings", json.dumps({"issue_count": 1, "warning_count": 3}), "issues:1"),
    ("counts absent entirely", json.dumps({"healthy_count": 24}), "healthy"),
    ("explicit nulls", json.dumps({"issue_count": None, "warning_count": None}), "healthy"),
    ("negative counts are not counts", json.dumps({"issue_count": -2, "warning_count": 0}), "healthy"),
    ("numeric string", json.dumps({"issue_count": "4"}), "issues:4"),
    ("zero-padded string", json.dumps({"issue_count": "010"}), "issues:10"),
    ("float is not a count", json.dumps({"issue_count": 3.5, "warning_count": 2}), "warn:2"),
    ("boolean is not a count", json.dumps({"issue_count": True, "warning_count": 0}), "healthy"),
    ("object is not a count", json.dumps({"issue_count": {"a": 1}}), "healthy"),
    ("unparseable summary", "{not json", ""),
    ("empty summary", "", ""),
    ("top level is a list", json.dumps([1, 2, 3]), ""),
]


def canonical_token(doctor_log_dir: Path) -> str:
    """doctor_state() from bin/doctor-state.sh, the canonical home."""
    completed = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'source "{DOCTOR_STATE}"; doctor_state',
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "CHRONO_DOCTOR_LOG_DIR": str(doctor_log_dir),
        },
    )
    return completed.stdout.strip()


def mirrored_segment(doctor_log_dir: Path, base: Path) -> str:
    """The pre-formatted segment bin/vs-lane-status.sh writes, run once."""
    vault = base / "vault"
    activity = vault / "_state" / "runtime" / "lane-activity"
    activity.mkdir(parents=True, exist_ok=True)
    status = base / "status"
    tasks = base / "tasks.json"
    tasks.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    subprocess.run(
        ["/bin/bash", str(POLLER)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            # A temporary VAULT_ROOT: the poller must not read or write anything
            # belonging to a live session.
            "VAULT_ROOT": str(vault),
            "PANEL_ACTIVITY_DIR": str(activity),
            "VIBESQUAD_STATUS_DIR": str(status),
            "VS_DAEMON_TASKS_FILE": str(tasks),
            "VS_STATUS_NOW": str(FIXED_EPOCH),
            "VS_STATUS_ONCE": "1",
            "CHRONO_DOCTOR_LOG_DIR": str(doctor_log_dir),
        },
    )
    return (status / "vs-doctor.status").read_text(encoding="utf-8")


def strip_markup(segment: str) -> str:
    return re.sub(r"#\[[^\]]*\]", "", segment).strip()


class DoctorTokenIdentityTests(unittest.TestCase):
    def test_canonical_and_mirror_agree_on_every_fixture(self) -> None:
        for label, content, expected in FIXTURES:
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as directory:
                    base = Path(directory)
                    logs = base / "doctor-logs"
                    logs.mkdir()
                    write_fixture(logs, content)

                    self.assertEqual(canonical_token(logs), expected)
                    segment = mirrored_segment(logs, base)
                    # The mirror renders "no reading" as `doctor:?`; the
                    # canonical shell renders it as nothing at all, and its
                    # caller decides. Everything else must be identical text.
                    self.assertEqual(
                        strip_markup(segment),
                        expected if expected else "doctor:?",
                    )

    def test_only_an_issue_count_earns_amber(self) -> None:
        """colour214 is the brightest thing on the bar; a healthy system
        should not shout."""
        seen = {}
        for label, content, expected in FIXTURES:
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                logs = base / "doctor-logs"
                logs.mkdir()
                write_fixture(logs, content)
                seen[label] = (expected, mirrored_segment(logs, base))
        for label, (expected, segment) in seen.items():
            with self.subTest(label):
                if expected.startswith("issues:"):
                    self.assertIn("colour214", segment)
                else:
                    self.assertNotIn("colour214", segment)

    def test_doctor_state_is_sourced_not_duplicated(self) -> None:
        """The badge renderer must use the canonical home, not its own copy."""
        segment = (ROOT / "bin" / "chrono-status-segment.sh").read_text(encoding="utf-8")
        self.assertIn("bin/doctor-state.sh", segment)
        self.assertNotIn("doctor_state() {", segment)

    def test_mirror_names_the_canonical_home(self) -> None:
        poller = POLLER.read_text(encoding="utf-8")
        self.assertIn("bin/doctor-state.sh", poller)


if __name__ == "__main__":
    unittest.main()
