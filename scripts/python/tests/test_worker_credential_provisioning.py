from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import MappingProxyType, SimpleNamespace
from typing import Any
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
SUPERVISOR = ROOT / "bin" / "board-supervisor.sh"
RESEARCH_ARSENAL = ROOT / "plugins" / "chrono-research-arsenal" / "mcp_server.py"
CAPABILITY_SOURCE = ROOT / "model-lanes" / "specialist-lane-capabilities.v1.json"
sys.path.insert(0, str(ROOT / "scripts" / "python"))

from lane_capability_enforcement import (  # noqa: E402
    RESEARCH_API_KEY_NAMES,
    CapabilityDenied,
    KimiLocalHostArtifacts,
    load_tool_classes,
    partition_absent_mcps,
    plan_lane,
)
import worktree_isolation as wti  # noqa: E402


def balanced_call(source: str, marker: str) -> str:
    """Return one complete call expression starting at ``marker``.

    The supervisor is a bash file with an embedded Python program, so it cannot
    be parsed whole. Slicing a call by paren balance lets a test EXECUTE the
    real expression instead of asserting on its text, which is the difference
    between pinning behavior and pinning a string.
    """

    start = source.index(marker)
    depth = 0
    for offset in range(source.index("(", start), len(source)):
        character = source[offset]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return source[start : offset + 1]
    raise AssertionError(f"unbalanced call for marker {marker!r}")


# Hermetic: no system/global config, no credential helper, no terminal prompt.
# One home for these four settings — a second copy is how one fixture quietly
# starts reading the operator's real ~/.gitconfig.
FIXTURE_GIT_ENV = MappingProxyType(
    {
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
    }
)


