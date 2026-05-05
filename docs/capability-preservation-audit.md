# Capability Preservation Audit

Baseline date: 2026-05-04

Status: draft v0, read-only decision artifact. Do not use this document as deletion approval.

## Purpose

Vibe Squad cleanup must preserve the working capability surface proven in the older `claude-chrono` system while returning this repo to a markdown-first, operator-light, production-ready daily driver.

This audit compares:

- current Vibe Squad Leads, specialists, modes, skills, scripts, and catalog files
- old `claude-chrono` subagent plugins, custom plugin inventory, skills, commands, MCPs, and tool wrappers
- current official guidance for subagents, Skills, slash commands, and MCPs

The cleanup rule is simple: no agent, skill, wrapper, memory, or runtime artifact is deleted until it is classified as one of:

- canonical source
- generated artifact
- private local config
- runtime state
- curated example
- archive
- capability to preserve
- quarantine candidate
- deletion candidate

## Research Anchors

Official docs support a mixed representation, not a single mechanism:

- Claude Code subagents are specialized delegated agents with separate context windows and optional tool scopes. If `tools` is omitted, they inherit the main thread's tools, including MCP tools. Source: https://docs.claude.com/en/docs/claude-code/subagents
- Claude Code Skills are reusable filesystem capabilities with `SKILL.md`, optional supporting files, progressive disclosure, and model-invoked discovery. Source: https://docs.claude.com/en/docs/claude-code/skills
- Slash commands are user-invoked markdown prompts. They are good for explicit session actions, not terminal lifecycle management. Source: https://docs.claude.com/en/docs/claude-code/slash-commands
- MCP servers expose three different primitives: model-controlled tools, application-controlled resources, and user-controlled prompts. Source: https://modelcontextprotocol.io/docs/learn/server-concepts
- MCP resources are read-oriented context surfaces with URI identity and access-control concerns. Source: https://modelcontextprotocol.io/docs/concepts/resources
- MCP prompts are explicit reusable templates and must validate inputs to prevent prompt injection or unauthorized access. Source: https://modelcontextprotocol.io/docs/concepts/prompts

Interpretation for Vibe Squad:

- Keep canonical behavior in markdown.
- Use Skills for reusable specialist procedures with examples, references, or helper scripts.
- Use subagents for delegated work with separate context and scoped tools.
- Use MCPs/plugins only for stable, repeated tool/resource surfaces that need structured calls, discovery, or cross-agent access.
- Keep shell/Python as rails and validators, not the brain.

## Local Evidence

Current Vibe Squad repo has these relevant source surfaces:

- Chrono interface: `chrono/CLAUDE.md`, `chrono/SPECIALIST-INDEX.md`, `chrono/current.md`
- shared operating rules: `shared/lifecycle.md`, `shared/routing.md`, `shared/protocol.md`, `shared/memory-discipline.md`, `shared/api-catalog.md`
- modes: `shared/modes/*.md`, `shared/mode-profiles/**`
- specialists: 46 indexed specialists across Coding, Security, Content, SysMgmt, Research, and cross-cutting roles
- current skills: `shared/skills/*.md` and specialist-local skill folders
- scripts: launch/status/dispatch/watch/doctor/nightly/weekly plus several Python helpers

Old `claude-chrono` plugin surfaces found locally:

- old agent plugin root: `~/chrono/plugins/chrono-agents/agents`
- old plugin cache: `~/.claude/plugins/cache/claude-chrono`
- old plugin types: agent prompts, plugin manifests, MCP servers, slash commands, Skills, tool wrappers, common tools, common skills, KG, catalog, observability, safety, dispatch, browser, and Obsidian surfaces

The old system is not just "extra files." It is a capability map. The valuable parts are the tool inventories, adaptive operating modes, output schemas, KG hooks, safety boundaries, and live wrapper names.

## Current-vs-Old Pattern

Example: `security-analyst`

