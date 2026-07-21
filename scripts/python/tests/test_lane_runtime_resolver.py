import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "lane_runtime_resolver.py"
SPEC = importlib.util.spec_from_file_location("lane_runtime_resolver", MODULE_PATH)
resolver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(resolver)


HEADER = (
    "specialist\tsource_namespace\tcapability_class\tsafety_level\tsafety_tags\ttool_profile\t"
    "primary_lane\tprimary_profile\tbackup_lane\tbackup_profile\tescalate_lane\tescalate_profile\t"
    "escalation_policy\treview_lane\treview_profile\tanti_affinity\tthroughput_lane\t"
    "throughput_profile\tthroughput_policy\tfailover_policy\toperator_gate\theightened_risk\t"
    "requires_approval\trequired_tools\tpreferred_tools\tnotes\ttags\tversion\t"
    "operator_model_consult"
)


def row(
    specialist,
    namespace,
    primary_lane,
    primary_profile,
    backup_lane="none",
    backup_profile="none",
    throughput_lane="none",
    throughput_profile="none",
    operator_model_consult="false",
):
    fields = [
        specialist,
        namespace,
        "implementation",
        "low",
        "[]",
        "none",
        primary_lane,
        primary_profile,
        backup_lane,
        backup_profile,
        primary_lane,
        primary_profile,
        "escalation.signal.v1",
        backup_lane,
        backup_profile,
        "none",
        throughput_lane,
        throughput_profile,
        "throughput.downshift_gated.v1" if throughput_lane != "none" else "throughput.never.v1",
        "failover.conservative.v1",
        "[]",
        "false",
        "[]",
        "[]",
        "[]",
        "fixture",
        "[]",
        "2.0",
        operator_model_consult,
    ]
    return "\t".join(fields)


