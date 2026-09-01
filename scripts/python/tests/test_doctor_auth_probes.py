#!/usr/bin/env python3
"""Plan D Task 4: doctor verifies that the five lane CLIs are authenticated.

For a system whose entire premise is five authenticated native CLIs, doctor
verified auth for none of them. The whole check was one hardcoded line --
"CLI authentication state is not verified by doctor" -- so an installed-and-
logged-out lane and a working one produced the same green CLI section, and the
first evidence of a logged-out lane was a failed dispatch.

Two lanes answer a zero-token status subcommand; three expose none and get a
credential-at-rest check that is deliberately reported as the WEAKER claim it is
(UNKNOWN, never OK).

SAFETY, read before touching anything here
------------------------------------------
No test in this file runs a real CLI, reaches a network, or reads a real
credential. Doctor prepends ``$HOME/.local/bin`` to PATH, so the lane stubs
placed there WIN over the operator's real ``claude``/``codex``/``gemini``/
``grok``/``kimi``, and every credential file a test looks at is one the test just wrote
inside its own temporary HOME.

``test_api_key_value_never_reaches_the_report`` is the one that matters most
here: API keys have leaked through this system before, so the secret-handling
claim is pinned by a test rather than by a comment.
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

# A lane CLI that answers --version, and answers its vendor's own auth
# subcommand from an environment variable. codex deliberately writes to STDERR,
# because the real one does (measured 2026-08-17: stdout empty, stderr
# "Logged in using ChatGPT", exit 0) and doctor's watchdog discards stderr for
# the version probe -- a stub that answered on stdout would let that regression
# back in without failing anything.
LANE_CLI_WITH_AUTH = r"""#!/bin/bash
name="$(basename "$0")"
case "$1" in
    --version) printf 'doctor-fixture stub 0.0.0\n'; exit 0 ;;
esac
if [[ "$name" == claude && "$1" == auth && "$2" == status ]]; then
    if [[ -n "${DOCTOR_TEST_CLAUDE_AUTH_SLEEP:-}" ]]; then
        sleep "${DOCTOR_TEST_CLAUDE_AUTH_SLEEP}"
    fi
    printf '%s\n' "${DOCTOR_TEST_CLAUDE_AUTH:-}"
    exit "${DOCTOR_TEST_CLAUDE_AUTH_RC:-0}"
fi
if [[ "$name" == codex && "$1" == login && "$2" == status ]]; then
    printf '%s\n' "${DOCTOR_TEST_CODEX_AUTH:-}" >&2
    exit "${DOCTOR_TEST_CODEX_AUTH_RC:-0}"
