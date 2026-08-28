from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner_python  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts" / "python" / "check_duplicate_blobs.py"
RUNNER = ROOT / "bin" / "test"
HEADER = (
    "blob_group\twinner_path\tmember_paths\tenforced_by\tdisposition\treason\n"
)
IDENTITY_ENFORCER = "scripts/python/check_duplicate_blobs.py"
SKILL_MIRROR_ENFORCER = "scripts/python/validate_skill_wiring.py"
SKILL_MIRROR_POLICY = "model-lanes/SKILL-HOMES.md"


class DuplicateBlobGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.registry = self.repo / "identical-blobs.tsv"
        self.run_git("init", "-q")
        (self.repo / "first.txt").write_text("same bytes\n", encoding="utf-8")
        (self.repo / "second.txt").write_text("same bytes\n", encoding="utf-8")
        (self.repo / "validator.py").write_text("# named validator\n", encoding="utf-8")
        identity_enforcer = self.repo / IDENTITY_ENFORCER
        identity_enforcer.parent.mkdir(parents=True)
        shutil.copyfile(CHECKER, identity_enforcer)
        self.registry.write_text(HEADER, encoding="utf-8")
        self.run_git(
            "add",
            "--",
            "first.txt",
            "second.txt",
            "validator.py",
            IDENTITY_ENFORCER,
            self.registry.name,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_git(self, *args: str) -> None:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def write_declaration(
        self,
        *,
        members: tuple[str, ...] = ("first.txt", "second.txt"),
        enforcers: tuple[str, ...] = (IDENTITY_ENFORCER,),
        disposition: str = "intentional",
    ) -> None:
        row = (
            "fixture-pair\t"
            f"{json.dumps(members[0])}\t"
            f"{json.dumps(list(members), separators=(',', ':'))}\t"
            f"{json.dumps(list(enforcers), separators=(',', ':'))}\t"
            f"{disposition}\t"
            "Test declaration with a named winner and enforcer.\n"
        )
        self.registry.write_text(HEADER + row, encoding="utf-8")
        self.run_git("add", "--", self.registry.name)

    def replace_default_duplicate_with_distinct_files(self) -> None:
        (self.repo / "first.txt").write_text("first bytes\n", encoding="utf-8")
        (self.repo / "second.txt").write_text("second bytes\n", encoding="utf-8")
        self.run_git("add", "--", "first.txt", "second.txt")

    def write_skill_mirror(
        self,
        *,
        name: str = "fixture-skill",
        audience: str = "specialist",
        track_contract: bool = True,
        include_canonical: bool = True,
        include_gemini_bridge: bool = False,
    ) -> bytes:
        content = (
            "---\n"
            f"name: {name}\n"
            f"audience: {audience}\n"
            "description: Use when exercising the exact staged skill mirror fixture.\n"
            "---\n\n"
            f"# {name}\n"
        ).encode("utf-8")
        mirror_paths = [f".agents/skills/{name}/SKILL.md"]
        if include_canonical:
            mirror_paths.append(f".claude/skills/{name}/SKILL.md")
        if include_gemini_bridge:
            mirror_paths.append(
                f"model-lanes/gemini/.agents/skills/{name}/SKILL.md"
            )
        for relative in mirror_paths:
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        staged = list(mirror_paths)
        if track_contract:
            enforcer = self.repo / SKILL_MIRROR_ENFORCER
            enforcer.parent.mkdir(parents=True, exist_ok=True)
            enforcer.write_text("# fixture mirror validator\n", encoding="utf-8")
            policy = self.repo / SKILL_MIRROR_POLICY
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text(
                "# Fixture policy: .claude/skills is the winner.\n",
                encoding="utf-8",
            )
            staged.extend((SKILL_MIRROR_ENFORCER, SKILL_MIRROR_POLICY))
        self.run_git("add", "--", *staged)
        return content

    def run_checker(
        self, env_overrides: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(env_overrides or {})
        return subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--repo",
                str(self.repo),
                "--registry",
                str(self.registry),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def run_runner(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                # bin/test blocks (exit 2) on any interpreter outside 3.13.x
                # before it ever runs the checker, so handing it the interpreter
                # running this suite would assert nothing about duplicates.
                "PYTHON_BIN": runner_python.require_runner_python(self, ROOT),
                "SQUAD_RUNNER_TEST_DUPLICATES": "1",
                "SQUAD_DUPLICATE_CHECK_ROOT_UNDER_TEST": str(self.repo),
                "SQUAD_DUPLICATE_ALLOWLIST_UNDER_TEST": str(self.registry),
            }
        )
        return subprocess.run(
            ["bash", str(RUNNER), "--duplicate-check-only"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def write_fake_tool(self, directory: Path, name: str, body: str) -> Path:
        path = directory / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_undeclared_duplicate_fails_the_actual_runner_then_declaration_passes(
        self,
    ) -> None:
        negative = self.run_runner()

        self.assertEqual(negative.returncode, 1, negative.stdout + negative.stderr)
        self.assertIn("==> one fact, one home", negative.stdout)
        self.assertIn("ONE-FACT-ONE-HOME FAIL", negative.stderr)
        self.assertIn("FAIL: one fact, one home", negative.stderr)

        self.write_declaration()
        positive = self.run_runner()

        self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
        self.assertIn("ONE-FACT-ONE-HOME PASS", positive.stdout)
        self.assertIn("PASS: one fact, one home", positive.stdout)

    def test_exact_staged_specialist_skill_mirror_is_validator_backed(self) -> None:
        self.replace_default_duplicate_with_distinct_files()
        self.write_skill_mirror()

        result = self.run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("validator-backed skill mirrors=1", result.stdout)

    def test_exact_staged_three_home_skill_mirror_is_validator_backed(self) -> None:
        self.replace_default_duplicate_with_distinct_files()
        self.write_skill_mirror(include_gemini_bridge=True)

        result = self.run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("validator-backed skill mirrors=1", result.stdout)

    def test_gemini_bridge_without_canonical_skill_is_not_validator_backed(
        self,
    ) -> None:
        self.replace_default_duplicate_with_distinct_files()
        self.write_skill_mirror(
            include_canonical=False,
            include_gemini_bridge=True,
        )

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("undeclared identical-blob group", result.stderr)
        self.assertIn("'.agents/skills/fixture-skill/SKILL.md'", result.stderr)
        self.assertIn(
            "'model-lanes/gemini/.agents/skills/fixture-skill/SKILL.md'",
            result.stderr,
        )

    def test_skill_mirror_does_not_hide_an_undeclared_copy_elsewhere(self) -> None:
        self.replace_default_duplicate_with_distinct_files()
        content = self.write_skill_mirror()
        third = self.repo / "copied-elsewhere" / "SKILL.md"
        third.parent.mkdir()
        third.write_bytes(content)
        self.run_git("add", "--", "copied-elsewhere/SKILL.md")

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("undeclared identical-blob group", result.stderr)
        self.assertIn("'copied-elsewhere/SKILL.md'", result.stderr)

    def test_skill_mirror_requires_its_tracked_validator_and_winner_policy(
        self,
    ) -> None:
        self.replace_default_duplicate_with_distinct_files()
        self.write_skill_mirror(track_contract=False)

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("undeclared identical-blob group", result.stderr)

    def test_unstaged_audience_edit_cannot_change_staged_classification(self) -> None:
        self.replace_default_duplicate_with_distinct_files()
        self.write_skill_mirror(audience="chrono")
        canonical = self.repo / ".claude/skills/fixture-skill/SKILL.md"
        canonical.write_text(
            canonical.read_text(encoding="utf-8").replace(
                "audience: chrono", "audience: specialist"
            ),
            encoding="utf-8",
        )

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("undeclared identical-blob group", result.stderr)

    def test_default_fast_runner_invokes_checker_and_propagates_failure(self) -> None:
        tools = self.repo / "fake-tools"
        tools.mkdir()
        marker = self.repo / "checker-invocations.txt"
        fake_python = self.write_fake_tool(
            tools,
            "selected-python",
            """case "$*" in
  *scripts/python/check_duplicate_blobs.py*)
    printf 'called\\n' >> "$CHECKER_MARKER"
    exec "$REAL_PYTHON" "$@"
    ;;
esac
case "${2:-}" in
  *version_info*) printf '3.13.0\\n' ;;
  *sys.prefix*) printf '%s\\n' "$FAKE_PREFIX" ;;
esac
exit 0
""",
        )
        (tools / "python3").symlink_to(fake_python)
        self.write_fake_tool(tools, "bash", "exit 0\n")
        self.write_fake_tool(tools, "node", "exit 0\n")
        env = os.environ.copy()
        env.update(
            {
                "CHECKER_MARKER": str(marker),
                "FAKE_PREFIX": str(self.repo / "fake-prefix"),
                "PATH": f"{tools}{os.pathsep}{env['PATH']}",
                "PYTHON_BIN": str(fake_python),
                "REAL_PYTHON": os.path.realpath(sys.executable),
                "SQUAD_CI_HOST_INDEPENDENT": "1",
                "SQUAD_RUNNER_TEST_DUPLICATES": "1",
                "SQUAD_DUPLICATE_CHECK_ROOT_UNDER_TEST": str(self.repo),
                "SQUAD_DUPLICATE_ALLOWLIST_UNDER_TEST": str(self.registry),
            }
        )

        result = subprocess.run(
            ["/bin/bash", str(RUNNER), "--fast"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "called\n")
        self.assertIn("ONE-FACT-ONE-HOME FAIL", result.stderr)
        self.assertIn("FAIL: one fact, one home", result.stderr)

    def test_blank_enforcer_is_not_an_allowlist_escape_hatch(self) -> None:
        self.write_declaration(enforcers=())

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("enforced_by must contain at least 1 path", result.stderr)

    def test_declared_group_fails_if_one_member_drifts(self) -> None:
        self.write_declaration()
        self.assertEqual(self.run_checker().returncode, 0)
        (self.repo / "second.txt").write_text("different bytes\n", encoding="utf-8")
        self.run_git("add", "--", "second.txt")

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("stale declaration 'fixture-pair'", result.stderr)

    def test_declared_group_fails_if_a_third_copy_joins_it(self) -> None:
        self.write_declaration()
        (self.repo / "third.txt").write_text("same bytes\n", encoding="utf-8")
        self.run_git("add", "--", "third.txt")

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("undeclared identical-blob group", result.stderr)
        self.assertIn("stale declaration 'fixture-pair'", result.stderr)

    def test_all_declared_members_may_change_together_and_remain_enforced(self) -> None:
        self.write_declaration()
        for name in ("first.txt", "second.txt"):
            (self.repo / name).write_text("new shared bytes\n", encoding="utf-8")
        self.run_git("add", "--", "first.txt", "second.txt")

        result = self.run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_extra_registry_row_fails(self) -> None:
        self.write_declaration()
        extra_members = tuple(sorted(("first.txt", "validator.py")))
        extra = (
            "stale-pair\t"
            f"{json.dumps(extra_members[0])}\t"
            f"{json.dumps(list(extra_members), separators=(',', ':'))}\t"
            f"{json.dumps([IDENTITY_ENFORCER], separators=(',', ':'))}\t"
            "known_defect\t"
            "Synthetic stale declaration for the negative test.\n"
        )
        with self.registry.open("a", encoding="utf-8") as handle:
            handle.write(extra)
        self.run_git("add", "--", self.registry.name)

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("stale declaration 'stale-pair'", result.stderr)

    def test_enforcer_must_itself_be_tracked(self) -> None:
        (self.repo / "untracked-validator.py").write_text(
            "# not in the index\n", encoding="utf-8"
        )
        self.write_declaration(
            enforcers=(IDENTITY_ENFORCER, "untracked-validator.py")
        )

        result = self.run_checker()

        self.assertEqual(result.returncode, 1)
        self.assertIn("names an untracked enforcer", result.stderr)

    def test_inherited_git_index_redirect_cannot_change_the_census(self) -> None:
        self.write_declaration()

        result = self.run_checker(
            {"GIT_INDEX_FILE": str(self.repo / "attacker-selected-index")}
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_registry_is_read_from_the_same_staged_snapshot_as_the_census(self) -> None:
        self.write_declaration()
        self.registry.write_text("unstaged and malformed\n", encoding="utf-8")

        result = self.run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_nul_delimited_census_handles_tabs_and_spaces_in_paths(self) -> None:
        (self.repo / "first.txt").write_text("no longer duplicate\n", encoding="utf-8")
        (self.repo / "second.txt").write_text("also distinct\n", encoding="utf-8")
        first = "path with space.txt"
        second = "path\twith-tab.txt"
        (self.repo / first).write_text("odd path duplicate\n", encoding="utf-8")
        (self.repo / second).write_text("odd path duplicate\n", encoding="utf-8")
        self.run_git("add", "--", "first.txt", "second.txt", first, second)
        self.write_declaration(members=tuple(sorted((first, second))))

        result = self.run_checker()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checked 1 identical-blob groups", result.stdout)


if __name__ == "__main__":
    unittest.main()
