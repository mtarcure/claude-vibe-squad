from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EXPORT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPORT_DIR.parents[1]
sys.path.insert(0, str(EXPORT_DIR))

from path_policy import PolicyError, audit_paths, load_policy  # noqa: E402


POLICY_PATH = EXPORT_DIR / "policy" / "path-policy.json"


class PathPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy(POLICY_PATH)

    def test_private_classes_are_denied(self) -> None:
        private_paths = [
            "_state/unexpected/nested/runtime.bin",
            "_state/feed-config.yaml",
            "_state/capability-inventory-host.md",
            "departments/coding/inbox/payload.json",
            "departments/coding/active/trace.bin",
            "departments/coding/outbox/result.txt",
            "departments/coding/archive/result.dat",
            "departments/coding/_state/runtime.json",
            "departments/coding/current.md",
            "chrono/memory.md",
            "_archive/session/result.txt",
            "projects/live-target/notes.md",
            "docs/handoffs/private.md",
            "docs/plans/nested/2026-private.txt",
            "docs/specs/nested/private.txt",
            "docs/superpowers/plans/example.md",
            "docs/superpowers/specs/spec-example.md",
            "docs/superpowers/specs/2026-08-07-vibesquad-v4-design.md",
            "docs/superpowers/specs/2026-08-07-vibesquad-v4-rounds1-8-source.md",
            "docs/v4-round9-audit.md",
            "docs/DEFERRED-RAIL-FIXES.md",
            "docs/brain-map.md",
            "docs/state-model.md",
            "docs/lineage.md",
            ".env",
            "nested/.env.local",
            "fixtures/client-secret.json",
            "keys/release.key",
            "keys/release.pem",
            "model-lanes/gemini/.gemini/settings.json",
            "model-lanes/gpt/.claude/settings.local.json",
            "model-lanes/claude/.mcp.json",
            "model-lanes/claude/.mcp.security-arsenal.staged.json",
            "model-lanes/gpt-codex/.codex/config.toml",
            "model-lanes/gpt-codex/.codex/security-arsenal.staged.toml",
            "plugins/security-mcp-stack/held-solodit.json",
            "plugins/security-mcp-stack/preactivate-security-stack.sh",
            "plugins/security-mcp-stack/snyk-preactivation-targets.json",
            "chrono/operator-setup.local.md",
            "logs/runtime.txt",
            "nested/runtime.log",
            "state/kg.db-wal",
            "plugins/chrono-dedup/mcp_server.py",
            "tools/standing-checks/proof-verifier-bounds/check.py",
            "tools/standing-checks/proof-verifier-bounds/fixtures/rust_anchor/strict_index_bounds_fixed.rs",
            "tools/radar/bin/scan-local.sh",
            ".claude/skills/systematic-attacking/SKILL.md",
            ".claude/skills/systematic-bug-hunting/SKILL.md",
            ".claude/skills/probe-canary/SKILL.md",
            "tools/export/target_scan.py",
        ]
        self.assertEqual(
            [self.policy.classify(path) for path in private_paths],
            ["private"] * len(private_paths),
        )

    def test_exact_public_exceptions_override_broad_denies(self) -> None:
        public_exceptions = [
            "_state/.gitkeep",
            "departments/coding/inbox/.gitkeep",
            "departments/security/active/.gitkeep",
            "departments/content/outbox/.gitkeep",
            "departments/research/archive/.gitkeep",
        ]
        self.assertEqual(
            [self.policy.classify(path) for path in public_exceptions],
            ["public"] * len(public_exceptions),
        )

    def test_public_agent_definitions_remain_public(self) -> None:
        self.assertEqual(
            self.policy.classify("model-lanes/gemini/.gemini/agents/reviewer.md"),
            "public",
        )
        self.assertEqual(
            self.policy.classify("model-lanes/claude/.mcp.example.json"),
            "public",
        )
        self.assertEqual(
            self.policy.classify("model-lanes/gpt-codex/.codex/agents/systems_engineer.toml"),
            "public",
        )
        self.assertEqual(
            self.policy.classify("plugins/security-mcp-stack/README.md"),
            "public",
        )

    def test_public_onboarding_docs_remain_public(self) -> None:
        self.assertEqual(self.policy.classify("docs/README.md"), "public")
        self.assertEqual(self.policy.classify("docs/getting-started.md"), "public")

    def test_novel_top_level_path_is_unknown(self) -> None:
        self.assertEqual(self.policy.classify("novel-surface/file.txt"), "unknown")
        denied, unknown = audit_paths(self.policy, ["README.md", "novel-surface/file.txt"])
        self.assertEqual(denied, [])
        self.assertEqual(unknown, ["novel-surface/file.txt"])

    def test_decision_names_the_exact_rule_and_default_deny(self) -> None:
        private = self.policy.decision("departments/coding/inbox/payload.json")
        self.assertEqual(private.classification, "private")
        self.assertEqual(private.policy_section, "deny")
        self.assertEqual(private.policy_pattern, "departments/*/inbox/**")

        public = self.policy.decision("README.md")
        self.assertEqual(public.classification, "public")
        self.assertEqual(public.policy_section, "public")
        self.assertEqual(public.policy_pattern, "README.md")

        unknown = self.policy.decision("novel-surface/file.txt")
        self.assertEqual(unknown.classification, "unknown")
        self.assertEqual(unknown.policy_section, "default_deny")
        self.assertEqual(unknown.policy_pattern, "<no matching rule>")

    def test_engagement_run_output_is_private_at_any_depth_and_in_either_form(self) -> None:
        """The two axes that let a third-party weakness map classify public.

        `tools/*/*/results/**` missed `tools/radar/mutation-sbf/results.json`
        twice over: the depth was hand-anchored (one `*` is one segment, so the
        policy enumerated depth 2 and depth 3 and a deeper path fell between
        them), and the rule was directory-shaped (`results/**` needs a directory
        literally named `results`; the leak was a FILE named `results.json`).

        Each pair below is the same run-output role in the directory form and
        the file form, at a depth no rule was hand-written for. A policy that
        fixes only one axis, or that adds `tools/radar/mutation-sbf/**` as a
        path, fails here.
        """
        run_output = [
            # The material that actually leaked, re-checked at its real path.
            "tools/radar/mutation-sbf/results.json",
            "tools/radar/mutation-sbf/mutants.json",
            # Same role, `.md` form and one level deeper than the old rules
            # reached. Both are real tracked files that classified public until
            # the shape rule landed.
            "tools/standing-checks/primitive-ledger.md",
            "tools/standing-checks/proof-verifier-bounds/PRIMITIVE-LEDGER.md",
            # The NEXT engagement: a rig and a campaign directory that do not
            # exist yet, at depths and in forms nobody enumerated.
            "tools/newrig/campaign-2027/results.json",
            "tools/newrig/campaign-2027/results/raw.txt",
            "tools/newrig/a/b/c/d/results.yaml",
            "tools/newrig/a/b/c/d/results/raw.txt",
            "tools/newrig/a/b/reports.json",
            "tools/newrig/a/b/reports/summary.md",
            "tools/newrig/a/b/evidence.md",
            "tools/newrig/a/b/evidence/poc.txt",
            "tools/newrig/a/b/c/run-manifest.yaml",
            "tools/newrig/a/b/c/ACTION-LOG.txt",
            "tools/newrig/a/b/c/action-log.md",
            "tools/newrig/a/b/c/primitive-ledger.md",
            "tools/newrig/a/b/c/PRIMITIVE-LEDGER.md",
            "tools/newrig/a/b/c/target-integrity.json",
            "tools/newrig/a/b/c/verification-evidence.txt",
            "tools/newrig/a/b/c/CANARY-RESULT.md",
            "tools/newrig/a/b/colima/machine.yaml",
        ]
        self.assertEqual(
            [self.policy.classify(path) for path in run_output],
            ["private"] * len(run_output),
            "a run-output role name must classify private at any depth in either form",
        )

    def test_only_enumerated_tool_families_publish(self) -> None:
        """A new tool family is private until publication is approved.

        Existing publishable mechanism remains available, but a novel rig no
        longer inherits publication merely by living below `tools/`.
        """
        rig_surface = [
            "tools/export/tests/test_path_policy.py",
            "tools/export/policy/path-policy.json",
            "tools/coverage-ledger/coverage_ledger.py",
            "tools/primitive-schema/validate_primitive_ledger.py",
            "tools/tss-bridge-fuzz/rig/src/lib.rs",
            "tools/wsguard/verify.sh",
        ]
        self.assertEqual(
            [self.policy.classify(path) for path in rig_surface],
            ["public"] * len(rig_surface),
        )
        self.assertEqual(self.policy.classify("tools/newrig/README.md"), "unknown")
        self.assertEqual(self.policy.classify("tools/newrig/bin/run.sh"), "unknown")

    def test_arbitrary_documents_do_not_inherit_a_namespace_wide_permit(self) -> None:
        self.assertEqual(self.policy.classify("docs/getting-started.md"), "public")
        for path in [
            "docs/unseen-record.json",
            "docs/target_scan.py",
            "docs/fenced-review.md",
            "docs/encoded-review.md",
        ]:
            self.assertEqual(self.policy.classify(path), "unknown")

    def test_bounty_moat_is_private_including_former_fixture_exceptions(self) -> None:
        private = [
            "plugins/chrono-dedup/README.md",
            "plugins/chrono-dedup/tests/test_sources.py",
            "tools/standing-checks/README.md",
            "tools/standing-checks/storage-slot-alignment/fixtures/good.tsv",
            "tools/radar/README.md",
            "tools/radar/templates/missing-pda-seeds-canary.yaml",
            ".claude/skills/systematic-attacking/SKILL.md",
            ".claude/skills/systematic-attacking/references/chain-strike-v2.md",
            ".claude/skills/systematic-bug-hunting/SKILL.md",
            ".claude/skills/probe-canary/SKILL.md",
        ]
        self.assertEqual(
            [self.policy.classify(path) for path in private],
            ["private"] * len(private),
        )

    def test_generated_public_subtree_is_not_unconditionally_publishable(self) -> None:
        """`public_exceptions` is evaluated BEFORE deny, so a subtree exception
        force-publishes everything written into it -- including material the
        hard deny rules exist to stop.

        `shared/capabilities/public/**` was such an entry, and it is the
        destination the capability-card generator writes to. Removing it changed
        no tracked classification (that subtree already matched `shared/**`
        under `public`) while restoring the deny rules over generated output.
        """
        self.assertEqual(
            self.policy.classify("shared/capabilities/public/bounty/web-api-saas.md"),
            "public",
            "real generated cards must still publish",
        )
        for hazard in [
            "shared/capabilities/public/notes.local.md",
            "shared/capabilities/public/run.log",
            "shared/capabilities/public/tls.pem",
            "shared/capabilities/public/current.md",
            "shared/capabilities/public/service-secret.json",
        ]:
            self.assertEqual(
                self.policy.classify(hazard),
                "private",
                f"a deny rule must still reach {hazard}",
            )

    def test_every_tracked_path_has_an_explicit_classification(self) -> None:
        """`unknown` fails the export closed, which is correct -- and therefore
        an unknown tracked path is an unmade decision, not a passing gate.

        This test is what makes that visible before a release rather than at the
        projector. It is the reason CODE_OF_CONDUCT.md and SECURITY.md are named
        in the policy: both were authored for publication and both classified
        unknown, so the export could not have run.
        """
        listing = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8", errors="surrogateescape")
        tracked = [path for path in listing.split("\0") if path]
        self.assertTrue(tracked, "expected a tracked file listing")
        unknown = [path for path in tracked if self.policy.classify(path) == "unknown"]
        self.assertEqual(unknown, [], "every tracked path needs a public/private decision")

    def test_malformed_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "policy.json"
            malformed.write_text(json.dumps({"version": 1, "deny": ["_state/**"]}))
            with self.assertRaises(PolicyError):
                load_policy(malformed)


if __name__ == "__main__":
    unittest.main()