- Current Vibe Squad file preserves the role, MCP-first posture, some skills, SAST/supply-chain scope, fanout boundaries, and output expectations.
- Old plugin adds concrete MCP tool wrappers: `semgrep_scan`, `semgrep_rule_add`, `nuclei_scan`, `ffuf_fuzz`, `gitleaks_scan`, `osv_scan`, `sqlmap_scan`, `nmap_scan`, `nikto_scan`, `wpscan_scan`, `submit_finding`, `emit_sarif`, `apply_rule_pack`, `darnit_query`.
- Old plugin also adds adaptive rules, KG recall/record hooks, strict active-scan scope boundaries, plugin self-discovery through `chrono-catalog`, and a structured return dict.

Example: `frontend-engineer`

- Current Vibe Squad file preserves the frontend role, test discipline, design handoff, and some skill references.
- Old plugin adds concrete wrappers: `pnpm_build`, `pnpm_dev`, `bun_run`, `bun_test`, `vite_dev`, `next_build`, `tsc_check`, `vitest_run`, `eslint_lint`, `prettier_format`, `playwright_trace_view`.
- Old plugin also adds browser performance routing, Tailwind/class management, KG recording, strict E2E handoff boundaries, and a structured return dict.

Conclusion: current specialists are directionally right, but old plugins are more operational. The recovery path is not "restore old plugin sprawl"; it is to extract capability manifests and strengthen current markdown/subagent definitions.

## Representation Policy

Use this as the target rule during cleanup and consolidation:

| Thing | Canonical Representation | Notes |
|---|---|---|
| Lead identity and routing | `departments/*/LEAD.md` | Human-readable and editable. |
| Specialist identity and operating rules | `departments/*/specialists/*.md` or `shared/specialists/*.md` | Source of truth. |
| Tool/MCP/skill inventory per specialist | proposed `shared/capability-manifests/*.md` | Derived from current docs plus old plugin manifests. |
| Reusable procedure | `shared/skills/*.md` or specialist-local `skills/*.md` | Prefer markdown first. Add helper scripts only when they save repeated execution work. |
| CLI-specific agent config | generated artifact | Generate from canonical specialist markdown plus capability manifest. |
| Stable callable tool surface | MCP/plugin | Use only when agents repeatedly need structured calls, not for one-off instructions. |
| Terminal lifecycle | small shell wrapper | `squad`/`vibesquad` should manage launch, stop, restart, status, doctor. |
| JSON/schema validation | small helper, maybe Python | Allowed when Bash becomes fragile. |
| Cleanup policy | markdown owned by SysMgmt | Scripts can report/apply, but policy lives in markdown. |

## Old Plugin Inventory Summary

