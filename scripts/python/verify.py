#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Multi-model verify — dispatch a writer's output to a different-family
reviewer per CLAUDE.md routing rules.

Per system rule: "Reviewer family ≠ writer family. If Codex wrote, Claude or
Gemini reviews — never Codex."

STATUS (2026-05-03): Ad-hoc utility for manual / mode-driven multi-model review.
NOT load-bearing in nightly automation. `dream_light.py` has its own hardcoded
reviewer logic (Gemini journal → Codex review with Kimi fallback) which is a
deliberate choice with different reviewer preferences than this script's
REVIEWER_CHAIN. Do not refactor `dream_light.py` to delegate to this script
without explicit operator approval — the reviewer family preferences differ
(this script's chain is Claude-first for Gemini writers; dream_light's is
Codex-first), and switching them is a behavior change.

If you want to unify them later, update REVIEWER_CHAIN below to match
dream_light's preferences (gemini → codex, kimi) BEFORE refactoring any consumer.

Usage:
  scripts/python/verify.py --writer <writer-cli> --output <file> [--prompt <text>]
  scripts/python/verify.py --writer codex --output draft.md
  scripts/python/verify.py --writer gemini --output finding.md --prompt 'Adversarial review'

Default reviewer assignments per REVIEWER_CHAIN below:
  claude → codex (or gemini, kimi fallback)
  codex  → claude (or gemini, kimi fallback)
  gemini → claude (or codex, kimi fallback)
  kimi   → claude (or codex, gemini fallback)

The reviewer is invoked headless with the output file's content prepended to
the prompt. Returns reviewer's response on stdout. Exit 0 always (the verdict
is in the response text — caller parses for APPROVE / REJECT / etc).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Writer → preferred reviewer chain (first available wins).
# Family rule: same-family pairs excluded. Sister CLI families:
#   anthropic = {claude}; openai = {codex}; google = {gemini}; moonshot = {kimi}
REVIEWER_CHAIN = {
    "claude": ["codex", "gemini", "kimi"],
    "codex":  ["claude", "gemini", "kimi"],
    "gemini": ["claude", "codex", "kimi"],
    "kimi":   ["claude", "codex", "gemini"],
}

DEFAULT_REVIEW_PROMPT = (
    "Adversarial review of the document below. Be ruthless: catch hallucinations, "
    "unsupported claims, internal contradictions, missing context, and unsafe "
    "recommendations. Output under these EXACT headers:\n\n"
    "## Verdict\n(One of: APPROVE | APPROVE-WITH-NOTES | REJECT)\n\n"
    "## Issues\n(Bulleted list. Each issue: where in the doc, what's wrong, "
    "what to do. If none, write 'none'.)\n\n"
    "## Strengths\n(0-3 bullets noting what's clearly correct or well-supported.)\n\n"
    "Rules:\n"
    "- Cite specific text from the document when flagging issues.\n"
    "- Don't propose substantial rewrites — just flag.\n"
    "- Under 250 words.\n\n"
    "DOCUMENT:\n{content}"
)


def oauth_env() -> dict:
    env = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env.pop(k, None)
    return env


def call_reviewer(reviewer: str, prompt: str, timeout: int = 300) -> tuple[int, str]:
    if not shutil.which(reviewer):
        return 127, f"reviewer '{reviewer}' not installed"
    if reviewer == "claude":
        args = [reviewer, "-p", "--permission-mode", "default", prompt]
    elif reviewer == "codex":
        args = [reviewer, "exec", "--skip-git-repo-check", "--sandbox", "read-only", prompt]
    elif reviewer == "gemini":
        args = [reviewer, "-p", prompt]
    elif reviewer == "kimi":
        args = [reviewer, "--quiet", "--no-thinking", "-p", prompt,
                "--max-steps-per-turn", "5"]
    else:
        return 2, f"unknown reviewer: {reviewer}"
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, env=oauth_env())
    except subprocess.TimeoutExpired:
        return 124, "reviewer timed out"
    out = r.stdout.strip()
    out = out.split("To resume this session:")[0].rstrip()
    if "tokens used" in out:
        out = out.split("tokens used")[-1].strip()
    return r.returncode, out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--writer", required=True, choices=list(REVIEWER_CHAIN.keys()),
                   help="CLI family that produced the output")
    p.add_argument("--output", required=True, help="Path to writer's output file to review")
    p.add_argument("--prompt", default=None, help="Custom review prompt (default: adversarial)")
    p.add_argument("--reviewer", default=None,
                   help="Override reviewer (must be different family from writer)")
    p.add_argument("--max-input-chars", type=int, default=20000,
                   help="Truncate input to bound reviewer cost (default 20000)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_path = Path(args.output)
    if not out_path.exists():
        print(f"output file not found: {out_path}", file=sys.stderr)
        return 1

    content = out_path.read_text(errors="replace")
    if len(content) > args.max_input_chars:
        content = content[:args.max_input_chars] + "\n\n[truncated for review]"
    prompt = (args.prompt or DEFAULT_REVIEW_PROMPT).format(content=content)

    if args.reviewer:
        if args.reviewer == args.writer:
            print(f"reviewer == writer ({args.writer}) violates family rule", file=sys.stderr)
            return 2
        reviewers = [args.reviewer]
    else:
        reviewers = REVIEWER_CHAIN[args.writer]

    last_err = ""
    for reviewer in reviewers:
        rc, response = call_reviewer(reviewer, prompt)
        if rc == 0 and response:
            print(f"=== Reviewed by: {reviewer} (writer was: {args.writer}) ===\n")
            print(response)
            return 0
        last_err = f"{reviewer}: rc={rc} — {response[:200]}"
        print(f"reviewer {reviewer} unavailable: {last_err}", file=sys.stderr)
    print(f"\nERROR: no reviewer succeeded. Last: {last_err}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
