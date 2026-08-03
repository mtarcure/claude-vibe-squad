#!/usr/bin/env python3
"""Fail the export when engagement-target material reaches the public candidate.

Why this exists, stated plainly: the export gate scanned for secrets and private
filesystem paths and reported a clean tree four times in a row, while the
candidate contained a reproducible exploit primitive against a named live bridge
and an 864-line target spec carrying its program id, PDA seeds and TSS pre-image
layout. The gate was not wrong -- it was never asked the question. The operator
asked it, in the last minute before publication.

Secrets, private paths and target identity are three different disclosures. Only
the first two had a scanner.

Two independent checks, because a name blocklist alone would rot the moment a new
engagement starts:

  1. Named targets  -- the identifiers of engagements we have run.
  2. Shape          -- exploit-primitive vocabulary (an attack sequence, a
                       witness citation, a vulnerable-line quote) regardless of
                       which target it names. This is what catches the NEXT
                       engagement, whose names are not in the list yet.

    python3 tools/export/target_scan.py <candidate-root>

Exit 1 on any hit. A finding here is not a formatting problem: it means work
product about somebody else's live system is about to become public.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Engagement identifiers. Extend when an engagement starts, not when it ends --
# the window where this matters is while the work is unsubmitted.
TARGET_NAMES = [
    r"\bpush\s?chain\b",
    r"\bUniversalGateway(?:PC)?\b",
    r"\bI?PRC20\b",
    r"\bUEAFactory\b",
    r"\bUEA_(?:EVM|SVM)\b",
    r"\bCEA_V2\b",
    r"\bsendUniversalTxToUEA\b",
]

# Target-agnostic shape of offensive work product.
PRIMITIVE_SHAPE = [
    r"^\s*action\.sequence\s*:",
    r"^\s*witness\s*:",
    r"^\s*quote\s*:",
    r"\bTSS pre-image\b",
    r"\bPDA seeds\b.*\baccount layouts\b",
]

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
# This file necessarily contains every pattern it hunts for.
SKIP_FILES = {"target_scan.py"}

# The primitive-schema spec DEFINES the field names the shape check hunts for,
# so any documentation of it matches by construction. Exempt from the SHAPE
# check only -- the target-name check still applies, so a real finding smuggled
# into the spec is still caught. One named file, not a glob: an exemption broad
# enough to be convenient is broad enough to be the hole.
SHAPE_EXEMPT = {"tools/primitive-schema/README.md"}


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    names = [(p, re.compile(p, re.I)) for p in TARGET_NAMES]
    shapes = [(p, re.compile(p, re.I | re.M)) for p in PRIMITIVE_SHAPE]

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SKIP_FILES:
            continue
        if SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root)
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, regex in names:
                if regex.search(line):
                    findings.append(f"target-name  {rel}:{lineno}  /{pattern}/  {line.strip()[:80]}")
            if rel.as_posix() in SHAPE_EXEMPT:
                continue
            for pattern, regex in shapes:
                if regex.search(line):
                    findings.append(f"primitive    {rel}:{lineno}  /{pattern}/  {line.strip()[:80]}")
    return findings


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <candidate-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    findings = scan(root)
    if findings:
        print("ENGAGEMENT-TARGET MATERIAL IN THE PUBLIC CANDIDATE:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(f"\n{len(findings)} finding(s). This is work product about somebody "
              f"else's live system; do not publish.", file=sys.stderr)
        return 1

    print(f"target scan clean: no engagement identifiers or exploit primitives in {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
