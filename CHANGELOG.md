# Changelog

## Unreleased

_Nothing yet._

## v1.1.3

The simplification release. Everything below shipped on top of v1.1.2 (`git tag v1.1.2`, 2026-08-22); the `v1.1.3` tag is applied to `main` after this work is pushed, so it never names an unpushed tree.

- Removed the fan-out and swarm dispatch transports entirely — about 5,500 deletions across the registry reconciler, dispatch context builder, and send path, with no transport CLI flag left behind. Chrono dispatches parallel lanes directly and specialists already self-fan-out through their own subagents, so the second transport was machinery with no caller.
- Dropped the `advisory` mode explored during this cycle; clearance, the verification contract, and the dispatch context builder stay closed to the two workflows, Project and Bounty.
- Wired `child_mcp_policy` instead of leaving it declared and unread: adapter validation now enforces it, so a `lead-broker-only` capability actually requires the native Kimi prompt to carry the MCP-unavailability notice.
- Consolidated work-state onto a single parser, projection, validator, and entry point, and migrated the live plan into one append-only workboard whose validator refuses any item that lacks a `why` and a `resume_action`.
- Collapsed duplicate operator notifications on both the promoted-response and terminal-receipt paths.
- Derived review-settlement provenance from the registry rather than trusting the reviewer's own frontmatter.
- Pinned guards that were live but untested with mutation-proven tests: the anti-affinity cross-family review — which a bare `if False:` could have disabled while the whole suite stayed green — and the compact subagent safety rails.

### Update — 2026-08-28

Four items deferred at the v1.1.3 publish, folded back in rather than pushed to a later release.
Shipped under the same version.

- **A lane's committed work no longer strands when only its return path fails.** A block inside the
  return-path window now integrates the worker's committed, in-scope code through the same gated
  path the success path uses, and names the commit on the receipt. The receipt still reads `blocked`
  and still exits 75 — recovery never reads as settlement. Proven on a deliberate no-envelope
  dispatch, and it went on to recover a real lane that died at its wall the same night. The operator
  notification was corrected in the same change: it read the preservation record only, so it reported
  recovered work as stranded while the commit sat on `main`.
- **`modeless` dispatch.** A prepared packet may omit `mode:` entirely; the controller renders that
  absence as an affirmative `modeless` token whose authority is the intersection of `project` and
  `bounty` on every axis, with the memory write floor computed from the aperture row rather than
  looked up, so no future column can widen it. A dropped or unknown mode is rejected, not admitted.
  The generating wrapper still refuses an omitted `--mode`: omission there is an unmade choice, and a
  wrapper must never invent a packet field. This also closed a real bypass — omitting `mode` used to
  skip verification-contract derivation altogether.
- **Canary defects fixed.** `--emit-packet` now produces a packet that passes admission unaided, and
  the skills probe reads a task-bound source that survives dispatch, so it can reach `PASS`.
- **The board `codex_apps` surface is measured, not assumed.** A live worker probe enumerated 125
  callable tools, and the per-server disable control was then run from the main checkout: 0 tools
  with the override, 125 in the positive control. It is an ordinary configurable MCP server, so the
  existing allowlist seam governs it.


## v1.1.2

The board-native release (`git tag v1.1.2`, 2026-08-22). Everything below shipped on top of v1.1.1, whose own
entry follows and is kept as the May marker it was.

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
