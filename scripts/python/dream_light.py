#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0",
# ]
# ///
"""Dream-light — nightly journal pass.

Phases:
  1. Skip-condition check (low disk, prior run alive, battery)
  2. Activity collection — files modified in past 24h within allowlist paths
  3. Privacy redaction — strip emails, API keys, common secret patterns
  4. Gemini journal pass — drafts structured insights
  5. Codex adversarial review — flags hallucinations, over-reach, sensitive content
  6. Write `_state/dream-logs/<date>.md` (journal + review verdict)
  7. If mode=propose: write proposals to `_state/dream-proposals/<date>.md`

Multi-model: writer family (Gemini) ≠ reviewer family (Codex). Per CLAUDE.md.

Default mode: shadow (no proposals). Toggle via dream-config.yaml.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
DREAM_CONFIG = STATE_DIR / "dream-config.yaml"
LOG_DIR = STATE_DIR / "dream-logs"
PROPOSALS_DIR = STATE_DIR / "dream-proposals"
PID_FILE = STATE_DIR / "dream-light.pid"
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

GEMINI_BIN = os.environ.get("GEMINI_BIN", "gemini")
KIMI_BIN = os.environ.get("KIMI_BIN", "kimi")
# Per design: writer = Gemini (cheap retrospective synthesis), reviewer = Codex
# (opposite family). But codex login state is uncertain in launchd context, so
# fall back to kimi review when codex isn't available.
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")

JOURNAL_PROMPT = """\
You are the dream-journaler for Claude-Vibe-Squad. Read the activity log below
(past 24h across the squad) and produce a structured journal under these EXACT
section headers. Be evidence-grounded — cite file paths from the log.

Required sections, in order:

## Notable Patterns
(2-5 bullets. Each bullet must reference at least one specific file path or
inbox/outbox message ID from the input. If you see fewer than 2 patterns, say
"none observed".)

## Friction Points
(0-3 bullets. Things that took multiple tries, errored, or required correction.)

## Skill Candidates
(0-3 bullets. Repeatable behaviors that could be codified into a skill or
specialist. NOT applied — just listed for operator review.)

## No-Action Notes
(0-2 bullets. Things noted but no action recommended.)

Rules:
- No invented file paths. Quote real ones from the log.
- No suggestions to modify operator's KG, memory.md, or current.md without
  evidence of explicit need.
- Under 400 words total.
- Output only the markdown — no preface like "Here is the journal".

ACTIVITY LOG:
{activity}
"""

PROPOSAL_PROMPT = """\
You are extracting actionable proposals from a dream journal. From the journal
below, identify 0-3 concrete, evidence-grounded proposals the operator could
APPROVE to apply to their knowledge graph or system. Output as YAML.

Format (YAML list, no markdown wrapper):

- id: P-1
  kind: promote-pattern | mark-stale | merge-dupes | new-skill | other
  title: <short imperative — e.g. "Promote 'multi-model dispatch verified'">
  rationale: <2-3 sentence why, citing journal sections/files>
  proposed_action: <specific filesystem operation; e.g. "Create vault/insights/dispatch-verified.md with content X">
  evidence_paths: [<list of paths from journal>]
  risk: low | medium | high
  reversible: true | false

Rules:
- ONLY propose actions the journal supports with specific evidence.
- Skip proposals where you'd have to guess or invent details.
- Empty list `[]` is a valid output if nothing's worth proposing.
- No commentary outside the YAML.

JOURNAL:
{journal}
"""

REVIEW_PROMPT = """\
You are the adversarial reviewer for a dream journal draft. The draft is below.
Your job: catch hallucinations, over-reach, and privacy issues. Be ruthless.

Output under these EXACT headers:

## Verdict
(One of: APPROVE | APPROVE-WITH-NOTES | REJECT)

## Issues
(Bulleted list. Each issue: cite which section, what's wrong, what to do.
If no issues, write "none".)

## Privacy concerns
(Anything that looks like PII, secrets, or sensitive info that shouldn't be
journaled. If none, write "none".)

Rules:
- Cite specific text from the draft when flagging issues.
- Do not propose substantial rewrites — just flag.
- Under 200 words.