| Old plugin | Current destination | Capability status | Preserve before cleanup |
|---|---|---|---|
| `chrono-plugin-security-analyst` | `departments/security/specialists/security-analyst.md` | Partially preserved | Tool wrappers, active/passive scope gates, finding schema, KG hooks, web-vuln skills. |
| `chrono-plugin-scout` | `departments/security/specialists/scout.md` | Partially preserved | Recon chain, scope gate, program intel, subdomain/API mapper tools. |
| `chrono-plugin-exploit-developer` | `departments/security/specialists/exploit-developer.md` | Partially preserved | Binary RE/fuzzing/pwntools skills, exploit-chain safety boundaries. |
| `chrono-plugin-impact-validator` | `departments/security/specialists/impact-validator.md` | Partially preserved | CVSS v4, program fit, self-inflicted detector, NVD/OSV calibration, chain rescore. |
| `chrono-plugin-smart-contract-engineer` | `departments/coding/specialists/smart-contract-engineer.md` | Partially preserved | Forge/Slither/Mythril/Echidna/Halmos/Medusa/Trident/Wake/LiteSVM, EVM/Solana audit flows, multi-stance fanout. |
| `chrono-plugin-frontend-engineer` | `departments/coding/specialists/frontend-engineer.md` | Partially preserved | pnpm/bun/vite/next/tsc/vitest/eslint/prettier/Playwright trace wrappers, browser perf loop. |
| `chrono-plugin-designer` | `departments/content/specialists/designer.md`, `departments/coding/specialists/ui-engineer.md` | Under-preserved | Figma fidelity, design tokens, a11y, visual review, component snapshots. |
| `chrono-plugin-e2e-runner` | `departments/coding/specialists/test-engineer.md` plus possible dedicated e2e specialist | Under-preserved | Playwright/Cypress/WebKit/Firefox/trace/video/visual diff/storybook tools. |
| `chrono-plugin-qa-tester` | `departments/coding/specialists/test-engineer.md` | Under-preserved | Hypothesis, mutmut, schemathesis, c8, stryker, coverage and integrity gates. |
| `chrono-plugin-code-reviewer` | `departments/coding/specialists/code-reviewer.md` | Partially preserved | diff-aware semgrep, ast-grep, CodeQL, ruff, mypy, SARIF, severity ladder. |
| `chrono-plugin-refactor-cleaner` | `departments/coding/specialists/refactor-cleaner.md` | Partially preserved | ast-grep rewrite, Comby, dead-code protocol, import reorg, tree-sitter. |
| `chrono-plugin-backend-engineer` | `departments/coding/specialists/backend-engineer.md` | Partially preserved | FastAPI, Axum/Tokio, migrations, HTTP API, logs, uv/cargo/go/node. |
| `chrono-plugin-devops-engineer` | `departments/coding/specialists/devops-engineer.md`, SysMgmt/mac-ops | Partially preserved | actionlint, zizmor, Docker, Kubernetes, Terraform, AWS, sandbox provisioning. |
| `chrono-plugin-performance-optimizer` | `departments/coding/specialists/performance-optimizer.md` | Partially preserved | hyperfine, py-spy, pprof, perf, samply, Chrome trace, benchmark compare. |
| `chrono-plugin-systems-engineer` | `departments/coding/specialists/systems-engineer.md` | Partially preserved | CMake/Ninja/Cargo/GDB/LLVM/NM/readelf, SIMD/cross-arch/build skills. |
| `chrono-plugin-ai-engineer` | `departments/coding/specialists/ai-engineer.md`, shared prompt-engineer | Partially preserved | MCP design, RAG eval, multi-model routing, local model experiments, Langfuse/RAGAS/DSPy. |
| `chrono-plugin-prompt-engineer` | `shared/specialists/prompt-engineer.md` | Partially preserved | promptfoo, prompt diff/compression/regression, token budget, adversarial prompt review. |
| `chrono-plugin-research` | `departments/research/specialists/research.md` | Partially preserved | source finding, citation discipline, KG recall, granular web/source tools. |
| `chrono-research-tools` | `shared/api-catalog.md`, research namespace MCPs | Needs live verification | arxiv, brave, serper, perplexity, HN, reddit, YouTube transcript, markitdown, GitHub, Apify/Twitter. |
| `chrono-plugin-large-context-analyst` | `departments/research/specialists/large-context-analyst.md` | Partially preserved | Kimi-scale long-context mapping, cross-file relationship synthesis, claim validation. |
| `chrono-plugin-synthesizer` | `departments/research/specialists/synthesizer.md`, shared summarizer | Partially preserved | preserve-outliers skill, provenance-preserving synthesis. |
| `chrono-plugin-scraping-engineer` | `departments/coding/specialists/scraping-engineer.md`, Research data extraction | Partially preserved | Playwright scrape, Firecrawl, trafilatura, OCRmyPDF, yt-dlp, rate limit, state persistence. |
| `chrono-plugin-memory-curator` | `departments/sysmgmt/specialists/memory-curator.md` | Under-preserved | KG vault health, stale knowledge purge, instinct prune, brain trio amendment flow. |
| `chrono-kg` | memory/KG layer, SysMgmt memory flow | Needs live verification | recall/search/list/show commands and KG navigation skill. |
| `chrono-plugin-_shared-chrono-obsidian` | `shared/api-catalog.md`, memory discipline | Needs live verification | vault list, note get, backlinks, search, dataview, path sandbox. |
| `chrono-catalog` | proposed capability manifest/catalog source | Underused | list tools, list skills, get skill, list playbooks, tool status. |
| `chrono-observability` | SysMgmt/AgentOps | Underused | structured event emission and readback for dispatch/test proof. |
| `chrono-audit` | SysMgmt/release hygiene | Underused | hash-chained audit trail. |
| `chrono-safety` | shared safety/privacy | Underused | redaction and sandboxing/hook-composition skills. |
| `chrono-dispatch` | dispatch architecture reference only | Needs design review | May be too heavy to restore; extract lessons, not necessarily code. |
| `chrono-plugin-loop-operator` | `departments/sysmgmt/specialists/loop-operator.md` | Partially preserved | checkpoint protocol, stall detection, safe intervention. |
| `chrono-plugin-harness-optimizer` | `departments/sysmgmt/specialists/harness-optimizer.md` | Partially preserved | baseline audit, leverage area identification, reversible changes. |
| `chrono-plugin-technical-writer` | `departments/content/specialists/technical-writer.md` | Partially preserved | ADRs, handoffs, changelog, markdownlint, Vale, MkDocs, Pandoc. |
| `chrono-plugin-triage` | `shared/specialists/triage.md` | Partially preserved | routing heuristics, duplicate detection, severity rubric. |
| `chrono-plugin-skeptic` and `chrono-plugin-challenger` | `shared/specialists/skeptic.md` plus review modes | Partially preserved | source triangulation, cross-model verification, differential review, council consensus. |
| `chrono-plugin-shared-common-skills` | `shared/skills/*.md` | Partially imported | Process, security, KG, adversarial review, verification, worktree, planning, skill writing. |
| `chrono-plugin-shared-common-tools` | MCP/tool catalog | Needs live verification | GH, HTTP, Docker, Playwright, pnpm/npm, semgrep, network, whois/dig. |

