#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Brain-cleanup — light KG sweep.

Per chrono memory rule: "purge invalidated knowledge in place — REMOVE, don't
add a contradicting line." This script *proposes* removals; operator approves.

Light pass (nightly):
  1. Orphan notes — markdown files with no inbound `[[wiki-links]]` or `[label](path.md)` references
  2. Broken vault links — `[label](path.md)` where the path doesn't exist
  3. Duplicate H1 headings across vault (potential merge candidates)
  4. Empty notes — files with <50 chars of non-frontmatter content

Output: `_state/cleanup-logs/<date>-brain.md` with proposals (no auto-deletion).
Memory-curator (or operator) acts on proposals separately.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
LOG_PATH = VAULT_ROOT / "_state" / "cleanup-logs" / f"{DATE}-brain.md"

# Skip these — not part of the KG content surface
SKIP_DIRS = {"_state", ".git", "runs", "node_modules", ".obsidian",
             "archive",   # archived mailbox messages — intentionally terminal
             "inbox",     # transient mailbox state
             "outbox",    # transient mailbox state
             "active"}    # transient mailbox state

WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)]+)\)")


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


def discover_md_files() -> list[Path]:
    files = []
    for path in VAULT_ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.relative_to(VAULT_ROOT).parts):
            continue
        files.append(path)
    return files


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[end + 4:].lstrip()
    return text


def extract_h1(text: str) -> str | None:
    body = strip_frontmatter(text)
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return None


