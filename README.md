<p align="center">
  <img src="assets/hero/vibe-squad-hero.svg" alt="Vibe Squad — one coordinator routes work across four model lanes" width="900">
</p>

<h1 align="center">Vibe Squad</h1>

<p align="center"><b>One coordinator. Four AI model families. Specialists that swarm — and review each other's work.</b></p>

You talk to **Chrono** in plain language; it routes your request to the best-fit specialist across four persistent model lanes, can fan the work out to a **parallel panel of specialists**, and sends review-required work to a **different model family** — with every step left as an inspectable file.

<p align="center">
  <img src="assets/media/swarm-demo.gif" alt="Two specialists run as a bounded panel and return evidence for one synthesis" width="820">
</p>

<p align="center"><sub>A “swarm”/panel runs 2–3 specialists inside one model family (Claude or Codex). The multi-model story is cross-lane routing plus a different-family reviewer — not four families debating in one panel.</sub></p>

<p align="center"><i>One front door for four model families, a validated registry of 69 specialist roles, opt-in parallel swarms, an independent second opinion on review-required work, and a paper trail made of files.</i></p>

<p align="center">
  <img alt="license AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue">
  <img alt="python 3.13" src="https://img.shields.io/badge/python-3.13-blue">
  <img alt="targeted CI checks" src="https://img.shields.io/badge/CI-targeted_checks-blue">
  <img alt="four provider lanes" src="https://img.shields.io/badge/provider_lanes-4-8a2be2">
  <img alt="69 specialist definitions" src="https://img.shields.io/badge/specialist_definitions-69-brightgreen">
  <img alt="markdown-first control plane" src="https://img.shields.io/badge/control_plane-markdown--first-orange">
</p>

Vibe Squad is a local, inspectable control plane for coordinating multiple AI coding CLIs as one team. It is designed for work that should be **bounded, observable, reviewable, and recoverable** — not for making more agents talk to one another forever.

---

## Watch it work

The demo above shows an optional panel run: two specialists start inside one Claude or Codex lane, their states remain visible, and the coordinator produces one evidence-weighted artifact. Dissent, timeouts, refusals, and missing coverage are preserved instead of being averaged away.

The example inputs and raw member returns live in [`examples/demo-run/`](examples/demo-run/). The activity ledger records panel lifecycle and batch closure; it should not be read as proof of a specific wall-clock speedup.

---

## Why Vibe Squad feels different

| | Benefit | What is real today |
|---|---|---|
| 🎛️ | **One front door, four visible lanes** | A persistent tmux session keeps Chrono, GPT/Codex, Claude, Gemini, Kimi, and watcher/status processes separately observable. |
| 🐝 | **Parallel analysis without an endless group chat** | Optional 2–3 member panels run inside Claude or Codex with quorum, deadlines, visible member states, and one accountable synthesis. |
| 🧭 | **The task chooses the model** | A canonical registry maps specialist roles to primary, backup, escalation, review, safety, and policy metadata. |
| 🔁 | **A second opinion can come from another model family** | Chrono coordinates the separate reviewer dispatch. Qualifying cross-family mandatory-review results are machine-held as `review-required` until Chrono explicitly settles them with a review response. |
| 🗂️ | **Files are the interface** | Requests and results are readable Markdown artifacts, so routing and failure states stay inspectable without a proprietary dashboard. |
| 🧠 | **Memory stays private and rebuildable** | Chrono Vault keeps Markdown notes outside the public worktree and builds a disposable lexical recall index from them. |

The guiding idea is simple: **use model diversity deliberately, then keep the evidence visible.**

---

## Flagship capability: an offensive-security research toolkit

The offensive-security research toolkit (in [`moat/`](moat/README.md)) is a public-safe set of building blocks for making JavaScript/TypeScript security research more repeatable:

- prior-work classification backed by restricted vault recall;
- JavaScript/TypeScript AST boundary scanning and a private exact-denylist scanner;
- patch/diff ingestion with human-reviewed invariant annotations;
- a vulnerable/patched synthetic twin with property-state fuzzing, coverage, controls, and structured `PASS / FAIL / INCONCLUSIVE` results;
- a hardened Docker runner with no network, a read-only root, a non-root user, resource limits, and negative egress canaries.

