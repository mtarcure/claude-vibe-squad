# Specialist Index — Chrono's Load-Bearing Dispatch Reference

This is Chrono's quick-reference for **which specialist owns what**. Loaded on session start. Cited by `chrono/CLAUDE.md`. Resynced when specialists are added/removed (audit hook in `bin/doctor.sh`).

**Total specialists**: 46 (14 Coding + 6 Security + 7 Content + 8 SysMgmt + 5 Research + 6 Cross-cutting)

---

## Cross-cutting rules every dispatch must include

These rules apply BEFORE dispatching any specialist. Bake them into the task brief.

1. **Knowledge-layer first** (`shared/lifecycle.md` rule 10): query chrono-vault for prior attempts/findings on this target/topic. Surface result inline in the brief: "Vault check: <X> prior attempts, <Y> findings." A brief without this line is incomplete.
2. **Browser attach** (`shared/lifecycle.md` rule 11): for any specialist that touches a web page, the brief must say "attach to operator's Chrome at port 9222 via CDP — do not spawn fresh."
3. **MCP-first, not WebFetch** (`shared/api-catalog.md`): the brief must name the specific MCP the specialist should use. "Use chrono-research-arsenal/perplexity for web research." If WebFetch is the only fit, justify it. Default-WebFetch wastes time.
4. **Multi-model verify family pairing**: when a writer-reviewer pair is required, reviewer family ≠ writer family. Codex writes → Claude or Gemini reviews. Per `vault root CLAUDE.md` hard rule 3.
5. **Memory discipline** (`shared/memory-discipline.md`): if the dispatch produces durable knowledge, the specialist must write it to its Lead's `memory.md` with timestamp + source citation per rule 1 of memory-discipline.
6. **Runtime overlay** (`docs/model-runtime-map.md` + `shared/routing.md`): every dispatch brief must name the owning Lead, primary runtime, whether review is single-runtime or multi-runtime, and which runtime owns writes. Parallel multi-runtime work is read-only unless Chrono assigns one implementation owner.
7. **Lane/specialist boundary** (`shared/protocol.md`): Chrono plans and assigns specialists to model lanes. Specialists execute. Dispatches default to `lead_direct_allowed: false`; direct lane work is allowed only when explicitly scoped and justified.

## Runtime Overlay Quick Rules

- Default: specialist inherits its Lead runtime.
- Multi-model is explicit, not automatic.
- Use `primary_plus_review` for implementation and cleanup: one runtime writes, another reviews.
- Use `independent_parallel` for adversarial review, research disagreement, impact validation, privacy/security judgment, architecture, and high-stakes bounty work.
- Use `council` only for high-impact decisions, unresolved disagreement, privacy/security risk, or operator request.
- Preserve minority opinions. Do not average contradictory model outputs into a fake consensus.
- State ownership wins over model preference. If a Kimi/Gemini/Codex reviewer spots a state-management issue, the owning Lead still closes the task and records the conflict.

---

## coding namespace — implementation, refactoring, deployment

