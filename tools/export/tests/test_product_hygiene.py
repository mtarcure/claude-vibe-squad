from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class ProductHygieneGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "candidate"
        self.reports = self.base / "reports"
        self.reports.mkdir()

        (self.root / "bin").mkdir(parents=True)
        (self.root / "tools/export/policy").mkdir(parents=True)
        (self.root / "_state").mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "bin/product-hygiene.sh", self.root / "bin/product-hygiene.sh")
        shutil.copy2(REPO_ROOT / "tools/export/path_policy.py", self.root / "tools/export/path_policy.py")
        shutil.copy2(REPO_ROOT / "tools/export/content_scan.py", self.root / "tools/export/content_scan.py")
        shutil.copy2(REPO_ROOT / "tools/export/gitleaks_filter.py", self.root / "tools/export/gitleaks_filter.py")
        shutil.copy2(
            REPO_ROOT / "tools/export/policy/path-policy.json",
            self.root / "tools/export/policy/path-policy.json",
        )
        shutil.copy2(
            REPO_ROOT / "tools/export/policy/content-fingerprints.json",
            self.root / "tools/export/policy/content-fingerprints.json",
        )
        shutil.copy2(
            REPO_ROOT / "tools/export/policy/gitleaks.toml",
            self.root / "tools/export/policy/gitleaks.toml",
        )
        shutil.copy2(
            REPO_ROOT / "tools/export/policy/gitleaks-fingerprints.json",
            self.root / "tools/export/policy/gitleaks-fingerprints.json",
        )
        (self.root / "README.md").write_text("# Clean fixture\n", encoding="utf-8")
        # _state/.gitkeep is the surviving exact public exception. dream-config.yaml
        # was one too until 2026-08-09; creating it here now makes the fixture tree
        # dirty (tracked_blockers=1) because it is no longer allowlisted.
        (self.root / "_state/.gitkeep").touch()
        self.denylist = self.base / "identifier-denylist.txt"
        self.denylist.write_text("blocked-codeword\n", encoding="utf-8")

        self._run(["git", "init", "-q"], check=True)
        self._run(["git", "add", "-f", "."], check=True)

    def _run(
        self,
        command: list[str],
        *,
        check: bool = False,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.root,
            check=check,
            text=True,
            capture_output=True,
            env=env,
        )

    def _gate(self, *, env: dict[str, str] | None = None, report: Path | None = None):
        report_path = report or self.reports / "gate.md"
        gate_environment = os.environ.copy()
        if env:
            gate_environment.update(env)
        gate_environment.setdefault(
            "GITLEAKS_CONFIG",
            str(self.root / "tools/export/policy/gitleaks.toml"),
        )
        return self._run(
            [
                "bash",
                "bin/product-hygiene.sh",
                "--public-export",
                "--root",
                str(self.root),
                "--identifier-denylist",
                str(self.denylist),
                "--report",
                str(report_path),
            ],
            env=gate_environment,
        )

    def _track(self, relative_path: str, content: str = "fixture\n") -> None:
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        self._run(["git", "add", "-f", "--", relative_path], check=True)

    def test_clean_product_tree_and_exact_exceptions_pass(self) -> None:
        result = self._gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = (self.reports / "gate.md").read_text(encoding="utf-8")
        self.assertIn("Path-policy status: 0", report)
        self.assertIn("Gitleaks status: 0", report)
        self.assertIn("Entropy/identifier status: 0", report)
        self.assertIn(f"Canonical root scanned: {self.root.resolve()}", result.stdout)

    def test_tracked_private_payload_fails(self) -> None:
        self._track("departments/coding/inbox/payload.bin")
        result = self._gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("departments/coding/inbox/payload.bin", (self.reports / "gate.md").read_text())

    def test_policy_failure_does_not_suppress_independent_content_scan(self) -> None:
        self._track("departments/coding/inbox/payload.bin")
        planted_home = "/" + "Users" + "/gate-canary/private/config.json"
        self._track("README.md", f"path={planted_home}\n")

        result = self._gate()

        self.assertEqual(result.returncode, 1)
        report = (self.reports / "gate.md").read_text(encoding="utf-8")
        self.assertIn("Path-policy status: 1", report)
        self.assertIn("Entropy/identifier status: 1", report)
        self.assertIn(
            'private-home-absolute path="README.md"',
            report,
        )
        self.assertNotIn("Skipped because the tracked-path policy failed closed", report)
        self.assertIn("departments/coding/inbox/payload.bin", result.stderr)
        self.assertIn("policy_section=deny", result.stderr)
        self.assertIn('policy_pattern="departments/*/inbox/**"', result.stderr)
        self.assertIn('private-home-absolute path="README.md"', result.stderr)

    def test_novel_top_level_path_fails_deny_unknown(self) -> None:
        self._track("novel-surface/readme.txt")
        result = self._gate()
        self.assertEqual(result.returncode, 1)
        report = (self.reports / "gate.md").read_text(encoding="utf-8")
        self.assertIn("Unknown tracked paths: 1", report)
        self.assertIn("novel-surface/readme.txt", report)

    def test_private_identifier_hit_fails(self) -> None:
        self._track("README.md", "Contains BLOCKED-CODEWORD deployment data.\n")
        result = self._gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("private-identifier", (self.reports / "gate.md").read_text())

    def test_utf16_private_identifier_hit_fails_closed(self) -> None:
        (self.root / "README.md").write_bytes(
            "Contains BLOCKED-CODEWORD deployment data.\n".encode("utf-16")
        )
        self._run(["git", "add", "-f", "--", "README.md"], check=True)
        result = self._gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("private-identifier", (self.reports / "gate.md").read_text())

    def test_utf16le_without_bom_private_identifier_fails_closed(self) -> None:
        (self.root / "README.md").write_bytes(
            "Contains BLOCKED-CODEWORD deployment data.\n".encode("utf-16le")
        )
        self._run(["git", "add", "-f", "--", "README.md"], check=True)
        result = self._gate()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("not valid UTF-8/16/32", (self.reports / "gate.md").read_text())

    def test_utf16be_without_bom_private_identifier_fails_closed(self) -> None:
        (self.root / "README.md").write_bytes(
            "Contains BLOCKED-CODEWORD deployment data.\n".encode("utf-16be")
        )
        self._run(["git", "add", "-f", "--", "README.md"], check=True)
        result = self._gate()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("not valid UTF-8/16/32", (self.reports / "gate.md").read_text())

    def test_private_home_absolute_paths_fail_the_maintained_gate(self) -> None:
        operator_home = self.base / "operator-home"
        macos_home = "/" + "Users" + "/alice/private/config.json"
        linux_home = "/" + "home" + "/bob/private/config.json"
        operator_path = str(operator_home / "private" / "config.json")
        unicode_home = "/" + "Users" + "/álîce/private/config.json"
        dollar_home = "/" + "home" + "/build$/private/config.json"
        plus_home = "/" + "home" + "/user+/private/config.json"
        punctuation_homes = [
            "/" + "Users" + f"/alice{suffix}"
            for suffix in (")", ",", "]", ":")
        ]
        self._track("README.md", f"path={macos_home}\n")
        self._track("CHANGELOG.md", f"path={linux_home}\n")
        self._track(
            "CODE_OF_CONDUCT.md",
            f"path={operator_path}\nexact={operator_home})\n",
        )
        self._track("CONTRIBUTING.md", f"path={unicode_home}\n")
        self._track("GEMINI.md", f"path={dollar_home}\n")
        self._track("SECURITY.md", f"path={plus_home}\n")
        self._track(
            "requirements-dev.txt",
            "".join(f"path={path}\n" for path in punctuation_homes),
        )
        symlink_path = self.root / "AGENTS.md"
        os.symlink("/" + "Users" + "/carol/private/config.json", symlink_path)
        self._run(["git", "add", "-f", "--", "AGENTS.md"], check=True)
        result = self._gate(env={"HOME": str(operator_home)})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = (self.reports / "gate.md").read_text(encoding="utf-8")
        self.assertIn("Independent content findings: 12", report)
        self.assertEqual(report.count("private-home-absolute"), 12)
        self.assertNotIn(str(operator_home), report)
        self.assertNotIn(macos_home, report)

    def test_relative_home_like_paths_do_not_fail_the_maintained_gate(self) -> None:
        self._track(
            "README.md",
            "Use Users/alice/config.json or home/bob/config.json as relative examples.\n",
        )
        result = self._gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_high_entropy_assignment_fails_independent_check(self) -> None:
        generated = "aB3_cD4-eF5_gH6-iJ7_kL8-mN9_oP0"
        self._track("README.md", f"access_token = {generated}\n")
        result = self._gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("high-entropy-token", (self.reports / "gate.md").read_text())

    def test_exact_synthetic_fixture_fingerprint_is_allowed_only_at_exact_path(self) -> None:
        fixture = (
            'export const apiKey = "api_key='
            + "sk_test_51"
            + "SyntheticCredentialValue9999"
            + '";\n'
        )
        self._track("moat/fixtures/purity/deny/credential.mjs", fixture)
        allowed = self._gate()
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)

        self._track("README.md", fixture)
        copied = self._gate()
        self.assertEqual(copied.returncode, 1)
        self.assertIn("high-entropy-token", (self.reports / "gate.md").read_text())

    def test_verified_false_positive_fingerprints_pass_at_exact_paths(self) -> None:
        config_key = "bm25" + "_weights"
        config_lookup = (
            f'connection.execute("SELECT value FROM config WHERE key=\'{config_key}\'")\n'
        )
        self._track(
            "plugins/chrono-vault/recall.py",
            config_lookup,
        )
        self._track(
            "plugins/chrono-vault/tests/test_index.py",
            config_lookup,
        )
        jwt_header = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"
        jwt_payload = "eyJzdWIiOiJzeW50aGV0aWMtdGVzdCJ9"
        jwt_signature = "c3ludGhldGljLXNpZ25hdHVyZV8t"
        self._track(
            "moat/fixtures/purity/allow/real-world-vectors.json",
            f'{{"jwt_test_vector":"{jwt_header}.{jwt_payload}.{jwt_signature}"}}\n',
        )
        result = self._gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = (self.reports / "gate.md").read_text(encoding="utf-8")
        self.assertIn("exact_fingerprint_allowed=3", report)
        self.assertNotIn(config_key, report)
        self.assertNotIn("eyJhbGci", report)

    def test_current_drift_documentation_passes_but_stale_names_and_fill_values_fail(self) -> None:
        self._track(
            "docs/adding-a-specialist.md",
            "Also validated: no `<FILL:...>` placeholders remain, and every skill exists.\n",
        )
        self._track(
            "shared/current-tools.md",
            "Use `perplexity_search` for current grounded research.\n",
        )
        current = self._gate()
        self.assertEqual(current.returncode, 0, current.stdout + current.stderr)

        self._track(
            "shared/stale-tools.md",
            "Do not retain the retired `perplexity_search_web` alias.\n",
        )
        retired = self._gate()
        self.assertEqual(retired.returncode, 1)
        self.assertIn(
            "perplexity_search_web",
            (self.reports / "gate.md").read_text(),
        )

        self._track("shared/stale-tools.md", "Use brave_search directly.\n")
        stale = self._gate()
        self.assertEqual(stale.returncode, 1)
        self.assertIn("brave_search", (self.reports / "gate.md").read_text())

        self._track("shared/stale-tools.md", "name: <FILL:specialist-name>\n")
        fill = self._gate()
        self.assertEqual(fill.returncode, 1)
        self.assertIn("<FILL:specialist-name>", (self.reports / "gate.md").read_text())

    def test_maintained_scanner_unavailable_fails_closed(self) -> None:
        environment = os.environ.copy()
        environment["GITLEAKS_BIN"] = str(self.base / "missing-gitleaks")
        result = self._gate(env=environment)
        self.assertEqual(result.returncode, 2)
        self.assertIn("scanner unavailable", result.stderr)

    def test_gate_refuses_in_tree_report_and_default_writes_nothing_in_tree(self) -> None:
        default_result = self._run(
            [
                "bash",
                "bin/product-hygiene.sh",
                "--public-export",
                "--root",
                str(self.root),
                "--identifier-denylist",
                str(self.denylist),
            ]
        )
        self.assertEqual(default_result.returncode, 0, default_result.stdout + default_result.stderr)
        self.assertFalse((self.root / "_state/cleanup-logs").exists())

        inside = self.root / "inside-report.md"
        refused = self._gate(report=inside)
        self.assertEqual(refused.returncode, 2)
        self.assertFalse(inside.exists())
        self.assertIn("outside the certified tree", refused.stderr)


if __name__ == "__main__":
    unittest.main()
