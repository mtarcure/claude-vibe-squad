#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.28",
# ]
# ///
"""Browser keep-alive — verify operator's persistent Chrome (CDP-attached)
has live tabs for the 5 bounty platforms.

Per chrono memory: operator keeps Chrome open with 2FA'd sessions and tools
attach via CDP — never fresh-launch. This script just *checks* state; if a
session has expired or a tab has been closed, surface in morning brief so the
operator can re-open it manually.

Default debug port: 9222 (Chrome's standard `--remote-debugging-port=9222`).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
LOG_PATH = VAULT_ROOT / "_state" / "cleanup-logs" / f"{DATE}-browser.md"
SUMMARY_PATH = VAULT_ROOT / "_state" / "cleanup-logs" / f"{DATE}-browser-summary.json"

CDP_URL = os.environ.get("CHROME_CDP_URL", "http://127.0.0.1:9222")

PLATFORMS = [
    ("hackerone.com", "HackerOne"),
    ("bugcrowd.com", "Bugcrowd"),
    ("intigriti.com", "Intigriti"),
    ("hackenproof.com", "HackenProof"),
    ("code4rena.com", "Code4rena"),
]


SESSION_EXPIRED_MARKERS = (
    "/login", "/signin", "/sign-in", "/sign_in", "/auth/", "/oauth", "/authorize",
    "/sso/", "/saml", "?signin", "?login",
)


@dataclass
class TabState:
    platform: str
    found: bool
    url: str = ""
    title: str = ""
    expired: bool = False
    note: str = ""


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


def fetch_cdp(path: str, timeout: float = 5.0) -> dict | list | None:
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{CDP_URL}{path}")
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return None


def render_log(states: list[TabState], browser_version: str | None,
               total_tabs: int, error: str | None) -> str:
    lines = [f"# Browser Keep-Alive — {DATE}", "",
             f"Run at: {datetime.now(timezone.utc).isoformat()}", ""]
    if error:
        lines.append("## Status")
        lines.append(f"✗ **{error}**")
        lines.append("")
        lines.append("To use bounty platforms with attached tools, ensure Chrome is")
        lines.append(f"running with `--remote-debugging-port=9222` and reachable at `{CDP_URL}`.")
        return "\n".join(lines) + "\n"

    lines.append(f"**Browser:** {browser_version or 'unknown'}")
    lines.append(f"**Open tabs:** {total_tabs}")
    lines.append("")
    lines.append("## Bounty platform sessions")
    for s in states:
        if not s.found:
            marker = "○"
        elif s.expired:
            marker = "⚠️"
        else:
            marker = "✓"
        if s.found:
            status = " *(session expired — at sign-in URL)*" if s.expired else ""
            lines.append(f"- {marker} **{s.platform}**{status}")
            lines.append(f"    - url: `{s.url[:100]}`")
            if s.title:
                lines.append(f"    - title: {s.title[:80]}")
        else:
            lines.append(f"- {marker} **{s.platform}** — no tab open")
    lines.append("")
    missing = [s.platform for s in states if not s.found]
    expired = [s.platform for s in states if s.found and s.expired]
    if missing or expired:
        lines.append("## Action items")
        lines.append("")
        if expired:
            lines.append("Operator should re-authenticate (browser is at sign-in screen):")
            for p in expired:
                lines.append(f"- {p}")
        if missing:
            lines.append("")
            lines.append("These platforms have no open tab — operator may want to re-open + 2FA:")
            for p in missing:
                lines.append(f"- {p}")
    return "\n".join(lines) + "\n"


def main() -> int:
    version = fetch_cdp("/json/version")
    if not version:
        atomic_write(LOG_PATH, render_log([], None, 0,
            f"Chrome not reachable at {CDP_URL} — debug port 9222 not listening"))
        atomic_write(SUMMARY_PATH, json.dumps({"reachable": False, "platforms_open": 0}))
        print(f"Browser keep-alive: Chrome not reachable at {CDP_URL}")
        return 1

    tabs = fetch_cdp("/json") or []
    if not isinstance(tabs, list):
        tabs = []

    states: list[TabState] = []
    for domain, label in PLATFORMS:
        match = next(
            (t for t in tabs if isinstance(t, dict) and domain in (t.get("url") or "")),
            None,
        )
        if match:
            url = match.get("url", "")
            url_lower = url.lower()
            expired = any(marker in url_lower for marker in SESSION_EXPIRED_MARKERS)
            title = match.get("title", "")
            if any(s in title.lower() for s in ("sign in", "log in", "login")):
                expired = True
            states.append(TabState(
                platform=label, found=True, url=url, title=title, expired=expired,
            ))
        else:
            states.append(TabState(platform=label, found=False))

    browser_version = (version.get("Browser") if isinstance(version, dict) else "unknown")
    total = len([t for t in tabs if isinstance(t, dict) and t.get("type") == "page"])

    atomic_write(LOG_PATH, render_log(states, browser_version, total, None))
    atomic_write(SUMMARY_PATH, json.dumps({
        "reachable": True,
        "browser_version": browser_version,
        "total_tabs": total,
        "platforms_open": sum(1 for s in states if s.found),
        "platforms_missing": [s.platform for s in states if not s.found],
        "platforms_expired": [s.platform for s in states if s.found and s.expired],
    }))
    print(f"Browser keep-alive log: {LOG_PATH}")
    print(f"Open: {sum(1 for s in states if s.found)}/{len(states)} platforms; "
          f"{total} total tabs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
