#!/usr/bin/env bash
# Persistent interactive claude session with Remote Control enabled.
# Mobile users attach to this session via the Claude mobile app.
# Shares conversation state with Ink's batch-mode Chrono via -c and shared cwd.
set -euo pipefail

REPO="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
cd "$REPO"

# Unset API-key env vars so claude uses OAuth/subscription auth (Max plan).
unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY

# Load the Chrono system prompt if present.
SYSTEM_PROMPT=""
if [[ -f "$REPO/shared/CHRONO-SOUL.md" ]]; then
    SYSTEM_PROMPT=$(cat "$REPO/shared/CHRONO-SOUL.md")
fi

# Start a persistent interactive session named "chrono" with Remote Control.
# -c: continue previous conversation (shares with Ink's batch Chrono)
# --remote-control chrono: registers session for mobile Claude app attach
# --append-system-prompt: adds Chrono's persona on top of default system prompt
if [[ -n "$SYSTEM_PROMPT" ]]; then
    exec "${HOME}/.local/bin/claude" \
        -c \
        --remote-control chrono \
        --append-system-prompt "$SYSTEM_PROMPT"
else
    exec "${HOME}/.local/bin/claude" \
        -c \
        --remote-control chrono
fi
