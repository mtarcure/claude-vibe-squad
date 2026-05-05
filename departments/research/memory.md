# Research Department — Durable Memory

Governed by `shared/memory-discipline.md`.

## Authoritative Sources

### AI / ML
- Anthropic blog (anthropic.com/news, anthropic.com/research)
- OpenAI blog (openai.com/blog, openai.com/research)
- Google DeepMind blog
- xAI blog
- arXiv cs.CL, cs.LG, cs.AI
- Latent Space (newsletter)
- Import AI (Jack Clark)
- The Artificial Intelligence Show podcast
- AI Daily Brief podcast

### Security
- Project Zero blog
- HackerOne disclosed reports
- Code4rena reports
- Trail of Bits blog

### General
- (operator's preferred sources by domain)

## Reading Queue

- (active reading list)

## Topic Maps

- (concept clusters and their cross-links)

## Disproven Claims

- (claims tested and refuted — keeps them from resurfacing)

---

## Bug Bounty Platform Intel

*Updated 2026-05-02 during TASK-2026-05-02-1705-ff8bedcb bounty scouting.*

| Platform | Program Volume | Typical Payout Range | Triage Speed | Best For | Quirks / Gotchas |
|----------|---------------|---------------------|--------------|----------|-----------------|
| **HackerOne** | Largest globally (~38% market share) | $500–$50,000+ (up to $2M at top programs) | Fast, SLA-backed | All levels, widest selection | Highest competition. Private programs need reputation. API access available (HACKERONE_API_TOKEN). |
| **Bugcrowd** | Large (~32% market share) | $300–$50,000+ | Good, AI-assisted triage deployed 2026 | Steady earners, less competition than HackerOne | Diverse public/private mix. No standout crypto programs verified in May 2026 sweep. |
| **Code4rena** | Contest-only (timed audits) | $15K–$150K+ pools | Judging + QA grading post-contest | Concentrated deep-dive sprints | Time-bounded (2–6 weeks). Rewards code quality and thoroughness. Rust/Solidity/Move coverage. |
| **HackenProof** | 200+ Web3 programs | $500–$1M+ | Moderate (3–5 days typical) | Crypto-native, Web3 specialists | Many programs require KYC. Some pages CF-blocked or gated. Eastern Europe/Asia heavy. |
| **Intigriti** | Growing EU base | €300–€30,000+ | Excellent (2–5 days for critical) | EU researchers, web/API targets | GDPR/compliance heavy. Geographic restrictions common (e.g., EU/UK only). |

### Key Programs on Radar
- **Code4rena K2** — Rust/Stellar DeFi lending, $135K pool, ends 2026-05-27
- **HackerOne Vercel OSS** — TypeScript ecosystem (Next.js, Turborepo, etc.), ongoing, public since Feb 2026
- **HackenProof Aptos** — Move language L1, up to $1M, ongoing (program page 403 — verify before committing)

### Platforms NOT in Operator Toolkit
- Cantina — explicitly ruled out
- Immunefi — not in operator's setup
- Sherlock — not in operator's setup

---

*Curated, not appended.*

## Bounty Workflow — Target Research vs. Program Scope

*Updated 2026-05-03 during TASK-2026-05-03-1952-5363c405 Phase 5 validation.*

**Finding:** Industry-leading audit firms universally separate "understanding the target" from "executing the audit," but they typically combine "target research" and "scope/engagement understanding" into a single pre-audit phase owned by one team. The squad's finer split (research namespace = external OSINT on target; security namespace = authed platform program rules) is divergent but justified by the squad's distributed tool boundaries (`chrono-research-arsenal` vs. port-9222 browser attach) and async mailbox architecture.

**Prior-art sources validated:**
- Trail of Bits — explicit `audit-context-building` skill separates context-building from vulnerability hunting (Separation of Concerns principle).
- OpenZeppelin — "Security Assessment" (high-level target understanding) precedes "Security Audit" (deep code review); 7-stage process starts with "Audit Preparation & Scope Definition."
- Sherlock — 8-step contest lifecycle with steps 1–3 as explicit pre-contest scoping before researcher code access.
- Code4rena — dedicated "Scout" role ($500 USDC fixed) for pre-audit intelligence and scope estimation before Wardens begin.
- Least Authority — methodology explicitly separates "investigating details other than the implementation" (docs, deps, prior audits) from manual code review.
- ISACA/IIA traditional audit frameworks — "Scoping and pre-audit survey" (background reading, web browsing, prior reports) precedes "fieldwork."

**Implication for squad design:** Phase 1 (Target Research) and Phase 2 (Program Intelligence) can run in parallel. Both must complete before Phase 3 (Recon). The Research → Security handoff artifact is `target-intel.md`, consumed primarily at Phase 3, not Phase 2.

## Subagent Architecture — Per-CLI Format Research

*Updated 2026-05-03 during TASK-2026-05-03-2156-070cbdc1 Spec 1 Phase 1.1.*

**Finding:** All four squad CLIs (Claude, Codex, Gemini, Kimi) support real subagents with isolated context, tool restriction, and model override. All enforce single-tier fan-out (subagents cannot spawn subagents). Key differences:

- **Gemini** (content pane): Markdown + YAML frontmatter, auto-discovered in `.gemini/agents/*.md`, dispatched via `@name` syntax. Closest to squad's existing specialist markdown format.
- **Kimi** (research pane): YAML config + separate markdown prompt template, loaded via `--agent-file`, dispatched via `Agent` tool with `subagent_type`. K2.6's 300-subagent / 4000-step scaling is automatic (model-level, not CLI flag).
- **Claude** (chrono/security/sysmgmt): `.claude/agents/<name>.md` with frontmatter (`name`, `description`, `tools`, `model`), dispatched via `Task` tool.
- **Codex** (coding): TOML roles in `config.toml`, `multi_agent` feature, `spawn_agents_on_csv` task tool.

**Smell flags:**
- Gemini has an active `mcpServers` validation bug in agent frontmatter (GitHub #26015).
- Kimi custom subagent dispatch syntax is partially unverified — docs show definition but not exact invocation parameter.
- Third-party comparison tables from March 2026 incorrectly mark Gemini subagents as "experimental preview" — they are stable since April 2026.

**Implication for squad design:** Use Gemini's markdown+frontmatter as the canonical specialist format (single file, readable, version-controllable). Transpile to Kimi YAML+Markdown, Claude `.md`, and Codex TOML during Phase 1.3 conversion.

## Spec 1 Phase 1.3 — Research Specialists Transpiled to Kimi Format

*Updated 2026-05-03 during TASK-2026-05-03-2210-c76b8196.*

**Finding:** All 11 Research-dispatchable specialists (5 own + 6 cross-cutting) have been mechanically transpiled to Kimi CLI's three-file subagent format:
- `main.yaml` — declares all subagents with paths and descriptions
- `subagents/<name>.yaml` — per-subagent config (`extend: coder`, `system_prompt_path`, `model: inherit`)
- `prompts/<name>.md` — body verbatim from source specialist file, frontmatter stripped

**Key smell flags preserved:**
- Kimi custom subagent dispatch by name is still unverified — all configs use `extend: coder` as fallback.
- Current specialist files lack canonical frontmatter (`task_shape`, `tools`, `brief_schema`) — transpile was mechanical from old format.
- Cross-cutting specialists need per-model-lane transpilation (other model leads need their own `main.yaml` subsets).

**Implication for squad design:** Use Gemini's markdown+frontmatter as the canonical specialist format (single file). Transpile to Kimi YAML+Markdown split at install time. Live-test custom subagent dispatch before Phase 1.4.

## Subagent Wiring — Verified Working 2026-05-03

*Updated during TASK-2026-05-03-2333-7f2a2afc.*

**Finding:** Kimi custom subagent dispatch via `Agent(subagent_type="research")` is **fully operational** in the research pane.

- No `--agent-file` flag required at launch for discovery
- `.kimi/agents/*.yaml` configs are auto-resolved relative to working directory
- `extend: ./main.yaml` + `system_prompt_path: ./prompts/<name>.md` pattern works
- `model: inherit` resolves correctly to parent model (Kimi K2.6)
- All 11 custom agents discoverable: `data-extraction-engineer`, `large-context-analyst`, `learning-coach`, `planner`, `prompt-engineer`, `research`, `skeptic`, `summarizer`, `synthesizer`, `triage`, `vibecoding-check`

**Disproven claim:** Prior run (TASK-2026-05-03-2324-b3114dc2) asserted `Unknown model alias: inherit` errors and required `--agent-file .kimi/agents/main.yaml` fix. This was transient; current session validates clean dispatch.

## Tool-catalog update — 2026-05-03

The squad shipped explicit tool catalogs in every specialist file,
per-pane effort/thinking tier defaults, capability inventory, and Topology B
direct-with-CC patterns. When dispatching a specialist now, trust that its
identity.md enumerates available MCPs / native CLI features / skills / APIs
— no need to remind it. model-lane-to-model-lane direct-with-CC patterns are documented
in this namespace shim. See shared/lifecycle.md for lifecycle rules.