These are real, tested components with explicit boundaries. The synthetic wave now runs **end-to-end inside the hardened Docker runner**: a mandatory pre-flight canary must confirm the loopback control reachable while every external class (IPv4/IPv6/DNS/proxy/host-gateway/TCP-TLS) is blocked, or the run aborts — no canary, no execution. The data-free Tier-A boundary scanner runs in CI and is present in the tracked, opt-in `.githooks/pre-commit` hook (activate it per clone with `git config core.hooksPath .githooks`). **By design it stays a synthetic impact engine, not a real-deployment exploit engine**: real targets remain Layer-2 private, so the toolkit proves or refutes impact against a known-vulnerable/patched twin. That scope is intentional, not a gap. (A clearly-labeled non-isolated in-process mode remains for fast local iteration.)

---

## 69 specialist definitions, one routing source of truth

The canonical map in [`shared/specialist-runtime-map.tsv`](shared/specialist-runtime-map.tsv) describes every role's primary lane and its routing, review, safety, and policy metadata. Browse the interactive view in [`docs/routing-map.html`](docs/routing-map.html).

| Domain (namespace) | Roles | Primary lanes used | Routable today |
|---|---:|---|---:|
| Coding | 19 | Claude, Codex | all 19 |
| Content | 11 | Claude, Gemini | all 11 |
| Media production (`content-engineer`) | 10 | Gemini, Codex, Claude | all 10 |
| Security | 10 | Claude, Codex | all 10 |
| System management | 8 | Claude | all 8 |
| Shared / planning | 6 | Claude | all 6 |
| Research | 5 | Claude, Codex | all 5 |
| **Total** | **69** | **Claude 38 · Codex 20 · Gemini 11 · Kimi 0** | **69 routable, 0 catalog-only** |

**69 role definitions in one validated registry, and all 69 are dispatchable through the standard path. Kimi is a throughput-only lane and holds no primary roles.**

<details>
<summary><b>Browse all 69 specialist roles</b></summary>

### Coding

