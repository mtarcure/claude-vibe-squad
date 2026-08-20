---
id: TASK-2026-08-18-1427-8882b0f0-response
in_response_to: TASK-2026-08-18-1427-8882b0f0
from: claude
to: chrono
type: RESULT
status: complete
return_artifact: departments/sysmgmt/outbox/TASK-2026-08-18-1427-8882b0f0-response.md
---

Classified all **130** unwired `shared/skills/*.md` files (a superset of the operator's "124" — see reconciliation) into exactly one bucket each: **WIRE 98 · MERGE 11 · STUB 21 · LEGACY 0 · DELETE 0**. The headline finding overturns the "some are legacy/expired/junk" premise: there is **no dead weight** here. The waste is (a) 21 unfinished 8-line stubs and (b) 11 genuine overlaps that would double-fire against an already-wired skill — the rest are complete, distinct methods whose only gap is a missing `description:` trigger. Wiring the backlog is therefore mostly a *description-authoring* exercise, not a content one — and the tool for it (`skill-description-trigger-authoring`) is itself sitting unwired in the backlog. This packet is classification only; no files were moved, wired, or deleted.

---

## 0. Count reconciliation (why 130, not 124)

`shared/skills/` holds **135** `*.md` files. Of the 8 skills currently wired under `.claude/skills/`, only **5** have a `shared/skills` source (`chain-construct`, `claim-verification`, `data-flow-trace`, `dedup-prior-art-check`, `visual-verify`) — the other three (`probe-canary`, `systematic-attacking`, `systematic-bug-hunting`) come from the **superpowers plugin** and have no `shared/skills` file. So `135 − 5 = **130**` unwired shared-skill files. The operator's "124" is an earlier/looser count; I classified all 130 so nothing is silently dropped. Status breakdown matches the brief: **21** `status: stub`, **113** `authored`, **1** with *no* `status` field (`solana-anchor-audit-checklist`, which nonetheless has real content).

## 1. Bucket totals

| Bucket | Count | Meaning |
|---|---|---|
| **WIRE** | 98 | Real, distinct, plausibly used — wire it (author a trigger description). |
| **MERGE** | 11 | Duplicates/overlaps a survivor's trigger — do not wire on the claude lane. |
| **STUB** | 21 | 8-line placeholder, no workflow to trigger to. |
| **LEGACY** | 0 | Nothing describes a fully-retired workflow with a namable killer (see §4). |
| **DELETE** | 0 | Nothing is valueless junk (redundancy here is MERGE/STUB, not junk). |
| **TOTAL** | **130** | |

## 2. Full classification (130 rows, alphabetical)

`skill | bucket | reason | survivor (MERGE only)`

| skill | bucket | reason | survivor |
|---|---|---|---|
| accessible-media-authoring | WIRE | Author alt-text/captions/transcripts for media; distinct from wcag-conformance-audit. [T5] | — |
| agent-prompt-engineering | WIRE | Design an agent's system prompt/instruction set. [T6] | — |
| agentic-safety-audit | WIRE | LLM-agent-in-the-loop failure-mode audit. [T2] | — |
| agentic-sandbox-escape | WIRE | Configuration-based sandbox escape (CBSE) audit of AI coding agents. [T2] | — |
| attack-coverage-map | WIRE | Detection coverage vs ATT&CK; gap analysis. [T7-blue] | — |
| audio-event-map-authoring | WIRE | Typed game-event→audio-cue contract for the engine. [T7] | — |
| audio-layering-techniques | WIRE | Layer a sound without masking/phase issues. [T7] | — |
| audio-production-basics | WIRE | Capture/edit/mix/master chain with honest levels. [T7] | — |
| audit-context-prep | STUB | 8-line placeholder; topic already covered by pre-audit-threat-model + audit-context-building plugin if ever finished. | — |
| auto-scaffold | WIRE | S6 delivery scaffolding (README/CHANGELOG/LICENSE/agent-context); refs shared/modes/project.md (exists). [T4] | — |
| behavior-preservation-test | STUB | 8-line placeholder; no workflow to trigger to. | — |
| chain-construct-smart-contract | WIRE | On-chain exploit-chain specialization proven with Forge/LiteSVM; distinct trigger from generic chain-construct. [T1] | — |
| chain-impact-rescore | MERGE | Forward-chaining-to-impact restates chain-construct's "compose weak observations into an impact-proving chain" trigger; fold its "keep chaining past critical" stance in. | chain-construct |
| citation-audit | MERGE | "Resolve each citation and confirm it supports the claim" is claim-verification's evidence-span check on already-cited content. | claim-verification |
| cite-properly | MERGE | Trigger "when an artifact makes factual claims" collides head-on with wired claim-verification; fold its citation-form table in. | claim-verification |
| claim-validation-gate | MERGE | "Refuse to let an unverified assertion leave…every claim carries its evidence" = claim-verification's decompose+verify gate. | claim-verification |
| code-reachability-audit | WIRE | Prove dead-code before deletion; absence-claim discipline. [T3] | — |
| code-review-loop | WIRE | Run a review as a bounded converging loop; distinct from superpowers request/receive. [T4] | — |
| color-grading-basics | WIRE | Grade video with scopes, correct-then-stylize. [T6] | — |
| color-theory | WIRE | Choose a color system by harmony/contrast/meaning. [T5] | — |
| composition-rules | WIRE | Arrange a frame for focal point, balance, flow. [T5] | — |
| consent-and-likeness-check | WIRE | Verify consent for assets resembling a real person. [T5] | — |
| conversation-design | WIRE | Voice/chat dialogue flow incl. recovery. [T6] | — |
| copy-refinement | WIRE | Tighten copy without changing meaning. [T7] | — |
| cosmos-sdk-audit-checklist | WIRE | Cosmos-SDK/CometBFT bug-class checklist; distinct chain we audit. [T1] | — |
| cross-arch-test-discipline | STUB | 8-line placeholder. | — |
| cross-chain-bridge-audit | WIRE | Bridge observe→attest→execute audit; survivor of the DVN merge. [T1] | — |
| cross-chain-dvn-audit | MERGE | DVN single-signer/weak-quorum forgery is a subset of cross-chain-bridge-audit's "Quorum soundness" + "forge an attestation" classes; fold its LayerZero cast recipe in. | cross-chain-bridge-audit |
| cross-file-relationship-synthesis | WIRE | Turn independently-read files into a traced-edge relationship map. [T4] | — |
| data-cleaning-pipeline | STUB | 8-line placeholder. | — |
| defensive-pattern-discovery | WIRE | Remediation/impl partner to the offensive audit skills. [T4] | — |
| defi-invariant-check | WIRE | DeFi invariant authoring/testing (echidna/medusa/forge/halmos); sub-skill of evm-audit-flow. [T1] | — |
| dependency-cycle-audit | WIRE | Detect/break dependency cycles at the granularity the loader enforces. [T4] | — |
| dependency-health-triage | WIRE | Turn a scanner dump into a ranked actionable dependency list. [T4] | — |
| detection-as-code | WIRE | Author SIEM/EDR detection rules as tested code. [T7-blue] | — |
| detection-tuning | WIRE | Reduce a rule's FP/FN with evidence. [T7-blue] | — |
| diff-aware-semgrep-scan | WIRE | Diff/baseline-scoped Semgrep so signal survives a legacy baseline. [T4] | — |
| differential-review | WIRE | Before/after behavior-diff review; note interactive-session plugin overlap. [T4] | — |
| dimensional-analysis-check | WIRE | Catch unit/scale/base/precision errors across boundaries. [T3] | — |
| dual-level-retrieval | WIRE | Coarse-then-fine retrieval so breadth keeps quoting accuracy. [T4] | — |
| durable-nonce-exploitation | WIRE | Solana durable-nonce pre-sign abuse audit. [T2] | — |
| erc1271-revert-data-check | WIRE | ERC-1271 revert-data confusion auth-bypass class. [T2] | — |
| error-based-ssti | WIRE | Blind SSTI/code-injection via forced runtime errors. [T2] | — |
| eval-harness-pattern | STUB | 8-line placeholder. | — |
| evidence-chain-preservation | STUB | 8-line placeholder; overlaps cite-properly/claim-verification if finished. | — |
| evm-audit-flow | WIRE | Stateful EVM audit pipeline on native CLIs; already migrated off the retired KG. [T1] | — |
| figma-implement-design | WIRE | Faithful Figma→code translation; note figma-plugin overlap. [T5] | — |
| findings-filter | WIRE | Reproduce/reachability/impact/precondition/dedup gate on candidate findings. [T1] | — |
| forensic-timeline-authoring | WIRE | Evidence-preserving incident timeline. [T7-blue] | — |
| game-design-fundamentals | WIRE | Concept → game-design contract (core loop, pillars). [T6] | — |
| game-mechanics-balancing | WIRE | Tune systems by model for fairness/curve. [T6] | — |
| gas-optimization-pattern | STUB | 8-line placeholder. | — |
| gptscan-prompt-templates | WIRE | Prompt shapes for LLM-driven smart-contract review. [T4] | — |
| head-tail | WIRE | Sample a too-large file from both ends; general utility with a real description. [T7] | — |
| incident-response-runbook | WIRE | Triage→contain→eradicate→recover→review. [T7-blue] | — |
| interactive-audio-design | WIRE | Adaptive music/SFX/state machines; note stale bin/randomization ref. [T7] | — |
| interface-ambiguity-check | WIRE | Surface assumptions before coding to a foreign interface/schema. [T3] | — |
| keyword-clustering | WIRE | Group keywords by search intent → pages. [T7] | — |
| knowledge-base-integration | WIRE | Wire an agent to a retrieval KB with honest coverage. [T4] | — |
| known-advisory-backport-check | WIRE | Forked/pinned-dependency missed-patch enumeration. [T1] | — |
| layered-analysis-loop | WIRE | Analyze in one-question passes; depth on a stable base. [T4] | — |
| level-design-patterns | WIRE | Contract → playable level structure/pacing/gating. [T6] | — |
| locale-adaptation | WIRE | Adapt content by meaning/tone for a locale. [T7] | — |
| mcp-reachability-audit | STUB | 8-line placeholder; overlaps wirework-preflight's MCP-reachability step if finished. | — |
| mcp-schema-poisoning | WIRE | MCP tool/schema/output poisoning audit; novel LLM-security class. [T2] | — |
| multi-agent-evidence-gating | MERGE | "Never surface until a sandboxed negative-controlled PoC confirms" = systematic-attacking's iron law #2; fold its 4-predicate gate in. | systematic-attacking |
| multi-stance-audit-fanout | WIRE | Eight-persona Solidity audit fan-out; Chrono-orchestrated. [T4] | — |
| music-production-basics | WIRE | Musical idea → finished track. [T7] | — |
| narrative-pacing | WIRE | Rhythm of a linear piece (video/story/deck). [T6] | — |
| narrative-structure | WIRE | Game story arc/quest graph/dialogue outline. [T6] | — |
| osint-platform-audit | WIRE | Public-source external footprint → exposure inventory. [T7] | — |
| parser-differential-route-confusion | WIRE | Route/permission desync across gateways/routers. [T2] | — |
| platform-compliance | WIRE | Fit a media deliverable to a platform's specs/policy before publish. [T5] | — |
| player-engagement-psychology | WIRE | Honest intrinsic-motivation/retention design. [T6] | — |
| pre-audit-threat-model | WIRE | Solidity audit-prep x-ray; "first skill on any engagement"; distinct from defensive security-threat-model. [T1] | — |
| program-rubric-lookup | WIRE | Map a finding to the program's payout rubric/severity language; bounty-critical. [T1] | — |
| prompt-cache-discipline | STUB | 8-line placeholder; per-"Lead"/dispatch-shape framing partly superseded by per-specialist model binding. | — |
| prompt-cache-hit-monitoring | STUB | 8-line placeholder; per-Lead cache dashboards; low likelihood we build this. | — |
| rate-limit-respect | STUB | 8-line placeholder. | — |
| read-only-reentrancy-check | WIRE | Read-only reentrancy audit class; distinct EVM technique. [T2] | — |
| refactor-scope-bounding | STUB | 8-line placeholder. | — |
| regional-compliance-check | WIRE | Flag locale legal/cultural content constraints. [T7] | — |
| regression-bisect-flow | STUB | 8-line placeholder. | — |
| representative-workload-design | STUB | 8-line placeholder. | — |
| requirements-elicitation | WIRE | Extract testable requirements from a vague ask; distinct from brainstorming. [T3] | — |
| responsive-design | WIRE | Content-out responsive layout across viewports/inputs. [T5] | — |
| review-severity-ladder | WIRE | Shared severity ladder; referenced by security-threat-model. [T1] | — |
| rights-and-provenance-gate | WIRE | Hard-Rule-6 pre-publication rights gate emitting a gate record. [T5] | — |
| rollback-test-coverage | STUB | 8-line placeholder. | — |
| sandbox-provision-discipline | STUB | 8-line placeholder. | — |
| schema-inference | STUB | 8-line placeholder. | — |
| scope-decomposition | WIRE | Break an ambiguous ask into bounded verifiable units. [T3] | — |
| scope-estimation | WIRE | Measure the corpus before analyzing; size confidence to what was read. [T3] | — |
| secret-rotation-discipline | STUB | 8-line placeholder. | — |
| secrets-provisioning | MERGE | "Inventory required credentials before work starts" fires on the same pre-task moment as wirework-preflight (which already probes credentials); fold its credential depth in. | wirework-preflight |
| security-ownership-map | WIRE | Who owns each security-relevant component. [T7-blue] | — |
| security-threat-model | WIRE | General/right-sized STRIDE threat model; survivor of the threat-model-loop merge. [T3] | — |
| semgrep-rule-author | WIRE | Turn a confirmed defect into a low-FP Semgrep rule; note plugin overlap. [T4] | — |
| session-rotation | WIRE | Hand a context-ceiling session to its successor via live state. [T3] | — |
| signature-validation-audit | WIRE | ECDSA-fallback / precompile-shadowing signature forgery classes. [T2] | — |
| simd-correctness-validation | STUB | 8-line placeholder. | — |
| skill-description-trigger-authoring | WIRE | Author trigger-shaped descriptions; the exact tool this rollout needs. [T3] | — |
| solana-anchor-audit-checklist | MERGE | Same Solana bug-class list (owner/signer/PDA/CPI) as vulnhunter-solana, the flow-integrated survivor; this file also has NO status field. | vulnhunter-solana |
| solana-audit-flow | WIRE | Stateful Solana/Anchor audit pipeline; the corrected native-tool version. [T1] | — |
| sonic-branding | WIRE | Brand audio identity (mnemonic/motifs/rules). [T7] | — |
| sound-design-principles | WIRE | Design sound by source/function/emotion. [T7] | — |
| structured-data-authoring | WIRE | JSON-LD/schema.org matching visible content. [T7] | — |
| supply-chain-audit | WIRE | Audit everything entering a build/release not written by the project. [T4] | — |
| take-over-resume | WIRE | Resume after a human edited the tree; KG mention is historical only. [T3] | — |
| technical-seo-audit | WIRE | Crawl/index/intent discoverability audit. [T7] | — |
| terminology-memory | WIRE | Glossary + do-not-translate discipline for localization. [T7] | — |
| threat-model-loop | MERGE | Thinner duplicate of security-threat-model (same asset→boundary→abuse-path→control→test method); its Acceptance section is empty. | security-threat-model |
| tos-compliance-check | STUB | 8-line placeholder. | — |
| uniswap-v4-hook-access-control | WIRE | Uniswap v4 hook missing-caller-check class. [T2] | — |
| variant-analysis | WIRE | After a confirmed defect, find its siblings; note interactive-session plugin overlap. [T3] | — |
| verification-before-completion | MERGE | Straight duplicate of the already-loaded superpowers plugin skill of the same name; wiring it collides with the plugin trigger. | superpowers:verification-before-completion |
| video-post-production | WIRE | Edit-to-delivery video pipeline. [T6] | — |
| video-production-principles | WIRE | Shot planning/direction before post. [T6] | — |
| virality-analysis | WIRE | Why content spreads → honest recs; note higgsfield virality tool overlap. [T6] | — |
| visual-design-principles | WIRE | Hierarchy/contrast/alignment/repetition/proximity/balance. [T5] | — |
| visual-regression-baseline | WIRE | Deterministic pixel-diff baseline; explicitly the diff half of wired visual-verify. [T5] | — |
| voice-consistency-audit | STUB | 8-line placeholder. | — |
| voice-performance-direction | WIRE | Direct a (human/synth) voice performance. [T7] | — |
| vulnhunter-solana | WIRE | Solana manual vuln-pattern review; survivor of the anchor-checklist merge. [T1] | — |
| wcag-conformance-audit | WIRE | Per-criterion WCAG audit of a UI; distinct from media a11y authoring. [T5] | — |
| web-performance-optimization | WIRE | Improve Core Web Vitals by measured mechanism. [T5] | — |
| wirework-preflight | WIRE | Pre-task readiness probe (MCP/cred/lane/worktree); survivor of the secrets-provisioning merge. [T3] | — |
| wirework-reflect | WIRE | Post-task planned-vs-actual reflection captured to vault. [T3] | — |
| writing-skills | MERGE | Straight duplicate of the already-loaded superpowers plugin skill of the same name. | superpowers:writing-skills |
| vibecheck | WIRE | Last discipline sweep before "done" (scope creep, leftover artifacts, inflated prose); distinct from verification-before-completion. [T3] | — |

*(Priority tiers T1–T7 drive the wire order in §5; `-blue` marks blue-team/defensive skills whose usage the operator should confirm.)*

## 3. MERGE evidence (quoted colliding lines)

Each MERGE proves the overlap against a wired or clearly-superior survivor.

1. **chain-impact-rescore → chain-construct** (wired).
   - chain-construct: *"Turn a set of individually-weak observations into a single demonstrated exploit chain whose end state proves realized impact."*
   - chain-impact-rescore: *"chain primitives *forward* until they reach real terminal impact — funds moved, users harmed, code executed, permanent freeze."* Same trigger (compose primitives → impact). Its distinctive stance ("keep going even after you hit a 'critical'") is worth folding into chain-construct.

2. **claim-validation-gate → claim-verification** (wired).
   - claim-validation-gate: *"Refuse to let an unverified assertion leave a review, report, or completion envelope; every claim carries its evidence or is downgraded."* / *"Extract every factual claim… Classify each claim as `observed`… `derived`… `asserted`."*
   - claim-verification: *"Decompose content into load-bearing claims and verify each against evidence (Hard Rule 8 truth gate)."* Same decompose-classify-cite-gate method.

3. **cite-properly → claim-verification** (wired).
   - cite-properly `description:`: *"Use when an artifact, report, or memory note makes factual claims…"*
   - claim-verification (wired) `description:`: *"Use before publishing or shipping any deliverable that makes factual, quoted, calculated, or forecast claims…"* Both fire on "makes factual claims" — direct trigger collision. Fold cite-properly's citation-form table (`file:line` / cmd+output / URL+date / note-id) into claim-verification's body.

4. **citation-audit → claim-verification** (wired).
   - citation-audit: *"Read the source and confirm it actually SUPPORTS the claim — not merely mentions the topic."*
   - claim-verification: *"Map each claim to the exact evidence span that would confirm it."* Citation-audit is claim-verification restricted to already-cited content.

5. **cross-chain-dvn-audit → cross-chain-bridge-audit** (WIRE survivor).
   - cross-chain-dvn-audit: *"Flag any pathway whose effective quorum is 1 (or trivially small / all controlled by one operator)… trusts a single attestation without an independent second verifier."*
   - cross-chain-bridge-audit already owns this: *"**Quorum soundness:** eligible-voter set, `(2N)/3+1` math, repeat-vote rejection"* and the *"forge an attestation"* inbound class. DVN is a named subset; keep its LayerZero `cast` recipe.

6. **multi-agent-evidence-gating → systematic-attacking** (wired).
   - multi-agent-evidence-gating: *"Never surface a candidate… until a sandboxed PoC has confirmed it with a negative control to high confidence."*
   - systematic-attacking (wired) `description:`: *"no finding without a reproduced, negative-controlled, intrinsic-impact proof."* Same iron law. Fold its four observable predicates (oracle match, control separation, repeat stability, harness fidelity) into systematic-attacking's proof section.

7. **secrets-provisioning → wirework-preflight** (WIRE survivor).
   - secrets-provisioning `description:`: *"inventory every required credential by name against what is actually available."*
   - wirework-preflight `description:`: *"probe that the MCPs, credentials, model lane, and worktree the task depends on are actually usable."* Both fire "before the task starts"; preflight is the superset. Fold secrets-provisioning's credential depth into preflight's credential step.

8. **solana-anchor-audit-checklist → vulnhunter-solana** (WIRE survivor).
   - solana-anchor-audit-checklist: *"Known critical-bug classes for Solana programs (native or Anchor)… **Owner check**… **Signer check**… **PDA**… **CPI**."*
   - vulnhunter-solana: *"Manual vulnerability pattern review for Solana Rust programs. Use this during `solana-audit-flow`."* — same class list, but flow-integrated and longer (79 vs 32 lines). The checklist also has **no `status:` field** (the one file that is neither stub nor authored).

9. **threat-model-loop → security-threat-model** (WIRE survivor).
   - threat-model-loop: *"Iteratively connect assets, trust boundaries, attacker goals, abuse paths, mitigations, and verification evidence."* — and its **`## Acceptance` section is empty**.
   - security-threat-model is the same method with a complete, gradeable Acceptance list and a termination floor (*"the model terminates at a stated floor"*).

10. **verification-before-completion → superpowers:verification-before-completion** (plugin, live in this session's skill list). Same-named straight copy; the superpowers plugin is confirmed loaded (its `using-superpowers` skill fired this session), so the shared copy would collide.

11. **writing-skills → superpowers:writing-skills** (plugin, live in this session's skill list). Same-named straight copy of a loaded plugin skill.

## 4. Why LEGACY = 0 and DELETE = 0

The brief expected legacy/expired/junk. It's largely not there, and the near-misses are instructive:

- **The retired KG did not strand anything.** Only two skills mention the retired in-repo SQLite knowledge graph. `evm-audit-flow` line 12 has *already migrated off it* (*"retired KG. Start from `pre-audit-threat-model`…"*). `take-over-resume` line 65 cites it only as historical provenance (*"The source of this procedure re-indexed each changed file into a knowledge graph…"*) — the skill's own method reads the git tree, not the KG. Neither depends on it → both WIRE, not LEGACY.
- **Plugin-superseded docs are MERGE, not LEGACY.** `verification-before-completion` and `writing-skills` duplicate live superpowers plugin skills — but the *workflow still runs* (via the plugin), so "name the survivor" (MERGE) fits better than "no longer run" (LEGACY).
- **Retired *terminology* rides on stubs, not finished skills.** The "per-Lead / model-lane cache" framing that per-specialist model binding is superseding appears only in `prompt-cache-discipline` / `prompt-cache-hit-monitoring` — both 8-line stubs → STUB (and flagged as low-likelihood-to-finish).
- **Path check:** every repo path referenced by a skill exists (`shared/modes/project.md`, `scripts/python/chrono_state/registry.py`, `bin/doctor.sh`, `bin/chrono-status-segment.sh`, `bin/validate-capabilities.sh`, `bin/test`, …) **except** `bin/randomization` (a minor, non-load-bearing mention in `interactive-audio-design`) — evidence of freshness, not rot.
- **DELETE = 0** because nothing is valueless. The redundancy present is duplication (→ MERGE) and incompleteness (→ STUB). If the operator decides we do **not** do blue-team/SOC work or deep manual audio production, the specific clusters flagged in §6 become the DELETE (or archive) candidates — but I have no evidence we *don't*, so I did not unilaterally down-bucket demand-referenced, complete skills.

## 5. Recommended WIRE order (98 skills, value-first)

**Recommended batch size: ~12, wired highest-tier-first, validator-green after each batch.** Rationale: mechanical risk is low (the validator only checks description-present + trigger-shaped + body-identical), so the binding constraint is the *shared trigger-attention budget* — every wired description competes at match time. Batches of ~12 let you (a) run `validate_skill_wiring.py` green after each, (b) live-test that the new descriptions fire without cross-firing the previous batch, and (c) stop if the attention budget shows strain. **Wire Batch 1 first as the proof batch** — it is the set the squad's active bounty/audit work reaches for daily, so it returns the most value per wire.

- **Batch 1 — offensive-audit core (T1, 12):** `pre-audit-threat-model`, `evm-audit-flow`, `solana-audit-flow`, `chain-construct-smart-contract`, `defi-invariant-check`, `vulnhunter-solana`, `cosmos-sdk-audit-checklist`, `cross-chain-bridge-audit`, `program-rubric-lookup`, `findings-filter`, `review-severity-ladder`, `known-advisory-backport-check`.
- **Batch 2 — niche exploit/audit classes (T2, 10):** `read-only-reentrancy-check`, `uniswap-v4-hook-access-control`, `erc1271-revert-data-check`, `signature-validation-audit`, `durable-nonce-exploitation`, `parser-differential-route-confusion`, `error-based-ssti`, `mcp-schema-poisoning`, `agentic-sandbox-escape`, `agentic-safety-audit`.
- **Batch 3 — cross-cutting work discipline/ops (T3, 14):** `skill-description-trigger-authoring` (wire this early — it authors the very descriptions the rollout needs), `interface-ambiguity-check`, `scope-decomposition`, `scope-estimation`, `requirements-elicitation`, `dimensional-analysis-check`, `code-reachability-audit`, `session-rotation`, `take-over-resume`, `wirework-preflight`, `wirework-reflect`, `variant-analysis`, `security-threat-model`, `vibecheck`.
- **Batch 4 — analysis/research + review + audit tooling (T4, 15):** `dual-level-retrieval`, `layered-analysis-loop`, `cross-file-relationship-synthesis`, `knowledge-base-integration`, `differential-review`, `diff-aware-semgrep-scan`, `semgrep-rule-author`, `supply-chain-audit`, `dependency-health-triage`, `dependency-cycle-audit`, `code-review-loop`, `defensive-pattern-discovery`, `gptscan-prompt-templates`, `multi-stance-audit-fanout`, `auto-scaffold`.
- **Batch 5 — visual/frontend + media-delivery compliance (T5, 12):** `visual-regression-baseline`, `wcag-conformance-audit`, `accessible-media-authoring`, `rights-and-provenance-gate`, `consent-and-likeness-check`, `platform-compliance`, `figma-implement-design`, `responsive-design`, `web-performance-optimization`, `visual-design-principles`, `color-theory`, `composition-rules`.
- **Batch 6 — game + long-form media (T6, 12; confirm usage):** `video-post-production`, `video-production-principles`, `color-grading-basics`, `game-design-fundamentals`, `game-mechanics-balancing`, `level-design-patterns`, `narrative-structure`, `narrative-pacing`, `player-engagement-psychology`, `conversation-design`, `agent-prompt-engineering`, `virality-analysis`.
- **Batch 7 — content/SEO/localization + audio craft + blue-team + misc (T7, 23; confirm usage per §6):** `keyword-clustering`, `technical-seo-audit`, `structured-data-authoring`, `copy-refinement`, `locale-adaptation`, `terminology-memory`, `regional-compliance-check`, `osint-platform-audit`, `head-tail`, `audio-production-basics`, `audio-layering-techniques`, `music-production-basics`, `sound-design-principles`, `sonic-branding`, `voice-performance-direction`, `interactive-audio-design`, `audio-event-map-authoring`, `detection-as-code`, `detection-tuning`, `attack-coverage-map`, `incident-response-runbook`, `forensic-timeline-authoring`, `security-ownership-map`.

## 6. Operator decisions to confirm before Batches 6–7

These are **proposals, not auto-adopted** — two clusters are WIRE only under an assumption I can't verify:

- **Blue-team / detection / IR (6):** `detection-as-code`, `detection-tuning`, `attack-coverage-map`, `incident-response-runbook`, `forensic-timeline-authoring`, `security-ownership-map`. Complete and demand-referenced by security specialists, but they assume *defensive/SOC engagements*. If the squad does offensive-only, these are DELETE/archive candidates.
- **Deep manual audio craft (5):** `audio-production-basics`, `audio-layering-techniques`, `music-production-basics`, `sound-design-principles`, `sonic-branding`. These describe hand-mixing/mastering. The squad *generates* audio (ElevenLabs/higgsfield) rather than DAW-mixing it; if we never hand-produce, these are DELETE/archive candidates. (`voice-performance-direction`, `accessible-media-authoring`, `platform-compliance`, `audio-event-map-authoring`, `interactive-audio-design` stay useful — they direct/gate generated media.)

## 7. What surprised me

1. **mtime is a mirage here.** The brief said "mtimes span May to August," but every file reads `2026-08-18` — `git checkout` stamped them all at worktree-creation time. Any staleness signal must come from `git log`, not the filesystem. I did not use mtime for any classification.
2. **The library is fresh, not rotting.** LEGACY = 0, DELETE = 0. The KG-retirement worry didn't materialize (§4). The real waste is 21 stubs + 11 trigger-collisions, not dead code.
3. **The rollout is a *description* problem, not a content one.** 98 WIRE candidates already have complete bodies; they just lack a `description:` trigger (114/135 have none). That makes the backlog cheap to clear — and the skill that does exactly this job, `skill-description-trigger-authoring`, is itself unwired (Batch 3, wire it early).
4. **The tightest collision risk is the truth/verification cluster.** `claim-verification` is wired, and three near-clones (`claim-validation-gate`, `cite-properly`, `citation-audit`) plus a plugin twin (`verification-before-completion`) all fire on "content that makes claims." Wiring them as-is is the exact double-fire the packet warns about. Consolidation matters more than volume here.
5. **`solana-anchor-audit-checklist` has no `status:` field** yet ships real content and duplicates `vulnhunter-solana` — a metadata gap and a dup in one file.

---

### Verification & manifest

- `verification_contract_sha256`: `e1a333635b7061131e996d31cbef59acc1f330bca076cd50a36f41df836f64db` (echoed; dispatcher-owned, immutable).
- `verification_contract`: `{"action_log_policy":{"required":true},"artifact_policy":{"bundle_hash_algorithm":"canonical-artifact-list-sha256/v1","hashes_required":true},"author_family":"claude","bounty_policy":null,"capability":{"card_sha256":null,"derived_state":null,"id":null},"contract_version":"verification-contract/v1","deliverable_review_policy":{"anti_affinity":"author_family","required":true,"subject":"artifact_bundle_sha256"},"dispatch_kind":"single","expected_gates":[],"external_delivery_policy":{"allowed":false},"iteration_policy":{"invalidates_on":["plan_sha256","artifact_bundle_sha256"],"routes":["S2","S3"]},"memory_policy":{"recall":"required","record":"required"},"mode":"project","plan_review_policy":{"anti_affinity":"author_family","required":true,"subject":"plan_sha256"},"required_phase_ids":["S0","S1","S2","S3","S4","S5","S6","S7"],"required_verification_kinds":["project_tests","recipient_contract"],"result_type":"normal","run_id":"none","task_id":"TASK-2026-08-18-1427-8882b0f0"}`
- **project_tests:** No code changed — write scope is a single markdown artifact — so the repo test suite is not a meaningful gate for this task. The domain-relevant validator was run instead: `python3 scripts/python/validate_skill_wiring.py` → `ok[skill-wiring] 8 wired skill(s) checked … 0 error(s)` (green; also reports the demand-referenced backlog this audit expands on).
- **recipient_contract:** satisfied — this file is both the `return_artifact` and the outbox envelope (same path), written worktree-relative with the required envelope frontmatter and a summary first paragraph.
- **Deliverable self-verification:** all 130 unwired files enumerated from `shared/skills/*.md` and classified (count asserted programmatically: MERGE 11 + STUB 21 + WIRE 98 = 130, none missing/extra); MERGE claims carry quoted colliding lines; referenced paths existence-checked.
- **subagents: 0** — solo worker; internal analysis via batched shell/read only.

### Memory (best-effort telemetry)
- `recall` (once): returned 5 notes; used `mem-5c05f94dd5ed` (claude load path + "114/135 have no description"), `mem-749274c174c2` (pilot: validator gates on integrity, ~39-item backlog), `mem-ac3a4e91e3ac` (registry-authored pattern-doc inventory), `mem-100fa267613d` (skills ported to shared/skills; fabricated slither-solana step removed). `mem-b87c32c9b9d6` was disputed and not relied upon.
- `record` / `record_usage`: attempted after writing this artifact (see envelope note); a memory error is noted here and does not gate the task.
