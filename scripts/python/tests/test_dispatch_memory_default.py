"""The dispatch default is the single change that turns memory on.

Measured 2026-08-17: 2,665 of 2,669 packets ran with memory off because
this defaulted to `cold`.

The second half of this module pins the aperture vocabulary. The set of
recognised apertures is one fact with four independent homes in this
repository -- `clearance._APERTURES`, `broker.CONTEXT_APERTURES`,
`dispatch_context_builder.MEMORY_APERTURES`, and a `case` alternation in
`bin/send-task.sh`. `clearance` owns the vocabulary because it is the
module that validates the policy TSV against it; the other three are
copies, and these tests are what CLAUDE.md rule 10 requires of a copy that
must exist. Without them, adding an aperture in one place and not the
others emits a dispatch the broker rejects outright.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import dispatch_context_builder as dcb  # noqa: E402
from dispatch_context_builder import resolve_memory_aperture  # noqa: E402

VAULT_DIR = ROOT / "plugins" / "chrono-vault"
SEND_TASK = ROOT / "bin" / "send-task.sh"


def _load_vault_module(name: str) -> ModuleType:
    """Import a chrono-vault module without putting its directory on sys.path.

    `plugins/chrono-vault/` holds generic names (`index`, `query`, `notes`,
    `audit`), and `unittest discover` runs every test module in one process.
    Inserting that directory into `sys.path` would change which module a
    *different* test file resolves those names to, so load by file location.
    """

    synthetic = f"_aperture_pin_{name}"
    spec = importlib.util.spec_from_file_location(synthetic, VAULT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` resolves its own module out of sys.modules during class
    # creation, so the entry has to exist before exec_module. The synthetic
    # name cannot collide with a real import.
    sys.modules[synthetic] = module
    spec.loader.exec_module(module)
    return module


class MemoryDefaultTests(unittest.TestCase):
    def test_absent_aperture_resolves_to_default_not_cold(self):
        self.assertEqual(resolve_memory_aperture({}), "default")

    def test_explicit_cold_is_still_honoured(self):
        self.assertEqual(resolve_memory_aperture({"memory_aperture": "cold"}), "cold")

    def test_explicit_none_is_still_honoured(self):
        self.assertEqual(resolve_memory_aperture({"memory_aperture": "none"}), "none")

    def test_empty_aperture_resolves_to_default(self):
        # An author who writes the key with no value gets the default, not a
        # validation error -- this is the shape `bin/send-task.sh` produces for
        # `memory_aperture:` with an empty value.
        self.assertEqual(resolve_memory_aperture({"memory_aperture": ""}), "default")

    def test_packet_contract_uses_the_resolver(self):
        aperture, focus = dcb.packet_memory_contract({})
        self.assertEqual(aperture, "default")
        self.assertIsNone(focus)


class DefaultAperturePermitsReadsTests(unittest.TestCase):
    """The launch prompt must agree with the policy the broker enforces.

    `memory.default.v1` allows recall, get_note and browse. A prompt that
    tells the worker not to call recall would switch memory off again in the
    only place that actually runs -- exactly the failure `shared/protocol.md`
    records for `record_usage` between 2026-07-25 and 2026-08-17.
    """

    def _prompt(self, aperture: str) -> str:
        return dcb.assemble_trusted_launch_prompt(
            "packet body",
            task_id="TASK-2026-08-17-0000-memory-default",
            attempt_id="d-" + "0" * 32,
            generation=1,
            memory_aperture=aperture,
        )

    def test_default_aperture_is_told_to_recall(self):
        prompt = self._prompt("default")
        self.assertIn("Recall prior context ONCE", prompt)
        self.assertNotIn("Do not call recall or get_note", prompt)

    def test_cold_aperture_is_still_told_not_to_recall(self):
        self.assertIn("Do not call recall or get_note", self._prompt("cold"))

    def test_pool_blind_aperture_is_still_told_not_to_recall(self):
        self.assertIn("Do not call recall or get_note", self._prompt("pool_blind"))


class ApertureVocabularyPinTests(unittest.TestCase):
    """One fact, four homes. These tests are the validator rule 10 asks for."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.clearance = _load_vault_module("clearance")
        cls.broker = _load_vault_module("broker")

    def test_dispatch_builder_matches_clearance(self):
        self.assertEqual(set(dcb.MEMORY_APERTURES), set(self.clearance._APERTURES))

    def test_broker_context_decoder_matches_clearance(self):
        self.assertEqual(
            set(self.broker.CONTEXT_APERTURES), set(self.clearance._APERTURES)
        )

    def test_policy_registry_defines_every_aperture(self):
        rows = (
            (ROOT / "shared" / "registries" / "memory-apertures.tsv")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        declared = {line.split("\t")[1] for line in rows[1:] if line.strip()}
        self.assertEqual(declared, set(self.clearance._APERTURES))

    def test_rich_and_default_declare_the_same_policy_deliberately(self):
        """M2/rule 10: two names for one policy needs a stated winner.

        `memory.rich.v1` and `memory.default.v1` are byte-identical apart
        from `policy_id` and `aperture`. `shared/protocol.md` records that
        `default` is the one that wins -- it is what an omitted field
        resolves to and what every dispatch gets -- and `rich` is kept as
        the name for saying "open memory, deliberately" rather than by
        omission. This is the enforcement that keeps the two in agreement:
        if they ever diverge, that has to be a decision someone made on
        purpose, not drift, and this test is where they will notice.
        """
        rows = (
            (ROOT / "shared" / "registries" / "memory-apertures.tsv")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        header = rows[0].split("\t")
        policies = {}
        for line in rows[1:]:
            if not line.strip():
                continue
            cells = dict(zip(header, line.split("\t")))
            policies[cells["aperture"]] = {
                key: value
                for key, value in cells.items()
                if key not in {"policy_id", "aperture"}
            }
        self.assertIn("rich", policies)
        self.assertIn("default", policies)
        self.assertEqual(
            policies["rich"],
            policies["default"],
            "rich and default have diverged. That may be right -- but "
            "shared/protocol.md states they are the same policy with "
            "`default` as the winner, so update that paragraph in the same "
            "change rather than leaving two answers.",
        )

    def test_the_documented_winner_is_the_dispatch_default(self):
        self.assertEqual(resolve_memory_aperture({}), "default")

    def test_send_task_case_arm_matches_clearance(self):
        text = SEND_TASK.read_text(encoding="utf-8")
        match = re.search(
            r'case "\$MEMORY_APERTURE" in\n\s*([a-z_|]+)\)\s*;;', text
        )
        self.assertIsNotNone(match, "send-task.sh no longer validates the aperture")
        self.assertEqual(set(match.group(1).split("|")), set(self.clearance._APERTURES))

    def test_send_task_default_matches_the_dispatch_default(self):
        text = SEND_TASK.read_text(encoding="utf-8")
        match = re.search(
            r'\[\[ -n "\$MEMORY_APERTURE" \]\] \|\| MEMORY_APERTURE="([a-z_]+)"', text
        )
        self.assertIsNotNone(match, "send-task.sh no longer defaults the aperture")
        self.assertEqual(match.group(1), resolve_memory_aperture({}))


if __name__ == "__main__":
    unittest.main()
