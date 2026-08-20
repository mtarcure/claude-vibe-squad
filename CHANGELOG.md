# Changelog

## Unreleased

- Kept Chrono as the single operator-facing coordinator while moving specialist work to fresh native Claude, Codex, Gemini, or Kimi CLI processes in isolated worktrees.
- Kept all 68 Markdown specialist briefs and exactly two workflows: Project and Bounty.
- Added exact process/receipt identity checks and artifact-first, envelope-last settlement so stale or partial work cannot appear complete.
- Preserved cross-family review routes and explicit operator holds for destructive, external, paid, credential, production, and public-release actions.
- Kept durable memory as private Markdown outside the repository, with a disposable lexical recall index.
- Converted unattended cleanup jobs to report-only while storage ownership and retention facts are completed.
- Removed disconnected policy, receipt, memory-store, and generated-output prototypes instead of turning them into parallel product architecture.
- Reworked onboarding and public-export boundaries for a simpler, more honest public release.
- Expanded production-path, adversarial, recall, and export tests; a configured surface is not called working until its real route is probed.

## v1.1.1

The first public release (`git tag v1.1.1`, 2026-05-03). Six reviewer-flagged bugs fixed on top of v1.1.0 the same day:

- `validate-specialists.sh`: an awk range collapse had made the citation checks a silent no-op, so the previously reported "39 PASS" proved nothing about them. Fixed the flag-pattern extraction for MCPs, skills, and peers.
- `dream_light.py`: replaced an over-broad `\b[A-Za-z0-9]{32,}\b` redaction — which ate git SHAs, UUIDs, and base64 — with 17 specific secret patterns (AWS, GitHub, Anthropic, Slack, JWT, Stripe, HuggingFace, OpenAI, xAI, Perplexity, Apify, Google, Discord, URL bearer params).
- `doctor.sh` retry-storm detection: pointed it at tmux CLI stdout instead of cleanup-log docs, where it could never have fired; tightened to MCP-specific failure patterns within the last hour.
- `doctor.sh` token-bleed: added a `dispatch-log.jsonl` signal alongside the artifact-count proxy, catching retry loops that produce a single artifact.
- `vibecoding_check.py`: implemented the project-mode `git_clean`, `new_code_has_tests`, and `no_destructive_ops` checks. Only `tests_pass` had existed, while the docstring claimed all four.
- `vibecoding_check.py`: the CVSS check now validates CVSS:4.0 vector structure and score range. Previously `cvss_v4: 'lol'` passed.

## v1.1.0

Tagged 2026-05-03. The v1.1 body of work, over 20 commits:

- Upgraded 39 specialist files to the v1.1 schema and added `bin/validate-specialists.sh` to enforce it, plus `bin/upgrade-specialists.py` to automate the migration.
- Updated the five LEAD.md files with v1.1 sections and repaired the broken specialist references in their decision trees.
- Added `shared/lifecycle.md` — nine lifecycle rules plus per-pane effort defaults — and per-pane effort/thinking flags in `launch-squad.sh`.
- Added `shared/api-catalog.md`, a full API/feature catalog with verified flags, following a capability inventory of CLI flags and MCPs per pane.
- Added `bin/aggregate-errors.sh` (nightly error aggregation), `spawn-specialist.sh`, and `graduation-scan.sh`.
- Added a first-week token-spend guardrail.
- Reworked two skills: the smart-contract checklist and the bounty report format.
- Fixed Claude MCP tilde-literal paths and flipped the Gemini `chrono-*` MCPs to `verified: yes` after a dispatch-toolkit reality check.

## v1.0.0

Initial public release target for the local Vibe Squad command center:

- Chrono coordinator.
- Four model leads: GPT/Codex, Claude, Gemini, Kimi.
- Markdown-first modes, specialist briefs, model lead prompts, task packets, and memory surfaces.
- Filesystem mailbox dispatch with tmux windows.
- Safety gates for review, public release, live sends, credentials, cleanup, and high-blast-radius work.
