# claude-vibe-squad — Changelog

All notable changes documented per [Keep a Changelog](https://keepachangelog.com/) format.

## [1.1.2] - 2026-05-03 — Daily-Driver Readiness

Fixes a broken first-run experience and tightens UI on the live sidebar. Codex (peer-gpt) reviewed the full repo before this pass; full review captured at `~/Obsidian-Chrono/chrono/reviews/2026-05-03/eea2fdb3-peer-gpt-output.md`.

### Fixed

- **`bin/launch-squad.sh` now runs the CLIs.** Previously echoed `'Start with: <cli>'` instead of executing — every Lead pane landed at a bash prompt. Replaced echoes with bare CLI commands so the launcher actually launches. (commit `5c03c33`)
- **`tmux set-option -g` calls now apply.** Added `tmux start-server` before the global option block so options don't silently fail when the server isn't yet up (e.g. after `kill-server`). Status bar + mouse mode + scrollback now apply on every launch. (commit `5c03c33`)
- **Chrono dispatch-first rule clarified.** `chrono/CLAUDE.md` and `chrono/SOUL.md` had a WebFetch fallback that let the Coordinator drift into specialist work. Tightened to: direct tools = housekeeping only; web research, code, security, content, infra, synthesis ALWAYS dispatch to the owning Lead. (commit `5c03c33`)
- **README quick-start.** Clone URL was `<you>` placeholder → `mtarcure`. Quick-start said "type claude / run the indicated CLI" → now reflects auto-start. Nightly automation softened (HTML scrape + full audio transcription are partially-implemented, not live). (commit `5c03c33`)
- **`bin/connect.sh` header comments.** Stale "sidebar-on by default" claims from rolled-back tmux experiment → updated. (commit `5c03c33`)

### Changed

- **Sidebar default-on.** `bin/launch-squad.sh` and `bin/connect.sh` now invoke `bin/sidebar.sh` automatically. Operator preference reversal — once the windows-vs-sidebar distinction is understood, the 5-Lead live mirror tiles are useful by default. Toggle off with `bin/sidebar-off.sh`. (commit `66ad1e4`)
- **Per-Lead accent colors on sidebar tiles.** `bin/watch-lead.sh` colors each Lead's UPPER label distinctly: CODING amber, SECURITY coral, CONTENT pink, SYSMGMT mint, RESEARCH sky. (commit `de8fedc`)
- **Cleaner `Last:` extraction on sidebar tiles.** Was: first non-empty body line, often truncated mid-sentence ("This TASK is byte-identical (in spec, asks, and success criteria) to…"). Now: prefers the response file's H1 heading; falls back to non-meta paragraph line. Real result on the squad's responses: "STRIDE-lite threat model — POST /api/squad/submit-task" instead of meta-prose. (commit `de8fedc`)
- **Spec ↔ reality sync.** `docs/specs/...v1.1`: "5 modes (Project/Bounty/Freelance/Research/Browse)" → "7 modes (Bounty/Project/Research/Content/Incident/Maintenance/Triage)". Added one-line acknowledgment of `shared/mode-profiles/{bounty,project}/`. (commit `5c03c33`)
- **CONTRIBUTING.md.** Clarified `shared/specialists/` is for cross-cutting roles callable by any Lead; `departments/<lead>/specialists/` for Lead-owned. Mode profiles are target-type overlays, not new modes. (commit `5c03c33`)
- **CHANGELOG terminology.** "39 specialist files" → "39 direct specialist identity files" (recursive find finds 41 if bundled skill docs are counted). (commit `5c03c33`)

### Removed

- 4 stray `.bak*` files from sed `-i.bak` artifacts (no functional impact).

### Repo hygiene

- `.gitignore` now excludes `departments/*/archive/` (operator-local task history) and `.gemini/` (per-CLI local state with absolute MCP paths). No leaked secrets in tracked files (verified by Codex scan).

## [1.1.0] - 2026-05-03 — Tool Utilization & Discipline

Multi-model reviewed (Codex GPT-5.5 + Gemini 3.1 — both GREEN after revision 2). Spec at `docs/specs/2026-05-02-vibe-squad-v1.1-tool-utilization.md`. Plan at `docs/plans/2026-05-02-vibe-squad-v1.1-tool-utilization-plan.md`.

### Added

- **Capability inventory** at `_state/capability-inventory-2026-05-02.md` — live-verified inventory of CLI flags, MCPs, and features per pane. Specialist files cite only `verified: yes` entries. (commit `da43212`)
- **`shared/lifecycle.md`** — 9 canonical lifecycle rules + per-pane effort/thinking tier defaults table. Referenced by every Lead. (commit `93870b6`)
- **`shared/api-catalog.md`** — full API/feature catalog with per-entry `verified: yes/no/needs-research` flags. chrono-* MCPs use per-pane verification matrix; Gemini `--thinking` flag explicitly marked `verified: no` (model-level implicit thinking instead). 8 needs-research categories form within-v1.1 backlog. (commits `24724dc`, `9552d91`)
- **`bin/upgrade-specialists.py`** (789 lines) — automation script that injects v1.1 schema sections (Tools available, fan-out, escalate, do-not) across all 39 direct specialist identity files. Reads api-catalog for per-Lead-CLI tool pre-fill. Atomic write, idempotent, leaves `<FILL: ...>` placeholders for human-judgment fields. (commit `8149f60`)
- **`bin/validate-specialists.sh`** — schema validator. Verifies required v1.1 sections, cited MCPs in api-catalog `verified: yes` set, cited skills exist, peer-specialist refs resolve. JSON-shaped output, exit 1 on any failure. Lenient on `<FILL: ...>` placeholders. (commit `9a5ba5d`)
- **`bin/dispatch-toolkit-verify.sh`** — per-pane MCP consistency check; parses each Lead's verified-MCP block and warns on enumerated-but-not-installed MCPs. Bash-3.2-compatible (macOS default). Handles gemini's stderr/stdout quirk. (commit `cf65ac7`)
- **`bin/spawn-specialist.sh`** — single helper that spawns a specialist subprocess via the right CLI (claude/codex/gemini/kimi headless) and writes 3 log streams: `_state/specialist-log.jsonl` (per-spawn metadata, full fidelity), `_state/tool-calls.jsonl` (best-effort stdout-grep), `_state/patterns.jsonl` (routine signatures for MCP graduation tracking). (commit `c2adcf0`)
- **`bin/graduation-scan.sh`** — weekly scan of `patterns.jsonl`. Surfaces routine signatures hitting ≥3 distinct engagement IDs in past 30 days to `_state/mcp-graduation-candidates.md`. Operator-gated, no auto-scaffold. (commit `c2adcf0`)
- **`bin/aggregate-errors.sh`** — nightly error aggregator. Greps tmux-logs + nightly-failures + doctor-logs for ERROR/Traceback/FAILED patterns, writes structured entries to `_state/errors.jsonl` with error_signature hashes for dedup. (commit `f0540ee`)
- **`bin/finance-daily.sh`** — first-week token-spend guardrail with daily monitoring. Alerts fire on any pane crossing 1.5× baseline; surfaces in morning brief. Token budget doc at `_state/token-budget-2026-05-W2.md`. (commit `c6b64d7`)
- **2 new skills (REMAKE policy, attribution preserved):**
  - `smart-contract-audit-checklist` — sources: tamjid0x01 + cryptofinlabs. 15 vulnerability classes, severity rubric, tooling chain, reporting format. (commit `79a7b08`)
  - `bounty-platform-report-format` — sources: HackerOne / Bugcrowd / Code4rena public docs. Per-platform expected report structure, severity mapping, common pitfalls. (commit `79a7b08`)
- **`chrono/operator-setup.md`** routing examples — cross-Lead direct-with-CC patterns for the most common v1.0 failure mode (Security not reaching Research). (commit `0db6e4f`)
- **Topology B chaser logic** in `chrono/CLAUDE.md` + `chrono/current.md` — Chrono now tracks pending CC'd cross-Lead threads and surfaces stalls past 2h. (commit `0db6e4f`)
- **Implementation plan** at `docs/plans/2026-05-02-vibe-squad-v1.1-tool-utilization-plan.md` — 24 tasks across 11 phases mapped to bite-sized TDD-shaped steps. (commit `e414be7`)

### Changed

- **All 39 direct specialist identity files** upgraded with v1.1 schema sections. 12 Tier-A specialists (code-reviewer, backend-engineer, frontend-engineer, ui-engineer, test-engineer, scout, security-analyst, threat-modeler, research, synthesizer, content-creator, technical-writer) had FILL placeholders manually completed. 27 Tier-B/C retain placeholders for future role-author completion. Validator passes on all 39. (commit `5797ced`)
- **5 LEAD.md files** updated with v1.1 sections — native CLI features (verified per api-catalog), specialist decision trees, direct-with-CC patterns, lifecycle discipline. (commit `b93b4c4`)
- **5 Lead memory.md files** record v1.1 release as durable insight: explicit tool catalogs, per-pane effort tiers, Topology B patterns, lifecycle rules. (commit `ee3f3e5`)
- **`bin/launch-squad.sh`** — per-pane effort/thinking flags. chrono+security: `--model opus --effort xhigh`. coding: `-c model_reasoning_effort=high`. sysmgmt: `--model sonnet --effort high`. content: `--model gemini-3.1-pro-preview` (no `--thinking` flag exists; thinking implicit at model level). research: `--thinking` (Kimi K2.6). Each combination tested live. (commit `55da375`)
- **`shared/dispatch-toolkit.sh`** — reality-check pass: trimmed `chrono-research-arsenal` from non-Research Lead sections (Research only); replaced placeholder MCP names with Capability Inventory verified entries per pane; added "Routing reminder" pointers for OSINT/web-research handoffs to Research. (commit `cf65ac7`)
- **Hybrid Path A Gemini MCP install** — installed 4 chrono-* MCPs on Gemini (`chrono-vault`, `chrono-obsidian`, `chrono-content-engineer`, `sequential-thinking`); 3 more (`chrono-kg`, `chrono-catalog`, `chrono-research-arsenal`) confirmed already present. All 7 show ✓ Connected via `gemini mcp list -d`. Discovered: gemini's `mcp list` writes to stderr and requires `-d` flag. Content-pane intentionally uses Google Search grounding via gemini-3.1-pro-preview as research substitute. (commit `cf65ac7`)
- **Vault root `CLAUDE.md`** — tightened "specialists must use named MCPs first" rule with concrete WebFetch-as-fallback-only example. (commit `0db6e4f`)
- **`chrono/CLAUDE.md` + `chrono/SOUL.md`** — references to lifecycle.md + api-catalog.md + operator-setup; routing-rule reminder for `research`/`scout` verbs; instinct-surfacing note (N=3 graduation, operator-gated). (commit `0db6e4f`)
- **8 broken specialist refs** in LEAD.md decision trees fixed (replaced invented names with actual roster files): coding (qa-tester, e2e-runner removed; test-engineer covers both); content (writer→content-creator, video-editor→content-creator, social-strategist row added); sysmgmt (doctor→agentops, dreamer+archiver removed); research (scraper→data-extraction-engineer). (commit `017f174`)

### Fixed

- **2026-05-03 Claude MCP tilde-path bug:** 7 chrono-* MCPs were silently failing to connect on all 3 Claude panes (chrono/security/sysmgmt) because the plugin manifests used `~/chrono/...` literal paths that Claude's MCP runtime didn't expand. Fixed via sed across source manifests + cache copies. Affected: chrono-vault, chrono-kg, chrono-obsidian, chrono-catalog, chrono-research-arsenal, chrono-content-engineer. All 7 now ✓ Connected. See `_state/incident-2026-05-03-claude-mcp-tilde.md`. Out of scope: goodmem/github/greptile remain failing for unrelated reasons (separate plugins). (commit `dd19bc1`)
- **Capability inventory mis-observation** corrected: gemini chrono-* MCPs were NOT missing — `gemini mcp list` writes to stderr and needs `-d` flag. Original "empty output" finding was a stdout-capture artifact. api-catalog Gemini rows flipped to `verified: yes` for 6 chrono-* MCPs accordingly. (commits `cf65ac7`, `9552d91`)

### Removed

- N/A (no v1.0 features removed).

### Out of Scope (deferred to v1.2)

- Hook-based message delivery (vs. tmux send-keys).
- Source Council parallel single-source agent pattern.
- Operator dashboard rebuild beyond `bin/dashboard.sh` + `bin/morning-brief.sh`.
- Roster expansion to 57 specialists.
- Custom routine MCPs (graduation criterion lets squad earn them organically).
- Terminal UX optimization.

## [1.0.0] - 2026-04-XX → 2026-05-02 — Initial squad

Initial squad bring-up: 6 tmux panes (chrono + 5 Leads), 39 specialists, mailbox protocol, fswatch-based inbox watchers, `bin/launch-squad.sh`, `bin/connect.sh`, `bin/sidebar.sh`, `bin/dashboard.sh`, `bin/morning-brief.sh`, `bin/where-are-we.sh`, `bin/vibecoding-check.sh`. ~3000 lines of Python+shell. Subscription auth pattern (`env -u`). Public on GitHub under AGPL-3.0.