| Specialist | Dispatch when |
|------------|---------------|
| **backend-engineer** | API/server-side implementation, data layer work, async pipelines |
| **frontend-engineer** | UI implementation, state management, browser-side logic |
| **ui-engineer** | Visual implementation, component design, design-system compliance |
| **code-reviewer** | Reviewing newly-written code (bugs, style, complexity, regressions) — NOT security review (that's Security/security-analyst) |
| **architect** | System design choices, dependency boundaries, trade-off analysis |
| **test-engineer** | Writing tests, designing test strategies, increasing coverage |
| **devops-engineer** | CI/CD pipelines, deployment, infrastructure-as-code, container work |
| **performance-optimizer** | Performance profiling, bottleneck analysis, optimization |
| **refactor-cleaner** | Mechanical refactors, dead code removal, structural cleanup |
| **scraping-engineer** | Data scraping, page extraction, structured data harvesting |
| **smart-contract-engineer** | Solidity/Vyper/Move contract work, audit-context implementation |
| **systems-engineer** | Low-level systems work, OS interfaces, performance-critical code |
| **ai-engineer** | LLM-app implementation, prompt engineering, agent design |
| **product-manager** | Requirements gathering, scope decisions, feature prioritization |

**Cross-Lead handoffs from Coding**: auth/crypto code → Security; library reputation check during build → Research; UX copy → Content.

---

## security namespace — bounty work, threat modeling, exploits

| Specialist | Dispatch when |
|------------|---------------|
| **scout** | Program reconnaissance, scope analysis, and bounty rule reading after Chrono Phase 0 target selection (NOT general research — that's Research/research; NOT initial "find me a bounty" discovery) |
| **security-analyst** | SAST, supply-chain audits, code review for security implications, agentic-safety analysis |
| **threat-modeler** | STRIDE, attack-tree construction, risk ranking, abuse case identification |
| **exploit-developer** | PoC construction, payload crafting, exploit chain assembly |
| **impact-validator** | Sanity check + CVSS v4.0 scoring on findings, duplicate detection, self-inflicted-injury check |
| **privacy-steward** | PII / data-flow concerns, GDPR/CCPA compliance reads, redaction policy |

**Cross-Lead handoffs from Security**: PoC scripting → Coding/backend-engineer; OSINT mid-scout → Research/research; submission narrative → Content/technical-writer.

**Always-multi-model**: impact-validator, threat-modeler, privacy-steward, scout (all reviewer family ≠ writer family).

---

## content namespace — writing, design, brand

| Specialist | Dispatch when |
|------------|---------------|
| **content-creator** | Long-form content, marketing copy, thought-leadership pieces |
| **media-producer** | Image, video, audio, voiceover, media editing, provenance, and cost gates |
| **technical-writer** | Documentation, technical posts, structured technical content |
| **editor** | Review/edit existing drafts, fact-check, voice consistency |
| **brand-voice** | Voice/tone definition, brand guideline enforcement, audience-fit review |
| **designer** | Visual assets, layout work, design-system component creation |
| **social-strategist** | Social distribution strategy, platform-fit copy, engagement tactics |

**Cross-Lead handoffs from Content**: fact-finding → Research; technical content review → Coding/code-reviewer; compliance review → Security/privacy-steward.

**Note**: Content uses Gemini's native Search grounding (Hybrid Path A) instead of chrono-research-arsenal — see `shared/api-catalog.md:949`.

---

## sysmgmt namespace — infra, processes, the squad itself

| Specialist | Dispatch when |
|------------|---------------|
| **mac-ops** | Mac configuration, brew/launchd/system tuning |
| **personal-ops** | Operator's daily logistics, calendar, finances triage |
| **finance-analyst** | Token spend analysis, cost anomalies, per-Lead spend audits |
| **memory-curator** | Stale knowledge purge proposals, KG contradiction sweeps, memory→vault graduations |
| **knowledge-librarian** | Vault indexing, cross-reference quality, broken-link sweeps |
| **harness-optimizer** | Squad self-improvement, pattern→MCP graduation candidates, repeat-detector tuning |
| **loop-operator** | Autonomous routine work, scheduled task execution, dream-system orchestration |
| **agentops** | Agent dispatch ergonomics, prompt-cache discipline, batch-dispatch tuning |

**Cross-Lead handoffs from SysMgmt**: code quality issues found in scripts → Coding; security issues found in scripts → Security; ALWAYS CC Chrono.

---

## research namespace — deep investigation, multi-source synthesis

| Specialist | Dispatch when |
|------------|---------------|
| **research** | Multi-source web research, deep investigation. **Auto-fanout**: dispatches to N=5 source-blind specialists in parallel (perplexity / brave / arxiv / github / youtube), synthesizer adjudicates |
| **synthesizer** | Cross-document synthesis, conflict resolution between sources, executive summary generation |
| **large-context-analyst** | Long-document analysis, codebase-wide pattern recognition (uses Kimi's 2M context) |
| **data-extraction-engineer** | Structured extraction from messy sources, schema inference, data normalization |
| **learning-coach** | Operator-facing skill-building, explanation pacing, study-plan construction |

**Cross-Lead handoffs from Research**: code validation → Coding/code-reviewer; brand/market research → Content/brand-voice; threat-actor research → Security/threat-modeler.

**NOT bounty target selection** — initial "find me a bounty" discovery is Chrono direct + operator in Bounty Mode Phase 0. Research handles Phase 1 target OSINT after `target-selection.md`, plus general OSINT, technical deep-dives, multi-document synthesis, and learning new domains.

---

## Cross-cutting (any Lead can dispatch)

| Specialist | Dispatch when |
|------------|---------------|
| **planner** | Multi-step plan creation, dependency mapping, sequencing decisions (Claude + Codex multi-model) |
| **skeptic** | Adversarial review of claims/findings, hallucination detection, council-consensus on contested calls |
| **triage** | Classifying incoming items (P0-P4), routing to right Mode, duplicate detection across trackers |
| **summarizer** | Compress long artifacts into operator-facing summaries |
| **prompt-engineer** | Improving specialist prompts, prompt-cache discipline, dispatch-brief authoring |
| **vibecoding-check** | Mode-end verification (operator approval, artifacts exist, citations resolve, no TODOs, all phase-tags emitted) |

---

## Anti-patterns (what NOT to do as Coordinator)

- ❌ Run `WebFetch` yourself. Dispatch to Research/research with chrono-research-arsenal MCP, or use Chrono's Bounty Mode Phase 0 browser workflow for initial bounty discovery.
- ❌ Browse a bounty platform yourself outside Bounty Mode Phase 0. In Phase 0, Chrono attaches to the operator's Chrome at port 9222 for collaborative candidate discovery; after target selection, Security/scout owns authenticated program reading.
- ❌ Read code to look for bugs yourself. Dispatch to Coding/code-reviewer (general) or Security/security-analyst (security implications).
- ❌ Dispatch a Lead without naming a specialist. The brief must specify which specialist(s) the Lead should fan out to.
- ❌ Skip the knowledge-layer check before scout/research/discovery work. Surface vault findings inline in every brief.
- ❌ Dispatch from stale scaffold assumptions. If a specialist file fails `bin/validate-specialists.sh`, fix or route around the failing surface first.

---

## Common-confusion routing (when operator's intent is ambiguous)

| Operator says... | Wrong route | Right route |
|------------------|-------------|-------------|
| "find me a bounty" | Research or Security/scout | Chrono direct (Bounty Mode Phase 0 — Chrono + operator collaborative) |
| "look through bounties" | Research or Security/scout | Chrono direct (Bounty Mode Phase 0 — Chrono + operator collaborative) |
| "research this vulnerability" | Research | Security/security-analyst or scout |
| "research this library for our project" | Security | Research/research |
| "investigate the state of X" | Security/scout | Research/research (Research Mode) |
| "build / implement / refactor this" | Research or SysMgmt | coding namespace (Project Mode) |
| "audit this code" | Coding | Security/security-analyst |
| "review this code" | Security | Coding/code-reviewer (unless security context) |
| "write a brief about X" | Coding | Content/content-creator or technical-writer |
| "make a campaign / design an asset" | Coding | content namespace (Content Mode) |
| "X is broken / production down" | Project Mode | sysmgmt namespace (Incident Mode), with Coding cross-Lead only if code fix is needed |
| "clean up my Mac / upgrade deps / weekly cleanup" | Project Mode | sysmgmt namespace (Maintenance Mode) |
| "what's this / should I worry about this?" | Immediate Lead dispatch | Chrono direct (Triage Mode) |
| "summarize this thread" | dispatch nothing | Cross-cutting/summarizer (any Lead) |
| "make a plan" | dispatch nothing | Cross-cutting/planner (Coding default) |

When the word "research" or "scout" appears, **check the noun and phase**: initial bounty discovery → Chrono direct Phase 0; selected target context → Research Phase 1; bounty program rules / vulnerability / security topic → Security; library/domain/general → Research. When the operator is asking for mode selection rather than execution, use Triage Mode and do not dispatch a Lead until the operator confirms the route.

---

## Audit hooks

- `bin/doctor.sh` validates this index against actual `departments/*/specialists/*.md` filesystem on every run; surfaces drift in the morning brief.
- `bin/validate-specialists.sh` confirms each specialist file has filled-in tool sections and dispatch criteria; fails on scaffold placeholders.
- This index resyncs whenever a specialist is added, removed, or its dispatch criteria changes. Resync is the operator's job (or memory-curator's nightly proposal).

---

## Known debt (as of 2026-05-04)

- Generated adapter files can drift from canonical markdown unless `bin/validate-specialists.sh` and `bin/doctor.sh` catch the mismatch. Treat canonical markdown as source of truth.
- Some live API/provider routes are `auth-pending` or `needs-research`; specialists must not cite them as live until `shared/api-catalog.md` is updated from proof.
- Per-Lead generated agent directories are adapter surfaces, not canonical specialist definitions.
