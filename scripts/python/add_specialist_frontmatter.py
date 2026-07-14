#!/usr/bin/env python3
"""Add/replace YAML frontmatter to specialist files with new v2.0 schema."""
from pathlib import Path
import os
import sys

REPO = Path(os.environ.get("VAULT_ROOT", str(Path.home() / "Obsidian-Claude-Vibe-Squad")))
SPECIALIST_DIRS = [
    REPO / "departments",
    REPO / "shared" / "specialists",
]

# Template YAML for new frontmatter
FRONTMATTER_TEMPLATE = """---
specialist: {specialist}
version: 2.0
department: {department}
lane: {lane}
model_key: {model_key}
required_tools: []
preferred_tools: []
safety_level: medium
requires_approval:
  - Write
  - Bash
  - WebFetch
tags: []
---
"""

def extract_old_frontmatter_and_body(text: str) -> tuple:
    """Extract old frontmatter block and rest of body.

    Returns (body_text).
    """
    if not text.strip().startswith("---"):
        return text

    lines = text.split("\n")
    if len(lines) < 2:
        return text

    # Look for closing ---
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:])

    return text

def has_new_frontmatter(text: str) -> bool:
    """Check if text has new-format frontmatter (with 'specialist:' and 'version: 2.0')."""
    if not text.strip().startswith("---"):
        return False

    # Get frontmatter block
    lines = text.split("\n")
    fm_block = ""
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm_block = "\n".join(lines[1:i])
            break

    # Check for new format markers
    return "specialist:" in fm_block and "version: 2.0" in fm_block

def infer_department(path: Path) -> str:
    """Extract department name from path."""
    parts = path.parts
    for i, p in enumerate(parts):
        if p == "departments" and i + 1 < len(parts):
            return parts[i + 1]
    return "shared"

def infer_lane(specialist_name: str) -> str:
    """Best-effort heuristics for lane routing based on specialist name."""
    name = specialist_name.lower()
    if any(t in name for t in ["security", "architect", "reviewer", "triage", "planner", "skeptic", "privacy", "threat", "impact", "memory", "knowledge", "personal"]):
        return "claude"
    if any(t in name for t in ["backend", "frontend", "exploit", "debugger", "refactorer", "engineer", "devops", "systems", "scraping", "contract", "product", "performance", "test", "ui", "ai-"]):
        return "codex"
    if any(t in name for t in ["research", "synthesizer", "large-context", "data-extraction", "finance", "learning", "scout"]):
        return "kimi"
    if any(t in name for t in ["design", "copy", "content", "media", "brand", "editor", "social", "writer"]):
        return "gemini"
    return "claude"

def process(path: Path, dry_run: bool = False) -> bool:
    """Replace/add frontmatter with new v2.0 schema if not already done.

    Returns True if file was modified (or would be in dry-run).
    """
    text = path.read_text()

    # Skip if already has new frontmatter
    if has_new_frontmatter(text):
        return False

    # Extract body (remove old frontmatter if present)
    body = extract_old_frontmatter_and_body(text)

    name = path.stem
    frontmatter = FRONTMATTER_TEMPLATE.format(
        specialist=name,
        department=infer_department(path),
        lane=infer_lane(name),
        model_key="default"
    )
    new_text = frontmatter + body

    if not dry_run:
        path.write_text(new_text)

    return True

def main() -> int:
    dry_run = "--dry-run" in sys.argv
    count = 0

    # Process departments/*/specialists/*.md only
    departments_dir = REPO / "departments"
    if departments_dir.exists():
        for dept_dir in departments_dir.iterdir():
            if not dept_dir.is_dir():
                continue
            specialists_dir = dept_dir / "specialists"
            if specialists_dir.exists():
                for md in specialists_dir.glob("*.md"):
                    # Skip special files
                    if md.name in ["README.md", "INDEX.md", "SPECIALIST-INDEX.md"]:
                        continue
                    if process(md, dry_run):
                        count += 1
                        print(f"{'DRY' if dry_run else 'ADD'} {md.relative_to(REPO)}")

    # Process shared/specialists/*.md only
    shared_specialists_dir = REPO / "shared" / "specialists"
    if shared_specialists_dir.exists():
        for md in shared_specialists_dir.glob("*.md"):
            # Skip special files
            if md.name in ["README.md", "INDEX.md", "SPECIALIST-INDEX.md"]:
                continue
            if process(md, dry_run):
                count += 1
                print(f"{'DRY' if dry_run else 'ADD'} {md.relative_to(REPO)}")

    print(f"\nProcessed: {count} files")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