fi
exit 0
"""

LOGGED_IN_JSON = json.dumps(
    {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "apiKeySource": "none",
    }
)
LOGGED_OUT_JSON = json.dumps({"loggedIn": False, "authMethod": None})

# A credential at rest, in the shape both file-based lanes actually use: a
# short-lived access token beside the durable refresh token. Values are
# obviously fake and never leave the fixture.
CREDENTIAL_WITH_REFRESH = json.dumps(
    {
        "access_token": "fixture-access",
        "refresh_token": "fixture-refresh",
        "expiry_date": 1,
        "token_type": "Bearer",
    }
)
CREDENTIAL_WITHOUT_REFRESH = json.dumps(
    {"access_token": "fixture-access", "expiry_date": 1}
)


def gemini_credential(home: Path) -> Path:
    return home / ".gemini" / "oauth_creds.json"


def kimi_credential(home: Path) -> Path:
    return home / ".kimi" / "credentials" / "kimi-code.json"


def write_credential(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)


class DoctorAuthRunner(unittest.TestCase):
    """Runs a real bin/doctor.sh whose five lane CLIs are stubs."""

    def run_doctor(
        self,
        *,
        env: dict[str, str] | None = None,
        credentials: bool = True,
        setup=None,
    ):
        with tempfile.TemporaryDirectory(prefix="doctor-auth-") as temp:
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
            for lane in ("claude", "codex", "gemini", "grok", "kimi"):
                doctor_fixture.write_stub(local_bin, lane, LANE_CLI_WITH_AUTH)
            if credentials:
                write_credential(gemini_credential(home), CREDENTIAL_WITH_REFRESH)
                write_credential(kimi_credential(home), CREDENTIAL_WITH_REFRESH)
                grok_secrets = home / ".config" / "shell" / "secrets.zsh"
                grok_secrets.parent.mkdir(parents=True, exist_ok=True)
                grok_secrets.write_text(
                    "export XAI_API_KEY=fixture-xai-key-never-log\n",
                    encoding="utf-8",
                )
                grok_secrets.chmod(0o600)

            environment = {
                **os.environ,
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "VAULT_ROOT": str(root),
                "TERM": "dumb",
                "LANG": "C",
                "TMPDIR": str(fixture),
                "DOCTOR_TEST_CLAUDE_AUTH": LOGGED_IN_JSON,
                "DOCTOR_TEST_CODEX_AUTH": "Logged in using ChatGPT",
            }
            environment.pop("CHRONO_DOCTOR_LOG_DIR", None)
            environment.pop("CHRONO_VAULT_ROOT", None)
            environment.pop("GEMINI_API_KEY", None)
            if setup is not None:
                setup(root, home, local_bin, environment)
            environment.update(env or {})

            result = subprocess.run(
                ["/bin/bash", str(root / "bin" / "doctor.sh")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
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


class ClaudeAuthProbeTest(DoctorAuthRunner):
    def test_logged_in_reports_method_and_key_source(self):
        """Step 3: apiKeySource is the field that has burned this system."""
        _result, summary, report = self.run_doctor(
            env={
                "DOCTOR_TEST_CLAUDE_AUTH": json.dumps(
                    {
                        "loggedIn": True,
                        "authMethod": "claude.ai",
                        "apiKeySource": "ANTHROPIC_API_KEY",
                    }
                )
            }
        )
        self.assertIn("authMethod=claude.ai", report)
        self.assertIn("apiKeySource=ANTHROPIC_API_KEY", report)
        self.assertEqual(
            [w for w in summary["warnings"] if w.startswith("claude ")],
            [],
            summary["warnings"],
        )

    def test_logged_out_is_a_warning_naming_the_login_command(self):
        _result, summary, _report = self.run_doctor(
            env={"DOCTOR_TEST_CLAUDE_AUTH": LOGGED_OUT_JSON}
        )
        self.assertTrue(
            any(
                "claude is NOT logged in" in warning and "claude auth login" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_probe_failure_is_unknown_not_logged_out(self):
        """Fail-closed: doctor established neither state."""
        _result, summary, _report = self.run_doctor(
            env={"DOCTOR_TEST_CLAUDE_AUTH_RC": "3", "DOCTOR_TEST_CLAUDE_AUTH": ""}
        )
        self.assertTrue(
            any("claude auth probe failed" in u for u in summary["unknowns"]),
            summary["unknowns"],
        )
        self.assertEqual(
            [w for w in summary["warnings"] if "NOT logged in" in w],
            [],
            summary["warnings"],
        )

    def test_unparseable_answer_is_unknown_not_a_pass(self):
        _result, summary, _report = self.run_doctor(
            env={"DOCTOR_TEST_CLAUDE_AUTH": "Anthropic CLI: something went wrong"}
        )
        self.assertTrue(
            any("could not be parsed" in u for u in summary["unknowns"]),
            summary["unknowns"],
        )

    def test_hanging_probe_is_bounded_and_reports_unknown(self):
        """A lane that never answers must not hang the 45s launch gate."""
        _result, summary, _report = self.run_doctor(
            env={"DOCTOR_TEST_CLAUDE_AUTH_SLEEP": "9"}
        )
        self.assertTrue(
            any("claude auth probe failed or timed out" in u for u in summary["unknowns"]),
            summary["unknowns"],
        )


class CodexAuthProbeTest(DoctorAuthRunner):
    def test_logged_in_answer_on_stderr_is_read(self):
        """`codex login status` answers on STDERR; the watchdog drops stderr."""
        _result, summary, report = self.run_doctor()
        self.assertIn("codex: Logged in using ChatGPT", report)
        self.assertEqual(
            [w for w in summary["warnings"] if w.startswith("codex ")],
            [],
            summary["warnings"],
        )
        # And it must not have fallen through to "could not be read", which is
        # exactly what an unmerged stderr produced before this was measured.
        self.assertEqual(
            [u for u in summary["unknowns"] if u.startswith("codex ")],
            [],
            summary["unknowns"],
        )

    def test_logged_out_is_a_warning_naming_the_login_command(self):
        _result, summary, _report = self.run_doctor(
            env={
                "DOCTOR_TEST_CODEX_AUTH_RC": "1",
                "DOCTOR_TEST_CODEX_AUTH": "Not logged in",
            }
        )
        self.assertTrue(
            any(
                "codex is NOT logged in" in warning and "codex login" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_unrecognised_answer_is_unknown_not_logged_out(self):
        _result, summary, _report = self.run_doctor(
            env={"DOCTOR_TEST_CODEX_AUTH": "usage: codex login [OPTIONS]"}
        )
        self.assertTrue(
            any("codex auth state could not be read" in u for u in summary["unknowns"]),
            summary["unknowns"],
        )


class CredentialFileLaneTest(DoctorAuthRunner):
    """gemini, grok, and kimi expose no zero-token status subcommand."""

    def test_refresh_credential_is_unknown_never_a_pass(self):
        """A credential at rest is not a login result, and must not read as one."""
        _result, summary, report = self.run_doctor()
        for lane in ("gemini", "kimi"):
            self.assertTrue(
                any(
                    lane in unknown and "login state not verifiable" in unknown
                    for unknown in summary["unknowns"]
                ),
                (lane, summary["unknowns"]),
            )
        self.assertIn(".gemini/oauth_creds.json", report)
        self.assertIn(".kimi/credentials/kimi-code.json", report)
        self.assertTrue(
            any(
                "grok login state not verifiable" in unknown
                and "XAI_API_KEY" in unknown
                for unknown in summary["unknowns"]
            ),
            summary["unknowns"],
        )
        self.assertNotIn("fixture-xai-key-never-log", report)

    def test_missing_credential_is_a_warning_naming_the_fix(self):
        _result, summary, _report = self.run_doctor(credentials=False)
        self.assertTrue(
            any(
                "kimi has no credential" in warning and "kimi login" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )
        self.assertTrue(
            any("gemini has no credential" in warning for warning in summary["warnings"]),
            summary["warnings"],
        )

    def test_credential_without_a_refresh_token_is_a_warning(self):
        """An access token alone cannot re-authenticate a headless dispatch."""

        def setup(_root, home, _local_bin, _environment):
            write_credential(kimi_credential(home), CREDENTIAL_WITHOUT_REFRESH)

        _result, summary, _report = self.run_doctor(credentials=True, setup=setup)
        self.assertTrue(
            any(
                "kimi credential file is present but carries no refresh token" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_api_key_value_never_reaches_the_report(self):
        """The secret-handling claim, pinned. Presence of the NAME only.

        API keys have leaked through this system before, so this asserts the
        value appears in NOTHING doctor writes or prints -- while the finding
        that the key is set still reaches the reader.
        """
        secret = "AIzaSy-doctor-fixture-secret-value-do-not-log"

        def setup(_root, home, _local_bin, _environment):
            gemini_credential(home).unlink(missing_ok=True)

        result, summary, report = self.run_doctor(
            env={"GEMINI_API_KEY": secret}, credentials=True, setup=setup
        )
        self.assertNotIn(secret, report)
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn(secret, json.dumps(summary))
        self.assertTrue(
            any(
                "GEMINI_API_KEY is set in this environment" in unknown
                for unknown in summary["unknowns"]
            ),
            summary["unknowns"],
        )


# Doctor probes the dispatch rail's lane inventory only when HOME matches the
# effective-UID account home, which a hermetic fixture never does. This stub
# answers both python3 calls that gate reaches: the effective-UID home (a script
# on stdin, no PYTHONPATH) and the inventory itself. The vault-root check also
# reads a script on stdin, and is told apart by the PYTHONPATH doctor sets for
# it -- it must keep failing, because this fixture configures no vault.
PYTHON3_INVENTORY_STUB = r"""#!/bin/bash
for argument in "$@"; do
    case "$argument" in
        *dispatch_context_builder.py)
            printf '%s\n' "${DOCTOR_TEST_LANE_INVENTORY:-}"
            exit 0
            ;;
    esac