class ResolverFixture:
    def __init__(self, root):
        self.root = Path(root).resolve()
        (self.root / "shared").mkdir(parents=True)
        (self.root / "shared" / "specialist-runtime-map.tsv").write_text(
            "\n".join(
                [
                    HEADER,
                    row("systems-engineer", "coding", "codex", "codex.sol.high", "claude", "claude.fable.xhigh"),
                    row("skeptic", "shared", "claude", "claude.fable.xhigh", "codex", "codex.sol.high"),
                    row("social-strategist", "content", "gemini", "gemini.flash.default", "claude", "claude.fable.xhigh"),
                    row("summarizer", "shared", "claude", "claude.fable.xhigh", "codex", "codex.sol.high", "kimi", "kimi.k2.7.bulk"),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        profiles = self.root / "shared" / "registries" / "profiles.tsv"
        profiles.parent.mkdir(parents=True)
        profiles.write_text(
            "profile_id\tlane\tmodel_id\teffort\tflags\tusage\n"
            "codex.sol.high\tcodex\tgpt-5.6-sol\thigh\tnone\tprimary\n"
            "claude.fable.xhigh\tclaude\tclaude-fable-5\txhigh\tnone\tprimary\n"
            "gemini.flash.default\tgemini\tgemini-3.5-flash\tdefault\tnone\tprimary\n"
            "kimi.k2.7.bulk\tkimi\tkimi-code/kimi-for-coding-highspeed\tdefault\thighspeed\tthroughput-only\n",
            encoding="utf-8",
        )
        self._canonical("coding", "systems-engineer")
        self._canonical("shared", "skeptic")
        self._canonical("content", "social-strategist")
        self._canonical("shared", "summarizer")
        self._adapter("codex", "systems-engineer", "systems_engineer")
        self._adapter("claude", "skeptic", "skeptic")
        self._adapter("gemini", "social-strategist", "social-strategist")
        self._adapter("kimi", "summarizer", "summarizer")

    def _canonical(self, namespace, specialist):
        if namespace == "shared":
            path = self.root / "shared" / "specialists" / f"{specialist}.md"
        else:
            path = self.root / "departments" / namespace / "specialists" / f"{specialist}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nspecialist: {specialist}\n---\n\n# {specialist}\n", encoding="utf-8")

    def _adapter(self, lane, specialist, native_name):
        if lane == "codex":
            path = self.root / "model-lanes" / "gpt-codex" / ".codex" / "agents" / f"{specialist}.toml"
            body = f'name = "{native_name}"\ndescription = "fixture"\n'
        elif lane == "claude":
            path = self.root / "model-lanes" / "claude" / ".claude" / "agents" / f"{specialist}.md"
            body = f"---\nname: {native_name}\ndescription: fixture\n---\n"
        elif lane == "gemini":
            path = self.root / "model-lanes" / "gemini" / ".gemini" / "agents" / f"{specialist}.md"
            body = f"---\nname: {native_name}\ndescription: fixture\n---\n"
        else:
            path = self.root / "model-lanes" / "kimi" / ".kimi" / "agents" / f"{specialist}.yaml"
            body = f"version: 1\nagent:\n  name: {native_name}\n  model: kimi-code/kimi-for-coding\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


class LaneRuntimeResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fixture = ResolverFixture(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def resolve(self, specialist, lane=None, env=None):
        return resolver.resolve_runtime(
            repo_root=self.fixture.root,
            specialist=specialist,
            requested_lane=lane,
            environ={} if env is None else env,
        )

    def test_pins_exact_model_and_profile_for_each_lane(self):
        cases = [
            ("systems-engineer", "codex", "codex.sol.high", "gpt-5.6-sol", "high"),
            ("skeptic", "claude", "claude.fable.xhigh", "claude-fable-5", "xhigh"),
            ("social-strategist", "gemini", "gemini.flash.default", "gemini-3.5-flash", "default"),
            ("summarizer", "kimi", "kimi.k2.7.bulk", "kimi-code/kimi-for-coding-highspeed", "thinking"),
        ]
        for specialist, lane, profile, model, reasoning in cases:
            with self.subTest(lane=lane):
                plan = self.resolve(specialist, lane=lane, env={"GEMINI_API_KEY": "present"})
                self.assertEqual(plan["lane"], lane)
                self.assertEqual(plan["profile"], profile)
                self.assertEqual(plan["model"], model)
                self.assertEqual(plan["reasoning"], reasoning)

    def test_primary_route_is_map_driven_not_namespace_driven(self):
        plan = self.resolve("systems-engineer")
        self.assertEqual(plan["lane"], "codex")
        self.assertEqual(plan["route_field"], "primary")
        self.assertFalse(plan["operator_model_consult"])

    def test_operator_model_consult_is_carried_into_plan_and_receipt(self):
        map_path = self.fixture.root / "shared" / "specialist-runtime-map.tsv"
        lines = map_path.read_text(encoding="utf-8").splitlines()
        fields = lines[1].split("\t")
        fields[-1] = "true"
        lines[1] = "\t".join(fields)
        map_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        plan = self.resolve("systems-engineer")
        self.assertTrue(plan["operator_model_consult"])
        receipt = resolver.sanitized_receipt(plan, {})
        self.assertTrue(receipt["operator_model_consult"])

    def test_legacy_runtime_schema_defaults_operator_model_consult_false(self):
        map_path = self.fixture.root / "shared" / "specialist-runtime-map.tsv"
        lines = map_path.read_text(encoding="utf-8").splitlines()
        lines[0] = "\t".join(resolver.LEGACY_RUNTIME_HEADER)
        lines[1:] = ["\t".join(line.split("\t")[:-1]) for line in lines[1:]]
        map_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        plan = self.resolve("systems-engineer")
        self.assertFalse(plan["operator_model_consult"])

    def test_explicit_lane_must_be_eligible_in_row(self):
        with self.assertRaisesRegex(resolver.ResolverError, "not an eligible route"):
            self.resolve("systems-engineer", lane="gemini", env={"GEMINI_API_KEY": "present"})

    def test_department_and_shared_canonical_paths(self):
        coding = self.resolve("systems-engineer")
        shared = self.resolve("skeptic")
        self.assertEqual(Path(coding["canonical_prompt"]).relative_to(self.fixture.root).as_posix(), "departments/coding/specialists/systems-engineer.md")
        self.assertEqual(Path(shared["canonical_prompt"]).relative_to(self.fixture.root).as_posix(), "shared/specialists/skeptic.md")

    def test_missing_or_mismatched_adapter_fails_closed(self):
        adapter = self.fixture.root / "model-lanes" / "gpt-codex" / ".codex" / "agents" / "systems-engineer.toml"
        adapter.rename(adapter.with_suffix(".away"))
        with self.assertRaisesRegex(resolver.ResolverError, "adapter does not exist"):
            self.resolve("systems-engineer")
        adapter.with_suffix(".away").rename(adapter)
        adapter.write_text('name = "wrong_name"\n', encoding="utf-8")
        with self.assertRaisesRegex(resolver.ResolverError, "adapter identity mismatch"):
            self.resolve("systems-engineer")

    def test_child_auth_matrix_is_lane_specific_and_parent_is_unchanged(self):
        parent = {
            "ANTHROPIC_API_KEY": "anthropic-secret",
            "OPENAI_API_KEY": "openai-secret",
            "GEMINI_API_KEY": "gemini-secret",
            "GOOGLE_API_KEY": "google-secret",
            "PATH": "/fixture/bin",
        }
        original = dict(parent)
        for specialist, lane in [
            ("systems-engineer", "codex"),
            ("skeptic", "claude"),
            ("social-strategist", "gemini"),
            ("summarizer", "kimi"),
        ]:
            with self.subTest(lane=lane):
                plan = self.resolve(specialist, lane=lane, env=parent)
                child = resolver.build_child_environment(plan, parent)
                self.assertNotIn("ANTHROPIC_API_KEY", child)
                self.assertNotIn("OPENAI_API_KEY", child)
                self.assertNotIn("GOOGLE_API_KEY", child)
                if lane == "gemini":
                    self.assertEqual(child.get("GEMINI_API_KEY"), "gemini-secret")
                else:
                    self.assertNotIn("GEMINI_API_KEY", child)
        self.assertEqual(parent, original)

    def test_gemini_requires_gemini_key(self):
        with self.assertRaisesRegex(resolver.ResolverError, "GEMINI_API_KEY"):
            self.resolve("social-strategist", lane="gemini", env={})

    def test_receipt_and_argv_never_contain_secret_values(self):
        secret = "unique-secret-marker"
        plan = self.resolve("social-strategist", lane="gemini", env={"GEMINI_API_KEY": secret})
        receipt = resolver.sanitized_receipt(plan, {"GEMINI_API_KEY": secret})
        rendered = json.dumps(receipt, sort_keys=True)
        self.assertNotIn(secret, rendered)
        self.assertTrue(receipt["auth"]["required_env_present"])
        self.assertEqual(receipt["auth"]["preserved_env"], ["GEMINI_API_KEY"])

    def test_native_and_composed_adapter_modes_are_explicit(self):
        codex = self.resolve("systems-engineer")
        claude = self.resolve("skeptic")
        gemini = self.resolve("social-strategist", env={"GEMINI_API_KEY": "present"})
        kimi = self.resolve("summarizer", lane="kimi")
        self.assertEqual(codex["adapter_mode"], "composed-validated")
        self.assertEqual(gemini["adapter_mode"], "composed-validated")
        self.assertEqual(claude["adapter_mode"], "native")
        self.assertIn("--agent", claude["argv"])
        self.assertEqual(kimi["adapter_mode"], "native")
        self.assertIn("--agent-file", kimi["argv"])

    def test_duplicate_specialist_rows_fail_closed(self):
        map_path = self.fixture.root / "shared" / "specialist-runtime-map.tsv"
        with map_path.open("a", encoding="utf-8") as handle:
            handle.write(row("systems-engineer", "coding", "codex", "codex.sol.high") + "\n")
        with self.assertRaisesRegex(resolver.ResolverError, "exactly one runtime-map row"):
            self.resolve("systems-engineer")

    def test_execute_n1_stubs_prove_each_child_auth_mask_and_exit_propagation(self):
        stub_dir = self.fixture.root / "stub-bin"
        stub_dir.mkdir()
        for cli in ("codex", "claude", "gemini", "kimi"):
            stub = stub_dir / cli
            stub.write_text(
                "#!/bin/sh\n"
                "test -n \"${ANTHROPIC_API_KEY:-}\" && a=1 || a=0\n"
                "test -n \"${OPENAI_API_KEY:-}\" && o=1 || o=0\n"
                "test -n \"${GEMINI_API_KEY:-}\" && g=1 || g=0\n"
                "test -n \"${GOOGLE_API_KEY:-}\" && x=1 || x=0\n"
                f"printf 'child={cli} mask=%s%s%s%s\\n' \"$a\" \"$o\" \"$g\" \"$x\"\n"
                "exit \"${STUB_EXIT:-0}\"\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
        parent = {
            **os.environ,
            "PATH": str(stub_dir) + os.pathsep + os.environ.get("PATH", ""),
            "ANTHROPIC_API_KEY": "anthropic-execute-secret",
            "OPENAI_API_KEY": "openai-execute-secret",
            "GEMINI_API_KEY": "gemini-execute-secret",
            "GOOGLE_API_KEY": "google-execute-secret",
        }
        cases = [
            ("systems-engineer", "codex", "0000"),
            ("skeptic", "claude", "0000"),
            ("social-strategist", "gemini", "0010"),
            ("summarizer", "kimi", "0000"),
        ]
        for specialist, lane, expected_mask in cases:
            with self.subTest(lane=lane):
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(MODULE_PATH),
                        "--repo-root",
                        str(self.fixture.root),
                        "--specialist",
                        specialist,
                        "--lane",
                        lane,
                        "--execute",
                    ],
                    env=parent,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                rendered = completed.stdout + completed.stderr
                self.assertEqual(completed.returncode, 0, rendered)
                self.assertIn(f"child={lane} mask={expected_mask}", rendered)
                self.assertNotIn("execute-secret", rendered)
        failed_env = dict(parent)
        failed_env["STUB_EXIT"] = "7"
        failed = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "--repo-root",
                str(self.fixture.root),
                "--specialist",
                "systems-engineer",
                "--lane",
                "codex",
                "--execute",
            ],
            env=failed_env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(failed.returncode, 7)


if __name__ == "__main__":
    unittest.main()
