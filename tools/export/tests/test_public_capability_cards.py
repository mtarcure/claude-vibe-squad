"""The card generator must audit the whole set before it writes any of it.

`shared/capabilities/public/` is a GENERATED tree, and until 2026-08-11 it was
also a `public_exceptions` entry -- evaluated before every deny rule, so nothing
written there could be caught by the path policy afterwards. That made the
generator's own leak audit the only guard, and the generator ran it too late:
each card was written at the top of the loop and `leaks` was evaluated after the
loop had finished.

These tests pin the ordering, not the wording of the report.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EXPORT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPORT_DIR.parents[1]
GENERATOR = EXPORT_DIR / "build_public_capability_cards.py"


def _load_generator():
    """Load the generator by PATH, not by import name.

    The suite is invoked three ways -- `python3 -m unittest <dotted>`, the same
    with FILE PATHS (`bin/test`'s run_export_core), and via
    `tools/export/tests/run_tests.py` discovery. Those do not agree on what is
    on `sys.path`, and `tools/export/` has no `__init__.py`. A path load works
    under all three. `main` is `__name__`-guarded, so this only defines names.
    """
    spec = importlib.util.spec_from_file_location(
        "build_public_capability_cards", GENERATOR
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR_MODULE = _load_generator()

#: Derived from the generator rather than restated, so a directory rename
#: cannot leave the test asserting against a path the generator abandoned.
PRIVATE_SOURCE_DIRS = [REPO_ROOT / d for d in GENERATOR_MODULE.SOURCE_DIRS]
COMMITTED_PUBLIC_DIR = REPO_ROOT / GENERATOR_MODULE.OUTPUT_DIR

CLEAN_CARD = """---
id: clean-card
mode: bounty
title: Clean Card
capability_state: partial
---

# Clean Card

Ordinary transferable method prose: intake, framing, and a capture step.
"""

# `measured census` is in LEAK_VOCAB and survives `transform` -- it is prose, not
# a parenthetical the rewriter strips. Any other LEAK_VOCAB entry would do; the
# test is about WHEN the audit runs, not about which phrase trips it.
LEAKING_CARD = """---
id: leaking-card
mode: project
title: Leaking Card
capability_state: yes
---

# Leaking Card

This section is a measured census of what runs on our own machine.
"""


class CapabilityCardGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "shared/capabilities/public"

    def _write_source(self, relative: str, text: str) -> None:
        path = self.root / "shared/capabilities" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GENERATOR), "--root", str(self.root), *extra],
            capture_output=True,
            text=True,
        )

    def _generated(self) -> list[str]:
        if not self.output.exists():
            return []
        return sorted(
            str(path.relative_to(self.output)) for path in self.output.rglob("*.md")
        )

    def test_one_leaking_card_stops_the_whole_set_from_being_written(self) -> None:
        """The clean card sorts FIRST, so a write-as-you-go generator publishes
        it before it ever evaluates the leak in the second card.

        That is the exact failure being fixed: a non-zero exit status is not a
        rollback. Under the previous ordering this assertion finds
        `bounty/clean.md` already on disk.
        """
        self._write_source("bounty/clean.md", CLEAN_CARD)
        self._write_source("project/leaking.md", LEAKING_CARD)

        result = self._run()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("measured census", result.stderr)
        self.assertEqual(
            self._generated(),
            [],
            "a failed audit must leave NOTHING published, not everything up to the leak",
        )

    def test_a_clean_set_is_written_and_then_verifies_clean(self) -> None:
        self._write_source("bounty/clean.md", CLEAN_CARD)
        self._write_source("project/also-clean.md", CLEAN_CARD.replace("Clean Card", "Second Card"))

        written = self._run()
        self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        self.assertEqual(self._generated(), ["bounty/clean.md", "project/also-clean.md"])

        # The transform strips `capability_state` -- confirm the guard is
        # auditing the RENDERED text and that the rendered text really lost it.
        rendered = (self.output / "bounty/clean.md").read_text(encoding="utf-8")
        self.assertNotIn("capability_state", rendered)
        self.assertIn("Method, not inventory.", rendered)

        checked = self._run("--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_check_mode_reports_staleness_without_writing(self) -> None:
        self._write_source("bounty/clean.md", CLEAN_CARD)
        self.assertEqual(self._run().returncode, 0)

        self._write_source("bounty/clean.md", CLEAN_CARD.replace("Ordinary", "Amended"))
        stale = self._run("--check")
        self.assertEqual(stale.returncode, 1)
        self.assertIn("stale", stale.stderr)
        self.assertNotIn("Amended", (self.output / "bounty/clean.md").read_text(encoding="utf-8"))

    def test_check_mode_rejects_orphaned_output_card(self) -> None:
        """An output without a private source must make currentness fail."""
        self._write_source("project/clean.md", CLEAN_CARD)
        self.assertEqual(self._run().returncode, 0)

        orphan = self.output / "project/orphan-deleted.md"
        orphan.write_text(
            (self.output / "project/clean.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        checked = self._run("--check")
        self.assertEqual(checked.returncode, 1, checked.stdout + checked.stderr)
        self.assertIn(str(orphan), checked.stderr)

    def test_no_sources_fails_closed(self) -> None:
        """An empty source set must not report a clean, complete generation."""
        (self.root / "shared/capabilities/bounty").mkdir(parents=True)
        (self.root / "shared/capabilities/project").mkdir(parents=True)
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self._generated(), [])

    def test_committed_public_cards_are_leak_free(self) -> None:
        """Audit what is COMMITTED, not what a regeneration would produce.

        This was fused with the currency check below until 2026-08-14, and the
        fusion is what made the pair unrunnable in a public clone: currency
        needs the PRIVATE sources, leak-freedom needs only the cards that ship.
        Splitting them lets this half -- the half that protects the reader --
        run identically in the maintainer tree and in a clone, where it is the
        only capability-card assertion there is.

        `shared/capabilities/{bounty,project}` classify `private` and
        `shared/capabilities/public/` classifies `public`
        (`tools/export/path_policy.py classify`), so a clone carries the output
        and none of the input.
        """
        cards = sorted(COMMITTED_PUBLIC_DIR.rglob("*.md"))
        self.assertNotEqual(
            cards,
            [],
            f"no committed public capability cards under {COMMITTED_PUBLIC_DIR}; "
            "they are tracked and ship in the public projection",
        )

        findings: list[str] = []
        for card in cards:
            findings.extend(
                GENERATOR_MODULE.audit(
                    str(card.relative_to(REPO_ROOT)),
                    card.read_text(encoding="utf-8"),
                )
            )
        self.assertEqual(
            findings,
            [],
            "private state in a COMMITTED public capability card",
        )

    def test_committed_public_cards_are_current_where_the_sources_exist(self) -> None:
        """`scripts/python/validate_capabilities.py:799` excuses `public/` from
        schema validation on the stated grounds that this `--check` runs in CI.
        Since 2026-08-14 it does -- `.github/workflows/squad-validate.yml:51`
        runs the generator with `--check`. That job runs on the maintainer
        repository, which is the only place the sources exist, and this test
        holds the same line for anyone running the suite locally.

        Currency is only decidable where the inputs are. The NAMED CONDITION is
        `PRIVATE_SOURCE_DIRS` holding no `*.md`, which happens exactly when the
        path policy withheld them, and the assertion then becomes the one that
        IS decidable: the generator must refuse, loudly and without writing,
        rather than report a clean generation from nothing. A public clone must
        not be able to believe it regenerated the cards.
        """
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--root", str(REPO_ROOT), "--check"],
            capture_output=True,
            text=True,
        )
        missing = [d for d in PRIVATE_SOURCE_DIRS if not any(d.glob("*.md"))]

        if not missing:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return

        self.assertEqual(
            len(missing),
            len(PRIVATE_SOURCE_DIRS),
            "the private card sources are withheld as a SET; a tree carrying "
            f"only some of them is broken, not projected. Missing: {missing}",
        )
        self.assertEqual(
            result.returncode,
            1,
            "with every source withheld the generator must fail closed, not "
            f"report success: {result.stdout + result.stderr}",
        )
        self.assertIn("no capability cards found", result.stderr)


if __name__ == "__main__":
    unittest.main()