done
case "${PYTHONPATH:-}" in
    *chrono-vault*) exit 1 ;;
esac
printf '%s\n' "${HOME}"
exit 0
"""


class DeclaredVersusObservedAuthTest(DoctorAuthRunner):
    """CLAUDE.md rule 9, applied to authentication: only actual counts."""

    def _inventory_row(self, lane: str, home: Path, auth_policy: str) -> str:
        binary = home / ".local" / "bin" / lane
        return "\t".join([lane, "true", str(binary), str(binary), "0.0.0", auth_policy, ""])

    def test_subscription_policy_with_api_key_method_is_a_warning(self):
        """The burn: a plan-billed lane reporting it authenticated by key."""

        def setup(_root, home, local_bin, environment):
            doctor_fixture.write_stub(local_bin, "python3", PYTHON3_INVENTORY_STUB)
            environment["DOCTOR_TEST_LANE_INVENTORY"] = "\n".join(
                self._inventory_row(lane, home, "subscription")
                for lane in ("claude", "codex")
            )

        _result, summary, report = self.run_doctor(
            env={
                "DOCTOR_TEST_CLAUDE_AUTH": json.dumps(
                    {
                        "loggedIn": True,
                        "authMethod": "apiKey",
                        "apiKeySource": "ANTHROPIC_API_KEY",
                    }
                )
            },
            setup=setup,
        )
        self.assertIn("observed-auth=apiKey/ANTHROPIC_API_KEY", report)
        self.assertTrue(
            any(
                "policy is subscription auth but the CLI reports it authenticated"
                " with an API key" in warning
                for warning in summary["warnings"]
            ),
            summary["warnings"],
        )

    def test_subscription_policy_with_subscription_method_is_not_a_finding(self):
        """An API key merely PRESENT in the environment is not this condition.

        This repository sets those variables deliberately and strips them before
        it execs a lane, so warning on their presence would fire every day.
        """

        def setup(_root, home, local_bin, environment):
            doctor_fixture.write_stub(local_bin, "python3", PYTHON3_INVENTORY_STUB)
            environment["DOCTOR_TEST_LANE_INVENTORY"] = self._inventory_row(
                "claude", home, "subscription"
            )

        _result, summary, report = self.run_doctor(
            env={
                "DOCTOR_TEST_CLAUDE_AUTH": json.dumps(
                    {
                        "loggedIn": True,
                        "authMethod": "claude.ai",
                        "apiKeySource": "ANTHROPIC_API_KEY",
                    }
                )
            },
            setup=setup,
        )
        self.assertIn("observed-auth=claude.ai/ANTHROPIC_API_KEY", report)
        self.assertEqual(
            [w for w in summary["warnings"] if "authenticated with an API key" in w],
            [],
            summary["warnings"],
        )


class BlanketAuthDisclaimerRemovedTest(DoctorAuthRunner):
    """The line this task replaces must not survive alongside the probes."""

    def test_hardcoded_not_verified_line_is_gone(self):
        _result, summary, report = self.run_doctor()
        self.assertNotIn("NOT VERIFIED for any lane", report)
        self.assertEqual(
            [
                unknown
                for unknown in summary["unknowns"]
                if unknown == "CLI authentication state is not verified by doctor"
            ],
            [],
            summary["unknowns"],
        )


if __name__ == "__main__":
    unittest.main()
