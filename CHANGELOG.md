# Changelog

## Unreleased

_Nothing yet._

## v1.1.4

Adds a fifth model family and makes the board reliable enough to trust with long work. Shipped on top of v1.1.3 (`git tag v1.1.3`, 2026-08-27).

### The grok lane

- Added `grok` as the fifth model lane with `smokey` as its advisor, native agent profile format, and adapters that are rejected outright if they carry no ranked routes. Grok binds as the `escalate_lane` for `research` and `bounty-researcher`.
- Applied Sol's ratified routing proposal across the roster — 13 primary rebinds — after an independent probe established what each lane actually exposes. Final distribution across 71 specialists: claude 31, codex 21, gemini 16, kimi 2, grok 1.
- The prose layer, README, brain map, model-runtime map and skill-home doc now all say five lanes. `docs/routing-map.html` is generated from `shared/specialist-runtime-map.tsv` rather than hand-maintained.

### Dispatch and settlement reliability

This is the bulk of the release, and most of it was found by measuring 275 blocked board tasks rather than by design review.

- **Finished work now reaches you even when the run behind it dies.** The detached supervisor inherits a PATH without Homebrew, so `python3` resolved to a 3.9 that has no `tomllib`, and `validate_capability_homes.py` died on import — reported as "candidate tree health check refused residue promotion", which reads as a verdict on the repository. Fixed at the environment: the supervisor already preserves the real PATH as `TRUSTED_HOST_PATH` for worker launches, and the health check now uses it too.
- **A busy machine now makes a task wait instead of dropping it.** `host_admission.py` returns `{"action": "queue", "backoff_seconds": N}` under momentary load, and the caller turned that into `die` while printing the word "queued". A busy host converted every correct dispatch into a dead one. It now retries on the admission's own backoff.
- **A task is judged on what it changed, not on the machine it ran on.** The gate ran live capability-home existence — whether `halmos`, `myth` and `anchor` are installed — at the moment of promoting a worker's residue, which a worker cannot influence and a sanitized supervisor PATH cannot answer (140 diagnostics versus 0, decided only by PATH). Live existence keeps its home in the pre-commit hook.
- **File permissions say what they mean.** Scopes are prefix paths compared on path components, so `dir/**` was a literal component matching no file — a permission that read as granted and behaved as empty, which flagged seven correct edits out of scope.
- **When something is refused, it says why.** The controller emitted the last 4000 characters of a validator that prints one passing line per file, so every stored error began mid-token inside a run of `"status":"pass"` and the cause had scrolled off. It now reports the lines that explain the failure and states how many passing lines it dropped.
- Deleted the skill-reference census: added ten hours after the last green CI run, it resolved skills through the maintainer's local plugin cache and never passed CI once.
- `bin/test` no longer OOM-kills the host. `run_moat_fast` called `node --test` with no concurrency cap, and `node --test` defaults to the CPU count — a 10-wide burst on a saturated machine, invisible to a search for concurrency flags because the parallelism is a default rather than a flag.

### Correctness of the guidance itself

- The gemini lane's skill bridge was a fourth, undeclared copy that received no content updates. `defi-invariant-check` was missing 43 lines — the entire 2026 oracle-robustness and governance section — so a specialist on that lane was auditing DeFi against the pre-2026 invariant set. Resynced, with the blob group declared so the validator now covers it.
- Bounty mode reduced to a kernel; the `KILLED` exit is closeable and archiving has a contract.
- `should_compact()` and `validate_worktree_outputs()` deleted — the first because the threshold rule lives in markdown, the second because it was genuinely dead.
- The `known-bugs` bench is classified private, keeping deferred work out of the public export.

**Release note.** This tag is cut on the correctness of its own changes rather than a fully green CI
run: six of seven jobs pass, and the remaining gate is red on tests that cannot execute in that
environment. Every change touching dispatch or settlement was reviewed by a different model family
than the one that wrote it.

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
