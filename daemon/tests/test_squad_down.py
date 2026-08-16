from __future__ import annotations

import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
SQUAD = REPO / "bin" / "squad"
LAUNCH_SQUAD = REPO / "bin" / "launch-squad.sh"
RUNBOOK = REPO / "docs" / "rollback-runbook.md"
DAEMON_LABEL = "com.vibesquad.daemon"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _fake_commands(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    state = tmp_path / "launchctl-state"
    state.write_text("loaded")
    log = tmp_path / "commands.log"
    log.write_text("")

    _write_executable(
        fake_bin / "launchctl",
        """#!/bin/bash
set -u
printf 'launchctl %s\n' "$*" >> "${SQUAD_TEST_LOG}"
case "${1:-}" in
    print)
        current="$(<"${SQUAD_TEST_STATE}")"
        if [[ "${current}" == "loaded" ]]; then
            exit 0
        fi
        if [[ "${current}" == "query-error" ]]; then
            exit "${SQUAD_TEST_PRINT_RC:-77}"
        fi
        exit 113
        ;;
    bootout)
        if [[ "${SQUAD_TEST_BOOTOUT_REMOVES:-1}" == "1" ]]; then
            printf 'stopped' > "${SQUAD_TEST_STATE}"
        fi
        exit "${SQUAD_TEST_BOOTOUT_RC:-0}"
        ;;
    bootstrap)
        if [[ "${SQUAD_TEST_BOOTSTRAP_LOADS:-1}" == "1" ]]; then
            printf 'loaded' > "${SQUAD_TEST_STATE}"
        fi
        exit "${SQUAD_TEST_BOOTSTRAP_RC:-0}"
        ;;
    *)
        exit 64
        ;;
esac
""",
    )
    _write_executable(
        fake_bin / "bash",
        """#!/bin/bash
printf 'bash %s\n' "$*" >> "${SQUAD_TEST_LOG}"
exit "${SQUAD_TEST_BASH_RC:-0}"
""",
    )
    _write_executable(
        fake_bin / "plutil",
        """#!/bin/bash
printf 'plutil %s\n' "$*" >> "${SQUAD_TEST_LOG}"
exit "${SQUAD_TEST_PLUTIL_RC:-0}"
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "VAULT_ROOT": str(REPO),
            "SQUAD_TEST_LOG": str(log),
            "SQUAD_TEST_STATE": str(state),
            "SQUAD_DAEMON_VERIFY_ATTEMPTS": "1",
            "SQUAD_DAEMON_VERIFY_DELAY": "0",
        }
    )
    return env, state, log


def _run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _case_squad_down_boots_out_daemon_and_verifies_before_tmux_shutdown(
    tmp_path: Path,
) -> None:
    env, state, log = _fake_commands(tmp_path)

    result = _run(["/bin/bash", str(SQUAD), "down"], env)

    target = f"gui/{os.getuid()}/{DAEMON_LABEL}"
    assert result.returncode == 0, result.stderr
    assert state.read_text() == "stopped"
    assert log.read_text().splitlines() == [
        f"launchctl print {target}",
        f"launchctl bootout {target}",
        f"launchctl print {target}",
        f"bash {REPO / 'bin' / 'squad-stop.sh'}",
    ]
    assert f"verified absent from launchd: {target}" in result.stdout


def _case_squad_down_positive_control_rejects_bootout_that_leaves_daemon_loaded(
    tmp_path: Path,
) -> None:
    env, state, log = _fake_commands(tmp_path)
    env["SQUAD_TEST_BOOTOUT_REMOVES"] = "0"

    result = _run(["/bin/bash", str(SQUAD), "down"], env)

    assert result.returncode != 0
    assert state.read_text() == "loaded"
    assert "daemon remains loaded after launchctl bootout" in result.stderr
    assert not any(line.startswith("bash ") for line in log.read_text().splitlines())


def _case_squad_down_is_idempotent_when_daemon_is_already_absent(
    tmp_path: Path,
) -> None:
    env, state, log = _fake_commands(tmp_path)
    state.write_text("stopped")

    result = _run(["/bin/bash", str(SQUAD), "down"], env)

    target = f"gui/{os.getuid()}/{DAEMON_LABEL}"
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        f"launchctl print {target}",
        f"bash {REPO / 'bin' / 'squad-stop.sh'}",
    ]
    assert f"already stopped: {target}" in result.stdout


def _case_squad_up_bootstraps_only_rendered_installed_daemon_plist(
    tmp_path: Path,
) -> None:
    env, state, log = _fake_commands(tmp_path)
    state.write_text("stopped")
    home = tmp_path / "home"
    installed_dir = home / "Library" / "LaunchAgents"
    installed_dir.mkdir(parents=True)
    installed_plist = installed_dir / f"{DAEMON_LABEL}.plist"
    template = (REPO / "launchd" / installed_plist.name).read_text()
    installed_plist.write_text(
        template.replace("__VAULT_ROOT__", str(REPO)).replace("__HOME__", str(home))
    )
    env.update({"HOME": str(home), "SQUAD_DAEMON_ENSURE_ONLY": "1"})

    result = _run(["/bin/bash", str(LAUNCH_SQUAD)], env)

    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{DAEMON_LABEL}"
    assert result.returncode == 0, result.stderr
    assert state.read_text() == "loaded"
    assert log.read_text().splitlines() == [
        f"launchctl print {target}",
        f"plutil -lint {installed_plist}",
        f"launchctl bootstrap {domain} {installed_plist}",
        f"launchctl print {target}",
    ]
    assert f"loaded and verified in launchd: {target}" in result.stdout


def _case_squad_up_refuses_unsubstituted_daemon_template(tmp_path: Path) -> None:
    env, state, log = _fake_commands(tmp_path)
    state.write_text("stopped")
    home = tmp_path / "home"
    installed_dir = home / "Library" / "LaunchAgents"
    installed_dir.mkdir(parents=True)
    installed_plist = installed_dir / f"{DAEMON_LABEL}.plist"
    installed_plist.write_text((REPO / "launchd" / installed_plist.name).read_text())
    env.update({"HOME": str(home), "SQUAD_DAEMON_ENSURE_ONLY": "1"})

    result = _run(["/bin/bash", str(LAUNCH_SQUAD)], env)

    assert result.returncode != 0
    assert "still contains a template token" in result.stderr
    assert not any(" bootstrap " in line for line in log.read_text().splitlines())


def _case_squad_up_positive_control_rejects_false_bootstrap(tmp_path: Path) -> None:
    env, state, _log = _fake_commands(tmp_path)
    state.write_text("stopped")
    home = tmp_path / "home"
    installed_dir = home / "Library" / "LaunchAgents"
    installed_dir.mkdir(parents=True)
    installed_plist = installed_dir / f"{DAEMON_LABEL}.plist"
    template = (REPO / "launchd" / installed_plist.name).read_text()
    installed_plist.write_text(
        template.replace("__VAULT_ROOT__", str(REPO)).replace("__HOME__", str(home))
    )
    env.update(
        {
            "HOME": str(home),
            "SQUAD_DAEMON_ENSURE_ONLY": "1",
            "SQUAD_TEST_BOOTSTRAP_LOADS": "0",
        }
    )

    result = _run(["/bin/bash", str(LAUNCH_SQUAD)], env)

    assert result.returncode != 0
    assert state.read_text() == "stopped"
    assert "still absent after launchctl bootstrap" in result.stderr


def _runbook_restore_script() -> str:
    text = RUNBOOK.read_text()
    marked = text.split("<!-- plist-restore-script: begin -->", 1)[1].split(
        "<!-- plist-restore-script: end -->", 1
    )[0]
    return marked.split("```bash\n", 1)[1].rsplit("\n```", 1)[0]


def _case_runbook_restore_renders_every_tracked_plist_before_bootstrap(
    tmp_path: Path,
) -> None:
    env, state, log = _fake_commands(tmp_path)
    state.write_text("stopped")
    home = tmp_path / "home"
    destination = home / "Library" / "LaunchAgents"
    env.update(
        {
            "HOME": str(home),
            "REPO_ROOT": str(REPO),
            "LAUNCH_AGENTS_DIR": str(destination),
        }
    )
    script = _runbook_restore_script()
    templates = sorted((REPO / "launchd").glob("*.plist"))
    assert len(templates) == 10

    for template in templates:
        run_env = env | {"AGENT": template.name}
        result = _run(["/bin/bash", "-c", script], run_env)
        assert result.returncode == 0, f"{template.name}: {result.stderr}"
        installed = destination / template.name
        rendered = installed.read_text()
        assert "__VAULT_ROOT__" not in rendered
        assert "__HOME__" not in rendered
        plistlib.loads(installed.read_bytes())

    bootstrap_lines = [
        line for line in log.read_text().splitlines() if line.startswith("launchctl bootstrap ")
    ]
    assert len(bootstrap_lines) == len(templates)


def _case_runbook_restore_placeholder_guard_has_a_positive_control(
    tmp_path: Path,
) -> None:
    env, state, log = _fake_commands(tmp_path)
    state.write_text("stopped")
    home = tmp_path / "home"
    fake_repo = tmp_path / "repo"
    launchd = fake_repo / "launchd"
    launchd.mkdir(parents=True)
    agent = "com.example.positive-control.plist"
    (launchd / agent).write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Label</key><string>__UNRESOLVED__</string></dict></plist>
"""
    )
    env.update(
        {
            "HOME": str(home),
            "REPO_ROOT": str(fake_repo),
            "LAUNCH_AGENTS_DIR": str(home / "Library" / "LaunchAgents"),
            "AGENT": agent,
        }
    )

    result = _run(["/bin/bash", "-c", _runbook_restore_script()], env)

    assert result.returncode != 0
    assert "still contains a template token" in result.stderr
    assert not any(" bootstrap " in line for line in log.read_text().splitlines())


class SquadLifecycleTests(unittest.TestCase):
    def _run_case(self, case) -> None:
        with tempfile.TemporaryDirectory(prefix="vibesquad-shutdown-test-") as temp:
            case(Path(temp))

    def test_squad_down_boots_out_daemon_and_verifies_before_tmux_shutdown(self):
        self._run_case(
            _case_squad_down_boots_out_daemon_and_verifies_before_tmux_shutdown
        )

    def test_shell_label_copies_match_the_canonical_launchd_plist(self):
        canonical = plistlib.loads(
            (REPO / "launchd" / "com.vibesquad.daemon.plist").read_bytes()
        )["Label"]
        self.assertEqual(canonical, DAEMON_LABEL)
        for script in (SQUAD, LAUNCH_SQUAD):
            self.assertIn(f'DAEMON_LABEL="{canonical}"', script.read_text())

    def test_squad_down_positive_control_rejects_false_shutdown(self):
        self._run_case(
            _case_squad_down_positive_control_rejects_bootout_that_leaves_daemon_loaded
        )

    def test_squad_down_is_idempotent_when_daemon_is_already_absent(self):
        self._run_case(_case_squad_down_is_idempotent_when_daemon_is_already_absent)

    def test_squad_up_bootstraps_only_rendered_installed_daemon_plist(self):
        self._run_case(
            _case_squad_up_bootstraps_only_rendered_installed_daemon_plist
        )

    def test_squad_up_refuses_unsubstituted_daemon_template(self):
        self._run_case(_case_squad_up_refuses_unsubstituted_daemon_template)

    def test_squad_up_positive_control_rejects_false_bootstrap(self):
        self._run_case(_case_squad_up_positive_control_rejects_false_bootstrap)

    def test_runbook_restore_renders_every_tracked_plist_before_bootstrap(self):
        self._run_case(
            _case_runbook_restore_renders_every_tracked_plist_before_bootstrap
        )

    def test_runbook_restore_placeholder_guard_has_a_positive_control(self):
        self._run_case(
            _case_runbook_restore_placeholder_guard_has_a_positive_control
        )
