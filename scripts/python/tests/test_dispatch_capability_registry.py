from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SEND_TASK = REPO_ROOT / "bin/send-task.sh"
TOOLKIT = REPO_ROOT / "shared/dispatch-toolkit.sh"


class DispatchCapabilityRegistryTests(unittest.TestCase):
    def _dry_run(
        self,
        body: str,
        *,
        to_model: str = "gpt-codex",
        specialist: str = "systems-engineer",
        namespace: str = "coding",
        mode: str | None = None,
        capability: str | None = None,
        acknowledgement: str | None = None,
        include_run_id: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        optional = ""
        if mode is not None:
            optional += f"mode: {mode}\n"
        if include_run_id and mode in {"project", "bounty"}:
            prefix = "PRJ" if mode == "project" else "BTY"
            optional += f"run_id: {prefix}-DISPATCH-REGISTRY-TEST\n"
        if capability is not None:
            optional += f"capability: {capability}\n"
        if acknowledgement is not None:
            optional += f"capability_degradation_ack: {acknowledgement}\n"
        packet = f"""---
id: TASK-2026-07-17-9999-dispatch-registry-test
to_model: {to_model}
specialist: {specialist}
source_namespace: {namespace}
compatibility_namespace: {namespace}
write_scope: []
parallel_safe: false
direct_lane_work_allowed: true
mandatory_review: false
review_model: none
return_artifact: _state/test-dispatch.md
{optional}---

{body}
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False
        ) as handle:
            handle.write(packet)
            path = Path(handle.name)
        self.addCleanup(path.unlink, missing_ok=True)
        env = dict(os.environ)
        env["VAULT_ROOT"] = str(REPO_ROOT)
        return subprocess.run(
            [str(SEND_TASK), str(path), "--dry-run"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_dry_run_matrix_uses_registry_state(self) -> None:
        allowed = {
            "existing-valid": "Perform a repository-only review.",
            "brave-legacy-alias": "Use brave_search within the declared budget.",
            "apify-legacy-alias": "Use apify_search after target authorization.",
            "serper-canonical": "Use `Serper` within the credit ceiling.",
        }
        blocked = {
            "registry-no": "Use `DigitalOcean API` for the deployment.",
            "registry-needs-research": "Use `Nano Banana` for image generation.",
        }

        for label, body in allowed.items():
            with self.subTest(label=label):
                result = self._dry_run(body)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("[DRY RUN]", result.stdout)
        for label, body in blocked.items():
            with self.subTest(label=label):
                result = self._dry_run(body)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("registry-state:", result.stderr)

    def test_cross_lane_yes_warns_but_no_state_still_gates(self) -> None:
        yes_result = self._dry_run(
            "Use `Brave Search` only if the handoff requires it.",
            to_model="claude",
            specialist="research",
            namespace="research",
            mode="research",
        )
        no_result = self._dry_run(
            "Use `DigitalOcean API` for the research task.",
            to_model="claude",
            specialist="research",
            namespace="research",
            mode="research",
        )

        self.assertEqual(yes_result.returncode, 2, yes_result.stderr)
        self.assertIn("tool-lane-mismatch:Brave Search", yes_result.stderr)
        self.assertEqual(no_result.returncode, 1, no_result.stderr)
        self.assertIn("registry-state:no", no_result.stderr)

    def test_capability_dispatch_dry_run_matrix(self) -> None:
        live = self._dry_run(
            "Build the declared application.", mode="project", capability="web-app"
        )
        acknowledged = self._dry_run(
            "Work only within the declared degraded profile.",
            mode="project",
            capability="systems-low-level",
            acknowledgement="needs_tool",
        )
        hold = self._dry_run(
            "Attempt the degraded profile without acknowledgement.",
            mode="project",
            capability="systems-low-level",
        )
        malformed = self._dry_run(
            "Malformed pointer.", mode="project", capability="../web-app"
        )
        missing = self._dry_run(
            "Missing pointer.", mode="project", capability="does-not-exist"
        )
        mismatch = self._dry_run(
            "Mode mismatch.", mode="research", capability="project/web-app"
        )

        self.assertEqual(live.returncode, 2, live.stderr)
        self.assertRegex(
            live.stdout,
            r"Capability snapshot: id=project/web-app state=live sha256=[0-9a-f]{64}",
        )
        self.assertEqual(acknowledged.returncode, 2, acknowledged.stderr)
        self.assertIn("state=needs_tool", acknowledged.stdout)
        self.assertEqual(hold.returncode, 1, hold.stderr)
        self.assertIn("capability dispatch HOLD", hold.stderr)
        for result in (malformed, missing, mismatch):
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("capability dispatch validation failed", result.stderr)

    def test_typed_dry_run_without_run_id_fails_admission(self) -> None:
        result = self._dry_run(
            "Missing typed run identifier.",
            mode="project",
            capability="web-app",
            include_run_id=False,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("run_id must be a nonempty string", result.stderr)
        self.assertNotIn("[DRY RUN]", result.stdout)

    def test_toolkit_renders_research_status_from_registry(self) -> None:
        result = subprocess.run(
            [str(TOOLKIT), "coding", "gpt-codex"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("`Brave Search` (codex · yes · metered)", result.stdout)
        self.assertIn("`Apify` (codex · yes · metered)", result.stdout)
        self.assertIn("`Serper` (codex · yes · metered)", result.stdout)
        self.assertNotIn("planned/unverified", result.stdout)


if __name__ == "__main__":
    unittest.main()