| Specialist | Domain | Primary lane | Role | Status |
|---|---|---|---|---|
| `ai-engineer` | Coding | GPT/Codex | LLM-application development — RAG pipelines, evals, agent tool design, prompt-cache strategy, multi-model routing. | routable |
| `architect` | Coding | Claude | System design, C4 models, service boundaries, interface contracts. | routable |
| `backend-engineer` | Coding | GPT/Codex | API design, async pipelines, databases, server-side implementation. Includes scraping/extraction work as bundled skills. | routable |
| `code-reviewer` | Coding | Claude | Diff-aware review with severity ladder. Spec compliance, security touchpoint check, refactor opportunity surface. | routable |
| `database-engineer` | Coding | GPT/Codex | Database architecture and operations: schema evolution, query planning, indexing, concurrency, backup/restore, replication, and zero-downtime migration. Optimizes for correctness and recoverability before benchmark speed. | routable |
| `devops-engineer` | Coding | GPT/Codex | CI/CD, Docker, deployments, cloud cost management. K8s only when target requires it. | routable |
| `frontend-engineer` | Coding | GPT/Codex | React / Vue / Svelte component work, Tailwind, build/bundling, web performance. | routable |
| `game-engineer` | Coding | GPT/Codex | Game-engine runtime implementation, gameplay state, input, physics, save systems, netcode, asset integration, builds, profiling, platform packaging, and audio-event wiring. Owns the executable runtime half of the staged game-production pipeline; does not replace game design, technical art, or asset generation. | routable |
| `performance-optimizer` | Coding | GPT/Codex | Profiling, flamegraph triage, benchmark validation, hyperfine-measured regression investigation. | routable |
| `product-manager` | Coding | Claude | Convert vague operator intent into PRDs, acceptance criteria, issue scope, roadmap tradeoffs, and "done" definitions. Used in Project Mode Phase 1 (Intake / Definition) and on-demand for scope work. | routable |
| `refactor-cleaner` | Coding | GPT/Codex | Mechanical structural cleanup — AST rewrites, dead-code elimination, import reorganization, semantic patches via Comby. Sister specialist to code-reviewer (which surfaces issues; this one applies fixes). | routable |
| `scraping-engineer` | Coding | GPT/Codex | Browser-based extraction (Playwright + browser-use), HTTP scraping, anti-bot considerations, state persistence across long scrapes. Sister to backend-engineer; lives separately because scraping has unique infrastructure needs. | routable |
| `site-reliability-engineer` | Coding | GPT/Codex | Production reliability engineering: SLOs, telemetry, capacity, incident mitigation, disaster recovery, and feedback loops that turn observed failure into tested system improvement. Distinct from `devops-engineer`, which primarily provisions infrastructure and delivery automation. | routable |
| `smart-contract-engineer` | Coding | GPT/Codex | EVM (Solidity / Vyper) and Solana (Rust / Anchor) smart contract work — audit, invariant fuzzing, symbolic execution. On-demand specialist; activates when bounty mode targets contracts or operator does crypto work. | routable |
| `software-supply-chain-engineer` | Coding | GPT/Codex | Software supply-chain integrity: dependency provenance, SBOMs, signing and verification, reproducible builds, package publication, vulnerability policy, and release integrity. Produces verifiable release evidence without taking custody of production signing secrets. | routable |
| `systems-engineer` | Coding | GPT/Codex | Low-level C/C++/Rust work, cross-architecture builds, NUMA-aware threading, SIMD porting, hardware-specific optimization. Optional specialist — most operator work doesn't reach this level. | routable |
| `technical-artist` | Coding | GPT/Codex | Real-time graphics and asset-pipeline engineering: shaders, materials, rigs, GLTF/USD interchange, LODs, WebGL/GPU performance, engine asset import, and conversion of generated art into runtime-safe assets. Bridges visual intent to measurable runtime constraints. | routable |
| `test-engineer` | Coding | GPT/Codex | Unit + property + e2e + flake-triage. Merged from chrono's qa-tester + e2e-runner — one specialist owns the whole testing surface. | routable |
| `ui-engineer` | Coding | GPT/Codex | Technical UI work — figma-to-code fidelity, design tokens, accessibility audits, visual regression. Lives next to frontend-engineer; the split is "frontend builds the framework code, UI engineer ensures the design implementation is correct." | routable |

### Content

| Specialist | Domain | Primary lane | Role | Status |
|---|---|---|---|---|
| `accessibility-engineer` | Content | Gemini | WCAG/ARIA conformance, keyboard navigation, contrast, and accessible-media production (captions, transcripts, alt-text). A cross-cutting acceptance gate over shipped UI and generated media. | routable |
| `asset-provenance-and-rights-auditor` | Content | Claude | Pre-publication rights gate (Hard Rule 6): license, consent, provenance, watermark, trademark, voice/face-likeness, and usage-terms fit for generated or third-party media before it is published or sold. Surfaces legal uncertainty; does not give legal advice. | routable |
| `brand-voice` | Content | Claude | Brand strategy, tone consistency, content principles. The "what would this brand say?" specialist. | routable |
| `content-verifier` | Content | Claude | Pre-publication truth gate (Hard Rule 8): verifies facts, statistics, and citations; flags hallucinated sources and unverifiable provider claims. Verifies and adjudicates evidence — does not rewrite. | routable |
| `editor` | Content | Claude | Long-form editing, copywriting, structure/flow review. Bundled: brand-voice consistency check (when invoked with that mode flag), copywriting (marketing/social/email). | routable |
| `growth-and-search-analyst` | Content | Gemini | Technical SEO and search growth: keyword research/clustering, JSON-LD/structured-data schema, meta/metadata, and Search Console/analytics interpretation. Gemini-primary for native Google Search grounding. | routable |
| `interactive-audio-designer` | Content | Claude | The interactive layer over generated audio assets: adaptive music, dynamic SFX systems, spatial audio, mix/ducking, audio state machines, event-wiring, loop-point authoring, and memory/format budgets. Design authority in the staged game-production pipeline; does not render assets or write engine code. | routable |
| `level-narrative-designer` | Content | Claude | Level design, narrative and quest/story structure, and level-specific pacing for the staged game-production pipeline. Turns the game-designer's mechanics/experience contract into playable structure and story. | routable |
| `localization-specialist` | Content | Claude | Dialect/idiom translation and cultural adaptation, locale QA, regional-compliance flagging, and terminology-memory maintenance. Adapts meaning and tone for a market — not word-for-word translation. | routable |
| `social-strategist` | Content | Gemini | Social media planning, posting cadence, platform-specific tactics, engagement strategies. | routable |
| `technical-writer` | Content | Claude | Changelogs, ADRs (architecture decision records), post-spec handoffs, documentation. The technical-content equivalent of editor. | routable |

