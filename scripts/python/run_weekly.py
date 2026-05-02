#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0",
# ]
# ///
"""Weekly deep run — Sunday 04:00, in addition to daily nightly.

Phases:
  1. Deep KG cleanup (longer-threshold orphan scan, dupe consolidation candidates)
  2. Deep dream (7-day activity pattern, propose-mode proposals if config flips)
  3. Subscription audit (CLI auth health for all 4)
  4. Mode archival (runs >30d to cold storage — extends nightly's 30d threshold)
  5. Cross-source synthesis (kimi summarizes the week's blog summaries + podcast briefs)
  6. Weekly brief generator

Output: `_state/cleanup-logs/<date>-weekly.md` + `_state/weekly-briefs/<date>-week.md`
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
LOG_PATH = STATE_DIR / "cleanup-logs" / f"{DATE}-weekly.md"
WEEKLY_BRIEF_PATH = STATE_DIR / "weekly-briefs" / f"{DATE}-week.md"

KIMI_BIN = os.environ.get("KIMI_BIN", "kimi")


def oauth_env() -> dict:
    env = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env.pop(k, None)
    return env


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


# ─── Phase 1: Deep KG cleanup ──────────────────────────────────────

def deep_kg_cleanup() -> dict:
    """Stricter orphan scan + larger dupe-H1 grouping. Reuses brain_cleanup."""
    script = VAULT_ROOT / "scripts" / "python" / "brain_cleanup.py"
    if not script.exists():
        return {"summary": "brain_cleanup.py not found", "log": ""}
    result = subprocess.run(
        ["uv", "run", "--quiet", str(script)],
        capture_output=True, text=True, timeout=120, env=oauth_env(),
    )
    return {"summary": result.stdout.strip(), "rc": result.returncode}


# ─── Phase 2: Deep dream ────────────────────────────────────────────

def deep_dream() -> dict:
    """7-day window. Reuses dream_light with extended hours param via env override."""
    script = VAULT_ROOT / "scripts" / "python" / "dream_light.py"
    if not script.exists():
        return {"summary": "dream_light.py not found"}
    env = oauth_env()
    env["DREAM_HOURS"] = "168"  # 7 days
    result = subprocess.run(
        ["uv", "run", "--quiet", str(script)],
        capture_output=True, text=True, timeout=900, env=env,
    )
    return {"summary": result.stdout.strip()[:500], "rc": result.returncode}


# ─── Phase 3: Subscription audit ──────────────────────────────────

def subscription_audit() -> dict:
    """Check OAuth/login state for each CLI. Doesn't query usage (CLI APIs vary)."""
    results = {}
    env = oauth_env()
    # Claude — fall back to OAuth, ask one trivial question; success = login good
    for cli, probe in [
        ("claude", ["claude", "-p", "--permission-mode", "default", "Reply 'ok' literally."]),
        ("codex", ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                   "Reply 'ok' literally."]),
        ("gemini", ["gemini", "-p", "Reply 'ok' literally."]),
        ("kimi", ["kimi", "--quiet", "--no-thinking", "-p", "Reply 'ok' literally.",
                  "--max-steps-per-turn", "2"]),
    ]:
        if not shutil.which(cli):
            results[cli] = "not installed"
            continue
        try:
            r = subprocess.run(probe, capture_output=True, text=True,
                               timeout=120, env=env)
            if r.returncode == 0 and "ok" in r.stdout.lower():
                results[cli] = "✓ subscription auth OK"
            else:
                snippet = (r.stderr or r.stdout)[:200].strip().replace("\n", " ")
                results[cli] = f"✗ exit {r.returncode}: {snippet}"
        except subprocess.TimeoutExpired:
            results[cli] = "✗ timed out"
    return results


# ─── Phase 4: Mode archival (extended) ─────────────────────────────

def mode_archival(days: int = 60) -> dict:
    """Same idea as system-cleanup, but with longer threshold for the weekly pass."""
    runs_dir = VAULT_ROOT / "runs"
    archive_dir = runs_dir / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = 0
    if runs_dir.is_dir():
        cutoff = datetime.now().timestamp() - days * 86400
        for run in runs_dir.iterdir():
            if not run.is_dir() or run.name.startswith("_"):
                continue
            if run.stat().st_mtime < cutoff:
                month_dir = archive_dir / datetime.now().strftime("%Y-%m")
                month_dir.mkdir(parents=True, exist_ok=True)
                target = month_dir / run.name
                if not target.exists():
                    shutil.move(str(run), str(target))
                    archived += 1
    return {"archived_count": archived, "threshold_days": days}


# ─── Phase 5: Cross-source synthesis (week in AI) ─────────────────

