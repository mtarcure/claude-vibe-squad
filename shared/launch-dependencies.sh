#!/usr/bin/env bash
# The external commands this installation cannot run without.
#
# ONE home for one fact (CLAUDE.md rule 10). Two programs ask about this list
# with opposite jobs: bin/launch-squad.sh REFUSES to start when one is missing,
# and bin/doctor.sh is what README's Quickstart tells a new user to run
# immediately BEFORE `squad up`. While the list lived only inside the launcher's
# loop, doctor never mentioned `fswatch`, `uv` or `curl` once in its 1,390 lines
# (measured 2026-08-17), so a fresh clone without fswatch got a GREEN pre-flight
# and then a launch that exited 1 -- the health check passing for the very
# launch it exists to pre-flight. A copied list would have aged back into that
# state; a shared one cannot.
#
# `uv` is on this list and was not on the launcher's. README's Quickstart has
# always required it, and bin/{run-nightly,run-weekly,browser-keep-alive,
# registry-reconciler,brain-cleanup,vibecoding-check}.sh all `exec uv run`, so a
# checkout without it launches and then fails every scheduled job -- the same
# "looked healthier than it was" shape, one layer down. Adding it here widens
# the launcher's gate by one command on purpose.
#
# The lane CLIs are on the list because the launcher gates on them. Doctor also
# reports them per-lane as WARNINGS in its CLI Status section; that is a
# different question (which CLI did THIS HOME install, at what version, and does
# the dispatch rail agree) and it keeps its own severity.
#
# This file is sourced, never executed, so it deliberately declares no `set -e`
# / `set -u` / `set -o pipefail` of its own: those would mutate the CALLER's
# shell, and bin/launch-squad.sh runs `set -uo pipefail` without -e on purpose
# so a failed step cannot abandon the rest of a launch. .githooks/pre-commit
# greps every *.sh for `set -` and warns here for exactly that reason;
# shared/repo-root.sh, shared/namespaces.sh, shared/lead-windows.sh and
# shared/process-identity.sh are sourced libraries in the same position.
SQUAD_REQUIRED_COMMANDS=(tmux fswatch jq curl uv claude codex gemini kimi)

# The one remedy string both callers print, so the list and the fix for it
# cannot drift apart either.
SQUAD_REQUIRED_COMMANDS_HINT='install/login the missing CLIs, and install core tools with: brew install jq tmux fswatch uv'