### Media production

| Specialist | Domain | Primary lane | Role | Status |
|---|---|---|---|---|
| `copywriter` | Media production | Gemini | Write short-form and long-form text content: marketing copy, landing pages, email campaigns, ad copy, blog articles, product descriptions, case studies. Match the operator's voice (direct, vibecoded, honest). Research references and brand context before drafting. When writing marketing copy for a project, read the project brief and any handoffs first. | routable |
| `game-designer` | Media production | Claude | Pipeline director for browser-based games: owns mechanics, player experience, and economy/progression design, and orchestrates the staged production pipeline. Produces the design contract the rest of the pipeline builds from; does not implement, render, or deploy. | routable |
| `image-designer` | Media production | Gemini | Generate original images for marketing, product, editorial, and design use. Write detailed visual briefs with composition, mood, style, and technical requirements. Upscale to required resolutions (2K, 4K, print). Edit and composite multiple images. Expand/uncrop frames for layout needs. Iterate on color, lighting, and visual hierarchy. | routable |
| `music-composer` | Media production | Gemini | Create original background music, theme tracks, and video accompaniment. Transform video narratives into matching musical scores. Write brief on mood, tempo, instrumentation preferences before generating. Iterate on pacing and emotional arc. | routable |
| `sound-designer` | Media production | Gemini | Create sound effects, ambient soundscapes, and audio branding elements. Generate SFX for interface interactions, motion sequences, and atmospheric audio layers. Layer multiple SFX sources for rich, dimensional sound design. Coordinate timing with video-director on visual sync points. | routable |
| `video-director` | Media production | Gemini | Generate video sequences and orchestrate motion across scenes. Write video briefs with scene descriptions, timing, motion requirements, and creative direction. Use virality predictor to validate hook strength and engagement risk. Coordinate narration timing with voice-narrator. Iterate on pacing, visual effects, and emotional arc. | routable |
| `video-editor` | Media production | Gemini | Post-production on video sequences: reframe for different aspect ratios (TikTok, YouTube Shorts, 16:9, square), upscale to 2K/4K, expand/uncrop frames for platform requirements. Polish visual composition and technical quality. Iterate on colors, timing, and output formats for multiple platforms. | routable |
| `voice-agent-builder` | Media production | Gemini | Create conversational AI agents using ElevenLabs: customer service bots, sales assistants, educational tutors, content narrators with interactivity. Write agent briefs (personality, knowledge domain, conversation flows). Integrate knowledge bases from docs or KGs. Configure voice, tone, and response patterns. Test conversation loops and edge cases. Deploy and monitor live agents. | routable |
| `voice-narrator` | Media production | Gemini | Convert written content to professional voiceover narration. Select or clone voices to match tone and audience. Produce clean, well-paced TTS output for explainer videos, podcasts, audiobooks, and narrated tutorials. Coordinate with video-director on pacing and timing. | routable |
| `web-builder` | Media production | GPT/Codex | Generate and deploy websites, landing pages, and web applications. Compose pages from copywriter and image-designer assets. Integrate Figma design systems and Firebase backend. Manage deployment configs, DNS, and hosting. Write clean, accessible HTML/CSS with performance optimization. Iterate on responsive design and user experience across devices. | routable |

### Security