## Gaps To Fix Before Cleanup

1. Current specialist files often have the right names but not the old plugin's exact capability contracts.
2. Some old Skills have not been imported into `shared/skills/` or specialist-local skill folders.
3. Some current docs claim capability availability based on older inventory dates, not live usable checks.
4. `chrono/SPECIALIST-INDEX.md` has stale known-debt text that conflicts with current validator results.
5. The current repo has many archived task/outbox files and phase drafts mixed with source surfaces.
6. Script/Python count is above the desired minimal architecture.
7. MCP audit currently needs to distinguish `registered`, `reachable`, `auth_ok`, `usable`, and `used_in_live_dispatch`.
8. Live dispatch tests do not yet prove that Leads select subagents and subagents use intended non-basic capabilities.

## Required Capability Manifests

Create one markdown manifest per specialist family before deleting or condensing old plugin assets:

```text
shared/capability-manifests/security-analyst.md
shared/capability-manifests/scout.md
shared/capability-manifests/exploit-developer.md
shared/capability-manifests/impact-validator.md
shared/capability-manifests/smart-contract-engineer.md
shared/capability-manifests/frontend-engineer.md
shared/capability-manifests/ui-designer.md
shared/capability-manifests/e2e-runner.md
shared/capability-manifests/test-engineer.md
shared/capability-manifests/memory-curator.md
shared/capability-manifests/prompt-engineer.md
shared/capability-manifests/research.md
shared/capability-manifests/sysmgmt-agentops.md
```

Each manifest must include:

- current canonical specialist file
- old plugin source paths
- required tools
- optional tools
- MCPs
- Skills
- safety boundaries
- output contract
- KG/memory behavior
- live dispatch proof
- public/private decision
- cleanup disposition

