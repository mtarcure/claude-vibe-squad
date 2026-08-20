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
  2. CLI authentication audit
  3. Mode archival census (report-only age observations; no moves)
  4. Weekly brief generator

A cross-source synthesis phase sat between 3 and 4 until 2026-08-17. It read
`_state/blog-summaries` and `_state/podcast-briefs`, whose producer -- the feed
and content pipeline -- was deleted 2026-08-16. Neither directory exists, so the
phase collected nothing, returned None every week, and printed
"(no briefs to synthesize)" into the log.

Output: `_state/cleanup-logs/<date>-weekly.md` + `_state/weekly-briefs/<date>-week.md`
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from repo_root import resolve_vault_root

VAULT_ROOT = resolve_vault_root()
STATE_DIR = VAULT_ROOT / "_state"
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
LOG_PATH = STATE_DIR / "cleanup-logs" / f"{DATE}-weekly.md"
WEEKLY_BRIEF_PATH = STATE_DIR / "weekly-briefs" / f"{DATE}-week.md"


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


# ─── Phase 2: CLI authentication audit ────────────────────────────

def subscription_audit() -> dict:
    """Check configured authentication for each CLI without querying usage."""
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
                auth_class = "gemini-api-key" if cli == "gemini" else "subscription"
                results[cli] = f"✓ {auth_class} auth OK"
            else:
                snippet = (r.stderr or r.stdout)[:200].strip().replace("\n", " ")
                results[cli] = f"✗ exit {r.returncode}: {snippet}"
        except subprocess.TimeoutExpired:
            results[cli] = "✗ timed out"
    return results


# ─── Phase 3: Mode archival (extended) ─────────────────────────────

def mode_archival(
    days: int = 60,
    *,
    runs_dir: Path | None = None,
    now: datetime | None = None,
    sample_limit: int = 20,
) -> dict:
    """Count old-looking runs and retain only a bounded diagnostic sample."""
    observed_at = now or datetime.now(timezone.utc)
    observed_runs_dir = runs_dir or VAULT_ROOT / "runs"
    cutoff = observed_at.timestamp() - days * 86400
    effective_limit = min(20, max(0, sample_limit))
    candidate_count = 0
    samples: list[dict[str, object]] = []
    scan_complete = True
    if observed_runs_dir.is_dir():
        try:
            runs = sorted(observed_runs_dir.iterdir())
        except OSError:
            runs, scan_complete = [], False
        for run in runs:
            try:
                is_directory = run.is_dir()
                modified_at = run.stat().st_mtime
            except OSError:
                scan_complete = False
                continue
            if not is_directory or run.name.startswith("_"):
                continue
            if modified_at < cutoff:
                candidate_count += 1
                if len(samples) < effective_limit:
                    samples.append(
                        {
                            "path": str(run),
                            "observed_age_days": int(
                                (observed_at.timestamp() - modified_at) // 86400
                            ),
                            "storage_class": "unknown",
                            "effective_storage_class": "DURABLE",
                            "cleanup_eligible": False,
                        }
                    )
    return {
        "mode": "report-only",
        "scan_complete": scan_complete,
        "candidate_count": candidate_count,
        "candidates": samples,
        "sample_limit": effective_limit,
        "omitted_candidate_count": candidate_count - len(samples),
        "archived_count": 0,
        "threshold_days": days,
        "age_basis": "mtime observation only; non-authoritative",
        "storage_class": "unknown",
        "effective_storage_class": "DURABLE",
        "cleanup_eligible": False,
    }


# ─── Phase 4: Weekly brief ────────────────────────────────────────

def render_weekly_brief(
    sub_audit: dict,
    archived: int,
    kg_summary: str,
    *,
    archival_candidates: int = 0,
) -> str:
    week_end = (datetime.now() + timedelta(days=(5 - datetime.now().weekday()) % 7)).strftime("%Y-%m-%d")
    lines = [f"# Weekly Brief — week ending {week_end}", ""]
    lines.append("## Authentication health\n")
    for cli, status in sub_audit.items():
        lines.append(f"- **{cli}**: {status}")
    lines.append("")
    lines.append("## Housekeeping")
    lines.append(
        "- Mode archival: report-only; "
        f"{archival_candidates} age-observed candidates, {archived} runs moved"
    )
    lines.append(f"- KG cleanup: {kg_summary.splitlines()[-1] if kg_summary else 'no run'}")
    lines.append("")
    lines.append("## Suggested next steps")
    lines.append("- Review pending dream proposals (if any)")
    lines.append("- Address any authentication failures above")
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
    print("Phase 1/4: deep KG cleanup")
    phases["Deep KG Cleanup"] = deep_kg_cleanup()
    print("Phase 2/4: subscription audit")
    phases["Subscription Audit"] = subscription_audit()
    print("Phase 3/4: mode archival")
    phases["Mode Archival"] = mode_archival()

    atomic_write(LOG_PATH, render_log(phases))

    print("Phase 4/4: weekly brief")
    brief = render_weekly_brief(
        sub_audit=phases["Subscription Audit"] if isinstance(phases["Subscription Audit"], dict) else {},
        archived=phases["Mode Archival"].get("archived_count", 0) if isinstance(phases["Mode Archival"], dict) else 0,
        kg_summary=phases["Deep KG Cleanup"].get("summary", "") if isinstance(phases["Deep KG Cleanup"], dict) else "",
        archival_candidates=phases["Mode Archival"].get("candidate_count", 0) if isinstance(phases["Mode Archival"], dict) else 0,
    )
    atomic_write(WEEKLY_BRIEF_PATH, brief)
    print(f"Weekly brief: {WEEKLY_BRIEF_PATH}")
    print(f"Log: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