def cross_source_synthesis(days: int = 7) -> str | None:
    """Concatenate the past week's blog summaries + podcast briefs and ask kimi
    for cross-source themes."""
    cutoff = datetime.now().timestamp() - days * 86400
    parts: list[str] = ["## Past-week briefs:"]
    for sub in ("blog-summaries", "podcast-briefs"):
        d = STATE_DIR / sub
        if not d.is_dir():
            continue
        files = sorted([f for f in d.glob("*.md")
                        if f.stat().st_mtime >= cutoff],
                       key=lambda f: f.stat().st_mtime, reverse=True)[:30]
        for f in files:
            try:
                content = f.read_text(errors="replace")[:2500]
            except OSError:
                continue
            parts.append(f"\n### {sub}/{f.name}\n{content}\n")
    if len(parts) <= 1:
        return None
    bundle = "\n".join(parts)[:50000]
    prompt = (
        "Synthesize the week-in-AI from these briefs (blogs + podcasts). Output:\n\n"
        "## Themes\n(3-5 bullets — recurring narratives across multiple sources)\n\n"
        "## What changed\n(2-4 bullets — concrete shifts: launches, prices, policy)\n\n"
        "## Worth re-reading\n(2-3 specific brief paths if any)\n\n"
        "Cite source filenames. Under 250 words. No preface.\n\n"
        f"{bundle}"
    )
    if not shutil.which(KIMI_BIN):
        return None
    try:
        r = subprocess.run(
            [KIMI_BIN, "--quiet", "--no-thinking", "-p", prompt,
             "--max-steps-per-turn", "5"],
            capture_output=True, text=True, timeout=300, env=oauth_env(),
        )
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    out = r.stdout.split("To resume this session:")[0].strip()
    return out or None


# ─── Phase 6: Weekly brief ────────────────────────────────────────

def render_weekly_brief(synthesis: str | None, sub_audit: dict, archived: int,
                        kg_summary: str, dream_summary: str) -> str:
    week_end = (datetime.now() + timedelta(days=(5 - datetime.now().weekday()) % 7)).strftime("%Y-%m-%d")
    lines = [f"# Weekly Brief — week ending {week_end}", ""]
    lines.append("## The Week in AI\n")
    lines.append(synthesis or "*(no briefs found this week)*")
    lines.append("")
    lines.append("## Subscription health\n")
    for cli, status in sub_audit.items():
        lines.append(f"- **{cli}**: {status}")
    lines.append("")
    lines.append("## Housekeeping")
    lines.append(f"- Mode archival: {archived} runs moved to cold storage")
    lines.append(f"- KG cleanup: {kg_summary.splitlines()[-1] if kg_summary else 'no run'}")
    lines.append(f"- Deep dream: see `_state/dream-logs/{DATE}.md`")
    lines.append("")
    lines.append("## Suggested next steps")
    lines.append("- Review pending dream proposals (if any)")
    lines.append("- Address any subscription auth failures above")
    lines.append("")
    lines.append("---")
    lines.append(f"*Generated by run_weekly.py at {datetime.now(timezone.utc).isoformat()}*")
    return "\n".join(lines) + "\n"


def render_log(phases: dict) -> str:
    lines = [f"# Weekly Deep Run — {DATE}", "",
             f"Run at: {datetime.now(timezone.utc).isoformat()}", ""]
    for phase, payload in phases.items():
        lines.append(f"## {phase}")
        if isinstance(payload, dict):
            for k, v in payload.items():
                lines.append(f"- {k}: {str(v)[:300]}")
        else:
            lines.append(str(payload)[:1000])
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    phases: dict = {}
    print("Phase 1/6: deep KG cleanup")
    phases["Deep KG Cleanup"] = deep_kg_cleanup()
    print("Phase 2/6: deep dream (7-day)")
    phases["Deep Dream"] = deep_dream()
    print("Phase 3/6: subscription audit")
    phases["Subscription Audit"] = subscription_audit()
    print("Phase 4/6: mode archival")
    phases["Mode Archival"] = mode_archival()
    print("Phase 5/6: cross-source synthesis")
    synth = cross_source_synthesis()
    phases["Cross-Source Synthesis"] = synth or "(no briefs to synthesize)"

    atomic_write(LOG_PATH, render_log(phases))

    print("Phase 6/6: weekly brief")
    brief = render_weekly_brief(
        synthesis=synth,
        sub_audit=phases["Subscription Audit"] if isinstance(phases["Subscription Audit"], dict) else {},
        archived=phases["Mode Archival"].get("archived_count", 0) if isinstance(phases["Mode Archival"], dict) else 0,
        kg_summary=phases["Deep KG Cleanup"].get("summary", "") if isinstance(phases["Deep KG Cleanup"], dict) else "",
        dream_summary=phases["Deep Dream"].get("summary", "") if isinstance(phases["Deep Dream"], dict) else "",
    )
    atomic_write(WEEKLY_BRIEF_PATH, brief)
    print(f"Weekly brief: {WEEKLY_BRIEF_PATH}")
    print(f"Log: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
