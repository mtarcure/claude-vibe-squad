#!/usr/bin/env python3
"""Pin the one LIVE enforcement point for the Kimi lead-broker MCP boundary.

Context. The subswarm transport removed in 93ea69ae carried the only test that
asserted "Kimi children never inherit MCP" -- it did so against a
`swarm_diff` directive that rejected `tool_mode: inherited` on a kimi member.
That transport is gone, and with it the directive.

The policy is NOT gone. Its surviving enforcement is
`lane_adapter_registry.validate_adapter_file`, which refuses any Kimi adapter
whose native system prompt does not state the boundary
(`lane_adapter_registry.py`, "lacks lead-broker MCP policy"). That guard was
reachable but unasserted: nothing named it, and `repository_report` only
exercised its happy path through an aggregate `generated_mismatches == []`.

Deliberately NOT covered here: the transport-level claim that a kimi member may
not declare `tool_mode: inherited`. No such gate exists any more, and inventing
a fixture for it would assert a guarantee nothing enforces. See the
TASK-2026-08-27-0430-w9b response for what died with the transport.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "python" / "lane_adapter_registry.py"
SPEC = importlib.util.spec_from_file_location("lane_adapter_registry", MODULE_PATH)
registry_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(registry_module)

KIMI_AGENTS = ROOT / "model-lanes" / "kimi" / ".kimi" / "agents"
KIMI_PROMPTS = ROOT / "model-lanes" / "kimi" / ".kimi" / "prompts"

# The literal the guard searches for. Kept as one constant so a rename in the
# validator and a rename in the prompts cannot pass each other in the night.
BOUNDARY_SENTENCE = "MCP tools are unavailable inside Kimi subagents"


def native_prompt_adapters() -> list[Path]:
    """Every Kimi adapter that points at its own prompt file under ../prompts/.

    The guard only fires for these: a direct canonical pointer makes no
    independent capability claim, so the validator checks it by identity alone.
    """
    selected = []
    for adapter in sorted(KIMI_AGENTS.glob("*.yaml")):
        if "../prompts/" in adapter.read_text(encoding="utf-8"):
            selected.append(adapter)
    return selected


class KimiLeadBrokerMcpPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapters = native_prompt_adapters()
        # A guard with nothing in its blast radius is not being tested. If the
        # lane stops using ../prompts/ pointers this suite must be revisited,
        # not left silently green over an empty set.
        self.assertTrue(
            self.adapters,
            "no Kimi adapter uses a ../prompts/ pointer; the lead-broker guard "
            "in lane_adapter_registry has no live subject and this suite is vacuous",
        )

    def test_every_live_kimi_native_prompt_states_the_lead_broker_boundary(self) -> None:
        for adapter in self.adapters:
            with self.subTest(specialist=adapter.stem):
                prompt = KIMI_PROMPTS / f"{adapter.stem}.md"
                self.assertIn(
                    BOUNDARY_SENTENCE,
                    prompt.read_text(encoding="utf-8"),
                    f"{prompt} must state the lead-broker boundary; a Kimi "
                    "subagent that believes it holds MCP will report tool "
                    "results it never obtained",
                )

    def _stage(self, root: Path, specialist: str) -> Path:
        """Copy the REAL adapter and prompt bytes, preserving the ../prompts/ hop.

        Copied rather than hand-authored on purpose: a rebuilt fixture would
        prove the validator works on a file shape that no lane ships.
        """
        agents = root / ".kimi" / "agents"
        prompts = root / ".kimi" / "prompts"
        agents.mkdir(parents=True)
        prompts.mkdir(parents=True)
        adapter = agents / f"{specialist}.yaml"
        shutil.copyfile(KIMI_AGENTS / f"{specialist}.yaml", adapter)
        shutil.copyfile(KIMI_PROMPTS / f"{specialist}.md", prompts / f"{specialist}.md")
        return adapter

    def test_validator_rejects_a_kimi_prompt_that_drops_the_boundary(self) -> None:
        specialist = self.adapters[0].stem
        with tempfile.TemporaryDirectory(prefix="kimi-lead-broker-") as directory:
            staged_root = Path(directory)
            adapter = self._stage(staged_root, specialist)
            prompt = staged_root / ".kimi" / "prompts" / f"{specialist}.md"

            # Positive control: the untouched real bytes must validate, or the
            # negative below would only prove the fixture is broken.
            registry_module.validate_adapter_file(ROOT, "kimi", adapter)

            original = prompt.read_text(encoding="utf-8")
            self.assertIn(BOUNDARY_SENTENCE, original)
            prompt.write_text(
                original.replace(BOUNDARY_SENTENCE, "MCP tools are available"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                registry_module.AdapterValidationError,
                "lacks lead-broker MCP policy",
            ):
                registry_module.validate_adapter_file(ROOT, "kimi", adapter)

            # Restoring the sentence restores the verdict: the guard keys on
            # this claim and not on some other difference in the staged tree.
            prompt.write_text(original, encoding="utf-8")
            registry_module.validate_adapter_file(ROOT, "kimi", adapter)


if __name__ == "__main__":
    unittest.main()