| Specialist | Domain | Primary lane | Role | Status |
|---|---|---|---|---|
| `detection-engineer` | Security | Claude | Detection-as-code: SIEM rules, signatures, analytics, and threat-detection content, plus coverage-gap analysis against a known TTP set (e.g. ATT&CK). Defensive product; models attacker behavior only to detect it. | routable |
| `exploit-developer` | Security | GPT/Codex | PoC development, binary RE, fuzzing, symbolic execution. Bounty Mode Phase 6/7/8. Multi-model is the central pattern: Codex AND Claude attempt independently. | routable |
| `impact-validator` | Security | Claude | CVSS v4.0 scoring, CWE policy check, NVD/OSV calibration, duplicate detection, self-inflicted detector, and — first and foremost — the **mandatory G1–G4 pre-submit gate**, the terminal go/no-go I run before greenlighting any bounty submission (see the very next section). Bounty Mode Phase 10. | routable |
| `incident-responder` | Security | Claude | Defensive incident handling: detection triage, containment, forensics, eradication, recovery, and post-incident review. Leads once compromise is suspected; plans and recommends live actions, which the operator authorizes. | routable |
| `privacy-steward` | Security | Claude | Tool permissions, data-retention paths, mailbox/vault leakage prevention, PII handling, secret exposure, OAuth scopes, "should this agent be allowed to act?" policies. | routable |
| `red-team-operator` | Security | GPT/Codex | Plan, coordinate, and execute authorized end-to-end adversary-emulation engagements. Exercise realistic attack paths—including scoped lateral movement and detection-evasion testing—to validate security controls, response readiness, and business-impact assumptions. Produce reproducible evidence and remediation-oriented reporting without exceeding the engagement's written authorization. | routable |
| `reverse-engineer` | Security | Claude | Analyze binaries, malware, packed or obfuscated artifacts, and firmware to explain structure, behavior, provenance indicators, vulnerabilities, and defensive implications. Support authorized vulnerability research and bug-bounty work, incident response, detection engineering, and remediation without turning analysis into unauthorized deployment or operational abuse. | routable |
| `scout` | Security | Claude | Recon, subdomain enumeration, attack-surface mapping, program scope. Bounty Mode Phase 2 (Program Scope) and Phase 3 (active recon). | routable |
| `security-analyst` | Security | Claude | SAST scans, supply-chain audits, OSINT, agentic-safety analysis. Bounty Mode Phase 3/4, also on-demand for any security-sensitive code review. | routable |
| `threat-modeler` | Security | Claude | Repository-grounded threat modeling — trust boundaries, abuse cases, threat-model loops. Bounty Mode Phase 4, Project Mode Phase 2 (when security-touching), on-demand. | routable |

### System management

| Specialist | Domain | Primary lane | Role | Status |
|---|---|---|---|---|
| `agentops` | System management | Claude | Observability, tracing, cost monitoring for the assistant itself. Owns runtime, doctor, status, mailbox, and process-drift detection. | routable |
| `finance-analyst` | System management | Claude | Subscriptions, invoices, budgets, tax-doc organization, spend summaries. Read-only by default — no transaction authority unless operator explicitly grants. | routable |
| `harness-optimizer` | System management | Claude | Audit and improve the assistant's own harness configuration — hooks, evals, model routing, context discipline, safety gates. Owns prompt, generated-adapter, tool-catalog, validator, and script-drift detection. The mechanics arm of dreaming (paired with memory-curator's interpretation arm). | routable |
| `knowledge-librarian` | System management | Claude | Operator's reading queue, bookmarks, PDFs, Obsidian curation, long-term knowledge organization. Distinct from memory-curator (which manages assistant's KG); this manages the operator's personal knowledge workspace. | routable |
| `loop-operator` | System management | Claude | Run autonomous agent loops with explicit stop conditions, checkpoint progress, detect stalls, intervene safely when a loop fails to advance. | routable |
| `mac-ops` | System management | Claude | Brew/npm/pip update checks, disk/memory/network monitoring, Hammerspoon, launchd, fswatch, osascript — local Mac automation and machine health. | routable |
| `memory-curator` | System management | Claude | Owns the assistant's KG vault health, brain-map hygiene, memory/vault source-of-truth clarity, dreaming system, instinct pruning, and stale knowledge purge. The interpretation arm of nightly self-review (paired with harness-optimizer for mechanics). | routable |
| `personal-ops` | System management | Claude | Calendar, reminders, todos, daily logistics, weekly review, email triage, lifestyle-concierge work. The "operations assistant for your life" specialist. | routable |