def run_git(
    case: unittest.TestCase,
    *args: str,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one git command against a throwaway fixture repository."""

    completed = subprocess.run(
        ["/usr/bin/git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=dict(FIXTURE_GIT_ENV),
    )
    if check and completed.returncode != 0:
        case.fail(
            f"git {args!r} failed with {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed


def make_fixture_repo(case: unittest.TestCase, root: Path) -> Path:
    """Initialise a committed one-file repository on branch ``v2``."""

    repo = root / "repo"
    repo.mkdir()
    run_git(case, "init", "-q", "-b", "v2", cwd=repo)
    run_git(case, "config", "user.email", "test@example.com", cwd=repo)
    run_git(case, "config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    run_git(case, "add", "README.md", cwd=repo)
    run_git(case, "commit", "-q", "-m", "fixture", cwd=repo)
    return repo


def add_linked_worktree(case: unittest.TestCase, repo: Path, root: Path) -> Path:
    """Register a linked worktree that predates any WorktreePool instance."""

    run_git(
        case,
        "worktree",
        "add",
        "-q",
        "-b",
        f"worktree/existing/{root.name}",
        str(root),
        "v2",
        cwd=repo,
    )
    return root


def credential_status(
    case: unittest.TestCase, worktree_root: Path
) -> subprocess.CompletedProcess[str]:
    return run_git(
        case,
        "status",
        "--porcelain",
        "--untracked-files=normal",
        "--",
        ".role-capabilities",
        cwd=worktree_root,
    )


def check_ignore(
    case: unittest.TestCase, worktree_root: Path
) -> subprocess.CompletedProcess[str]:
    return run_git(
        case,
        "check-ignore",
        "-v",
        "--",
        ".role-capabilities",
        cwd=worktree_root,
        check=False,
    )


def plant_credential_config(worktree_root: Path) -> Path:
    config = worktree_root / ".role-capabilities" / "kimi-mcp.json"
    config.parent.mkdir()
    config.write_text("synthetic config\n", encoding="utf-8")
    return config


def strip_exclusion_rule(repo: Path) -> None:
    """Remove the containment rule from the common exclude, leaving the rest."""

    exclude_path = repo / ".git" / "info" / "exclude"
    try:
        original = exclude_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    retained = [
        line for line in original.splitlines() if line != "/.role-capabilities/"
    ]
    exclude_path.write_text(
        ("\n".join(retained) + "\n") if retained else "", encoding="utf-8"
    )


class WorkerCredentialProvisioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.supervisor_source = SUPERVISOR.read_text(encoding="utf-8")
        cls.research_arsenal_source = RESEARCH_ARSENAL.read_text(encoding="utf-8")

    def test_research_loader_reads_all_three_managed_names(self) -> None:
        start = self.supervisor_source.index("def load_research_api_keys():")
        end = self.supervisor_source.index("\n\ndef load_github_mcp_token", start)
        namespace = {
            "os": os,
            "subprocess": subprocess,
            "RESEARCH_API_KEY_NAMES": RESEARCH_API_KEY_NAMES,
        }
        exec(
            compile(
                self.supervisor_source[start:end],
                "board-supervisor.sh",
                "exec",
            ),
            namespace,
        )
        completed = SimpleNamespace(
            returncode=0,
            stdout="synthetic-xai\tsynthetic-perplexity\tsynthetic-firecrawl",
        )
        with (
            mock.patch.dict(os.environ, {"HOME": "/synthetic/home"}, clear=False),
            mock.patch.object(subprocess, "run", return_value=completed) as run,
        ):
            loaded = namespace["load_research_api_keys"]()

        self.assertEqual(
            loaded,
            {
                "XAI_API_KEY": "synthetic-xai",
                "PERPLEXITY_API_KEY": "synthetic-perplexity",
                "FIRECRAWL_API_KEY": "synthetic-firecrawl",
            },
        )
        command = run.call_args.args[0]
        for name in loaded:
            self.assertIn(name, command[-1])

    def test_research_snapshot_reaches_only_an_authorized_worker(self) -> None:
        start = self.supervisor_source.index("MANAGED_CREDENTIAL_NAMES = (")
        end = self.supervisor_source.index("\n\ntrusted_environment =", start)

        def load_research_api_keys() -> dict[str, str]:
            return {
                "XAI_API_KEY": "synthetic-xai",
                "PERPLEXITY_API_KEY": "synthetic-perplexity",
                "FIRECRAWL_API_KEY": "synthetic-firecrawl",
            }

        namespace = {
            "MappingProxyType": MappingProxyType,
            "RESEARCH_API_KEY_NAMES": RESEARCH_API_KEY_NAMES,
            "load_solodit_api_key": lambda: None,
            "load_research_api_keys": load_research_api_keys,
            "load_github_mcp_token": lambda: None,
        }
        exec(
            compile(
                self.supervisor_source[start:end],
                "board-supervisor.sh",
                "exec",
            ),
            namespace,
        )
        load = namespace["load_managed_credentials"]
        project = namespace["project_worker_credentials"]
        base = {"PATH": "/usr/bin:/bin"}
        for worker_lane in ("claude", "codex", "gemini", "kimi"):
            with self.subTest(worker_lane=worker_lane):
                snapshot, missing = load(worker_lane, ["chrono-research-arsenal"])
                projected = project(base, snapshot)
                self.assertEqual(missing, ())
                for name in namespace["RESEARCH_API_KEY_NAMES"]:
                    self.assertIn(name, projected)

        grok_snapshot, grok_missing = load("grok", [])
        self.assertEqual(dict(grok_snapshot), {"XAI_API_KEY": "synthetic-xai"})
        self.assertEqual(grok_missing, ())
        self.assertEqual(
            project(base, grok_snapshot),
            {**base, "XAI_API_KEY": "synthetic-xai"},
        )

        # Negative control: an unenabled lane must still receive no snapshot,
        # even when it asks for an MCP whose keys the loader can supply. This
        # distinguishes lane projection from an unconditional credential load.
        unknown_snapshot, unknown_missing = load(
            "unsupported", ["chrono-research-arsenal"]
        )
        self.assertEqual(dict(unknown_snapshot), {})
        self.assertEqual(unknown_missing, ())
        self.assertEqual(project(base, unknown_snapshot), base)

        unauthorized = project(
            {
                **base,
                "XAI_API_KEY": "ambient-xai",
                "PERPLEXITY_API_KEY": "ambient-perplexity",
                "FIRECRAWL_API_KEY": "ambient-firecrawl",
            },
            MappingProxyType({}),
        )
        self.assertEqual(unauthorized, base)

    def test_each_lane_projects_only_credentials_for_authorized_mcps(self) -> None:
        start = self.supervisor_source.index("MANAGED_CREDENTIAL_NAMES = (")
        end = self.supervisor_source.index("\n\ntrusted_environment =", start)
        supplied = {
            "SOLODIT_API_KEY": "synthetic-solodit",
            **{
                name: f"synthetic-{name.lower()}"
                for name in RESEARCH_API_KEY_NAMES
            },
            "GITHUB_PERSONAL_ACCESS_TOKEN": "synthetic-github",
        }
        namespace = {
            "MappingProxyType": MappingProxyType,
            "RESEARCH_API_KEY_NAMES": RESEARCH_API_KEY_NAMES,
            "load_solodit_api_key": lambda: supplied["SOLODIT_API_KEY"],
            "load_research_api_keys": lambda: {
                name: supplied[name] for name in RESEARCH_API_KEY_NAMES
            },
            "load_github_mcp_token": lambda: supplied[
                "GITHUB_PERSONAL_ACCESS_TOKEN"
            ],
        }
        exec(
            compile(
                self.supervisor_source[start:end],
                "board-supervisor.sh",
                "exec",
            ),
            namespace,
        )
        load = namespace["load_managed_credentials"]
        project = namespace["project_worker_credentials"]
        managed_names = set(supplied)
        base = {
            "PATH": "/usr/bin:/bin",
            **{name: f"ambient-{name.lower()}" for name in managed_names},
        }
        cases = (
            ((), set()),
            (("guarded-solodit",), {"SOLODIT_API_KEY"}),
            (("chrono-research-arsenal",), set(RESEARCH_API_KEY_NAMES)),
            (("github",), {"GITHUB_PERSONAL_ACCESS_TOKEN"}),
            (
                ("guarded-solodit", "chrono-research-arsenal", "github"),
                managed_names,
            ),
        )

        for worker_lane in ("claude", "codex", "gemini", "kimi"):
            for authorized_mcps, expected_names in cases:
                with self.subTest(
                    worker_lane=worker_lane,
                    authorized_mcps=authorized_mcps,
                ):
                    snapshot, missing = load(worker_lane, authorized_mcps)
                    projected = project(base, snapshot)
                    self.assertEqual(missing, ())
                    self.assertEqual(set(snapshot), expected_names)
                    self.assertEqual(
                        managed_names.intersection(projected),
                        expected_names,
                    )
                    for name in expected_names:
                        self.assertEqual(projected[name], supplied[name])

        for authorized_mcps, _expected_names in cases:
            with self.subTest(worker_lane="grok", authorized_mcps=authorized_mcps):
                snapshot, missing = load("grok", authorized_mcps)
                projected = project(base, snapshot)
                self.assertEqual(missing, ())
                self.assertEqual(set(snapshot), {"XAI_API_KEY"})
                self.assertEqual(
                    managed_names.intersection(projected), {"XAI_API_KEY"}
                )

        # Load-bearing negative control: the ambient GitHub token begins in the
        # input environment, yet a research-only role finishes with the name
        # genuinely absent. The `github` case above is the positive control that
        # proves this same path can project the variable when authorized.
        for worker_lane in ("claude", "codex", "gemini", "kimi"):
            snapshot, _missing = load(
                worker_lane,
                ("chrono-research-arsenal",),
            )
            projected = project(base, snapshot)
            self.assertNotIn("GITHUB_PERSONAL_ACCESS_TOKEN", projected)

    def test_arxiv_search_requests_relevance_ordering(self) -> None:
        start = self.research_arsenal_source.index("@mcp.tool()\ndef arxiv_search(")
        end = self.research_arsenal_source.index(
            "\n\n@mcp.tool()\ndef xai_search(", start
        )
        captured: dict[str, Any] = {}

        class FakeMcp:
            @staticmethod
            def tool():
                return lambda function: function

        class FakeClient:
            def __init__(self, **_kwargs: Any) -> None:
                pass

            @staticmethod
            def results(_search: Any) -> tuple[Any, ...]:
                return ()

        def fake_search(**kwargs: Any) -> object:
            captured.update(kwargs)
            return object()

        relevance = object()
        submitted_date = object()
        descending = object()
        fake_arxiv = SimpleNamespace(
            Client=FakeClient,
            Search=fake_search,
            SortCriterion=SimpleNamespace(
                Relevance=relevance,
                SubmittedDate=submitted_date,
            ),
            SortOrder=SimpleNamespace(Descending=descending),
            HTTPError=RuntimeError,
        )
        namespace = {
            "Any": Any,
            "arxiv": fake_arxiv,
            "mcp": FakeMcp(),
            "_ok": lambda payload: {"ok": True, "result": payload},
            "_err": lambda reason, **extra: {
                "ok": False,
                "error": reason,
                **extra,
            },
            "_openalex_fallback": lambda *_args: {},
        }
        exec(
            compile(
                self.research_arsenal_source[start:end],
                "mcp_server.py",
                "exec",
            ),
            namespace,
        )

        response = namespace["arxiv_search"](
            "vector databases", max_results=3, categories=["cs.IR"]
        )

        self.assertTrue(response["ok"])
        self.assertEqual(captured["query"], "(cat:cs.IR) AND (vector databases)")
        self.assertIs(captured["sort_by"], relevance)
        self.assertIsNot(captured["sort_by"], submitted_date)
        self.assertIs(captured["sort_order"], descending)

    def test_xai_attribute_errors_are_actionable(self) -> None:
        start = self.research_arsenal_source.index("def _xai_exception_fields(")
        end = self.research_arsenal_source.index(
            "\n\ndef _message_text_and_citations(", start
        )
        namespace = {
            "Any": Any,
            "re": re,
        }
        exec(
            compile(
                self.research_arsenal_source[start:end],
                "mcp_server.py",
                "exec",
            ),
            namespace,
        )

        try:
            raise AttributeError(
                "'LegacyResponse' object has no attribute 'reason_phrase'"
            )
        except AttributeError as exc:
            fields = namespace["_xai_exception_fields"](exc)
        self.assertEqual(fields["exception_type"], "AttributeError")
        self.assertEqual(fields["attribute"], "reason_phrase")
        self.assertEqual(fields["object_type"], "LegacyResponse")
        self.assertRegex(
            fields["location"],
            r"^test_xai_attribute_errors_are_actionable:\d+$",
        )

    def test_xai_http_error_uses_reason_fallback(self) -> None:
        class FakeHttpStatusError(Exception):
            def __init__(self, response: object) -> None:
                super().__init__("synthetic provider error")
                self.response = response

        class LegacyResponse:
            status_code = 400

            def raise_for_status(self) -> None:
                raise FakeHttpStatusError(self)

        class FakeClient:
            def __init__(self, **_kwargs: Any) -> None:
                pass

            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, *_args: Any) -> None:
                return None

            @staticmethod
            def post(*_args: Any, **_kwargs: Any) -> LegacyResponse:
                return LegacyResponse()

        helper_start = self.research_arsenal_source.index("def _xai_http_status(")
        helper_end = self.research_arsenal_source.index(
            "\n\ndef _xai_exception_fields(", helper_start
        )
        namespace = {
            "Any": Any,
            "HTTPStatus": __import__("http").HTTPStatus,
        }
        exec(
            compile(
                self.research_arsenal_source[helper_start:helper_end],
                "mcp_server.py",
                "exec",
            ),
            namespace,
        )
        namespace.update(
            {
                "json": json,
                "os": os,
                "mcp": SimpleNamespace(tool=lambda: (lambda function: function)),
                "httpx": SimpleNamespace(
                    Client=FakeClient,
                    HTTPStatusError=FakeHttpStatusError,
                ),
                "_coerce_result": lambda *_args: None,
                "_message_text_and_citations": lambda *_args: ("", []),
                "_tool_source_urls": lambda *_args: [],
                "_err": lambda reason, **extra: {
                    "ok": False,
                    "error": reason,
                    **extra,
                },
                "_xai_exception_fields": lambda exc: {
                    "exception_type": type(exc).__name__
                },
            }
        )
        function_start = self.research_arsenal_source.index(
            "@mcp.tool()\ndef xai_search("
        )
        function_end = self.research_arsenal_source.index(
            "\n\n@mcp.tool()\ndef perplexity_search(", function_start
        )
        exec(
            compile(
                self.research_arsenal_source[function_start:function_end],
                "mcp_server.py",
                "exec",
            ),
            namespace,
        )

        with mock.patch.dict(
            os.environ,
            {"XAI_API_KEY": "synthetic-xai"},
            clear=False,
        ):
            fields = namespace["xai_search"](
                "example domain",
                max_results=1,
            )
        self.assertEqual(
            fields,
            {
                "ok": False,
                "error": "xai_http_error",
                "query": "example domain",
                "status_code": 400,
                "reason_phrase": "Bad Request",
            },
        )

    def test_codex_config_drops_only_managed_literal_placeholders(self) -> None:
        start = self.supervisor_source.index("def _toml_table_header(")
        end = self.supervisor_source.index("\n\ndef _inject_codex_vault_context", start)
        namespace = {"re": re}
        exec(
            compile(
                self.supervisor_source[start:end],
                "board-supervisor.sh",
                "exec",
            ),
            namespace,
        )
        config = """[mcp_servers.chrono-research-arsenal]
command = "/usr/bin/false"

[mcp_servers.chrono-research-arsenal.env]
XAI_API_KEY = "${XAI_API_KEY}"
PERPLEXITY_API_KEY = "${PERPLEXITY_API_KEY}"
FIRECRAWL_API_KEY = "${FIRECRAWL_API_KEY}"
BRAVE_API_KEY = "${BRAVE_API_KEY}"
"""
        rendered = namespace["_remove_codex_mcp_env_placeholders"](
            config,
            "chrono-research-arsenal",
            ("XAI_API_KEY", "PERPLEXITY_API_KEY", "FIRECRAWL_API_KEY"),
        )

        for name in ("XAI_API_KEY", "PERPLEXITY_API_KEY", "FIRECRAWL_API_KEY"):
            self.assertNotIn(f'{name} = "${{{name}}}"', rendered)
        self.assertIn('BRAVE_API_KEY = "${BRAVE_API_KEY}"', rendered)
        self.assertNotIn("synthetic-", rendered)

    def test_codex_gate_forwards_names_without_serializing_values(self) -> None:
        start = self.supervisor_source.index(
            'if execution_kind == "lane" and lane == "codex":'
        )
        end = self.supervisor_source.index(
            '\nif execution_kind == "lane":', start
        )
        gate = self.supervisor_source[start:end]
        self.assertIn("partition_absent_mcps(", gate)
        self.assertIn("set(existing_env_vars).union(RESEARCH_API_KEY_NAMES)", gate)
        self.assertIn('f"mcp_servers.{server_name}.env_vars="', gate)
        self.assertNotIn("credential_snapshot", gate)
        self.assertNotIn("synthetic-", gate)

    def test_bounty_researcher_preferred_github_absence_degrades(self) -> None:
        classes = load_tool_classes(
            repo_root=ROOT,
            lane="codex",
            specialist="bounty-researcher",
        )
        mcp_classes = {
            name.removeprefix("mcp:"): details
            for name, details in classes.items()
            if name.startswith("mcp:")
        }
        blocking, degraded = partition_absent_mcps(
            authorized=["chrono-vault", "github"],
            configured=["chrono-vault"],
            mcp_classes=mcp_classes,
        )
        self.assertEqual(blocking, ())
        self.assertEqual(degraded, ("github",))

    def test_required_or_unknown_mcp_absence_still_blocks(self) -> None:
        for classes in (
            {"github": {"requirement": "required"}},
            {"github": {"requirement": "unexpected"}},
            {},
        ):
            with self.subTest(classes=classes):
                blocking, degraded = partition_absent_mcps(
                    authorized=["github"],
                    configured=[],
                    mcp_classes=classes,
                )
                self.assertEqual(blocking, ("github",))
                self.assertEqual(degraded, ())

    # ── KEY-03: the two confirmed causes of the Kimi research-key failure ────
    #
    # Cause 1 was an id-shape mismatch: the credential gate read only direct
    # `mcps` while the Kimi plan authorized `brokered_mcps`. Cause 2 was that
    # widening the parent environment never reaches Kimi's stdio child, which
    # inherits a fixed name list plus the server record's own `env`. Fixing
    # either alone leaves the tools dead, so both are pinned here.

    def _kimi_host_artifacts(self) -> KimiLocalHostArtifacts:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        paths = []
        for name in ("python", "sequential-thinking"):
            executable = directory / name
            executable.write_text("fixture executable\n", encoding="utf-8")
            executable.chmod(0o700)
            paths.append(executable)
        return KimiLocalHostArtifacts(
            interpreter=paths[0],
            sequential_thinking=paths[1],
        )

    @staticmethod
    def _synthetic_research_environment() -> dict[str, str]:
        return {name: f"synthetic-{name.lower()}" for name in RESEARCH_API_KEY_NAMES}

    def _kimi_plan(self, research_environment: dict[str, str] | None):
        return plan_lane(
            lane="kimi",
            projection={
                "mcps": [],
                "brokered_mcps": ["chrono-research-arsenal", "sequential-thinking"],
                "tools": [],
            },
            configured_servers={},
            repo_root=ROOT,
            kimi_research_environment=research_environment,
            kimi_host_artifacts=self._kimi_host_artifacts(),
        )

    def test_research_key_names_have_exactly_one_home(self) -> None:
        # Hard rule 10: the loader, the missing-credential report, the Codex
        # `env_vars` forward, and the Kimi `env` binding must read the SAME
        # tuple. A restated copy here is how a fourth name silently stops
        # being provisioned on one lane only.
        self.assertIn(
            "        RESEARCH_API_KEY_NAMES,\n", self.supervisor_source
        )
        self.assertNotIn("RESEARCH_API_KEY_NAMES = (", self.supervisor_source)

    def test_worktree_pool_excludes_credential_configs_for_existing_and_new_attempts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture_repo(self, root)

            pool_root = root / "pool"
            pool_root.mkdir()
            existing_root = add_linked_worktree(
                self, repo, pool_root / ("d-" + "a" * 32)
            )
            plant_credential_config(existing_root)

            # Positive control for the defect: before WorktreePool applies its
            # local exclusion, an already-live linked worktree exposes the
            # credential-bearing directory as ordinary untracked content.
            before = credential_status(self, existing_root)
            self.assertEqual(before.stdout, "?? .role-capabilities/\n")

            pool = wti.WorktreePool(repo, pool_root, base_branch="v2")
            fresh = pool.provision(
                "TASK-2026-08-30-1030-sec02-test",
                "d-" + "b" * 32,
            )
            plant_credential_config(fresh.worktree_root)
            legitimate_output = fresh.worktree_root / "worker-result.txt"
            legitimate_output.write_text("legitimate output\n", encoding="utf-8")

            for worktree_root in (existing_root, fresh.worktree_root):
                with self.subTest(worktree_root=worktree_root.name):
                    status = credential_status(self, worktree_root)
                    self.assertEqual(status.stdout, "")
                    ignored = check_ignore(self, worktree_root)
                    self.assertIn("info/exclude", ignored.stdout)
                    self.assertIn("/.role-capabilities/", ignored.stdout)

            visible_output = run_git(
                self,
                "status",
                "--porcelain",
                "--untracked-files=normal",
                "--",
                legitimate_output.name,
                cwd=fresh.worktree_root,
            )
            self.assertEqual(visible_output.stdout, "?? worker-result.txt\n")

            # Mutation-sensitive negative control: remove exactly the
            # containment rule and prove the same path becomes visible again.
            exclude_path = repo / ".git" / "info" / "exclude"
            original_line_count = len(
                exclude_path.read_text(encoding="utf-8").splitlines()
            )
            strip_exclusion_rule(repo)
            self.assertLess(
                len(exclude_path.read_text(encoding="utf-8").splitlines()),
                original_line_count,
            )

            no_rule = check_ignore(self, fresh.worktree_root)
            self.assertEqual(no_rule.returncode, 1)
            for worktree_root in (existing_root, fresh.worktree_root):
                exposed = credential_status(self, worktree_root)
                self.assertEqual(exposed.stdout, "?? .role-capabilities/\n")

    # The test above is satisfied by EITHER install site alone: info/exclude is
    # common to the whole repository, so installing the rule during provision()
    # of a new attempt retroactively covers the pre-existing fixture worktree
    # too. The two tests below separate the sites, one each.

    def test_pool_construction_alone_retrofits_an_already_live_worktree(
        self,
    ) -> None:
        """Pins the __init__ retrofit; no provision() call can satisfy it.

        Constructing the pool over a pre-existing worktree and provisioning
        nothing is the only state the reassert cannot have produced.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture_repo(self, root)
            pool_root = root / "pool"
            pool_root.mkdir()
            existing_root = add_linked_worktree(
                self, repo, pool_root / ("d-" + "c" * 32)
            )
            plant_credential_config(existing_root)

            # Positive control: the rule is genuinely absent beforehand, so a
            # later pass cannot be inherited from the fixture's own state.
            self.assertEqual(check_ignore(self, existing_root).returncode, 1)
            self.assertEqual(
                credential_status(self, existing_root).stdout,
                "?? .role-capabilities/\n",
            )

            pool = wti.WorktreePool(repo, pool_root, base_branch="v2")
            # Nothing was provisioned, so only __init__ can have installed it.
            self.assertEqual(pool.active(), ())

            ignored = check_ignore(self, existing_root)
            self.assertEqual(ignored.returncode, 0)
            self.assertIn("info/exclude", ignored.stdout)
            self.assertIn("/.role-capabilities/", ignored.stdout)
            self.assertEqual(credential_status(self, existing_root).stdout, "")

    def test_provision_reasserts_the_rule_after_a_post_construction_edit(
        self,
    ) -> None:
        """Pins the provision() reassert; the __init__ retrofit cannot satisfy it.

        The rule __init__ installed is deleted after construction, exactly the
        operator edit the reassert exists for, so only the reassert can put it
        back before the new worktree is created.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture_repo(self, root)
            pool_root = root / "pool"
            pool_root.mkdir()
            existing_root = add_linked_worktree(
                self, repo, pool_root / ("d-" + "d" * 32)
            )
            plant_credential_config(existing_root)

            pool = wti.WorktreePool(repo, pool_root, base_branch="v2")

            # An operator rewrites the repository-local excludes after the pool
            # was constructed, keeping their own patterns and dropping ours.
            exclude_path = repo / ".git" / "info" / "exclude"
            exclude_path.write_text(
                "# operator pattern\n/scratch/\n/.role-capabilities/\n",
                encoding="utf-8",
            )
            strip_exclusion_rule(repo)

            # Positive control: the rule really is gone at this point.
            self.assertEqual(check_ignore(self, existing_root).returncode, 1)
            self.assertEqual(
                credential_status(self, existing_root).stdout,
                "?? .role-capabilities/\n",
            )

            fresh = pool.provision(
                "TASK-2026-08-30-1030-sec02-reassert",
                "d-" + "e" * 32,
            )
            plant_credential_config(fresh.worktree_root)

            for worktree_root in (existing_root, fresh.worktree_root):
                with self.subTest(worktree_root=worktree_root.name):
                    ignored = check_ignore(self, worktree_root)
                    self.assertEqual(ignored.returncode, 0)
                    self.assertIn("info/exclude", ignored.stdout)
                    self.assertIn("/.role-capabilities/", ignored.stdout)
                    self.assertEqual(
                        credential_status(self, worktree_root).stdout, ""
                    )

            # The reassert appends; it must not discard operator patterns.
            self.assertIn("/scratch/", exclude_path.read_text(encoding="utf-8"))

    def test_exclusion_lock_failure_raises_the_module_error_and_frees_the_fd(
        self,
    ) -> None:
        """A raw OSError from flock would escape the only handler there is.

        `bin/board-supervisor.sh` catches WorktreeIsolationError at the
        WorktreePool construction site and nothing else, so every OS call in
        this helper has to convert.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture_repo(self, root)

            operations: list[int] = []
            lock_descriptors: list[int] = []
            closed: list[int] = []
            real_open, real_close = os.open, os.close

            def failing_flock(descriptor: int, operation: int) -> None:
                operations.append(operation)
                raise OSError(errno.EDEADLK, "resource deadlock avoided")

            def spy_open(path: Any, flags: int, mode: int = 0o777) -> int:
                descriptor = real_open(path, flags, mode)
                if str(path).endswith("board-integration.lock"):
                    lock_descriptors.append(descriptor)
                return descriptor

            def spy_close(descriptor: int) -> None:
                closed.append(descriptor)
                real_close(descriptor)

            with mock.patch.object(wti.fcntl, "flock", failing_flock):
                with mock.patch.object(wti.os, "open", spy_open):
                    with mock.patch.object(wti.os, "close", spy_close):
                        with self.assertRaises(wti.WorktreeIsolationError) as caught:
                            wti._ensure_worker_credential_exclusion(repo)

            self.assertIn("board-integration.lock", str(caught.exception))
            self.assertIsInstance(caught.exception.__cause__, OSError)
            # Released, and no LOCK_UN issued for a lock never acquired.
            self.assertEqual(len(lock_descriptors), 1)
            self.assertIn(lock_descriptors[0], closed)
            self.assertEqual(operations, [wti.fcntl.LOCK_EX])

            # Positive control: the flock is what failed, not the fixture — the
            # same call installs the rule once flock works again.
            wti._ensure_worker_credential_exclusion(repo)
            self.assertIn(
                "/.role-capabilities/",
                (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8"),
            )
    def test_credential_gate_authorizes_brokered_servers_too(self) -> None:
        # Cause 1, executed rather than asserted as text: a Kimi role declares
        # `lead:chrono-research-arsenal`, which `load_projection` strips into
        # `brokered_mcps`, leaving `mcps` empty.
        snippet = balanced_call(
            self.supervisor_source,
            "credential_snapshot, credential_missing = load_managed_credentials(",
        )
        captured: dict[str, Any] = {}

        def fake_load(worker_lane: str, authorized: Any) -> tuple[Any, tuple[()]]:
            captured["lane"] = worker_lane
            captured["authorized"] = tuple(authorized)
            return MappingProxyType({}), ()

        namespace = {
            "lane": "kimi",
            "capability_projection": {
                "mcps": [],
                "brokered_mcps": ["chrono-research-arsenal", "chrono-vault"],
            },
            "load_managed_credentials": fake_load,
        }
        exec(compile(snippet, "board-supervisor.sh", "exec"), namespace)

        self.assertEqual(captured["lane"], "kimi")
        self.assertIn("chrono-research-arsenal", captured["authorized"])

        # Negative control: the same expression on a direct-declaration role
        # must not invent an authorization the projection never made.
        namespace["capability_projection"] = {"mcps": ["guarded-solodit"], "brokered_mcps": []}
        exec(compile(snippet, "board-supervisor.sh", "exec"), namespace)
        self.assertEqual(captured["authorized"], ("guarded-solodit",))

    def test_kimi_binds_research_keys_into_the_stdio_child_record(self) -> None:
        # Cause 2: the values must land on the server record, because the Kimi
        # MCP client does not pass the parent environment through.
        expected = self._synthetic_research_environment()
        servers = json.loads(self._kimi_plan(expected).role_config_json)["mcpServers"]

        self.assertEqual(servers["chrono-research-arsenal"]["env"], expected)
        # Least privilege: no other selected server receives them.
        self.assertNotIn("env", servers["sequential-thinking"])

    def test_kimi_omits_research_env_when_the_store_supplied_nothing(self) -> None:
        # Best-effort, exactly like `load_research_api_keys`: an absent key is
        # reported under `credential_missing` and the tool returns its own
        # "<KEY> missing" error. Writing an empty `env` instead would look
        # identical in the config and hide which state we are in.
        for absent in (None, {}):
            with self.subTest(absent=absent):
                servers = json.loads(
                    self._kimi_plan(absent).role_config_json
                )["mcpServers"]
                self.assertNotIn("env", servers["chrono-research-arsenal"])

        # Positive control for the assertion above: the same call path DOES
        # produce an `env` when the store supplies keys, so "absent" here is a
        # real degrade and not a silently broken binding.
        partial = {"XAI_API_KEY": "synthetic-xai"}
        servers = json.loads(self._kimi_plan(partial).role_config_json)["mcpServers"]
        self.assertEqual(servers["chrono-research-arsenal"]["env"], partial)

    def test_kimi_rejects_an_unmanaged_or_unsafe_research_environment(self) -> None:
        for hostile in (
            {"AWS_SECRET_ACCESS_KEY": "synthetic"},
            {**self._synthetic_research_environment(), "PATH": "/tmp"},
        ):
            with self.subTest(hostile=hostile):
                with self.assertRaises(CapabilityDenied):
                    self._kimi_plan(hostile)

        for invalid in (
            {"XAI_API_KEY": ""},
            {"XAI_API_KEY": "synthetic\ninjected=1"},
            {"XAI_API_KEY": "synthetic\x00"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(CapabilityDenied):
                    self._kimi_plan(invalid)

    def test_kimi_refuses_credentials_for_an_unauthorized_arsenal(self) -> None:
        with self.assertRaises(CapabilityDenied):
            plan_lane(
                lane="kimi",
                projection={
                    "mcps": [],
                    "brokered_mcps": ["sequential-thinking"],
                    "tools": [],
                },
                configured_servers={},
                repo_root=ROOT,
                kimi_research_environment=self._synthetic_research_environment(),
                kimi_host_artifacts=self._kimi_host_artifacts(),
            )

    def test_capability_source_contains_only_typed_mcp_requirements(self) -> None:
        payload = json.loads(CAPABILITY_SOURCE.read_text(encoding="utf-8"))
        requirements = {
            capability.get("requirement")
            for entry in payload["entries"]
            for capability in entry.get("mcps", [])
        }
        self.assertEqual(requirements, {"preferred", "required"})


if __name__ == "__main__":
    unittest.main()
