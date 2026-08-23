#!/usr/bin/env python3
"""Plan D Task 6: the checks that read a config file instead of probing.

CLAUDE.md rule 9: "Capability is proven by a live probe, never by a config file.
Declared != delivered != actual — only actual counts." Five checks violated it,
and each had the same shape: a stat() standing in for a claim about whether
something works.

  * secrets.zsh was `[[ -f ]]` -> OK. Never sourced, not one key name checked.
  * docs/brain-map.md was existence only, and it can gate exit 1.
  * launchd: `launchctl` appeared ZERO times. Doctor read plists and verified the
    SCRIPTS existed; it never asked whether a job was loaded or what its last run
    did -- which is how a scheduled job that failed every time stayed invisible.
  * the browser read `.reachable` out of a file another process wrote and never
    touched port 9222.
  * the runtime repository was `[[ -d ]] && [[ -w ]]` with no write attempted.

SAFETY, read before touching anything here
------------------------------------------
Not one test here reaches the operator's launchd domain, Chrome, secrets file or
repository. ``launchctl`` and ``curl`` are STUBS on the fixture's own PATH, and
two tests assert on what doctor asked them for -- that no mutating launchctl
subcommand is ever issued, and that no CDP endpoint other than /json/version is
ever requested. Those two are the safety contract for this task, pinned as tests
rather than promised in a comment.

``test_secret_values_never_reach_any_output`` is the other one that matters: API
keys have leaked through this system before.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_checkout import normal_checkout_root  # noqa: E402
import doctor_fixture  # noqa: E402

ROOT = normal_checkout_root(Path(__file__).resolve().parents[3])

# Records every argv it is handed, then answers from the environment. The
# recording is what lets a test assert doctor issued `print` and nothing else.
LAUNCHCTL_STUB = r"""#!/bin/bash
printf '%s\n' "$*" >> "${DOCTOR_TEST_LAUNCHCTL_CALLS:-/dev/null}"
[[ "$1" == "print" ]] || exit 64
label="${2##*/}"
case " ${DOCTOR_TEST_LAUNCHD_UNLOADED:-} " in
    *" ${label} "*) exit 113 ;;
esac
printf '\tstate = not running\n\tlast exit code = %s\n' \
    "${DOCTOR_TEST_LAUNCHD_EXIT:-0}"
exit 0
"""

# Answers /json/version from the environment and records the URL it was asked
# for, so a test can prove no tab-mutating endpoint was ever requested.
CURL_STUB = r"""#!/bin/bash
for argument in "$@"; do
    case "$argument" in
        http*) printf '%s\n' "$argument" >> "${DOCTOR_TEST_CURL_URLS:-/dev/null}" ;;
    esac
done
[[ "${DOCTOR_TEST_CDP_UP:-1}" == "1" ]] || exit 7
printf '{"Browser": "Chrome/148.0.7778.98", "Protocol-Version": "1.3"}\n'
exit 0
"""

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
{label}    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/opt/Obsidian-Claude-Vibe-Squad/{script}</string>
    </array>
</dict>
</plist>
"""


def write_launch_agent(home: Path, filename: str, *, label: str | None, script: str) -> None:
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    label_block = f"    <key>Label</key>\n    <string>{label}</string>\n" if label else ""
    (agents / filename).write_text(
        PLIST_TEMPLATE.format(label=label_block, script=script), encoding="utf-8"
    )


BRAIN_MAP_RESOLVING = """# Brain Map

Status: canonical

| Layer | Canonical files |
|---|---|
| Chrono brain | `chrono/CLAUDE.md` |
| Specialist map | `shared/specialist-runtime-map.tsv` |
"""

BRAIN_MAP_BROKEN = """# Brain Map

| Layer | Canonical files |
|---|---|
| Chrono brain | `chrono/CLAUDE.md` |
| Retired layer | `shared/this-moved-away.md` |
"""

BRAIN_MAP_EMPTY = """# Brain Map

Status: canonical

It used to have a Source Layers table.
"""