### Shared / planning

| Specialist | Domain | Primary lane | Role | Status |
|---|---|---|---|---|
| `planner` | Shared / planning | Claude | Goal decomposition: turn a multi-week / multi-component goal into ordered phases, milestones, and explicit dependencies. Used in any mode that needs upfront planning beyond a single-task request. | routable |
| `prompt-engineer` | Shared / planning | Claude | Prompt linting, few-shot curation, regression suites, system-prompt compression. Used by any model lead when their specialists' prompts need tuning. | routable |
| `skeptic` | Shared / planning | Claude | Epistemic audit + cross-model verification + council-consensus (the absorbed challenger functionality). Used by every model lead. | routable |
| `summarizer` | Shared / planning | Claude | Compresses old context into compact summaries so long-running model lead sessions don't bloat their context windows. | routable |
| `triage` | Shared / planning | Claude | Classify incoming work, route to right mode and model lead, surface routing decision to Coordinator. Used inside Triage Mode and on-demand when Coordinator is uncertain where to send a task. | routable |
| `vibecoding-check` | Shared / planning | Claude | Mode-exit contract verifier. Mechanically verifies that promises a mode made were satisfied before it can declare itself "done." | routable |

### Research

| Specialist | Domain | Primary lane | Role | Status |
|---|---|---|---|---|
| `data-extraction-engineer` | Research | GPT/Codex | PDF parsing, dataset wrangling, table extraction, structured-data normalization. Sister to scraping-engineer (Coding) — that one is web-focused; this one is document-focused. | routable |
| `large-context-analyst` | Research | Claude | 1M-2M context full-codebase / multi-doc / multi-repo synthesis. Kimi K2's 2M context shines here. | routable |
| `learning-coach` | Research | Claude | Study plans, drills, spaced repetition, reading ladders, progress checks. For when operator wants to learn something new (a framework, a topic, a skill). | routable |
| `research` | Research | Claude | Source discovery, multi-source synthesis, claim validation, citation. The primary research specialist (sister to large-context-analyst for synthesis and skeptic for verification). | routable |
| `synthesizer` | Research | Claude | Aggregate parallel-fan-out trajectories from multiple specialists/models into a unified report. Preserves outliers — minority findings don't disappear. | routable |

</details>

---

## Try it in about a minute

If the four provider CLIs are already installed and logged in:

```bash
# from a clone of this repository
cd claude-vibe-squad
bin/squad up --safe
```

That opens a persistent tmux control room. Move to the `chrono` window and ask for work in plain language.

```text
Ctrl-b 0  chrono       Ctrl-b 3  gemini
Ctrl-b 1  gpt-codex    Ctrl-b 4  kimi
Ctrl-b 2  claude       Ctrl-b 5  watchers/status
Ctrl-b d  detach — the lanes keep running
```

```bash
bin/squad doctor   # check the local setup
bin/squad status   # see what each lane is doing
bin/squad stop     # stop the session
```

> [!IMPORTANT]
> Start with `--safe`. Running `bin/squad up` without it uses the autonomous daily-driver profile, which launches model CLIs with bypass/yolo-style permissions after a one-time warning and health check. Review the scopes and workflow before using that profile.

**Prerequisites:** macOS, tmux, `fswatch`, `jq`, `curl`, logged-in Claude Code, Codex, Gemini, and Kimi CLIs, and Python 3.13 for the vendored MCP servers and optional daemon.

---

## How it works

<p align="center">
  <img src="assets/media/dispatch-demo.gif" alt="One plain-language request becomes a typed task packet, routes to a lane by capability, and returns as an inspectable file inside a declared write scope" width="820">
</p>

<p align="center">
  <img src="assets/hero/architecture-lanes.svg" alt="Chrono routes task packets to four persistent provider lanes and coordinates a separate review path" width="820">
</p>

```text
request
  │
  ▼
Chrono
  │  choose role · lane · scope · review metadata
  ▼
packet validation ──▶ department inbox ──▶ lane + specialist adapter
                                                │
                                                ▼
                                      result artifact / outbox
                                                │
                                                ▼
                                      completion queue ──▶ Chrono
```

