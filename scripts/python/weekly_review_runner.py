#!/usr/bin/env python3
"""Generate weekly review markdown from handoffs + tool-use manifests."""
import asyncio
import datetime
import os
import httpx
from pathlib import Path

REPO = Path("/Users/user/Obsidian-Claude-Vibe-Squad")


async def collect_handoffs(week_start: datetime.date) -> str:
    """Collect all handoff files from this week."""
    handoffs = REPO / "docs" / "handoffs"
    collected = []
    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        f = handoffs / f"{d.isoformat()}.md"
        if f.exists():
            collected.append(f.read_text())
    return "\n\n---\n\n".join(collected)


async def collect_manifests(week_start: datetime.date) -> str:
    """Collect all manifest files from this week."""
    outbox = REPO / "daemon" / "state" / "outbox"
    if not outbox.exists():
        return ""
    manifests = []
    for lane_dir in outbox.iterdir():
        if lane_dir.is_dir():
            for m in lane_dir.glob("*.md"):
                mtime = datetime.datetime.fromtimestamp(m.stat().st_mtime).date()
                if mtime >= week_start:
                    manifests.append(m.read_text())
    return "\n\n---\n\n".join(manifests)


async def main():
    """Main entry point: collect week's data, call /summarize, write review."""
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    year, week, _ = today.isocalendar()

    handoffs = await collect_handoffs(week_start)
    manifests = await collect_manifests(week_start)

    combined = f"# Handoffs this week\n\n{handoffs}\n\n# Tool manifests this week\n\n{manifests}"
    instructions = (
        "Generate a weekly review markdown document with these sections:\n"
        "- Surprising moments\n"
        "- Underused required tools\n"
        "- Overused preferred tools (candidates for required)\n"
        "- Specialist patches accumulated this week\n"
        "- Handoff patterns worth codifying\n"
        "- Projects touched this week\n"
    )

    # Get auth token from environment
    token = os.environ.get("VIBESQUAD_DAEMON_TOKEN")
    if not token:
        raise RuntimeError("VIBESQUAD_DAEMON_TOKEN not set")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://127.0.0.1:9876/summarize",
            json={"text": combined, "instructions": instructions},
            headers={"Authorization": f"Bearer {token}"},
            timeout=120.0,
        )
        resp.raise_for_status()
        summary = resp.json()["summary"]

    out_dir = REPO / "docs" / "reviews" / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{year}-W{week:02d}.md"
    out.write_text(f"# Week {year}-W{week:02d}\n\n{summary}\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