## Live Dispatch Test Matrix

Mailbox-only smoke tests are insufficient. A production test must prove the whole chain.

Common assertions for every test:

- Chrono routes the task to the correct Lead.
- Lead selects a named specialist/subagent.
- Specialist uses at least one intended non-basic tool, Skill, MCP, or structured missing-capability report.
- Evidence is written to response/output.
- `_state/active-tasks.json` closes.
- Chrono can summarize result.
- SysMgmt cleanup expectations are satisfied.

| Test | Route | Required proof |
|---|---|---|
| Security local scan | Chrono -> Security -> security-analyst | Run safe fixture through semgrep/gitleaks/osv or report missing dependency in schema. |
| Bounty recon dry run | Chrono Bounty Mode -> Security -> scout | Scope gate before recon; no active scan without scope. |
| Impact validation | Security -> impact-validator | CVSS/program-fit/self-inflicted checks against sample finding. |
| Smart contract fixture | Coding/Security -> smart-contract-engineer | Forge/Slither/Echidna fixture or structured missing-tool report. |
| Frontend implementation | Coding -> frontend-engineer -> ui/test handoff | tsc/lint/test/build or local fixture equivalent; visual/a11y check for UI work. |
| E2E runner | Coding -> test-engineer or e2e-runner | Playwright run with trace/screenshot evidence. |
| Prompt quality | SysMgmt/Coding -> prompt-engineer | prompt lint/token budget/regression check on one specialist prompt. |
| Memory hygiene | SysMgmt -> memory-curator | Vault/memory scan proposal; no self-deletion. |
| Research | Chrono -> Research -> research -> synthesizer | Source-backed answer with citation/provenance and synthesis of disagreement. |
| Loop/AgentOps | SysMgmt -> loop-operator/harness-optimizer | checkpoint, stall detection, reversible change proposal. |

## Cleanup Gates

Before cleanup:

- build capability manifests from old plugin cache and current specialists
- run current specialist validator
- run MCP/tool audit with real usability checks
- run live dispatch capability tests
- classify all runtime/archive/outbox/spec/handoff files
- identify private/local-only artifacts
- create quarantine manifest

During cleanup:

- move first, do not delete first
- preserve source paths in manifest
- generate a reviewable diff
- run QA after every cleanup batch

After cleanup:

- confirm `doctor` passes
- confirm public repo has no runtime/private patterns
- confirm old capability coverage is represented in canonical markdown or manifests
- confirm GitHub/local state match intentionally

## Recommendations

1. Add `shared/capability-manifests/` and populate it from this audit before touching old plugin files.
2. Update current specialist files from manifests, not directly from plugin code.
3. Keep old plugin code quarantined until every capability has a disposition.
4. Do not reintroduce every old MCP/plugin. Promote only stable, repeatable, cross-agent tool surfaces.
5. Make SysMgmt own recurring hygiene through markdown routines plus minimal scripts.
6. Replace generic smoke tests with live dispatch capability tests.
7. Treat current `shared/api-catalog.md` verified claims as stale until a live `registered/reachable/auth_ok/usable/used_in_dispatch` audit proves them.
8. Consolidate scripts only after capability manifests exist, so we do not remove support rails that still back a real specialist.

## Immediate Next Actions

1. Generate the first four capability manifests: `security-analyst`, `frontend-engineer`, `memory-curator`, `prompt-engineer`.
2. Patch `chrono/SPECIALIST-INDEX.md` stale debt section after confirming current validator output.
3. Define the exact live dispatch test harness shape using existing `bin/send-task.sh`, watcher/sweep, and Lead outboxes.
4. Decide public/private disposition for old plugin-derived capabilities before copying any old private content into public repo docs.
5. Start script/Python consolidation only after the above manifests identify which scripts are still load-bearing.
