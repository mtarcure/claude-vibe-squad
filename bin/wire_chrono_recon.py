#!/usr/bin/env python3
"""Wire chrono-recon into the claude lane as a plugin (durable, idempotent).

Root cause (see TASK-2026-07-12-1458-737956e7): the claude CLI surfaces MCP
servers from the plugin system, NOT from `~/.claude/settings.json -> mcpServers`.
So chrono-recon only loads once it is (a) advertised by the chrono marketplace and
(b) enabled in settings. This script performs both edits atomically, plus removes
the now-vestigial `mcpServers.chrono-recon` key that caused the ignored-config trap.

Discipline: mode-preserving timestamped backups, atomic temp+fsync+os.replace,
idempotent (safe to re-run), touches ONLY chrono-recon keys. Does not edit any
other lane's config. Prints a unified diff of each file it changes.

Usage: python3 bin/wire_chrono_recon.py
"""
import datetime
import difflib
import json
import os
import shutil
import sys
import tempfile

MARKETPLACE = "/Users/user/chrono/.claude-plugin/marketplace.json"
SETTINGS = os.path.expanduser("~/.claude/settings.json")

RECON_PLUGIN = {
    "name": "chrono-recon",
    "description": "OSINT recon tools for Vibe Squad specialists (dns, whois, "
                   "crt.sh, wayback, github leaked-secrets). Owner roles: scout, "
                   "security-analyst, exploit-developer.",
    "category": "recon",
    "source": "./plugins/chrono-recon",
    "homepage": "https://github.com/mtarcure/chrono",
}


def dump(data):
    # Match existing files: 2-space indent, non-ASCII preserved (em-dashes),
    # single trailing newline.
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def backup(path):
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    bak = f"{path}.bak.{ts}"
    shutil.copy2(path, bak)  # preserves mode + timestamps
    return bak


def atomic_write(path, text):
    mode = os.stat(path).st_mode
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode & 0o7777)
        os.replace(tmp, path)  # atomic within the same filesystem
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def show_diff(path, before, after):
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"{path} (before)",
        tofile=f"{path} (after)",
    )
    out = "".join(diff)
    print(out if out else f"  (no change needed: {path})")


def edit_marketplace():
    with open(MARKETPLACE, encoding="utf-8") as f:
        before = f.read()
    data = json.loads(before)
    names = [p.get("name") for p in data.get("plugins", [])]
    if "chrono-recon" in names:
        print(f"[marketplace] chrono-recon already present -> no change")
        return False
    data["plugins"].append(RECON_PLUGIN)
    after = dump(data)
    bak = backup(MARKETPLACE)
    atomic_write(MARKETPLACE, after)
    print(f"[marketplace] backup: {bak}")
    show_diff(MARKETPLACE, before, after)
    return True


def edit_settings():
    with open(SETTINGS, encoding="utf-8") as f:
        before = f.read()
    data = json.loads(before)
    changed = False
    ep = data.setdefault("enabledPlugins", {})
    if ep.get("chrono-recon@chrono") is not True:
        ep["chrono-recon@chrono"] = True
        changed = True
    if "chrono-recon" in data.get("mcpServers", {}):
        del data["mcpServers"]["chrono-recon"]  # sanctioned vestigial-key removal
        changed = True
    if not changed:
        print(f"[settings] already wired -> no change")
        return False
    after = dump(data)
    bak = backup(SETTINGS)
    atomic_write(SETTINGS, after)
    print(f"[settings] backup: {bak}")
    show_diff(SETTINGS, before, after)
    return True


def main():
    for path in (MARKETPLACE, SETTINGS):
        if not os.path.exists(path):
            print(f"FATAL: missing {path}", file=sys.stderr)
            sys.exit(1)
    print("=== marketplace.json ===")
    edit_marketplace()
    print("\n=== settings.json ===")
    edit_settings()
    print("\nDone. Verify with: claude mcp list | grep chrono-recon")


if __name__ == "__main__":
    main()
