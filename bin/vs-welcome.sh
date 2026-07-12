#!/usr/bin/env bash
# vs-welcome.sh — Chrono greeting, printed before Claude Code launches in the
# chrono pane. Establishes "you are talking to the coordinator" context so the
# operator lands on the squad's identity, and Claude Code's own banner reads as
# "engine started" beneath it.
#
# Auth policy (matches launch-squad.sh MEDIA_AUTH_PREFIX): unset the Anthropic /
# Gemini / Google API keys so Claude falls back to the Max-plan OAuth session,
# but KEEP OPENAI_API_KEY — the chrono pane hosts the chrono-content-engineer
# plugin, and Sora needs that key. Do NOT unset all four here (the handoff
# shorthand did; it would silently break media generation in this pane).
set -u

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

# Locked palette — colour74 cyan accent, colour252 near-white, colour240 dim.
c() { printf '\033[38;5;%sm' "$1"; }
CYAN=$(c 74); TEXT=$(c 252); DIM=$(c 240); R=$'\033[0m'; B=$'\033[1m'

clear
printf '\n'
printf '  %s%s▎ vibe-squad%s  %s· 4 lanes standing by%s\n\n' "$CYAN" "$B" "$R" "$DIM" "$R"
printf '  %sYou are talking to %s%schrono%s%s — the coordinator.%s\n' "$TEXT" "$R" "$CYAN" "$R" "$TEXT" "$R"
printf '  %sPeers (codex · claude · gemini · kimi) work in the lanes.%s\n\n' "$DIM" "$R"
printf '  %s──────────────────────────────────────────────%s\n' "$DIM" "$R"
printf '  %sfan-out%s  %s"send this to all four"%s\n'      "$TEXT" "$R" "$DIM" "$R"
printf '  %sroute%s    %s"ask gemini about X"%s\n'         "$TEXT" "$R" "$DIM" "$R"
printf '  %sstatus%s   %s"what is each lane on?"%s\n'      "$TEXT" "$R" "$DIM" "$R"
printf '  %speek%s     %sC-b 1-4 lanes · C-b Space reset view · C-b d detach%s\n' "$TEXT" "$R" "$DIM" "$R"
printf '  %s/stop%s    %sinterrupt the active dispatch%s\n' "$TEXT" "$R" "$DIM" "$R"
printf '  %s──────────────────────────────────────────────%s\n\n' "$DIM" "$R"

sleep 1

# Launch Claude Code as the coordinator. acceptEdits (not bypass) because the
# operator watches this pane directly; --add-dir grants the vault. Keep
# OPENAI_API_KEY (media), drop the rest so Claude uses the Max-plan session.
exec env -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
    "${HOME}/.local/bin/claude" \
        --permission-mode acceptEdits \
        --model opus \
        --effort xhigh \
        --add-dir "${VAULT_ROOT}"