class DoctorProbeRunner(unittest.TestCase):
    """Runs a real bin/doctor.sh against stubs for launchctl, curl and friends."""

    def run_doctor(self, *, env: dict[str, str] | None = None, setup=None):
        with tempfile.TemporaryDirectory(prefix="doctor-probes-") as temp:
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
            doctor_fixture.write_stub(local_bin, "launchctl", LAUNCHCTL_STUB)
            doctor_fixture.write_stub(local_bin, "curl", CURL_STUB)

            environment = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "VAULT_ROOT": str(root),
                "TERM": "dumb",
                "LANG": "C",
                "TMPDIR": str(fixture),
                "DOCTOR_TEST_LAUNCHCTL_CALLS": str(fixture / "launchctl-calls.txt"),
                "DOCTOR_TEST_CURL_URLS": str(fixture / "curl-urls.txt"),
            }
            environment.pop("CHRONO_DOCTOR_LOG_DIR", None)
            environment.pop("CHRONO_VAULT_ROOT", None)
            if setup is not None:
                setup(root, home, local_bin, environment)
            environment.update(env or {})

            try:
                result = subprocess.run(
                    ["/bin/bash", str(root / "bin" / "doctor.sh")],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=180,
                )
            finally:
                # A test may have made the tree read-only on purpose; the
                # temporary directory still has to be removable afterwards.
                root.chmod(0o755)

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
            calls = fixture / "launchctl-calls.txt"
            urls = fixture / "curl-urls.txt"
            return (
                result,
                summary,
                reports[0].read_text(encoding="utf-8"),
                calls.read_text(encoding="utf-8") if calls.exists() else "",
                urls.read_text(encoding="utf-8") if urls.exists() else "",
                root,
            )


def write_secrets(home: Path, assignments: dict[str, str]) -> None:
    secrets = home / ".config" / "shell" / "secrets.zsh"
    secrets.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f'export {name}="{value}"' for name, value in assignments.items())
    secrets.write_text(body + "\n", encoding="utf-8")
    secrets.chmod(0o600)


def bootstrap_declaring(names: list[str]) -> str:
    """A bootstrap-mcps.sh carrying the one line doctor parses key names out of."""
    return (
        "#!/bin/bash\n"
        "MCP_SERVERS=(\n"
        f'    "fixture-server|/tmp/fixture.py|{" ".join(names)}"\n'
        ")\n"
        "exit 0\n"
    )