1. **Ask once.** Chrono turns a plain-language goal into a typed Markdown task packet.
2. **Route by capability.** The specialist registry selects a primary model lane; the mailbox folder is only an organizational namespace.
3. **Execute visibly.** A persistent lane reads the packet and its specialist instructions. An optional panel can collect multiple same-family specialist views under a deadline.
4. **Return durable work.** The lane writes its response envelope and requested artifact; the live outbox watcher reconciles that envelope and brings completion back to Chrono.
5. **Review when needed.** Chrono dispatches the separate reviewer. Qualifying cross-family mandatory-review results remain held as `review-required` until Chrono explicitly settles them with a review response.

Current dispatch deliberately leaves git untouched. Repository history still contains more than 100 task-checkpoint commits from an earlier workflow:

```bash
git log --oneline --grep='auto-snapshot: before TASK-'
```

### The Markdown mailbox

<p align="center">
  <img src="assets/hero/mailbox-flow.svg" alt="A Markdown task packet moves from Chrono through an inbox to a model lane and returns through an outbox" width="760">
</p>

The mailbox is the control plane. Chrono writes a packet to a department inbox, the selected lane receives a terminal nudge, and the result returns as an artifact. The files remain easy to inspect, diff, archive, and debug. The FastAPI service in [`daemon/`](daemon/) is optional supporting infrastructure, not the primary dispatch path.

### Parallel panels and independent review

- **Panels** gather 2–3 specialist perspectives concurrently inside one Claude or Codex lane. They are bounded by quorum and deadlines, and the coordinator is the only writer of the final artifact.
- **Fan-out** is a distinct, opt-in panel mode that runs the same specialist 2–3 times on different assignments; the coordinator remains the sole writer. It is enabled for Claude, gated for Codex, and excludes Gemini/Kimi because their subagents lose MCP access.
- **Independent review** is a separate Chrono-coordinated dispatch. For qualifying cross-family mandatory-review work, the runtime holds the original result as `review-required` until Chrono explicitly settles it with a review response. The runtime does not launch the reviewer or infer verdict authority.

<p align="center">
  <img src="assets/hero/review-loop.svg" alt="A risky result can take a separate review path through another model family before Chrono synthesizes it" width="700">
</p>

> Chrono launches the review separately. For qualifying cross-family mandatory-review work, the runtime holds the original result as `review-required` until Chrono explicitly settles it with a review response; it does not auto-launch the reviewer or infer verdict authority.

Safety refusals remain visible and are not rerouted to search for a more permissive answer. Operational failures such as timeouts are handled separately.

<details>
<summary><b>Panel contract</b></summary>

```bash
bin/send-task.sh <task-file> \
  --panel code-reviewer,security-analyst \
  --panel-quorum all \
  --panel-timeout 900
```

- Supported lanes: `claude` and `gpt-codex`.
- Panel size: 2–3 members; nested panels are prohibited.
- Collection uses monotonic and wall-clock deadlines.
- Late, failed, refused, and timed-out members remain explicit coverage gaps.
- Synthesis is evidence-weighted, not a majority vote.

See [`shared/modes/panel.md`](shared/modes/panel.md) and [`bin/panel-activity.sh`](bin/panel-activity.sh).

</details>

---

## Private-by-construction memory

[`chrono-vault`](plugins/chrono-vault/README.md) gives the coordinator durable recall without placing private notes in the public repository:

- private Markdown notes remain the source of truth;
- a locked FTS5/BM25 index can be rebuilt from those notes;
- content hashes, lifecycle revisions, provenance, and sensitivity clearance travel with recall;
- recalled snippets are quoted as untrusted evidence, not treated as instructions;
- explicit usage feedback records whether a recalled note helped.

The loop is explicit rather than magical: the live watcher now reconciles lane completion envelopes and auto-captures responses, while usage feedback does not automatically change ranking. Chrono Vault is lexical memory, not a vector database or knowledge graph.

---

## What is shipped, opt-in, and still policy-level

