# Capability Manifest: chrono-modes

Status: draft, required markdown product surface
Owner: Chrono / all Leads
Canonical current surface: `shared/modes/*.md`, `shared/mode-profiles/`, `shared/lifecycle.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-_shared-chrono-modes/1.0.0/`

## Role Contract

`chrono-modes` defines the markdown-first operating modes, phase gates, cleanup expectations, lead/specialist routing, and mode-exit contracts for Vibe Squad.

## Preserved Current Behavior

- Modes are markdown instructions, not a Python brain.
- Each mode defines phases, artifacts, gates, and cleanup.
- Vibecoding-check validates mode exit.
- Chrono remains user-facing coordinator.

## Old Plugin Capabilities To Preserve

Old shared mode plugin files:

- `assembler.py`
- `validator.py`
- `mcp_server.py`

Preserve assembly/validation semantics, but prefer markdown and validators over Python orchestration where possible.

## Required Tools

- Mode markdown files.
- Mode profile files.
- Mode validator.
- Phase/artifact schema.
- Cleanup expectations.

## Optional Tools

- Generated assembled mode prompt.
- MCP mode server if needed.

## MCPs

- `chrono-catalog`
- `chrono-kg`
- `chrono-vault` / `chrono-obsidian`

## Skills

- `requirements-elicitation`
- `scope-decomposition`
- `vibecoding-check`
- `mode-cleanup`

## Adaptive Operating Mode

Keep mode behavior in markdown, validate mode artifacts mechanically, use Python only for syntax/consistency rails, and ensure every mode has cleanup and live proof expectations.

## Output Contract

- `mode`
- `phases`
- `artifacts`
- `gates`
- `cleanup`
- `validation_status`

## KG And Memory Behavior

- Record mode lessons after review.
- Do not treat roadmaps/handoffs as live runtime truth.

## Safety Boundaries

- No silent mode completion without checks.
- No mode-specific bypass of safety gates.
- No unbounded autonomous mode without stop conditions.

## Live Dispatch Proof

Each production mode needs at least one live dispatch proof showing Chrono routing, Lead specialist use, artifact production, cleanup expectation, and vibecoding status.

## Public/Private Disposition

Public: mode markdown, profiles, validators, sanitized examples. Private: live runs and client artifacts.

## Cleanup Disposition

Do not delete old mode plugin assets until markdown modes plus validator cover assembly/validation behavior.
