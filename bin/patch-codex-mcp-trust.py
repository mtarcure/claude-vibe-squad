#!/usr/bin/env python3
"""
Idempotent patcher: adds default_tools_approval_mode = "approve"
to every [mcp_servers.chrono-*] section in ~/.codex/config.toml.

Safe to run multiple times — no-ops if trust is already present.
Writes atomically via temp+rename so a crash never corrupts the config.
"""
import os
import sys
import tempfile

TRUST_LINE = 'default_tools_approval_mode = "approve"'
CONFIG_PATH = os.path.expanduser("~/.codex/config.toml")


def patch(content: str) -> tuple[str, int]:
    """Return patched content and count of sections modified."""
    lines = content.splitlines(keepends=True)
    out = []
    changes = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)

        stripped = line.strip()
        # Detect [mcp_servers.chrono-*] section headers
        if (
            stripped.startswith("[mcp_servers.chrono-")
            and stripped.endswith("]")
            and "." not in stripped[len("[mcp_servers.chrono-"):-1]
            # guard: not a sub-table like [mcp_servers.chrono-vault.env]
        ):
            # Collect the rest of this section (until next header or EOF)
            section_lines = []
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("["):
                section_lines.append(lines[j])
                j += 1

            # Check if trust line already present in this section
            already_present = any(
                TRUST_LINE in sl or "default_tools_approval_mode" in sl
                for sl in section_lines
            )

            if not already_present:
                out.append(TRUST_LINE + "\n")
                changes += 1

            out.extend(section_lines)
            i = j
            continue

        i += 1

    return "".join(out), changes


def main() -> None:
    if not os.path.exists(CONFIG_PATH):
        print(f"[codex-mcp-trust] config not found at {CONFIG_PATH} — skipping")
        sys.exit(0)

    with open(CONFIG_PATH, "r") as f:
        original = f.read()

    patched, changes = patch(original)

    if changes == 0:
        print("[codex-mcp-trust] all chrono MCP servers already pre-trusted — no changes needed")
        sys.exit(0)

    # Atomic write via temp + rename
    config_dir = os.path.dirname(CONFIG_PATH)
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, prefix=".config.toml.tmp.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(patched)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        os.unlink(tmp_path)
        raise

    print(f"[codex-mcp-trust] patched {changes} chrono MCP server section(s) — trust pre-approved")


if __name__ == "__main__":
    main()
