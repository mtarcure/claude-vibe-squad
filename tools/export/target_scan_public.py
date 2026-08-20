#!/usr/bin/env python3
r"""Fail public CI when target-agnostic engagement material is present.

This is the publishable half of the engagement-target scanner. It deliberately
contains only the checks whose rules reveal no engagement identity:

  2. Line shape -- exploit-primitive vocabulary.
  3. Record shape -- field-name conjunctions and distinctive work-product keys.
  4. Engagement citation -- references to a dated private campaign directory.

The private ``target_scan.py`` adds check 1, the engagement-name blocklist, and
remains the full pre-export scanner. The two implementations are intentionally
kept behaviorally aligned by ``tests/test_target_scan.py``: the test compares
all check-2/3/4 rule data and runs both scanners over the same disclosure corpus.

    python3 tools/export/target_scan_public.py <candidate-root>

Exit 1 on a finding and exit 2 when no readable file was examined. A clean
result without a positive file count is not evidence that the control ran.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# Check 2: target-agnostic shape of offensive work product, line by line.
PRIMITIVE_TEXT = [
    r"^\s*action\.sequence\s*:",
    r"^\s*witness\s*:",
    r"^\s*quote\s*:",
    r"\bTSS pre-image\b",
    r"\bPDA seeds\b.*\baccount layouts\b",
]

# The same primitive-ledger fields resolved from a real JSON parse, so a
# minified record cannot evade the line-oriented forms above. Parse-only is
# deliberate: a textual single-field rule would mistake typed parameter lists
# for records.
PRIMITIVE_PARSED_FIELDS = {"action.sequence", "witness", "quote"}

# Check 3: whole-file conjunctions over field names. Each field alone is common
# vocabulary; the conjunction is a map of a third party's guard surface.
RECORD_FIELD_SHAPE = [
    (
        "guard-weakening census",
        ({"guard"}, {"terminus"}, {"old", "file"}),
    ),
]

# Check 4: citations into a dated campaign directory. The rule describes a
# path shape rather than any campaign or target identity.
ENGAGEMENT_CITATION = [
    ("campaign-directory citation", r"_state/bounty/[A-Za-z0-9][A-Za-z0-9_]*-20\d{2}-\d{2}-\d{2}"),
]

# Distinctive work-product keys are safe as textual triggers because they do
# not occur as ordinary vocabulary in the tracked public tree.
RECORD_TOKEN_SHAPE = [
    ("mutation-campaign result", r'\bkilling_tests\b\s*"?\s*:'),
    ("third-party repository pin", r'\btarget_repo_pin\b\s*"?\s*:'),
]

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}

# The public scanner has no whole-file skip. Its own source is read so the
# unexemptible campaign-citation check remains live on it; only the shape rules
# it defines by construction are exempted below.
SKIP_PATHS: frozenset[str] = frozenset()

SHAPE_CHECKS = frozenset({"primitive", "record"})

# Named files that define or fixture the shape vocabulary. Exemptions suppress
# only the named shape checks; campaign citations remain unexemptible.
SHAPE_EXEMPT = {
    "tools/primitive-schema/README.md": frozenset({"primitive"}),
    "docs/standards/instruction-layer-standard-and-rubric.md": frozenset({"primitive"}),
    "tools/export/tests/test_target_scan.py": SHAPE_CHECKS,
    "tools/export/target_scan_public.py": SHAPE_CHECKS,
}

_unknown_exemptions = {
    relative: sorted(checks - SHAPE_CHECKS)
    for relative, checks in SHAPE_EXEMPT.items()
    if checks - SHAPE_CHECKS
}
if _unknown_exemptions:
    raise ValueError(f"unknown shape-check names in SHAPE_EXEMPT: {_unknown_exemptions}")


# A field name in field position: at line start or after a serialized-record
# delimiter. This reaches minified records without treating prose like
# ``the guard: ...`` as a declared field.
_FIELD_NAME = re.compile(
    r"""(?:^|[{\[,])\s*["']?(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)["']?\s*:""",
    re.M,
)


@dataclass(frozen=True)
class _Fields:
    parsed: frozenset[str]
    names: frozenset[str]


def _parsed_field_names(text: str) -> set[str]:
    """Return field names from a real JSON parse, or empty for non-JSON text."""
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        return set()
    names: set[str] = set()
    stack = [document]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str):
                    names.add(key.lower())
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return names


def _fields(text: str) -> _Fields:
    """Resolve the field names ``text`` declares, independent of layout."""
    parsed = frozenset(_parsed_field_names(text))
    textual = {match.group("name").lower() for match in _FIELD_NAME.finditer(text)}
    return _Fields(parsed=parsed, names=parsed | textual)


@dataclass(frozen=True)
class ScanResult:
    """Findings plus receipts that distinguish clean from never examined.

    `paths_skipped` records every walked file this scan did NOT read, tagged
    with why: an exemption, or a decode/read failure. Both are "unread", and an
    unread file leaves no mark on `files_scanned`, so reporting only one of them
    reads as full coverage while the other silently vanishes.
    `files_scanned + len(paths_skipped)` therefore equals the files walked, and
    that arithmetic is the receipt a caller can actually check.
    """

    findings: list[str]
    files_scanned: int
    paths_skipped: tuple[str, ...] = ()


def scan(root: Path) -> ScanResult:
    """Run target-agnostic checks 2–4 over ``root``."""
    findings: list[str] = []
    files_scanned = 0
    paths_skipped: list[str] = []
    primitives = [(pattern, re.compile(pattern, re.I | re.M)) for pattern in PRIMITIVE_TEXT]
    tokens = [
        (label, re.compile(pattern, re.I | re.M))
        for label, pattern in RECORD_TOKEN_SHAPE
    ]
    engagements = [
        (label, re.compile(pattern, re.I))
        for label, pattern in ENGAGEMENT_CITATION
    ]

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        rel = relative_path.as_posix()
        if SKIP_DIRS & set(relative_path.parts):
            continue
        if rel in SKIP_PATHS:
            paths_skipped.append(rel)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as error:
            # Recorded rather than dropped, for the same reason as the private
            # scanner: unread is unread, and a receipt that omits it overstates
            # coverage.
            paths_skipped.append(f"{rel} (unread: {type(error).__name__})")
            continue
        files_scanned += 1
        exempt = SHAPE_EXEMPT.get(rel, frozenset())
        primitive_exempt = "primitive" in exempt
        record_exempt = "record" in exempt

        for lineno, line in enumerate(text.splitlines(), 1):
            # Check 4 is deliberately evaluated before shape exemptions.
            for label, regex in engagements:
                if regex.search(line):
                    findings.append(
                        f"engagement   {rel}:{lineno}  [{label}]  {line.strip()[:80]}"
                    )
            if primitive_exempt:
                continue
            for pattern, regex in primitives:
                if regex.search(line):
                    findings.append(
                        f"primitive    {rel}:{lineno}  /{pattern}/  {line.strip()[:80]}"
                    )

        if primitive_exempt and record_exempt:
            continue
        fields = _fields(text)
        if not primitive_exempt:
            for name in sorted(PRIMITIVE_PARSED_FIELDS & fields.parsed):
                findings.append(f"primitive    {rel}  [parsed field {name}]")
        if not record_exempt:
            for label, clauses in RECORD_FIELD_SHAPE:
                if all(clause & fields.names for clause in clauses):
                    joined = " AND ".join(
                        "|".join(sorted(clause)) for clause in clauses
                    )
                    findings.append(
                        f"record       {rel}  [{label}]  fields {joined}"
                    )
            for label, regex in tokens:
                if regex.search(text):
                    findings.append(
                        f"record       {rel}  [{label}]  /{regex.pattern}/"
                    )

    return ScanResult(
        findings=findings,
        files_scanned=files_scanned,
        paths_skipped=tuple(paths_skipped),
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <candidate-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    result = scan(root)
    if result.findings:
        print("ENGAGEMENT-TARGET MATERIAL IN THE PUBLIC CANDIDATE:", file=sys.stderr)
        for finding in result.findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            f"\n{len(result.findings)} finding(s) across {result.files_scanned} "
            "file(s) scanned. This is engagement work product; do not publish.",
            file=sys.stderr,
        )
        return 1

    if result.files_scanned == 0:
        print(
            f"target-shape scan examined 0 readable files under {root}; refusing "
            "to report clean",
            file=sys.stderr,
        )
        return 2

    print(
        "target-shape scan clean: no exploit primitives, guard-census records "
        f"or campaign-directory citations in {result.files_scanned} file(s) "
        f"under {root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
