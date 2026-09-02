#!/usr/bin/env python3
"""The settlement guard census must not drift from the code it indexes.

`docs/standards/settlement-guard-coverage.md` maps 36 guard messages in
`registry_reconciler.py` to whether each is under test. It was written to be
self-pinning: doc and tests commit together, so `git log -1 -- <the doc>` was
supposed to name the tree its numbers describe.

That did not work. Measured 2026-09-01: every line number in it was stale by
+67, and its own verification recipe returned `521475ea` -- the commit that
SHIPPED that revision of the doc and also touched the reconciler, so the recipe
pointed at a tree where the numbers were already wrong. A doc that certifies
itself certifies nothing.

The census CONTENT held (36 guards, the per-function split, 66 tests). Only the
index rotted -- which is the half a reader actually uses.

So the index is now the guard MESSAGE, which is stable across edits and
greppable. This test enforces the identity Hard Rule 10 requires for a legitimate
duplicate: every documented message remains in its named owner function, every
source guard has exactly one row, classification and evidence totals derive from
those rows, and the stated review-test count matches the test AST.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
CENSUS = REPO_ROOT / "docs" / "standards" / "settlement-guard-coverage.md"
RECONCILER = REPO_ROOT / "scripts" / "python" / "registry_reconciler.py"
REVIEW_TESTS = (
    REPO_ROOT / "scripts" / "python" / "tests" / "test_review_enforcement.py"
)
GUARD_FUNCTIONS = (
    "_validate_factual_attestation",
    "_validate_security_review",
    "require_approval_verdict",
    "_validate_standard_review",
    "settle_review",
)


class GuardCensusIsCurrentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.census = CENSUS.read_text(encoding="utf-8")
        # Join adjacent string literals and drop f-string placeholders, so a
        # message the source wraps across two lines -- or interpolates a
        # constant into -- still matches. Without this the check reports drift
        # for three guards that are merely line-wrapped, and a test that cries
        # wolf gets muted, which costs more than the drift it was watching for.
        raw = RECONCILER.read_text(encoding="utf-8")
        self.raw_source = raw
        joined = re.sub(r'"\s*\n\s*(?:f?")', "", raw)
        self.source = re.sub(r"\{[^{}]*\}", "\x00", joined)
        self.tree = ast.parse(raw)

    def _present(self, message: str, source: str | None = None) -> bool:
        """Is this documented message still in the source?

        Compares on the longest fragment free of the doc's own elisions, so a
        row that renders an f-string as `... observed …` still anchors on the
        stable half.
        """
        for sep in ("…", "..."):
            message = message.split(sep)[0]
        message = message.strip().rstrip(";:,")
        # Normalise the DOC the same way as the source. A row may render an
        # interpolated constant either as a placeholder or as its value; both
        # must compare equal, or the check reports drift for a row that is
        # merely written the other way round.
        message = re.sub(r"\{[^{}]*\}", "\x00", message)
        return bool(message) and message in (
            self.source if source is None else source
        )

    def _function_sources(self) -> dict[str, str]:
        sources: dict[str, str] = {}
        lines = self.raw_source.splitlines()
        for node in ast.walk(self.tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in GUARD_FUNCTIONS
            ):
                segment = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                joined = re.sub(r'"\s*\n\s*(?:f?")', "", segment)
                sources[node.name] = re.sub(r"\{[^{}]*\}", "\x00", joined)
        return sources

    def _documented_rows(self) -> list[tuple[str, str, str, str]]:
        """Return (owner function, message, class, basis) for guard rows only."""
        found: list[tuple[str, str, str, str]] = []
        for function in GUARD_FUNCTIONS:
            heading = f"## `{function}`"
            start = self.census.index(heading)
            end = self.census.find("\n## ", start + len(heading))
            section = self.census[start : end if end >= 0 else None]
            for row in section.splitlines():
                if not row.startswith("| `"):
                    continue
                cells = [cell.strip() for cell in row.split("|")[1:-1]]
                message = re.fullmatch(r"`([^`]{12,})`", cells[0])
                if message and len(cells) >= 3:
                    found.append((function, message.group(1), cells[1], cells[2]))
        return found

    def _source_guard_counts(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in GUARD_FUNCTIONS:
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Raise) or not isinstance(
                    child.exc, ast.Call
                ):
                    continue
                called = child.exc.func
                if isinstance(called, ast.Name) and called.id == "ValueError":
                    counts[node.name] += 1
        return counts

    @staticmethod
    def _class_name(value: str) -> str:
        lowered = value.lower()
        if "prose-only" in lowered:
            return "Prose-only"
        if "uncovered" in lowered:
            return "Uncovered"
        return "Genuinely controlled"

    def test_every_documented_guard_message_still_exists(self) -> None:
        function_sources = self._function_sources()
        missing = [
            f"{function}: {msg}"
            for function, msg, _class, _basis in self._documented_rows()
            if not self._present(msg, function_sources[function])
        ]
        self.assertEqual(
            missing, [],
            "the census documents guard messages that no longer appear in "
            "registry_reconciler.py. Either a guard was renamed or removed and "
            "the census did not follow, or a row names a guard that never "
            "existed. Both make the map lie about coverage.",
        )

    def test_census_has_exactly_one_row_per_owned_source_guard(self) -> None:
        documented = Counter(
            function for function, *_rest in self._documented_rows()
        )
        actual = self._source_guard_counts()
        self.assertEqual(
            documented,
            actual,
            "the census must have exactly one row for every ValueError guard in "
            "its five source-owner functions",
        )

    def test_summary_class_counts_are_derived_from_guard_rows(self) -> None:
        actual = Counter(
            self._class_name(classification)
            for _function, _message, classification, _basis in self._documented_rows()
        )
        summary = Counter(
            {
                name: int(count)
                for name, count in re.findall(
                    r"^\| (Genuinely controlled|Prose-only[^|]*|Uncovered[^|]*) "
                    r"\| (\d+) \|$",
                    self.census,
                    re.MULTILINE,
                )
            }
        )
        normalized_summary = Counter()
        for name, count in summary.items():
            normalized_summary[self._class_name(name)] += count
        self.assertEqual(normalized_summary, actual)

    def test_basis_counts_are_derived_from_guard_rows(self) -> None:
        def basis_name(value: str) -> str | None:
            plain = value.replace("**", "").lower()
            for name in (
                "mutation (this sweep)",
                "mutation (earlier sweep, not re-verified)",
                "assertion text",
                "absence",
            ):
                if plain.startswith(name):
                    return name
            return None

        actual = Counter(
            name
            for _function, _message, _classification, basis in self._documented_rows()
            if (name := basis_name(basis)) is not None
        )
        section = self.census.split("## How each row was established", 1)[1].split(
            "### The three ways", 1
        )[0]
        claimed = Counter()
        for row in section.splitlines():
            if not row.startswith("| **"):
                continue
            cells = [cell.strip() for cell in row.split("|")[1:-1]]
            name = basis_name(cells[0])
            if name is not None:
                claimed[name] = int(cells[1])
        self.assertEqual(claimed, actual)

    def test_claimed_review_test_count_matches_the_source_owner(self) -> None:
        claimed = re.search(r"\*\*(\d+) tests\*\*", self.census)
        self.assertIsNotNone(claimed, "census no longer states its test count")
        tree = ast.parse(REVIEW_TESTS.read_text(encoding="utf-8"))
        actual = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
        self.assertEqual(int(claimed.group(1)), actual)


if __name__ == "__main__":
    unittest.main()
