---
name: project
version: 2.0
primary_mode_namespace: coding
status: active
phases: 8
---

# Mode: Project

The single build/engineering work mode — **and the home for every domain that used to be its own
mode.** Content/media, research, outreach, operations/maintenance, and reactive incident work all fold in
here as **Capabilities grouped by a `profile_family` field**, running the one S0–S7 lifecycle under the one
verification contract. Chrono controls the workflow, then dispatches the best specialist to the mapped model
lead.

## The model (`Mode → Capability → Protocol`)

There are exactly **two work modes** — `project` and `bounty`. (`advisory` is additionally accepted by
the typed contract as a compatibility mode, restricted to `result_type: normal`, but it is not a work
mode and no workflow selects it.) A consult may remain advisory in tone, but
`advisory` is not a third mode. A **Capability** is
one distinctive protocol inside a mode. The retired domain modes (`content`, `research`, `outreach`,
`maintenance`, `incident`) are now project Capabilities, tagged with a `profile_family` frontmatter field —
**not** a `profile:` schema noun (retired) and **not** a folder layer. A family tunes the default
specialists, overlays, and gates, but reuses the same lifecycle + contract.

**Gates and overlays are per-card, never per-folder.** Folding a card into `project/` does not weaken its
controls: every mode-implied gate was re-anchored onto its card (content → Truth/Rights overlay; outreach →
`live_outreach` gate; operations → delete/cleanup/credential/production gates) **before** the move, and the
capability-alias resolver preserves them for any legacy packet id. Each card's declared `capability_state`
is machine-checked by `bin/validate-capabilities.sh` against the state derived from the tool registry: a
card may declare a **more conservative** state (e.g. the zero-key `needs_tool` headline) but never one more
generous than derived. The cards are the source of truth. The **State** column below mirrors each card's
declared `capability_state`; it is a hand-maintained summary that is **not** itself validated against the
cards, so keep it in step whenever a card's state changes. Cards live in `shared/capabilities/project/`.

## Capabilities (by `profile_family`)

### Engineering (`profile_family`: engineering — the base lifecycle)

| Capability | State | When |
|---|---|---|
| [Backend service / API (server, persistence, data flows)](../capabilities/project/backend-service-api.md) | `needs_tool` | headless server / API / data-flow — protocol, persistence, concurrency |
| [Data pipeline (ETL / analytics / ML-wiring)](../capabilities/project/data-pipeline.md) | `needs_tool` | ETL / analytics plumbing, or wire data into an ML/serving system |
| [AI / LLM application (agents · RAG · tool-use · evals)](../capabilities/project/ai-llm-application.md) | `needs_tool` | ship an AI-enabled product — agents, RAG, tool-use, eval harnesses |
| [Smart-contract / web3 BUILD — EVM/Solidity](../capabilities/project/smart-contract-web3.md) | `needs_tool` | author/test/deploy EVM/Solidity contracts (non-bounty) |
| [Platform / release (CI · IaC · release rails)](../capabilities/project/platform-release.md) | `needs_tool` | CI/CD, IaC, release rails, production reliability |
| [Self-extension — MCP servers · plugins · skills · agents](../capabilities/project/self-extension-agent-tooling.md) | `needs_tool` | build or change the agent/tool platform itself |
| [Web application (browser UI / SaaS)](../capabilities/project/web-app.md) | `needs_tool` | browser-facing app / SaaS UI — browser build + required visual-verify + e2e gate |
| [Game production (browser game — design · build · playtest)](../capabilities/project/game-production.md) | `needs_tool` | browser game — mechanics/levels/narrative + build, visual-verify + e2e + human playtest sign-off |
| [Systems / low-level (cross-arch · SIMD · runtime)](../capabilities/project/systems-low-level.md) | `needs_tool` | cross-arch / SIMD / runtime — build+emulation toolchain not cataloged |

### Content / media (`profile_family`: content — **Truth/Rights overlay on any publish**)

Fires the Rule-8 truth gate (`content-verifier`) on factual claims and the Rule-6 rights/provenance gate
(`asset-provenance-and-rights-auditor`) on generated/third-party media; publish/paid-media/live-send are
operator-gated.

| Capability | State | When |
|---|---|---|
| [Editorial / technical longform](../capabilities/project/editorial-longform.md) | `needs_tool` | articles, docs, ADRs, technical longform |
| [Marketing campaign](../capabilities/project/marketing-campaign.md) | `needs_tool` | landing/product/blog copy + social — creation live, send is `needs_tool` |
| [Search / discoverability](../capabilities/project/search-discoverability.md) | `needs_tool` | on-page SEO / schema / growth — authoring live, measured impact `needs_tool` |
| [Image asset generation](../capabilities/project/image.md) | `needs_tool` | stills / graphics — governed `generate_image` wrapper (raw `higgsfield__*` forbidden) |
| [Video / motion asset generation](../capabilities/project/video.md) | `needs_tool` | video / motion — governed `generate_video` wrapper |
| [Audio assets (music · SFX · voice · interactive)](../capabilities/project/audio-assets.md) | `needs_tool` | music/SFX/voice/interactive — `generate_audio` wrapper; ElevenLabs is Claude-lane-only |