| Capability | Status | Important boundary |
|---|---|---|
| tmux + Markdown dispatch | **Wired** | Local provider CLIs are required. |
| specialist registry and validator | **Wired** | All 69 catalog roles validate and dispatch through the standard path. |
| parallel panels and terminal status | **Wired, opt-in per task** | Panels are collection, not independent review; fan-out is Claude-enabled, Codex-gated, and excludes Gemini/Kimi. |
| cross-family review | **Machine-enforced hold** | Qualifying results wait as `review-required` for explicit Chrono settlement with a review response; reviewer dispatch is still separate. |
| Chrono Vault | **Implemented** | Completion-envelope capture is wired; recall and usage feedback remain explicit. |
| automatic failover controller | **Implemented, dormant/opt-in** | Requires explicit enablement and separate recurrent monitoring. |
| Offensive-security research toolkit (`moat/`) | **Synthetic path wired** | The synthetic twin runs inside the hardened isolated runner; real targets intentionally remain private Layer 2. |
| FastAPI daemon | **Optional** | Auxiliary state and endpoints; not the dispatch spine. |

This vocabulary is intentional. Vibe Squad aims to show failures and boundaries instead of hiding them behind a polished demo.

---

## Tools and repository tour

<details>
<summary><b>Vendored tools</b></summary>

The repository includes MCP servers for private memory, research helpers, media generation, and reconnaissance. Availability varies by credentials and lane; [`shared/api-catalog.md`](shared/api-catalog.md) records verified and unverified capabilities.

- [`plugins/chrono-vault/`](plugins/chrono-vault/) — private Markdown memory and lexical recall;
- [`plugins/chrono-research-arsenal/`](plugins/chrono-research-arsenal/) — research-provider wrappers;
- [`plugins/chrono-content-engineer/`](plugins/chrono-content-engineer/) — image, video, and audio entry points;
- [`plugins/chrono-recon/`](plugins/chrono-recon/) — DNS, WHOIS, certificate-transparency, Wayback, and repository-search helpers.

</details>

<details>
<summary><b>Repository map</b></summary>

| Path | Purpose |
|---|---|
| `bin/squad`, `bin/launch-squad.sh` | Canonical lifecycle CLI and six-window tmux launcher (`bin/vibe-squad` remains a compatibility alias). |
| `scripts/send-task.sh`, `bin/send-task.sh` | Packet generation, validation, registry checks, delivery, and lane nudge |
| `shared/specialist-runtime-map.tsv` | Canonical specialist routing data |
| `shared/routing.md`, `shared/protocol.md` | Routing, packet, lifecycle, and review contracts |
| `departments/*/specialists/` | Canonical specialist briefs |
| `departments/*/inbox/`, `departments/*/outbox/` | Local Markdown dispatch board |
| `plugins/chrono-vault/` | Private memory and lexical recall |
| `moat/` | Synthetic offensive-security research components |
| `daemon/` | Optional FastAPI support service |
| `docs/` | Architecture, runtime, specialist, and operating guides |

</details>

<details>
<summary><b>Implementation boundaries worth knowing</b></summary>

- Inbox publication uses a same-directory temporary file, file `fsync`, and atomic rename.
- Declared write scopes are checked for overlap; they are not OS-level sandboxes.
- Operator approval fields remain policy metadata. Qualifying cross-family mandatory-review completions have a machine-enforced hold, but this is workflow enforcement rather than an OS-level authorization boundary.
- The public CI workflow runs targeted validation, not every test suite in the repository.
- The generated `model-lanes/ROSTER.md` view was regenerated from the TSV; the TSV remains canonical.

</details>

---

## Built through its own workflow

Vibe Squad has been used to design and review Vibe Squad. Natural-language goals became scoped task packets, different lanes handled implementation and judgment work, and the resulting artifacts fed the next iteration.

The repository preserves more than 100 historical `auto-snapshot: before TASK-…` checkpoint commits from an earlier workflow. Current dispatch intentionally does **not** auto-commit, so the honest receipt is the history itself — not a promise about today's runtime.

> **A multi-model control plane developed through the same multi-model workflow it exposes.**

---

## Contributing

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md). Architecture and operating guides live under [`docs/`](docs/), and [`docs/adding-a-specialist.md`](docs/adding-a-specialist.md) explains how to extend the role catalog.

## License

AGPL-3.0. See [`LICENSE`](LICENSE).