JOURNAL DRAFT:
{journal}
"""


@dataclass
class ActivityFile:
    path: Path
    rel_path: str
    mtime: datetime
    size: int


def load_config() -> dict:
    if not DREAM_CONFIG.exists():
        sys.exit(f"dream-config.yaml not found at {DREAM_CONFIG}")
    return yaml.safe_load(DREAM_CONFIG.read_text())


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
    tmp.write_text(content)
    try:
        with open(tmp, "rb") as fh:
            os.fsync(fh.fileno())
    except OSError:
        pass
    tmp.rename(path)


def check_skip_conditions(cfg: dict) -> str | None:
    """Return reason-to-skip, or None if OK to run."""
    # Prior run still alive?
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)  # raises if not alive
            return f"previous dream-light still running (pid {pid})"
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)

    skip_if = cfg.get("skip_if", [])
    flat: dict = {}
    for entry in skip_if:
        if isinstance(entry, dict):
            flat.update(entry)

    if flat.get("low_disk", False):
        # macOS df -k for portability
        try:
            out = subprocess.check_output(["df", "-k", str(VAULT_ROOT)], text=True)
            line = out.strip().splitlines()[-1].split()
            avail_kb = int(line[3])
            total_kb = int(line[1])
            # Skip only on true emergency (<5% free). 5-15% is "tight, but
            # dreams are cheap to write — let them run."
            if total_kb > 0 and (avail_kb / total_kb) < 0.05:
                return f"low disk ({avail_kb // 1024} MB free)"
        except (subprocess.CalledProcessError, ValueError, IndexError):
            pass

    if flat.get("on_battery", False):
        try:
            out = subprocess.check_output(["pmset", "-g", "batt"], text=True)
            if "Battery Power" in out:
                return "on battery"
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    return None


def collect_activity(cfg: dict, hours: int = 24) -> list[ActivityFile]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    inputs = cfg.get("inputs", {})
    includes: list[str] = inputs.get("include", [])
    excludes: list[str] = inputs.get("exclude", [])

    matches: list[ActivityFile] = []
    seen: set[Path] = set()
    for pattern in includes:
        full = VAULT_ROOT / pattern
        # Glob via Path.glob — convert ** to recursive
        if "**" in pattern:
            base = pattern.split("**")[0].rstrip("/") or "."
            base_path = VAULT_ROOT / base if base != "." else VAULT_ROOT
            it = base_path.rglob("*")
        else:
            it = VAULT_ROOT.glob(pattern)
        for p in it:
            if p in seen or not p.is_file():
                continue
            rel = str(p.relative_to(VAULT_ROOT))
            if any(fnmatch.fnmatch(rel, e) or e in rel for e in excludes):
                continue
            try:
                mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if mt < cutoff:
                continue
            seen.add(p)
            matches.append(ActivityFile(path=p, rel_path=rel, mtime=mt, size=p.stat().st_size))

    matches.sort(key=lambda a: a.mtime)
    return matches


SECRET_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # emails
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),                            # OpenAI-style
    re.compile(r"\b[A-Za-z0-9]{32,}\b"),                                  # generic 32+ hex
    re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b"),                            # xAI
    re.compile(r"\bpplx-[A-Za-z0-9_-]{20,}\b"),                           # Perplexity
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),                            # Google API
    re.compile(r"\bapify_api_[A-Za-z0-9]{20,}\b"),                        # Apify
]


def redact(text: str) -> str:
    out = text
    for pat in SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def render_activity_log(files: list[ActivityFile], max_total_chars: int = 30000) -> str:
    """Concatenate activity files into one log, redacted, truncated."""
    parts = [f"# Activity log — generated {datetime.now(timezone.utc).isoformat()}",
             f"# {len(files)} files modified in last 24h", ""]
    used = sum(len(p) for p in parts)
    for af in files:
        if used >= max_total_chars:
            parts.append(f"... [truncated; remaining {len(files) - len(parts) + 3} files omitted]")
            break
        try:
            content = af.path.read_text(errors="replace")
        except OSError:
            continue
        # Skip files larger than 30KB to bound token usage
        if len(content) > 30000:
            content = content[:30000] + f"\n\n... [file truncated, original {af.size} bytes]"
        snippet = (
            f"\n## file: {af.rel_path}  ({af.mtime.isoformat()})\n"
            f"```\n{redact(content)}\n```\n"
        )
        if used + len(snippet) > max_total_chars:
            parts.append(f"... [truncated at {af.rel_path}]")
            break
        parts.append(snippet)
        used += len(snippet)
    return "\n".join(parts)


def oauth_env() -> dict[str, str]:
    """Return env with API-key vars dropped, forcing each CLI to fall back to
    OAuth/subscription auth (Max plan, ChatGPT Plus, Gemini personal OAuth, etc.)."""
    keys_to_drop = (
        "ANTHROPIC_API_KEY",   # claude headless prefers this over keychain
        "OPENAI_API_KEY",      # codex headless prefers this over ChatGPT login
        "GEMINI_API_KEY",      # gemini -p prefers this over oauth-personal
        "GOOGLE_API_KEY",      # gemini falls back to this if GEMINI_API_KEY unset
    )
    env = os.environ.copy()
    for k in keys_to_drop:
        env.pop(k, None)
    return env


def call_cli(bin_path: str, prompt: str, *, extra_args: list[str] | None = None,
             timeout: int = 240) -> str | None:
    args = [bin_path]
    if "kimi" in bin_path:
        args += ["--quiet", "--no-thinking", "--max-steps-per-turn", "5"]
    elif "gemini" in bin_path:
        pass  # gemini -p is non-interactive
    elif "codex" in bin_path:
        args += ["exec", "--skip-git-repo-check", "--sandbox", "read-only"]
    if extra_args:
        args += extra_args
    args += ["-p" if "codex" not in bin_path else "", prompt]
    args = [a for a in args if a != ""]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env=oauth_env())
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    out = out.split("To resume this session:")[0].rstrip()
    return out or None


def gemini_journal(activity: str) -> str | None:
    return call_cli(GEMINI_BIN, JOURNAL_PROMPT.format(activity=activity), timeout=300)


def gemini_proposals(journal: str) -> list[dict] | None:
    """Generate 0-3 proposal cards (only when mode=propose).

    Returns parsed YAML list. Empty list is valid (means no actionable proposals).
    """
    raw = call_cli(GEMINI_BIN, PROPOSAL_PROMPT.format(journal=journal), timeout=300)
    if not raw:
        return None
    # Strip markdown code fences if model wrapped output despite instruction
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n", "", cleaned)
        cleaned = re.sub(r"\n```\s*$", "", cleaned)
    try:
        parsed = yaml.safe_load(cleaned)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, list):
        return None
    return parsed


def write_proposals(proposals: list[dict], run_id: str) -> list[Path]:
    """Write each proposal to _state/dream-proposals/<run-id>-<id>.md as
    individual files with a status field operator can flip to APPROVE/REJECT."""
    proposals_dir = STATE_DIR / "dream-proposals"
    written: list[Path] = []
    for p in proposals:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or f"P-{len(written) + 1}")
        path = proposals_dir / f"{run_id}-{pid}.md"
        body = (
            f"---\n"
            f"id: {pid}\n"
            f"run_id: {run_id}\n"
            f"created: {datetime.now(timezone.utc).isoformat()}\n"
            f"status: pending  # change to APPROVE / REJECT\n"
            f"kind: {p.get('kind', 'other')}\n"
            f"risk: {p.get('risk', 'unknown')}\n"
            f"reversible: {p.get('reversible', 'unknown')}\n"
            f"---\n\n"
            f"# {p.get('title', '(untitled proposal)')}\n\n"
            f"## Rationale\n\n{p.get('rationale', '(none)')}\n\n"
            f"## Proposed action\n\n{p.get('proposed_action', '(none)')}\n\n"
            f"## Evidence\n\n"
        )
        for ev in (p.get("evidence_paths") or []):
            body += f"- `{ev}`\n"
        body += (
            "\n## How to act\n\n"
            "Edit this file and change `status: pending` to `status: APPROVE` or "
            "`status: REJECT`. Add a `reason: ...` line for REJECT. The "
            "morning brief surfaces all `pending` proposals.\n"
        )
        atomic_write(path, body)
        written.append(path)
    return written


def codex_review(journal: str) -> str | None:
    """Codex exec with read-only sandbox; falls back to kimi if codex unavailable."""
    if shutil.which(CODEX_BIN):
        out = subprocess.run(
            [CODEX_BIN, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
             REVIEW_PROMPT.format(journal=journal)],
            capture_output=True, text=True, timeout=300, env=oauth_env(),
        )
        if out.returncode == 0 and out.stdout.strip():
            # Codex exec emits "tokens used" + repeated final block; keep last block.
            text = out.stdout
            text = text.split("tokens used")[-1] if "tokens used" in text else text
            return text.strip() or None
    # Fallback: kimi reviews (different family from gemini, still satisfies rule)
    return call_cli(KIMI_BIN, REVIEW_PROMPT.format(journal=journal), timeout=240)


def render_dream_log(activity_files: list[ActivityFile], journal: str | None,
                     review: str | None, mode: str, skip_reason: str | None) -> str:
    fm = (
        f"---\n"
        f"date: {DATE}\n"
        f"mode: {mode}\n"
        f"journaler: gemini\n"
        f"reviewer: {'codex' if shutil.which(CODEX_BIN) else 'kimi (codex unavailable)'}\n"
        f"events_scanned: {len(activity_files)}\n"
        f"generated_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"---\n\n"
    )
    if skip_reason:
        return fm + f"# Dream Log: {DATE}\n\n*Skipped: {skip_reason}*\n"

    body = [f"# Dream Log: {DATE}", ""]
    body.append(f"## Inputs Scanned\n\n{len(activity_files)} files in past 24h.\n")
    if activity_files[:5]:
        body.append("Sample (most recent):")
        for af in activity_files[-5:]:
            body.append(f"- `{af.rel_path}` ({af.mtime.isoformat()})")
    body.append("")
    body.append("## Journal (gemini)\n")
    body.append(journal or "*(journaler returned empty — see logs)*")
    body.append("")
    body.append("## Adversarial Review")
    body.append(review or "*(reviewer returned empty — see logs)*")
    body.append("")
    body.append("---")
    body.append("*This log is shadow-mode (journal only). To convert insights to "
                "proposals, set `mode: propose` in `_state/dream-config.yaml`.*")
    return fm + "\n".join(body) + "\n"


def main() -> int:
    cfg = load_config()
    mode = cfg.get("mode", "shadow")

    skip_reason = check_skip_conditions(cfg)
    log_path = LOG_DIR / f"{DATE}.md"
    if skip_reason:
        atomic_write(log_path, render_dream_log([], None, None, mode, skip_reason))
        print(f"Dream-light skipped: {skip_reason}")
        return 0

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    try:
        files = collect_activity(cfg)
        if not files:
            atomic_write(log_path, render_dream_log([], None, None, mode,
                                                   "no activity in last 24h"))
            print("Dream-light: no activity to journal.")
            return 0

        activity = render_activity_log(files)
        print(f"Activity collected: {len(files)} files, {len(activity)} chars")

        print("Calling gemini for journal...")
        journal = gemini_journal(activity)
        if not journal:
            print("WARNING: journal pass returned empty")

        review = None
        if journal:
            print("Calling reviewer for adversarial pass...")
            review = codex_review(journal)
            if not review:
                print("WARNING: review pass returned empty")

        atomic_write(log_path, render_dream_log(files, journal, review, mode, None))
        print(f"Dream log: {log_path}")

        # Propose mode: extract structured proposal cards
        if mode == "propose" and journal:
            print("Mode=propose: extracting proposal cards...")
            proposals = gemini_proposals(journal)
            if proposals is None:
                print("WARNING: proposal extraction returned empty/unparseable")
            else:
                run_id = f"DRM-{DATE}-{uuid.uuid4().hex[:6]}"
                cap = cfg.get("max_proposals_per_night", 3)
                written = write_proposals(proposals[:cap], run_id)
                print(f"Wrote {len(written)} proposal card(s) to _state/dream-proposals/")

        return 0
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
