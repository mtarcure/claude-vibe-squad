#!/usr/bin/env python3
"""Generate publishable capability cards from the private ones.

A capability card is two artifacts fused together:

  1. A workflow spine -- S0 Intake -> S1 Frame -> ... -> S7 Capture, with the
     roles, skills and gates that own each step. Pure method, nothing about our
     machine, and the most transferable thing the system has.
  2. A per-cell capability assertion -- `forge` (local . yes . --). That is a
     census of what WE have working, and read inversely, a map of our gaps.

The projector is path-selection only, so a card cannot be stripped at export
time. This emits a public variant instead, exactly as build_public_catalog.py
does for the registry.

What is removed, and why each one matters:

  - The `(lane . state . cost_tier)` parenthetical. `state` is the census.
  - Skill `(type)` parentheticals -- `stub` and `untyped` mark OUR unfinished
    work, so the type column is a to-do list of our gaps.
  - Frontmatter `capability_state`, `state_reason`, `state_evidence`,
    `cost_note`. These carry MORE state than the table: probe task ids,
    literal `claude.yes.subscription` triples, and our paid-provider stack.
  - Any internal `TASK-...` identifier, wherever it appears.

Stripping state is not a loss for the reader. `forge (local . yes . --)`
asserts OUR liveness inside THEIR repo, which is the same error the toolchain
catalog banner warns about: whether a tool works on our machine is not a fact
about anyone else's.

    python3 tools/export/build_public_capability_cards.py [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SOURCE_DIRS = ["shared/capabilities/bounty", "shared/capabilities/project"]
OUTPUT_DIR = Path("shared/capabilities/public")

FRONTMATTER_KEEP = {"id", "mode", "title", "overlays", "gates"}

# A parenthetical is a capability assertion when it carries the `·` separator of
# a lane/state/cost triple, or when it is a bare registry type word.
TYPE_WORDS = r"authored|stub|untyped|needs_doc|SKILL\.md|pattern-doc[a-z-]*|invokable|knowledge-skill"
ASSERTION_PAREN = re.compile(r"\s*\((?:[^()]*·[^()]*|(?:" + TYPE_WORDS + r"))\)")
TASK_ID = re.compile(r"\bTASK-[0-9A-Za-z-]+")

LANES = r"all|local|claude|codex|gemini|kimi"
STATES = r"yes|no|partial|lane-live|needs-research|needs_tool|authored|stub"
# The lane.state.cost triple also appears INLINE in prose, inside backticks --
# "`godot` (`claude · yes · --`, Godot 4.7.1)". A table-cell rewrite never sees
# those, which is how six of them survived the first pass.
INLINE_TRIPLE = re.compile(
    r"`?\b(?:" + LANES + r")\s*·\s*(?:" + STATES + r")\s*·\s*[^`,)\s]+`?"
)
INLINE_PAIR = re.compile(r"`(?:" + LANES + r")\s*·\s*(?:" + STATES + r")`")

# Prose phrasings that assert our state. Anchored, because the first version
# used bare substrings and flagged "routines · reminders · notifications" via
# "· no", and the gate NAME "capability_state precheck" via "capability_state".
# A guard that cries wolf gets switched off.
LEAK_VOCAB = [
    r"·\s*(?:yes|no|partial)\b",
    r"\b(?:" + LANES + r")\s*·",
    r"\bneeds[-_]research\b",
    r"\blane-live\b",
    r"^(?:capability_state|state_evidence|state_reason|cost_note)\s*:",
    r"\bzero executables\b",
    r"\bwe own no\b",
    r"\bmeasured census\b",
    r"\bprobe-verified\b",
    r"\bTASK-[0-9]",
    # Added after a MANUAL sweep found these surviving a green run. The guard
    # reported "no private state detected" while our lifetime bounty conversion
    # rate sat in three generated cards. Blocklists only catch what was thought
    # of, which is why a human read of the output is required, not optional.
    r"\d+\s*/\s*\d+\s+lifetime",
    r"\bThe moat is\b",
    r"\b49k-finding\b",
    r"\bprimary_exception\b",
]

# Narrative that legitimately discusses our own coverage cannot be rewritten
# mechanically without changing its meaning, so the private card fences it and
# the generator drops the block whole. Explicit beats a cleverer regex.
PRIVATE_FENCE = re.compile(
    r"^[ \t]*<!--\s*private:begin\s*-->.*?^[ \t]*<!--\s*private:end\s*-->[ \t]*\n?",
    re.S | re.M,
)

# Targeted redactions, applied to the generated card only -- the private cards
# keep every word. Each follows one principle: the DISCIPLINE publishes, the
# NUMBERS and the POSITIONING do not.
#
#   "only intrinsic-impact deterministic findings convert"  -> publishes. It is
#   operating discipline an adopter can act on.
#   "(~1/21 lifetime)"                                      -> redacted. That is
#   our measured conversion rate, and a number we paid for.
#   "The moat is beyond commodity tools+chaining: <list>"   -> the list is method
#   and stays; the "our moat" framing is positioning and goes.
#   "kimi `primary_exception`"                              -> internal routing.
REDACTIONS = [
    (re.compile(r"\s*\(~?\d+\s*/\s*\d+\s+lifetime\)"), ""),
    (re.compile(r"\bThe moat is\b"), "Go"),
    (re.compile(r"\s*\(kimi\s+`primary_exception`(?:,[^)]*)?\)"), ""),
    (re.compile(r"\b49k-finding\s+"), ""),
]

BANNER = """> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.
"""


def transform(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0

    if lines and lines[0].strip() == "---":
        out.append("---")
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            key = lines[i].split(":", 1)[0].strip()
            if key in FRONTMATTER_KEEP:
                out.append(lines[i])
            i += 1
        out.append("---")
        i += 1
        out.append("")
        out.extend(BANNER.splitlines())

    body = "\n".join(lines[i:])
    body = PRIVATE_FENCE.sub("", body)
    rendered = []
    for line in body.splitlines():
        line = ASSERTION_PAREN.sub("", line)
        line = INLINE_TRIPLE.sub("", line)
        line = INLINE_PAIR.sub("", line)
        line = TASK_ID.sub("an internal task", line)
        for pattern, replacement in REDACTIONS:
            line = pattern.sub(replacement, line)
        rendered.append(line)
    out.extend(rendered)

    return "\n".join(out).rstrip() + "\n"


def audit(name: str, text: str) -> list[str]:
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern in LEAK_VOCAB:
            if re.search(pattern, line, re.M):
                findings.append(f"{name}:{lineno} matched /{pattern}/ :: {line.strip()[:90]}")
                break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root)

    sources = sorted(
        p for d in SOURCE_DIRS for p in (root / d).glob("*.md") if p.is_file()
    )
    if not sources:
        print("no capability cards found", file=sys.stderr)
        return 1

    leaks: list[str] = []
    stale: list[str] = []
    written = 0

    for src in sources:
        rendered = transform(src.read_text(encoding="utf-8"))
        leaks.extend(audit(src.name, rendered))
        # Preserve the mode subdirectory. Flattening collided
        # bounty/smart-contract-web3.md with project/smart-contract-web3.md and
        # silently dropped one -- 29 sources produced 28 files, and the count
        # said so before anyone noticed.
        target = root / OUTPUT_DIR / src.parent.name / src.name
        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != rendered:
                stale.append(str(target))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        written += 1

    if leaks:
        print("PRIVATE STATE SURVIVED THE TRANSFORM:", file=sys.stderr)
        for leak in leaks:
            print(f"  {leak}", file=sys.stderr)
        return 1
    if stale:
        print("public capability cards are stale; regenerate with "
              "python3 tools/export/build_public_capability_cards.py", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        return 1

    if not args.check and written != len(sources):
        print(f"card count mismatch: {len(sources)} sources -> {written} written",
              file=sys.stderr)
        return 1
    print(f"{'checked' if args.check else 'wrote'} {len(sources) if args.check else written}"
          f" of {len(sources)} public capability card(s); no private state detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
