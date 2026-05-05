#!/usr/bin/env bash
# Vibe Squad topology helpers.
#
# Source namespaces choose mailbox/storage. Model lanes choose the visible
# tmux window and runtime. Do not infer one from the other unless a legacy
# caller has no task packet to inspect.

MODEL_LANES=(gpt-codex claude gemini kimi)
SOURCE_NAMESPACES=(coding security content sysmgmt research)

runtime_window_name() {
    case "$1" in
        codex|gpt-codex) echo "gpt-codex" ;;
        claude) echo "claude" ;;
        gemini) echo "gemini" ;;
        kimi) echo "kimi" ;;
        chrono)   echo "chrono" ;;
        watchers) echo "watchers/status" ;;
        *)        echo "$1" ;;
    esac
}

runtime_display_name() {
    case "$1" in
        codex|gpt-codex) echo "GPT/Codex" ;;
        claude) echo "Claude" ;;
        gemini) echo "Gemini" ;;
        kimi) echo "Kimi" ;;
        chrono)   echo "Chrono Coordinator" ;;
        *)        echo "$1" ;;
    esac
}

runtime_short_name() {
    case "$1" in
        codex|gpt-codex) echo "CODEX" ;;
        claude) echo "CLAUDE" ;;
        gemini) echo "GEMINI" ;;
        kimi) echo "KIMI" ;;
        chrono) echo "CHRONO" ;;
        watchers) echo "WATCH" ;;
        *) echo "$1" ;;
    esac
}

runtime_accent_color() {
    case "$1" in
        codex|gpt-codex) echo "214" ;; # amber
        claude) echo "203" ;;         # coral
        gemini) echo "141" ;;         # violet
        kimi) echo "45" ;;            # cyan
        chrono) echo "39" ;;
        *) echo "250" ;;
    esac
}

runtime_terminal_color() {
    case "$1" in
        codex|gpt-codex) echo "33" ;; # yellow
        claude) echo "31" ;;          # red/coral
        gemini) echo "35" ;;          # magenta
        kimi) echo "36" ;;            # cyan
        chrono) echo "34" ;;
        *) echo "37" ;;
    esac
}

namespace_default_model() {
    case "$1" in
        coding) echo "gpt-codex" ;;
        security|sysmgmt) echo "claude" ;;
        content) echo "gemini" ;;
        research) echo "kimi" ;;
        *) echo "$1" ;;
    esac
}

namespace_mailbox_dir() {
    local vault_root="$1" namespace="$2"
    echo "${vault_root}/departments/${namespace}"
}

lead_window_name() {
    runtime_window_name "$(namespace_default_model "$1")"
}

lead_display_name() {
    runtime_display_name "$(namespace_default_model "$1")"
}