### Research (`profile_family`: research — source-first, citation-heavy)

Load-bearing web claims route through the Rule-8 grounding path — `Google Search grounding`
(gemini · yes · subscription, verified cited results); the metered `perplexity_search` is unverifiable ⇒
`needs_tool`, not PASS. Review overlay on high-impact claims.

| Capability | State | When |
|---|---|---|
| [Multi-source investigation + synthesis](../capabilities/project/investigation-synthesis.md) | `needs_tool` | deep research / competitive / literature → cited synthesis |
| [Data extraction + dataset wrangling](../capabilities/project/data-extraction-dataset.md) | `needs_tool` | machine-readable extraction/wrangling — PDF/OCR is `needs_tool` |
| [Learning + study](../capabilities/project/learning-study.md) | `needs_tool` | study plans, drills, learning paths |

### Outreach (`profile_family`: outreach — **`live_outreach` gate; no automatic send**)

Finding, qualifying, and drafting is live; the actual send is `needs_tool` + operator-gated. Privacy overlay
whenever private contact/email/calendar state is touched.

| Capability | State | When |
|---|---|---|
| [Prospecting / outreach](../capabilities/project/prospecting-outreach.md) | `needs_tool` | client-acquisition / job-search / prospecting — draft live, send is `needs_tool` + `live_outreach` |

### Operations / maintenance (`profile_family`: operations — delete/cleanup/credential/production gates)

Environment health, dependency/supply-chain integrity, memory-vault hygiene, harness audit, and personal
operations. Deletes, cleanup, credential changes, dependency-trust changes, and live-production mutation are
operator-gated (Hard Rule 6). See the Memory Curation Sweep note below.

| Capability | State | When |
|---|---|---|
| [Environment / repo health](../capabilities/project/environment-repo-health.md) | `needs_tool` | repo/env hygiene, cleanup, upgrades, refactors |
| [Dependency / release integrity](../capabilities/project/dependency-release-integrity.md) | `needs_tool` | dep trust / supply-chain / advisory — signing/attestation is `needs_tool` |
| [Memory / vault hygiene](../capabilities/project/memory-vault-hygiene.md) | `needs_tool` | durable-knowledge curation — legacy `chrono-kg` runtime-retired and protected pending migration |
| [Harness audit / compatibility](../capabilities/project/harness-audit-compatibility.md) | `needs_tool` | prompt/tool/script drift + MCP reachability (audit-only) |
| [Personal operations](../capabilities/project/personal-operations.md) | `needs_tool` | routines / reminders / draft — send + calendar-write are `needs_tool` |

### Incident (reactive, safety-critical — 0 cards)

`incident` folds in as a **mode-level reactive workflow**, not a registry Capability (it has no cards). Use
it when something is broken: stabilize with the smallest reversible fix, preserve volatile evidence and
chain of custody before changing state, and require multi-model review for security/auth/secrets/network
incidents. Reliability-only incidents lead with `site-reliability-engineer`; suspected compromise leads with
`incident-responder` (evidence-preserving, hands observed TTPs to `detection-engineer`). See the Incident
flow note under Gates.

## Flow (S0–S7)

| Phase | Work | Likely specialists |
|---|---|---|
| 0 | Scope audit / admit | Chrono direct |
| 1 | Requirements / recall | `product-manager`, `architect`; `editor`/`brand-voice` (content), `large-context-analyst` (research) |
| 2 | Design / plan | `architect`, `planner`; `security-analyst` when security-touching |
| 3 | Build / produce | domain implementation specialist for the family (see profile notes) |
| 4 | Verify | `test-engineer`, domain validators; Truth/Rights (`content-verifier`, `asset-provenance-and-rights-auditor`) on content |
| 5 | Review / hold | `code-reviewer`, `skeptic` (cross-family from the author) |
| 6 | Local deliver | `technical-writer`, `devops-engineer` — local package/report only in v1 |
| 7 | Record / clean | `memory-curator` + `chrono-vault` |

**Phase 6 missing-standard-files trigger:** when Local deliver begins and the verified repository lacks
`README.md`, `CHANGELOG.md`, `LICENSE`, or its agent-context file, load `auto-scaffold` before handoff.
It may create only the operator-approved missing files, never overwrite an existing file, and never choose
a license by default; an unanswered license choice remains an explicitly reported outstanding item.

## Profile family notes (what each folded family adds)

- **Content / media (Phase 3 asset routing):** dispatch the real media specialist for the deliverable —
  `brand-voice` (text), `image-designer` (image), `video-director`/`video-editor` (video),
  `music-composer`/`sound-designer` (music/SFX), `voice-narrator`/`voice-agent-builder` (voice),
  `interactive-audio-designer` (interactive). Media generation runs through the live
  `generate_image`/`generate_video`/`generate_audio` wrappers of the chrono-media-studio plugin — never the
  raw `higgsfield__*` tools. Pre-publication gates: `content-verifier` (Rule-8 truth) and
  `asset-provenance-and-rights-auditor` (Rule-6 rights); each emits a machine-readable gate record and a
  non-PASS/stale-hash blocks publish. Dispatch these as their named specialists — never fold the check
  inline into Chrono.
