from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


EXPORT_DIR = Path(__file__).resolve().parents[1]
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
        ]
        self.assertEqual(
            [self.policy.classify(path) for path in private_paths],
            ["private"] * len(private_paths),
        )

    def test_exact_public_exceptions_override_broad_denies(self) -> None:
        public_exceptions = [
            "_state/dream-config.yaml",
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

    def test_public_agent_definitions_and_superpowers_docs_remain_public(self) -> None:
        self.assertEqual(
            self.policy.classify("model-lanes/gemini/.gemini/agents/reviewer.md"),
            "public",
        )
        self.assertEqual(
            self.policy.classify("docs/superpowers/plans/example.md"),
            "public",
        )
        self.assertEqual(
            self.policy.classify("docs/superpowers/specs/spec-example.md"),
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

    def test_novel_top_level_path_is_unknown(self) -> None:
        self.assertEqual(self.policy.classify("novel-surface/file.txt"), "unknown")
        denied, unknown = audit_paths(self.policy, ["README.md", "novel-surface/file.txt"])
        self.assertEqual(denied, [])
        self.assertEqual(unknown, ["novel-surface/file.txt"])

    def test_malformed_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "policy.json"
            malformed.write_text(json.dumps({"version": 1, "deny": ["_state/**"]}))
            with self.assertRaises(PolicyError):
                load_policy(malformed)


if __name__ == "__main__":
    unittest.main()