class SecretsContentProbeTest(DoctorProbeRunner):
    """The gate for every optional integration used to be a stat()."""

    def test_missing_key_name_is_named_in_a_warning(self):
        def setup(root, home, _local_bin, _environment):
            doctor_fixture.write_stub(
                root / "scripts",
                "bootstrap-mcps.sh",
                bootstrap_declaring(["FIXTURE_ONE_KEY", "FIXTURE_TWO_KEY"]),
            )
            write_secrets(home, {"FIXTURE_ONE_KEY": "value-one"})

        _result, summary, _report, _calls, _urls, _root = self.run_doctor(setup=setup)
        self.assertTrue(
            any(
                "secrets.zsh is missing 1 of 2 expected key name(s): FIXTURE_TWO_KEY"
                in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_all_names_present_is_healthy(self):
        """Positive control -- without it an always-failing check would pass."""

        def setup(root, home, _local_bin, _environment):
            doctor_fixture.write_stub(
                root / "scripts",
                "bootstrap-mcps.sh",
                bootstrap_declaring(["FIXTURE_ONE_KEY", "FIXTURE_TWO_KEY"]),
            )
            write_secrets(
                home, {"FIXTURE_ONE_KEY": "value-one", "FIXTURE_TWO_KEY": "value-two"}
            )

        _result, summary, report, _calls, _urls, _root = self.run_doctor(setup=setup)
        self.assertIn("every one of the 2 environment names", report)
        self.assertEqual(
            [w for w in summary["warnings"] if "secrets.zsh" in w], [], summary["warnings"]
        )

    def test_empty_secrets_file_no_longer_passes(self):
        """The defect: a file that defines nothing satisfied `[[ -f ]]`."""

        def setup(root, home, _local_bin, _environment):
            doctor_fixture.write_stub(
                root / "scripts",
                "bootstrap-mcps.sh",
                bootstrap_declaring(["FIXTURE_ONE_KEY"]),
            )
            write_secrets(home, {})

        _result, summary, _report, _calls, _urls, _root = self.run_doctor(setup=setup)
        self.assertTrue(
            any(
                "missing 1 of 1 expected key name(s): FIXTURE_ONE_KEY" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_unreadable_expected_names_is_gate_blocking(self):
        """Fail-closed: presence alone must not stand in for the probe."""

        def setup(_root, home, _local_bin, _environment):
            write_secrets(home, {"FIXTURE_ONE_KEY": "value-one"})

        result, summary, _report, _calls, _urls, _root = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "secrets.zsh contents were NOT checked" in entry
                for entry in summary["gate_unknowns"]
            ),
            summary["gate_unknowns"],
        )

    def test_secret_values_never_reach_any_output(self):
        """The safety contract, pinned. Names out, values never."""
        secret = "sk-doctor-fixture-secret-value-must-not-be-logged"

        def setup(root, home, _local_bin, _environment):
            doctor_fixture.write_stub(
                root / "scripts",
                "bootstrap-mcps.sh",
                bootstrap_declaring(["FIXTURE_ONE_KEY", "FIXTURE_TWO_KEY"]),
            )
            write_secrets(home, {"FIXTURE_ONE_KEY": secret})

        result, summary, report, _calls, _urls, _root = self.run_doctor(setup=setup)
        self.assertNotIn(secret, report)
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn(secret, json.dumps(summary))
        # ...while the finding it supports still reaches the reader.
        self.assertIn("FIXTURE_TWO_KEY", json.dumps(summary))


@unittest.skipUnless(
    sys.platform == "darwin",
    "launchd is macOS-only: doctor's registration audit needs `plutil`, which "
    "Linux does not ship, so the probe correctly reports "
    "'launchd registration audit could not run: plutil is unavailable' and "
    "returns before the launchctl stub is ever reached. These five cases then "
    "fail for the environment rather than for the behaviour they assert -- they "
    "were red on the Linux hermetic gate from at least 2026-08-20. Gated, not "
    "masked: the assertions are unchanged and still run on macOS, where they pass.",
)
class LaunchdLivenessProbeTest(DoctorProbeRunner):
    """`launchctl` appeared zero times in 2,000 lines of health check."""

    def _repo_job(self, root: Path, home: Path, *, label: str | None = "com.fixture.job"):
        doctor_fixture.write_stub(root / "bin", "fixture-job.sh")
        write_launch_agent(
            home, "com.fixture.job.plist", label=label, script="bin/fixture-job.sh"
        )

    def test_loaded_job_with_clean_exit_is_healthy(self):
        """Positive control."""
        _result, summary, report, calls, _urls, _root = self.run_doctor(
            setup=lambda root, home, _lb, _env: self._repo_job(root, home)
        )
        self.assertIn("launchctl print answered for all 1 job(s)", report)
        self.assertIn("print gui/", calls)

    def test_declared_but_unloaded_job_is_a_blocking_issue(self):
        """A plist and a script are not a scheduled job."""
        result, summary, _report, _calls, _urls, _root = self.run_doctor(
            env={"DOCTOR_TEST_LAUNCHD_UNLOADED": "com.fixture.job"},
            setup=lambda root, home, _lb, _env: self._repo_job(root, home),
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "declared but NOT loaded" in issue and "com.fixture.job" in issue
                for issue in summary["issues"]
            ),
            summary["issues"],
        )

    def test_loaded_job_that_last_failed_is_a_warning_naming_the_code(self):
        """The weekly job that failed every week for months, made visible."""
        _result, summary, _report, _calls, _urls, _root = self.run_doctor(
            env={"DOCTOR_TEST_LAUNCHD_EXIT": "78"},
            setup=lambda root, home, _lb, _env: self._repo_job(root, home),
        )
        self.assertTrue(
            any(
                "last run FAILED" in warning and "com.fixture.job (last exit 78)" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_unlabelled_plist_is_unknown_not_loaded(self):
        """`launchctl print gui/501/` with an empty label prints the DOMAIN.

        Probing without a label would report every unlabelled plist as a healthy
        loaded job, which is the reassuring-wrong answer this program exists to
        prevent.
        """
        _result, summary, _report, calls, _urls, _root = self.run_doctor(
            setup=lambda root, home, _lb, _env: self._repo_job(root, home, label=None)
        )
        self.assertTrue(
            any("could not be probed" in unknown for unknown in summary["unknowns"]),
            summary["unknowns"],
        )
        self.assertNotIn("print gui/", calls)

    def test_no_mutating_launchctl_subcommand_is_ever_issued(self):
        """SAFETY. The operator's live jobs run through launchd."""
        _result, _summary, _report, calls, _urls, _root = self.run_doctor(
            setup=lambda root, home, _lb, _env: self._repo_job(root, home)
        )
        self.assertTrue(calls.strip(), "the launchctl stub was never called")
        for line in calls.splitlines():
            self.assertEqual(
                line.split()[0],
                "print",
                f"doctor issued a non-print launchctl subcommand: {line}",
            )


class BrowserCdpProbeTest(DoctorProbeRunner):
    """Reachability came out of a file another process wrote."""

    def test_live_probe_reports_the_browser_build(self):
        _result, summary, report, _calls, urls, _root = self.run_doctor()
        self.assertIn("Chrome/148.0.7778.98", report)
        self.assertIn("/json/version", urls)
        self.assertEqual(
            [w for w in summary["warnings"] if "CDP not reachable" in w],
            [],
            summary["warnings"],
        )

    def test_unreachable_port_is_a_warning_even_with_no_summary_file(self):
        """The old check could only answer this from a file that may not exist."""
        _result, summary, _report, _calls, _urls, _root = self.run_doctor(
            env={"DOCTOR_TEST_CDP_UP": "0"}
        )
        self.assertTrue(
            any(
                "Chrome CDP not reachable at 127.0.0.1:9222" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_probe_touches_no_tab_mutating_endpoint(self):
        """SAFETY. This Chrome holds authenticated bounty sessions."""
        _result, _summary, _report, _calls, urls, _root = self.run_doctor()
        self.assertTrue(urls.strip(), "the curl stub was never called")
        for url in urls.split():
            self.assertTrue(
                url.endswith("/json/version"),
                f"doctor requested a CDP endpoint other than /json/version: {url}",
            )


class BrainMapProbeTest(DoctorProbeRunner):
    """Existence stood in for a claim about the source-of-truth map."""

    def _write_map(self, root: Path, body: str) -> None:
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "brain-map.md").write_text(body, encoding="utf-8")
        (root / "chrono").mkdir(parents=True, exist_ok=True)
        (root / "chrono" / "CLAUDE.md").write_text("# Chrono\n", encoding="utf-8")
        registry = root / "shared" / "specialist-runtime-map.tsv"
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text("specialist\tto_model\nfixture\tclaude\n", encoding="utf-8")

    def test_all_canonical_paths_resolving_is_healthy(self):
        """Positive control."""
        result, _summary, report, _calls, _urls, _root = self.run_doctor(
            setup=lambda root, _h, _lb, _env: self._write_map(root, BRAIN_MAP_RESOLVING)
        )
        self.assertIn("every one of the 2 canonical path(s) it names resolves", report)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_path_that_moved_is_a_blocking_issue(self):
        result, summary, _report, _calls, _urls, _root = self.run_doctor(
            setup=lambda root, _h, _lb, _env: self._write_map(root, BRAIN_MAP_BROKEN)
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "brain map points at 1 path(s) that no longer exist" in issue
                and "shared/this-moved-away.md" in issue
                for issue in summary["issues"]
            ),
            summary["issues"],
        )

    def test_map_that_names_nothing_is_gate_blocking_not_a_pass(self):
        result, summary, _report, _calls, _urls, _root = self.run_doctor(
            setup=lambda root, _h, _lb, _env: self._write_map(root, BRAIN_MAP_EMPTY)
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "brain map names no canonical path" in entry
                for entry in summary["gate_unknowns"]
            ),
            summary["gate_unknowns"],
        )


class RuntimeRepositoryWriteProbeTest(DoctorProbeRunner):
    """`[[ -d ]] && [[ -w ]]` with no write attempted.

    The branch where the permission bits allow a write that the filesystem then
    refuses -- a read-only mount, a full disk -- cannot be produced inside a unit
    test without a special filesystem, and is not simulated here. What is pinned
    is that a write is genuinely ATTEMPTED and genuinely CLEANED UP, and that an
    unwritable root is still caught.
    """

    def test_probe_writes_and_removes_its_file(self):
        _result, _summary, report, _calls, _urls, root = self.run_doctor()
        self.assertIn("a probe file was created and removed", report)
        self.assertEqual(
            list(root.glob(".doctor-write-probe.*")),
            [],
            "the write probe left its file behind",
        )

    def test_unwritable_root_is_an_issue(self):
        def setup(root, _home, _local_bin, _environment):
            root.chmod(0o555)

        result, summary, _report, _calls, _urls, _root = self.run_doctor(setup=setup)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(
            any("runtime repository not writable" in issue for issue in summary["issues"]),
            summary["issues"],
        )


if __name__ == "__main__":
    unittest.main()
