#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Cluster depth-tier content briefs for the morning brief."""

from __future__ import annotations

import json
import os
import argparse
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
STATE_DIR = VAULT_ROOT / "_state"
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

TRIAGE_PATH = STATE_DIR / f"content-triage-{DATE}.json"
OUTPUT_PATH = STATE_DIR / f"content-synthesis-{DATE}.md"
LOG_PATH = STATE_DIR / "cleanup-logs" / f"{DATE}-content-synthesis.md"
KIMI_BIN = os.environ.get("KIMI_BIN", "kimi")


def current_time_section() -> str:
    now_utc = datetime.now(timezone.utc)
    local = now_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"=== CURRENT TIME ===\nUTC: {now_utc.isoformat()}\nLocal (PDT/PST): {local.isoformat()}"


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


def oauth_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env.pop(key, None)
    return env


def slugify(text: str, max_len: int = 60) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text.lower())
    out = "-".join(filter(None, out.split("-")))
    return out[:max_len].rstrip("-") or "untitled"


def expected_brief_path(item: dict) -> Path:
    meta = item.get("feed_metadata", {})
    feed = item.get("source_name", "")
    title = meta.get("title", "")
    feed_type = meta.get("feed_type", "")
    out_dir = "podcast-briefs" if feed_type == "podcast" else "blog-summaries"
    filename = f"{DATE}-{feed[:20].strip().replace(' ', '-')}-{slugify(title)}.md"
    return STATE_DIR / out_dir / filename


def load_depth_context(triage: dict) -> str:
    chunks: list[str] = []
    for item in triage.get("items", []):
        if item.get("tier") != "depth":
            continue
        path = expected_brief_path(item)
        body = ""
        if path.exists():
            body = path.read_text(errors="replace")[:5000]
        meta = item.get("feed_metadata", {})
        chunks.append(
            f"## item: {item.get('source_name')} / {item.get('source_lane')}\n"
            f"title: {meta.get('title')}\n"
            f"url: {meta.get('url')}\n"
            f"score: {item.get('relevance_score')}\n"
            f"reason: {item.get('reason')}\n"
            f"brief_path: {path.relative_to(VAULT_ROOT) if path.exists() else '(missing)'}\n"
            f"brief:\n{body}\n"
        )
    return "\n\n".join(chunks)


def fallback_synthesis(triage: dict, reason: str) -> str:
    lines = [
        f"# Content Synthesis — {DATE}",
        "",
        f"*Synthesis LLM skipped: {reason}*",
        "",
        "## Clusters",
    ]
    depth = [i for i in triage.get("items", []) if i.get("tier") == "depth"]
    if not depth:
        lines.append("- No depth-tier items were available.")
    else:
        by_angle: dict[str, list[dict]] = {}
        for item in depth:
            by_angle.setdefault(item.get("operator_angle", "wildcard"), []).append(item)
        for angle, items in by_angle.items():
            titles = "; ".join(i.get("feed_metadata", {}).get("title", "(untitled)") for i in items[:3])
            lines.append(f"- **{angle}**: {len(items)} item(s): {titles}")
    lines += ["", "## Contradictions", "- none observed", "", "## Action Cards", "- none"]
    return "\n".join(lines) + "\n"


def call_kimi(context: str) -> tuple[str | None, str]:
    prompt = (
        "Cluster these depth-tier content briefs for a morning brief. Output markdown with exactly:\n"
        f"{current_time_section()}\n\n"
        "## Clusters\n- 2-5 bullets, grouping related items.\n\n"
        "## Contradictions\n- contradictions or deltas vs prior assumptions; write none observed if absent.\n\n"
        "## Action Cards\n- 1-3 operator decisions in the form: **title** — action and rationale. Use none if no action is warranted.\n\n"
        "Keep under 500 words. Cite brief paths when present.\n\n"
        f"{context}"
    )
    start = time.monotonic()
    try:
        result = subprocess.run(
            [KIMI_BIN, "--quiet", "--no-thinking", "--max-steps-per-turn", "5", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=240,
            env=oauth_env(),
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    duration = time.monotonic() - start
    log = (
        f"# Content Synthesis subprocess\n\n"
        f"- command: `{KIMI_BIN} --quiet --no-thinking -p <prompt>`\n"
        f"- returncode: {result.returncode}\n"
        f"- stdout_len: {len(result.stdout or '')}\n"
        f"- duration_s: {duration:.1f}\n"
        f"- current_time:\n\n```\n{current_time_section()}\n```\n"
        f"- stderr:\n\n```\n{(result.stderr or '')[:1200]}\n```\n"
    )
    atomic_write(LOG_PATH, log)
    if result.returncode != 0:
        return None, f"returncode {result.returncode}"
    out = (result.stdout or "").split("To resume this session:")[0].strip()
    return (out or None), "empty stdout" if not out else "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster depth-tier content briefs for the morning brief.")
    parser.parse_args()
    if not TRIAGE_PATH.exists():
        atomic_write(OUTPUT_PATH, fallback_synthesis({"items": []}, "triage manifest missing"))
        print(f"Content synthesis: {OUTPUT_PATH}")
        return 0
    triage = json.loads(TRIAGE_PATH.read_text())
    scorer = triage.get("scorer", {})
    if scorer.get("llm_status") not in ("ok", "skipped-no-candidates"):
        atomic_write(OUTPUT_PATH, fallback_synthesis(triage, f"triage degraded ({scorer.get('llm_status')})"))
        print(f"Content synthesis: {OUTPUT_PATH}")
        return 0
    context = load_depth_context(triage)
    if not context.strip():
        atomic_write(OUTPUT_PATH, fallback_synthesis(triage, "no depth context"))
        print(f"Content synthesis: {OUTPUT_PATH}")
        return 0
    if not shutil.which(KIMI_BIN):
        atomic_write(OUTPUT_PATH, fallback_synthesis(triage, f"kimi not found: {KIMI_BIN}"))
        print(f"Content synthesis: {OUTPUT_PATH}")
        return 0
    out, status = call_kimi(context)
    if not out:
        atomic_write(OUTPUT_PATH, fallback_synthesis(triage, status))
    else:
        atomic_write(OUTPUT_PATH, f"# Content Synthesis — {DATE}\n\n{out}\n")
    print(f"Content synthesis: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