def find_orphans(files: list[Path]) -> list[Path]:
    """A file is an orphan if no other file links to it."""
    by_stem = {f.stem: f for f in files}
    by_relpath = {str(f.relative_to(VAULT_ROOT)): f for f in files}
    by_basename = {f.name: f for f in files}

    referenced: set[Path] = set()
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for match in WIKI_LINK_RE.finditer(text):
            target = match.group(1).strip()
            if target in by_stem:
                referenced.add(by_stem[target])
            elif target + ".md" in by_basename:
                referenced.add(by_basename[target + ".md"])
        for match in MD_LINK_RE.finditer(text):
            href = match.group("href").split("#")[0].split(" ")[0]
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            # Resolve relative to the file's directory
            target_path = (f.parent / href).resolve()
            try:
                rel = target_path.relative_to(VAULT_ROOT)
            except ValueError:
                continue
            if str(rel) in by_relpath:
                referenced.add(by_relpath[str(rel)])

    # Files referenced by name (not wiki-link) are NOT orphans:
    # - Top-level docs
    # - Model-lane identity files (CLI auto-loads them by filename)
    # - Modes, mode-profiles, specialists (dispatched by name from routing tables)
    entry_points: set[Path] = {
        VAULT_ROOT / "README.md",
        VAULT_ROOT / "CLAUDE.md",
        VAULT_ROOT / "chrono" / "SOUL.md",
        VAULT_ROOT / "chrono" / "CLAUDE.md",
        VAULT_ROOT / "chrono" / "current.md",
        VAULT_ROOT / "shared" / "protocol.md",
        VAULT_ROOT / "shared" / "routing.md",
    }
    # Per-namespace state files
    for d in (VAULT_ROOT / "departments").iterdir() if (VAULT_ROOT / "departments").is_dir() else []:
        for name in ("LEAD.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "current.md", "memory.md"):
            entry_points.add(d / name)
        # All specialists in this namespace's specialists/ dir
        for spec in (d / "specialists").glob("*.md") if (d / "specialists").is_dir() else []:
            entry_points.add(spec)
    # All shared modes, mode-profiles, specialists, mailbox templates
    for sub in ("modes", "mode-profiles", "specialists", "mailbox"):
        sub_dir = VAULT_ROOT / "shared" / sub
        if sub_dir.is_dir():
            for f in sub_dir.rglob("*.md"):
                entry_points.add(f)

    orphans = [f for f in files if f not in referenced and f not in entry_points]
    return orphans


def find_broken_links(files: list[Path]) -> list[tuple[Path, str]]:
    """Return list of (file, broken-target) pairs."""
    broken: list[tuple[Path, str]] = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for match in MD_LINK_RE.finditer(text):
            href = match.group("href").split("#")[0].split(" ")[0]
            if not href or href.startswith(("http://", "https://", "mailto:", "tel:", "#")):
                continue
            if href.startswith("/"):
                # Treat as absolute path inside vault
                target = VAULT_ROOT / href.lstrip("/")
            else:
                target = (f.parent / href).resolve()
            if not target.exists():
                # If symlink points at non-existing target, also broken
                broken.append((f, href))
    return broken


def find_duplicate_h1(files: list[Path]) -> dict[str, list[Path]]:
    by_h1: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        h1 = extract_h1(text)
        if h1:
            by_h1[h1.lower()].append(f)
    return {h1: paths for h1, paths in by_h1.items() if len(paths) > 1}


def find_empty_notes(files: list[Path], min_chars: int = 50) -> list[Path]:
    empty: list[Path] = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        body = strip_frontmatter(text)
        # Count non-whitespace, non-heading-marker chars
        meaningful = re.sub(r"[\s#*\-]+", "", body)
        if len(meaningful) < min_chars:
            empty.append(f)
    return empty


def render_report(orphans: list[Path], broken: list[tuple[Path, str]],
                  dupes: dict[str, list[Path]], empties: list[Path],
                  total_files: int) -> str:
    def rel(p: Path) -> str:
        return str(p.relative_to(VAULT_ROOT))

    lines = [f"# Brain Cleanup — {DATE}", "",
             f"Run at: {datetime.now(timezone.utc).isoformat()}",
             f"Files scanned: {total_files}",
             ""]

    lines.append("## Summary")
    lines.append(f"- Orphan notes: {len(orphans)}")
    lines.append(f"- Broken links: {len(broken)}")
    lines.append(f"- Duplicate H1 sets: {len(dupes)}")
    lines.append(f"- Empty notes: {len(empties)}")
    lines.append("")

    if orphans:
        lines.append("## Orphan notes (no inbound links)")
        lines.append("")
        lines.append("These are candidates for removal. Operator decides — *do not auto-delete*.")
        lines.append("")
        for p in orphans[:50]:
            lines.append(f"- `{rel(p)}`")
        if len(orphans) > 50:
            lines.append(f"- *(+{len(orphans) - 50} more)*")
        lines.append("")

    if broken:
        lines.append("## Broken links")
        lines.append("")
        for p, target in broken[:50]:
            lines.append(f"- `{rel(p)}` → `{target}`")
        if len(broken) > 50:
            lines.append(f"- *(+{len(broken) - 50} more)*")
        lines.append("")

    if dupes:
        lines.append("## Duplicate H1 headings (merge candidates)")
        lines.append("")
        for h1, paths in dupes.items():
            lines.append(f"- **{h1}**:")
            for p in paths:
                lines.append(f"    - `{rel(p)}`")
        lines.append("")

    if empties:
        lines.append("## Empty / stub notes")
        lines.append("")
        for p in empties[:30]:
            lines.append(f"- `{rel(p)}`")
        if len(empties) > 30:
            lines.append(f"- *(+{len(empties) - 30} more)*")
        lines.append("")

    if not (orphans or broken or dupes or empties):
        lines.append("✓ No issues found this pass.")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    files = discover_md_files()
    orphans = find_orphans(files)
    broken = find_broken_links(files)
    dupes = find_duplicate_h1(files)
    empties = find_empty_notes(files)
    report = render_report(orphans, broken, dupes, empties, len(files))
    atomic_write(LOG_PATH, report)
    print(f"Brain cleanup log: {LOG_PATH}")
    print(f"Files scanned: {len(files)}")
    print(f"Orphans: {len(orphans)}, broken: {len(broken)}, dupes: {len(dupes)}, empties: {len(empties)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