- **Research:** use primary sources; label weak sources and unresolved contradictions; citation-bearing
  output must carry enough source metadata for Chrono to verify. Fan grounded/bulk work off the Claude+Codex
  default — grounded web claims to the Gemini grounding path; bulk summarization downshifts to Kimi
  throughput (`summarizer`).
- **Outreach:** every candidate carries provenance; drafts stay draft-only until the operator approves exact
  recipients and exact wording; no automated live send by default.
- **Operations / maintenance:** cleanup proposals are not cleanup approval; one writer owns each path during
  execution; keep private/runtime artifacts out of public release.
- **Incident:** capture volatile evidence before changing state; use the smallest reversible fix first;
  security/auth/secrets/network incidents require multi-model review.

## Memory Curation Sweep (operations family)

- **Owner:** `memory-curator` (link-integrity support: `knowledge-librarian`). Chrono schedules it; the
  operator approves the housekeeping dispatch. NOT run inline by Chrono.
- **Cadence:** one general pass on the first operator session past a 30-day mark, reviewing at most the 100
  oldest `candidate` notes that are ≥30 days old. Not per-task.
- **Actions per candidate (evidence-based):** promote to `verified` only when reusable, current,
  source-backed, and review provenance exists; `invalidated` when contradicted; `superseded` (linked) when
  duplicate; `archived` when task-local/stale/non-reusable. **Never delete; never promote or invalidate from
  age, confidence, or usage-count alone.**
- **Capacity gate:** each pass reports total note count, candidate count, and the vault index size in bytes. At **10,000
  notes or 250 MiB**, stop and surface to the operator before any capture-pause or physical-retention change
  — never silent purge, never silent disable.

## Dispatch Notes

- Use `source_namespace: coding` for code specialists, but do not infer the model lead from that namespace;
  the model lead comes from `shared/routing.md`, never the folder.
- **Selection discipline (`shared/routing.md` §10):** pick the most specific Build specialist for the task
  shape — `backend-engineer` is the general default, `database-engineer` for persistence, `devops-engineer`
  for infra/tool-wiring, `performance-optimizer` for hot-paths. `systems-engineer` is ONLY for genuine
  low-level/cross-arch/SIMD/runtime work, never the catch-all.
- **Never route Phase 5 review to a Phase 4 implementer.** Review is `code-reviewer` / `skeptic` (or the
  packet `review_model`), cross-family from the author.
- Security-touching design, auth, privacy, secrets, or public release work requires review from a different
  model family.
- **`panel` / `swarm` / `triage` are dispatch mechanics, not modes** — any can be invoked under this mode.
  They select *how* work is dispatched, never *what* mode it is (mechanics described in `shared/routing.md`).
- Only one writer owns a file path at a time.

## Gates

- Operator approval before implementing a broad design.
- Operator approval before destructive changes, credential changes, dependency trust changes, cleanup
  actions, live-production mutation, public release actions, force pushes, live outreach sends, or paid media
  generation — the per-family gates above are project's subset of the held-category operator-gate tokens
  (`cleanup` · `credential_change` · `delete` · `live_outreach` · `malware_detonation` · `offensive_execution` ·
  `paid_media` · `production_mutation` · `public_release`); `malware_detonation` and `offensive_execution` are
  held for offensive work, not project-family engineering.
- Content publish fires the Truth (Rule-8) and Rights (Rule-6) gates; outreach send fires `live_outreach`.
- **Incident:** operator approval before destructive actions, rollback, credential changes, public
  disclosure, broad cleanup, or live production mutation; preserve evidence first.
- Mandatory multi-model review is governed by the four change-level triggers and the single
  distinct-family reviewer defined in `shared/protocol.md` § Mandatory Review Behavior — the one home
  for that gate and its cardinality, pinned in `scripts/python/registry_reconciler.py` and
  `bin/send-task.sh`. A content/severity list (security, privacy, auth, release, …) or `safety_level`
  never manufactures a change-level review.
- **Machine-enforced close boundary:** the final Project close packet declares
  a JSON-compatible YAML `_state/runs/<run-id>/manifest.yaml` and every newly produced file that
  manifest references in `evidence_outputs`, all inside its `write_scope`; the operator-owned approval
  record must already exist.
  The ordinary supervisor bridge promotes that declared evidence, runs
  `bash bin/vibecoding-check.sh --run-id <run-id> --quiet`, and publishes the close task's return artifact
  and settlement envelope only after a fresh matching `PASS` (or strictly attested
  `PASS-AFTER-AUTOFIX`) report. Ordinary phase packets without that exact run-bound manifest declaration
  do not trigger the mode-close gate.
