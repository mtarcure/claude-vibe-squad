---
id: TASK-2026-08-18-1725-29c8820d-response
in_response_to: TASK-2026-08-18-1725-29c8820d
from: claude
to: chrono
type: RESULT
status: needs_review
return_artifact: departments/coding/outbox/TASK-2026-08-18-1725-29c8820d-response.md
---

All 17 batch-C process/method skills were read in full and assessed against the nine required fields. Every named file exists. The batch splits sharply in two: **~11 polished, house-aware skills** carrying real gate/gotcha value that a generic model would get wrong (`session-rotation`, `wirework-preflight`, `vibecheck`, `auto-scaffold`, `take-over-resume`, `multi-stance-audit-fanout`, `scope-decomposition`, `requirements-elicitation`, `wirework-reflect`, `head-tail`, `skill-description-trigger-authoring`) and **~6 thin, generic checklists** that teach general competence with no house-specific hook (`agent-prompt-engineering`, `dimensional-analysis-check`, `dual-level-retrieval`, `layered-analysis-loop`, `scope-estimation`, `terminology-memory`). All 17 are inventoried in `shared/registries/skill-tool-registry.tsv` but **none is referenced as a consumer anywhere in the workflow layer** (`shared/modes/`, `shared/protocol.md`, `shared/routing.md`, `shared/specialist-runtime-map.tsv`, `docs/standards/tool-trigger-map.md` — grep returned zero). Concrete defects found: a **dead cross-reference** in `vibecheck` (and its registry row) to the retired `claim-validation-gate`; `head-tail` and `wirework-reflect` **duplicate guidance already injected into every board packet**; `scope-decomposition` and `requirements-elicitation` carry **workflow-summary descriptions** that violate the exact rule their sibling `skill-description-trigger-authoring` teaches; and `terminology-memory` names chrono-vault as a "glossary" store with no working retrieval model. Disposition (keep/retire/merge) is deliberately **not** recommended, per the packet's hard boundary. Full evidence, per-skill, below. `subagents: 0` (worked solo; read-and-analysis task, no independent sub-domains to fan out).

---

## Run manifest

- Task: `TASK-2026-08-18-1725-29c8820d` · specialist `architect` · lane `claude` · mode `project`
- `verification_contract_sha256`: `70d4b02b60978da77039bbeffbe1bc6cd6fd78c353052c73073cc4178d74dcfe` (dispatcher-owned, echoed verbatim)
- `verification_contract`: echoed as pinned by dispatcher (author_family `claude`; contract_version `verification-contract/v1`; required phases S0–S7; memory recall+record `required`, best-effort).
- Deliverable type: **descriptive audit of documentation** (17 markdown skill files). Not a triage, not an edit, no keep/retire/merge verdicts.

### Method / scope (measured, per `scope-estimation`'s own discipline)
- Files assessed: 17 of 17 named; all present under `shared/skills/`. Sizes 19–133 lines, ~1,000 lines total. **All read whole, in one operation each** (no paging).
- Comparison corpus read in full for OVERLAP grounding: `superpowers` 6.3.0 `writing-skills`, `brainstorming`, `writing-plans`, `dispatching-parallel-agents`, `executing-plans`; `skill-creator`; `plugin-dev:agent-development`; `chrono-vault:compact-now`.
- Wiring probed by `rg`: workflow layer (modes/protocol/routing/specialist-map/tool-trigger-map), the retired set (`shared/skills/_retired/`, 32 files), the wired set (`.claude/skills/`, 23 dirs — none of the 17), `catalog.txt`, and `skill-tool-registry.tsv`.
- What this scope **cannot** answer: whether any skill has ever executed (the repo says most never have; the registry marks them `verified_state: authored`), and board-lane reachability of the external plugin skills I compare against (superpowers/skill-creator) — flagged per-skill as UNKNOWN where load-bearing.

### Field key
1 WHAT · 2 CLARITY (+ vaguest step quoted) · 3 EFFECTIVENESS (real-work step) · 4 SAFETY (quoted if any) · 5 USEFULNESS (consumer / "no identified consumer") · 6 OVERLAP (named + quoted) · 7 REDUNDANCY (house-rule / gotcha / gate / our-surface — or "adds nothing") · 8 IMPROVEMENT (single highest-value) · 9 UNKNOWN (mandatory).

A recurring USEFULNESS fact, stated once to avoid repetition: **all 17 appear in `skill-tool-registry.tsv`; none is referenced as a consumer in the workflow layer.** So every "consumer" below is *inferred from content*, and "no declared workflow consumer" is the shared baseline unless noted.

---

## Per-skill assessments

### 1. agent-prompt-engineering  (20 lines · no `description:`)
1. **WHAT** — A five-step recipe for designing an agent's system prompt (role/boundaries → structure → tool-and-grounding rules → few-shot → eval set); fires when authoring the instruction set for a conversational or task agent.
2. **CLARITY** — Executable but abstract. Vaguest: step 5 — *"Define an eval set of representative and adversarial turns; iterate the prompt against it rather than against a single demo."* No count, no definition of "adversarial" here, no harness; a specialist would ask "iterate against what, run how?"
3. **EFFECTIVENESS** — Real work is step 2 (priority-ordered prompt skeleton) and step 5 (eval-driven iteration). Produces a reasonable skeleton; nothing a competent model wouldn't already generate.
4. **SAFETY** — None. Read/author only; step 3 forbids fabrication ("forbid fabrication and require citing/handing off") — safety-positive.
5. **USEFULNESS** — Inferred: `ai-engineer` building an LLM/agent tool. No identified consumer. Note the name collides conceptually with our board specialists but is about *building* agents, not dispatching them.
6. **OVERLAP** — `plugin-dev:agent-development` covers the same ground with more specificity: *"The markdown body becomes the agent's system prompt… Define output format… Address edge cases"* (its System-Prompt-Design section). Also `skill-creator`'s description/prompt guidance. This file is the generic subset.
7. **REDUNDANCY** — Adds nothing. A capable model asked to write an agent prompt already does role/boundaries/output-contract/grounding. No house rule, gate, gotcha, or our-surface knowledge. General competence → dead weight per the rubric.
8. **IMPROVEMENT** — Anchor it to *our* surface: a worked example built on our board specialist adapters (`model-lanes/*/.claude/agents/*.md`, the capability-projection frontmatter and lane overlay), so it teaches something the plugin doesn't.
9. **UNKNOWN** — Whether "agent" means our board specialists or product agents (the file never says); whether it has ever been used.

### 2. auto-scaffold  (77 lines · rich `description:`)
1. **WHAT** — At delivery, generates the standard repo files (README, CHANGELOG, LICENSE, CLAUDE.md) from what the work actually produced, never overwriting existing files; fires when a delivered repo lacks these standard files.
2. **CLARITY** — High; ordered steps, explicit overwrite rule, two-gate approval. Vaguest: step 2 *"Gather the source material"* is broad, but the "What gets generated" section pins each file down. Executable without a question.
3. **EFFECTIVENESS** — Load-bearing: the overwrite check (*"Never overwrite a file that already exists. Skip it, and report the skip"*) and step 5 (*"Verify the instructions you just wrote. Run the build and test commands exactly as the README states them"*). The latter is what separates it from a template dump.
4. **SAFETY** — Writes files; correctly self-gated: *"This skill writes files. That makes it a gated action."* Two distinct gates — operator approval before writing, and a separate publish gate for LICENSE (*"Do not default a license"*, Hard Rule 6). No deletion. A model of a properly-gated write skill.
5. **USEFULNESS** — Inferred: whoever owns S6 delivery in project mode (`devops-engineer` or the lead). No identified consumer — and see IMPROVEMENT: the mode it claims to attach to does not reference it back.
6. **OVERLAP** — None in the comparison set generates gated repo scaffolding; superpowers has no equivalent. Effectively unique. (Closest external is generic `git init`/templating, which lacks the no-overwrite and no-default-license gates.)
7. **REDUNDANCY** — Earns its place: Hard Rule 6 publish gate on LICENSE, the CLAUDE.md-is-our-convention note, and the no-default-license judgment are all things a generic model gets wrong (it will happily write an MIT LICENSE). Not general competence.
8. **IMPROVEMENT** — Fix the anchor claim: the skill asserts it *"runs at the S6 Ship/Deliver step (`shared/modes/project.md`)"*, but a grep of `project.md` for `scaffold`/`S6`/`Ship` returns nothing — the wiring is one-directional. Make the trigger real (correct the step name or add the reciprocal reference) rather than asserted.
9. **UNKNOWN** — The actual S6 wiring (`project.md` doesn't name the skill and I couldn't confirm its phase label maps to "Ship/Deliver"); whether auto-scaffold has ever run.

### 3. dimensional-analysis-check  (25 lines · no `description:`)
1. **WHAT** — An eight-point checklist to catch unit/scale/base/precision/sign/time errors across expressions, boundaries, and storage round-trips; fires during review of a change touching numeric quantities.
2. **CLARITY** — High and concrete (names wei vs ether, bps vs percent, epoch vs monotonic). Vaguest: step 2 *"a ratio's unit must be what the consumer expects"* — needs the consumer known, but that is inherent to the check, not a defect.
3. **EFFECTIVENESS** — Real work is step 3 (boundary crossings) and step 7 (time), the highest-yield defect classes. A solid memory aid; it would catch real unit bugs. But it is a checklist, not a method — no tooling, no automation.
4. **SAFETY** — None. Read/analysis only.
5. **USEFULNESS** — Inferred: `code-reviewer`, `smart-contract-engineer` (decimals/wei), `performance-optimizer`. No identified consumer.
6. **OVERLAP** — No dedicated external skill; general code-review competence. Its crypto vocabulary overlaps `multi-stance-audit-fanout`'s "math-precision" stance (*"rounding direction, decimal scaling, fixed-point overflow, division before multiplication… precision loss across token decimals"*) — i.e., it is a subset of that stance's lens.
7. **REDUNDANCY** — Mostly general competence: a model reviewing arithmetic already checks truncation/overflow/units. Its one house-adjacent value (crypto units) is already covered by the audit skills. Adds a reminder, not a capability.
8. **IMPROVEMENT** — Add a trigger description and scope it to **non-contract** code (general backend/units), where the EVM/Solana audit skills don't reach — otherwise it duplicates `multi-stance-audit-fanout` stance 2.
9. **UNKNOWN** — none.

### 4. dual-level-retrieval  (24 lines · no `description:`)
1. **WHAT** — A retrieval discipline: coarse recall pass over the whole corpus to locate candidates, then a precise read pass inside them, quoting only from the fine pass; fires when searching a corpus for evidence.
2. **CLARITY** — High (step 1 *"names, symbols, and identifiers rather than concepts"*; step 5 *"Quote from the fine pass only"*). Vaguest: step 3 *"Rank the hit set by expected decisiveness, not by match count"* — a judgment term, but the example clarifies it.
3. **EFFECTIVENESS** — Load-bearing is step 5 (*"a grep line is not a reading of the code"*) — it prevents a real, costly anti-pattern (citing grep output). Coarse→fine structure is sound.
4. **SAFETY** — None.
5. **USEFULNESS** — Inferred: any research/audit specialist doing corpus search. No identified consumer. (I executed exactly this workflow — coarse `rg`, then full `Read` — in *this* task, without the skill.)
6. **OVERLAP** — General research competence; conceptually overlaps the ToB `audit-context-building` plugin (*"ultra-granular, line-by-line code analysis to build deep architectural context"*) and the retired in-repo `audit-context-prep`. The "quote only from full reads" rule also restates the board's injected efficiency guidance (*"Read a whole file in ONE operation… Do not page a file"*).
7. **REDUNDANCY** — Adds little. A model with `rg` + `Read` already runs coarse-then-fine and knows not to cite a grep line. Its one non-obvious bit is step 6 (feed fine-pass vocabulary back into a new coarse query) — a genuine technique, thin justification for a standalone skill.
8. **IMPROVEMENT** — Make step 6 (the vocabulary-feedback loop) the spine and cut steps 1–5, which restate default search behavior a capable agent already performs.
9. **UNKNOWN** — none.

### 5. head-tail  (66 lines · rich `description:`)
1. **WHAT** — Sample a too-large-to-read file (logs, build output, dumps) by reading a bounded slice from each end, with explicit rules against using it on source files; fires when a file is too large to read whole *and its middle is repetitive*.
2. **CLARITY** — High; the deciding question is spelled out (*"is this file's middle repetitive?"*), slice defaults given (20 lines/end), failure modes enumerated. Vaguest: step 2 *"Take more from the tail when you are chasing a failure"* — no number, but a reasonable judgment call.
3. **EFFECTIVENESS** — The value is the guardrails, not the mechanic: the "Wrong: source files… Read those whole" rule and the masked-exit-status trap (*"`some-build | tail` reports the status of `tail`, not of the build"*) are genuinely load-bearing and non-obvious. The head/tail mechanic itself is trivial.
4. **SAFETY** — None (read-only); it actively teaches capturing exit status correctly.
5. **USEFULNESS** — Inferred: any specialist triaging CI/test logs (`test-engineer`, `devops-engineer`). No identified consumer.
6. **OVERLAP** — **Heavy overlap with the board's own injected guidance.** This very packet's "Execution efficiency — the cost unit is ROUND-TRIPS" block already teaches *"Read a whole file in ONE operation… Do not page a file in 260-line windows"* and *"a piped command returns the status of its last stage"* — the same content as head-tail's steps 2–6 and its masked-exit-status failure mode. My own memory index carries "Piped exit status masks failure" as a standing note.
7. **REDUNDANCY** — For the base technique, adds nothing (shell competence). Its genuinely useful parts (source-file exclusion, masked exit status, gap-reporting) are **already injected into every board packet and recorded in memory**, so on the board it is doubly redundant. On a bare CLI with no injected guidance it would earn a slot; on our board it largely doesn't.
8. **IMPROVEMENT** — Resolve the duplication with the injected efficiency block — the skill and the packet boilerplate are two homes for one fact (Hard Rule 10). Name which is canonical and have the other cite it.
9. **UNKNOWN** — Whether the injected efficiency block is *generated from* this skill or independently authored; if they share an origin, their agreement is non-corroborating (Hard Rule 9) and both could drift.

### 6. layered-analysis-loop  (25 lines · no `description:`)
1. **WHAT** — Analyze a target in deliberate passes (structure → behavior → edges → contradiction), each answering one pre-written question, closing each with a written delta and stopping at convergence; fires when doing deep analysis of a system.
2. **CLARITY** — High; four layers named with distinct purposes. Vaguest: step 5 *"actively try to falsify the model"* — intent clear, execution left to judgment (appropriately).
3. **EFFECTIVENESS** — Load-bearing: step 5 (contradiction/falsification layer) and steps 6–7 (written delta per layer + stop-at-convergence). These impose discipline a single undirected read lacks. A genuine method.
4. **SAFETY** — None.
5. **USEFULNESS** — Inferred: `architect` (system review), `code-reviewer`, security specialists doing deep reads. No identified consumer.
6. **OVERLAP** — General analysis competence; overlaps `superpowers:systematic-debugging` (falsification loop) and the ToB `audit-context-building` plugin. The "contradiction layer" echoes our review skills' adversarial stance.
7. **REDUNDANCY** — Partial. The layered structure is general, but "contradiction layer + written delta per layer + stop at convergence" is a real discipline gate a model does not reliably self-impose under budget pressure. Earns a thin slot as a discipline aid, not a capability.
8. **IMPROVEMENT** — Add the missing trigger description and one worked delta example; the method is sound but undiscoverable and abstract without either.
9. **UNKNOWN** — none.

### 7. multi-stance-audit-fanout  (100 lines · no `description:`)
1. **WHAT** — A Chrono-orchestrated fan-out: eight persona stances read the same Solidity source through different lenses, then findings are deduped by `group_key` with a composite-chain pass; fires after `evm-audit-flow`'s tool passes when logic-bug coverage is still needed on a ≤2k-nSLOC contract.
2. **CLARITY** — High for its complexity — orchestration model, stance roster, output schema, and dedup/promotion rules are all concrete. Vaguest: step 6 promotion — *"Promote LEAD → FINDING at confidence 75 if either: (a) a complete exploit chain is traced… OR (b) `[stances: 2+]` agree"* — "complete exploit chain" is a judgment threshold, bounded by the surrounding rules.
3. **EFFECTIVENESS** — Real work is stance isolation (*"the diversity comes from role isolation"*) + dedup-by-`group_key` + the composite-chain pass. A genuine method, not a checklist; correctly separates itself from the tool pipeline (*"Distinct from `evm-audit-flow` (tool pipeline) — this fans out human-style review… to catch logic bugs no detector finds"*).
4. **SAFETY** — Analysis only; encodes our orchestration gate correctly: *"Workers NEVER self-spawn, launch a model CLI, or dispatch sub-agents — that is Chrono's job"*, routing fan-out through `## NEEDS FROM CHRONO`. Safety-positive and house-accurate.
5. **USEFULNESS** — Inferred: `smart-contract-engineer`/security coordinator on an EVM bounty, with Chrono as dispatcher. No identified consumer. Carries external provenance: *"inspired by pashov/skills:solidity-auditor (MIT); recast Chrono-orchestrated."*
6. **OVERLAP** — Overlaps `superpowers:dispatching-parallel-agents` in *concept* but is the **opposite mechanism**: that skill says *"Issue all three subagent dispatches in the same response — they run in parallel,"* which multi-stance explicitly forbids (*"workers never launch sub-agents"*). Also overlaps our wired `evm-audit-flow` (distinguished) and `systematic-bug-hunting`; the stance roster overlaps the audit skills' lenses.
7. **REDUNDANCY** — Earns its place via our surface + orchestration gate (board fan-out, `group_key` dedup contract, the NEEDS-FROM-CHRONO protocol, chrono-vault record schema). A model knows to review a contract from multiple angles, but not our board-dispatch constraint or dedup contract. Not redundant.
8. **IMPROVEMENT** — Add a trigger description (it has none, despite being one of the most complex files — it will never auto-load) naming the moment: *"after evm-audit-flow static+symbolic passes, logic bugs still uncovered, ≤2k nSLOC."*
9. **UNKNOWN** — Whether the `impact-validator (G1–G4)` handoff resolves to a loadable artifact: `impact-validator` appears in `shared/protocol.md` and several wired `.claude/skills/` but has **no skill file** of its own — it is a repo-wide gate concept, not a loadable skill; whether the 8-stance fan-out has ever actually run on the board.

### 8. scope-decomposition  (49 lines · `description:` present but workflow-summary style)
1. **WHAT** — Break a broad/ambiguous ask into bounded, independently verifiable units — each with its own write set, pass/fail check, and named exclusions, ordered riskiest-assumption-first; fires when an ask is too large to verify in one pass or will be split across dispatches.
2. **CLARITY** — High; concrete steps, a worked "add auth to the API" example, and failure modes. Vaguest: step 3 *"Slice along existing seams — module, interface, data boundary — not by activity phase"* — needs recognizing a "seam," but the horizontal-slicing failure mode clarifies.
3. **EFFECTIVENESS** — Load-bearing: step 4 (independently verifiable units), step 5 (explicit write set, disjoint or declared as an ordering edge), step 6 (named exclusions). These map directly to our board's `write_scope`/`success_criteria`. The worked example proves the method produces a real decomposition.
4. **SAFETY** — None (planning). Contains an accurate, non-obvious house detail: *"A packet's `write_scope` is enforced mechanically at controller integration, not as an action-time worker filesystem boundary."*
5. **USEFULNESS** — Inferred: Chrono (dispatch planning) and `architect`. No identified consumer, but its write-set/exclusion framing is our board's native vocabulary — the closest thing to a dispatch-authoring skill in the batch.
6. **OVERLAP** — Overlaps `superpowers:brainstorming` (*"help the user decompose into sub-projects: what are the independent pieces, how do they relate, what order"*) and `superpowers:writing-plans` (*"map out which files will be created or modified… Task Right-Sizing"*). The batch-C skill is board-aware (write_scope enforcement) where the superpowers pair is repo/PR-aware.
7. **REDUNDANCY** — Partial earn. The general method is covered by brainstorming/writing-plans; its house-specific value is the write_scope-disjointness rule and the mechanical-integration note — knowledge of our board the plugins lack. Without those it would be redundant.
8. **IMPROVEMENT** — Its `description:` is a workflow summary (*"Break an ambiguous or large ask into bounded, independently verifiable units…"*) with **no "Use when" trigger** — the exact anti-pattern its sibling `skill-description-trigger-authoring` and `superpowers:writing-skills` both forbid (*"NEVER summarize the skill's process or workflow"*). Rewrite the description as a firing trigger.
9. **UNKNOWN** — none.

### 9. scope-estimation  (24 lines · no `description:`)
1. **WHAT** — Measure a corpus (file count, bytes, largest file) before analyzing it, convert to a binding budget, classify into read/sample/index tiers, and carry the numbers into the deliverable so every claim has a denominator; fires before analyzing a corpus.
2. **CLARITY** — High; step 4 gives the exact shape (*"read 34 of 210 files, all 9 entry points"*). No genuinely vague step.
3. **EFFECTIVENESS** — Load-bearing: step 1 (count before opening) and step 4 (sampling fractions as counts, not adjectives). The honesty it enforces — *"No coverage claim exceeds the measured read set"* — is exactly the discipline this audit needed (I ran `wc -l` before reading). Sound.
4. **SAFETY** — None.
5. **USEFULNESS** — Inferred: any audit/research specialist scoping a large target; Chrono sizing a dispatch. No identified consumer. (This audit used its method implicitly.)
6. **OVERLAP** — General research competence; tightly clustered with `dual-level-retrieval` and `layered-analysis-loop` (all three are "measure/scope before reading"), and with the board's injected *"Front-load orientation into one batch"* guidance. No dedicated external skill.
7. **REDUNDANCY** — Mostly general competence — a careful model already sizes a corpus and states denominators. The honesty framing (*"Sampling fractions appear as counts with denominators, never as adjectives"*) is a good discipline but not house-specific and not a gate. Adds a reminder.
8. **IMPROVEMENT** — This, `dual-level-retrieval`, and `layered-analysis-loop` are three thin views of one "scope → read → cite" discipline; give this one a distinct trigger (corpus *sizing/budgeting* specifically) so it doesn't collide with the other two.
9. **UNKNOWN** — none.

### 10. requirements-elicitation  (50 lines · `description:` present but workflow-summary style)
1. **WHAT** — Turn a vague operator ask into observable, testable, confirmed requirements via a question ladder, DEFAULT/BLOCKING assumption logging, adjective→metric conversion, and named negative scope; fires when an ask is goal-shaped but fuzzy, before scope is cut.
2. **CLARITY** — High; ladder rungs enumerated, worked example (*"make the dashboard faster" → "incident view p95 initial load < 2s"*), failure modes. Vaguest: step 5 *"Hunt the requirement classes operators reliably omit"* — but it then lists them, so even that is concrete.
3. **EFFECTIVENESS** — Load-bearing: step 3 (DEFAULT/BLOCKING assumption log) and step 4 (adjective → measurable threshold). These convert a wish into a spec; the worked example demonstrates it end to end. Strong.
4. **SAFETY** — None. Maps BLOCKING assumptions to our status vocabulary (*"blockers justify a `blocked` status"*) — a correct house tie-in.
5. **USEFULNESS** — Inferred: `architect` (before design) and Chrono (before dispatch). No identified consumer, but it is the explicit front-of-lifecycle partner to `scope-decomposition` (*"Before `scope-decomposition`: decomposition of an unelicited ask bakes the wrong goal into every slice"*).
6. **OVERLAP** — Heavy overlap with `superpowers:brainstorming`: *"ask questions one at a time to refine the idea… Focus on understanding: purpose, constraints, success criteria"* plus its Red-Flags table. Both convert vague asks to confirmed intent before implementation. brainstorming adds an approval gate + spike/bounded/architectural classification; this skill adds adjective-conversion and assumption-log rigor. Substantial, real overlap.
7. **REDUNDANCY** — Partial. The elicitation method is classic BA competence, also covered by brainstorming. Its house hooks (DEFAULT/BLOCKING → `blocked`; the scope-decomposition handoff) are thin. A model does most of this by default; the add is discipline framing, not new capability.
8. **IMPROVEMENT** — Same description defect as scope-decomposition (workflow summary, no "Use when"). And it shares a slot with brainstorming with no cross-reference — highest-value change is an **anti-trigger** disambiguating it from `superpowers:brainstorming` (which our specialists also carry).
9. **UNKNOWN** — Whether `superpowers:brainstorming` is actually reachable on the board lanes; if it is, the two compete for the same firing situation.

### 11. session-rotation  (133 lines · rich `description:`)
1. **WHAT** — Hand a long-running session to its successor by bringing live state (resume capsule, registry partition, `current.md` files) up to date *before* the context ceiling, instead of writing a handoff doc; fires when a long session nears its ceiling and work continues past it.
2. **CLARITY** — High and unusually precise — names exact files, the winning liveness path (`registry_view()`), and a runnable query snippet. Vaguest: step 1 *"Around four-fifths of the context ceiling, start the handover"* — "four-fifths" is a concrete-enough threshold.
3. **EFFECTIVENESS** — Load-bearing is the liveness-path settlement (the table proving *neither* `active-tasks.json` *nor* `tasks/active.json` may be read directly — only `registry_view()`) and step 2 (reconcile in-flight before writing). Deep, correct, hard-won house knowledge. Highly effective **for Chrono**.
4. **SAFETY** — Writes shared state; correctly requires atomic temp+sync+rename (step 7, Hard Rule 7: *"A half-written state file read by the next session is worse than a stale one"*) and warns against removing a worktree with work in flight. No deletion. Safety-accurate.
5. **USEFULNESS** — Consumer is unambiguous and it is the **only one in the batch with a named owner**: Chrono, per root CLAUDE.md (*"There is a single resume contract, and it is Chrono's to execute — no board worker runs it"*). But that means it would never fire in a board specialist dispatch; it is Chrono-scoped, so "no declared workflow consumer" is *correct*, not a defect.
6. **OVERLAP** — Heavy overlap with the wired `chrono-vault:compact-now` skill — both externalize load-bearing state before context loss and both key on `registry_view()` live/deferred/unclassified. compact-now: *"Reads the live board partition via `registry_view()`… Externalizes load-bearing state to the Vault… before invoking… `/compact`."* Different trigger (ceiling-rotation vs operator `/compact`), same mechanism, same house facts, two files.
7. **REDUNDANCY** — Strongly earns its place — every load-bearing fact (registry_view() as the sole liveness oracle, the retired handoff path, the resume capsule) is house-specific and non-derivable. Zero general competence. Caveat under OVERLAP: it and compact-now are two homes for the registry-liveness fact (Hard Rule 10 risk).
8. **IMPROVEMENT** — Reconcile with `compact-now`: the registry-liveness settlement, the `load_active()` gotcha, and the atomic-write rule live in both files and will age independently. Name the winner; have the other cite it.
9. **UNKNOWN** — Whether both session-rotation and compact-now are actively used or one supersedes the other; the file flags compact-now's `load_active()` as *"flagged for repair"* but I cannot confirm the repair status.

### 12. take-over-resume  (93 lines · rich `description:`)
1. **WHAT** — Resume work on a tree a human may have edited while you were away, by diffing against a recorded anchor (**including untracked files**) and reading the changes as intent, never reverting a manual fix; fires when picking work back up after a hand-edit or a paused task.
2. **CLARITY** — High; concrete commands (`git diff --stat`, `git status --porcelain`) with the crucial untracked-files caveat. Vaguest: resume step 2 *"Read the changes as intent… Work out what the edit is telling you"* — inherently interpretive, appropriately so.
3. **EFFECTIVENESS** — Load-bearing: the untracked-file handling (*"`git diff <anchor>` does not show untracked files, and a new file is the most common human edit"*) and step 4 (*"Do not revert a manual change to restore your plan"*). These two prevent the exact failure the skill targets.
4. **SAFETY** — None destructive; explicitly forbids reverting operator edits and warns *"Never remove a worktree with work still in flight."* Safety-positive.
5. **USEFULNESS** — Inferred: any specialist resuming a paused/hand-fixed task; Chrono on session resume. No identified consumer. The untracked-file gotcha is broadly valuable.
6. **OVERLAP** — Partial overlap with `superpowers:executing-plans` (*"Review critically… Ensure an isolated workspace"*), but that skill has no diff-against-anchor or human-edit-as-intent concept. No strong external match; largely novel.
7. **REDUNDANCY** — Mostly general git competence (diff, porcelain, don't clobber), but two things earn a slot: (a) the non-obvious untracked-files caveat a model reliably forgets, and (b) the house-specific chrono-vault warning (*"using `record` to stuff file contents into note bodies would be a misuse that pollutes recall"*). The KG-provenance note is correctly framed as historical (*"That has no honest equivalent here, and none is invented"*), so it is **not** a dead reference.
8. **IMPROVEMENT** — Reconcile the anchor step with board reality: it assumes *"the commit the work was built on"* exists at pause, but a board worktree may pause without a commit. Offer a fallback anchor (record `HEAD` + the uncommitted diff) so the "Missing anchor" failure mode is preventable, not just named.
9. **UNKNOWN** — none.

### 13. terminology-memory  (19 lines · no `description:`)
1. **WHAT** — Maintain glossary consistency and a do-not-translate list across localization jobs, recording new terms (with rationale + per-locale rendering) to chrono-vault; fires during a localization/translation job.
2. **CLARITY** — Medium; the four steps are terse. Vaguest: step 1 *"Build or load the locale glossary and the do-not-translate list"* — *where* does the glossary live? Step 3 says record *"back to the glossary (chrono-vault)"* but never says how a glossary is represented in chrono-vault (a markdown note store, not a keyed glossary). A specialist would ask "what *is* the glossary — a note? a file?"
3. **EFFECTIVENESS** — The claimed work (consistent pinned terms, conflict resolution to an authoritative entry) is sound in principle, but the mechanism is underspecified: chrono-vault records `attempt`/`finding`/`learning` notes, not a retrievable glossary, so *"record any new term… back to the glossary (chrono-vault)"* has no obvious working backing store. Effectiveness hinges on a storage model the file never defines.
4. **SAFETY** — None.
5. **USEFULNESS** — Consumer would be a localization/i18n specialist — **which the coding namespace roster does not contain** (no locale/translation specialist listed). Sibling locale skills exist in `shared/skills/` (`locale-adaptation.md`, `regional-compliance-check.md`). Likely **no identified consumer** on the coding board.
6. **OVERLAP** — No external skill in the comparison set. Overlaps our own `locale-adaptation`/`regional-compliance-check` (the glossary concern may belong with those).
7. **REDUNDANCY** — For a model doing translation, glossary/DNT discipline is somewhat general; "pin terms, resolve to authoritative entry" is a real localization gate. The issue is **fit**, not redundancy: it names chrono-vault as the glossary store without a working retrieval model, so it may not function as written.
8. **IMPROVEMENT** — Define the glossary's actual home and retrieval path — either a note convention (recall-by-term) or a glossary file. As written, step 3's backing store does not exist as a queryable structure.
9. **UNKNOWN** — Whether we have any localization specialist/workflow to consume this; how a "glossary" is represented in chrono-vault (the note schema has no glossary type).

### 14. vibecheck  (104 lines · rich `description:`)
1. **WHAT** — A last discipline sweep before "done" — nine checks (C1–C9) catching false-done, leftover artifacts, undelivered state, runaway loops, compat cruft, unsourced metrics, hype prose, scope creep, and unsolicited refactors — blocking the completion claim on any un-overridden failure; fires immediately before emitting "done".
2. **CLARITY** — High; each check named with a rule, plus an explicit skip-honestly rule and override protocol. Vaguest: C4 *"No sign of the same call repeated against the same arguments with the same result"* — detecting this from a transcript is left to judgment.
3. **EFFECTIVENESS** — Load-bearing: C2 (leftover artifacts detected and reported, not deleted), C8 (scope/write_scope discipline), C7 (honest register). The skill correctly narrows its unique value to C2–C9 and delegates C1 to `verification-before-completion`. Effective as a house-style gate.
4. **SAFETY** — Safety-**positive**, and this is its core: C2 forbids self-cleanup — *"Do not delete them… Cleanup and deletion require explicit operator approval under Hard Rule 6… 'I made it, so I may remove it' is exactly the reasoning the rule exists to stop."* Encodes our no-delete gate correctly.
5. **USEFULNESS** — Inferred: every specialist at the completion step, and Chrono before surfacing results. No identified consumer in the workflow layer, but it is the natural verify-to-ship gate; the registry row marks it *"read-on-start pre-done discipline sweep; never invoke as a tool,"* `lanes: all`. High latent usefulness.
6. **OVERLAP** — Overlaps `superpowers:verification-before-completion` (C1 defers to it) and the retired-in-repo `claim-validation-gate` (C1 relationship section). vibecheck: *"`verification-before-completion` owns running the falsifying checks… `claim-validation-gate` owns classifying each assertion."* The hype-word check (C7) overlaps the board's de-AI conventions.
7. **REDUNDANCY** — Earns its place decisively — every check binds to a house rule (Hard Rule 6 no-delete, write_scope, our honest-register style, our override protocol). A model would not, by default, refuse to delete its own scratch file (C2) or block "done" on an unpushed branch (C3) under our rules. Not general competence.
8. **IMPROVEMENT** — **Dead cross-reference.** C1's relationship section (and the skill's own registry row) hands ownership to `claim-validation-gate`, which is **retired** (now in `shared/skills/_retired/`, referenced live only here and in `code-review-loop`); `verification-before-completion` is also retired in-repo, surviving only as the `superpowers` plugin skill. Repoint C1 to the live homes (the plugin) or drop the retired-sibling name, so the gate doesn't delegate to a skill no reader can load.
9. **UNKNOWN** — Whether `superpowers:verification-before-completion` is reachable as a plugin skill on the board lanes (wired via superpowers, but board-lane reachability of superpowers skills is unverified here).

### 15. wirework-preflight  (82 lines · rich `description:`)
1. **WHAT** — A **read-only** readiness gate that probes — with real bounded *calls*, not config reads — that the MCPs, credentials, model lane, and worktree a task depends on are actually usable, before an expensive task starts; fires before a long/dependency-heavy task, or after any wiring change.
2. **CLARITY** — High; each check is a call not a lookup, with anti-patterns and a folded credential procedure. Vaguest: step 2 *"make one cheap real call against the server"* — "cheap real call" depends on the MCP, left to judgment (appropriately).
3. **EFFECTIVENESS** — Load-bearing is the whole premise — Hard Rule 9 (*"capability is proven by a live probe, never by a config file"*) — plus specific gotchas: handshake ≠ liveness, an empty env value shadows inherited auth, board workers don't inherit operator env. These are exactly our repeatedly-recorded failures. Highly effective and house-accurate.
4. **SAFETY** — Explicitly read-only (*"It reports; it does not fix, install, authenticate, or mutate"*); the credential half is name-only (*"never reads, echoes, logs, stores, or forwards a credential value"*). A safety-model skill; defers provisioning to the operator gate (Hard Rule 6).
5. **USEFULNESS** — Inferred: Chrono before dispatch, and any specialist before an expensive run. No identified consumer, but it operationalizes Hard Rule 9, to which every dispatch is subject.
6. **OVERLAP** — **Correctly** absorbs the retired `secrets-provisioning` (stated: *"Credential provisioning (folded from secrets-provisioning, retired)"*) — a declared absorption, not a dead reference. Overlaps the retired `mcp-reachability-audit` and `sandbox-provision-discipline` conceptually. No external plugin equivalent; the "probe don't trust config" discipline overlaps our own live-probe memory notes.
7. **REDUNDANCY** — Earns its place strongly — Hard Rule 9, the `~/.config/shell/secrets.zsh` convention, board-worker env non-inheritance, and handshake≠liveness are all house-specific facts a generic model lacks. Not redundant.
8. **IMPROVEMENT** — Give the trigger an observable threshold: *"before an expensive task"* is subjective, so name the measurable predicate (runtime / context cost / external dependency present) that should fire it — otherwise it is skipped precisely when a task doesn't *feel* expensive yet.
9. **UNKNOWN** — none.

### 16. wirework-reflect  (62 lines · rich `description:`)
1. **WHAT** — After a task/phase finishes, compare planned vs actual, classify the divergence (matched/partial/missed/exceeded), extract exactly one durable transferable lesson, and record it to chrono-vault (best-effort, never blocking); fires when a task or phase has just completed.
2. **CLARITY** — High; concrete steps, the `record()` call spelled out with field names, and *"Where nothing was learned, that is stated rather than padded into a note."* Vaguest: step 4 *"Check it is durable, not situational"* — the example helps, but the durable/situational line is judgment.
3. **EFFECTIVENESS** — Load-bearing: step 3 (exactly one lesson, one line, *"would it change a future run's behaviour"*) and the exceeded-bucket rule (*"a run that went unexpectedly well carries a reusable technique"*). These make the note recallable rather than a status update.
4. **SAFETY** — None; explicitly non-blocking (*"A memory error is logged in one line and never blocks the work"*).
5. **USEFULNESS** — Inferred: every specialist at task close, and Chrono. No identified consumer — and notably, **this very packet's memory policy is a hardcoded instance of exactly this skill** (recall / record / record_usage).
6. **OVERLAP** — Overlaps the board's *injected* per-packet memory policy (every dispatch instructs record-on-completion) and `session-rotation` step 6: *"Anything true beyond this task… belongs in memory rather than in a state file."* Same instruction, multiple homes.
7. **REDUNDANCY** — Earns a thin slot via our surface (the exact `record()` schema, `note_type=learning`, best-effort framing). But the *behavior* is already injected into every dispatch packet's memory policy, so on the board the skill largely restates what the harness already forces. Off-board it would add more.
8. **IMPROVEMENT** — Reconcile with the injected per-packet memory policy and `session-rotation` step 6 — three homes for "record one durable lesson to chrono-vault." Name the canonical one so the record schema doesn't drift across them (see UNKNOWN).
9. **UNKNOWN** — Whether the documented call matches the current chrono-vault API: this skill shows `record(note_type="learning", fields={...})`, `compact-now` shows positional `record("learning", {...})`, and the live tool schema is `record(note_type, title, body, target, attack_class, fields)` — three superficially different renderings; unclear which the file should track.

### 17. skill-description-trigger-authoring  (47 lines · rich `description:`)
1. **WHAT** — Author a skill's `description:` as a recognition trigger (name firing situations + real cue phrases, front-loaded, disambiguated from siblings) and replay-test it against real past tasks; fires when writing/fixing a description or diagnosing a skill that exists but never fires.
2. **CLARITY** — High; concrete steps, a bad/good worked example, and a replay-test procedure. Vaguest: step 7 *"take three real past tasks where the skill should have fired and two adjacent ones where it shouldn't"* — assumes labeled past tasks exist, which for a never-run skill they may not.
3. **EFFECTIVENESS** — Load-bearing: step 2 (write from the reader's pre-skill state — *"they cannot recognize the method's vocabulary"*) and step 7 (replay-test from the description alone). The correct method — and it is exactly the fix for the library-wide missing-description problem this audit documents.
4. **SAFETY** — None.
5. **USEFULNESS** — Inferred: anyone authoring skills — the `sysmgmt` skill-library work, Chrono, `skill-creator` users. No identified consumer, but it is the **meta-skill for the current library-wiring effort** (memory: "114/135 `shared/skills` lack a `description:` trigger").
6. **OVERLAP** — **Directly overlaps** `superpowers:writing-skills`' SDO section — *"`description`: Third-person, describes ONLY when to use (NOT what it does)… Start with 'Use when…'… NEVER summarize the skill's process or workflow"* — the same thesis. Also `skill-creator`'s Description-Optimization section, which ships an **automated** `run_loop.py` optimizer (train/test split) this manual skill lacks. Substantial overlap with two more-complete external skills.
7. **REDUNDANCY** — Largely redundant with `superpowers:writing-skills` (which the library already treats as canonical — the in-repo `writing-skills.md` is retired in favor of the plugin). Its one distinctive contribution is the replay-test-against-real-tasks procedure. **But** the automated optimizer it duplicates (`skill-creator run_loop.py`) needs `claude -p`, which board workers are forbidden to exec (the exit-75 trap) — so on the board this manual method may be the *only reachable* description-authoring path, which would flip the verdict from "redundant" to "the usable fallback." (See UNKNOWN.)
8. **IMPROVEMENT** — Reconcile with the tool it duplicates by hand: cite `skill-creator`'s `run_loop.py` and state when the manual replay-test is preferred (e.g., board lanes that cannot exec `claude -p`), so a reader knows which to use rather than re-deriving.
9. **UNKNOWN** — Whether `skill-creator`'s automated optimizer is reachable on our board lanes (it needs `claude -p`; if unreachable, this manual skill becomes the primary, not the redundant, method).

---

## Cross-cutting: dead references, drift, and duplication

- **Dead cross-reference (confirmed):** `vibecheck` C1 and its `skill-tool-registry.tsv` row both delegate ownership to **`claim-validation-gate`**, which is **retired** (`shared/skills/_retired/claim-validation-gate.md`; live references only in `vibecheck`, `code-review-loop`, and two registries). A reader following that delegation lands on a skill they cannot load.
- **Retired-but-relocated reference:** `vibecheck` also names **`verification-before-completion`**, retired in-repo (`_retired/`) but live as the `superpowers` plugin skill of the same name. The reference resolves only if the reader maps it to the plugin — the file names it as if it were an in-repo sibling.
- **Correctly-declared absorption (not a defect):** `wirework-preflight` folds the retired `secrets-provisioning` and says so. `take-over-resume` cites the retired knowledge-graph provenance explicitly as historical and invents no equivalent. Both are clean.
- **Unresolved handoff target:** `multi-stance-audit-fanout` hands off to `impact-validator (G1–G4)`, which exists as a **gate concept** across `shared/protocol.md` and several wired skills but has **no loadable skill file**. Not dead, but not loadable — worth a note.
- **One-fact-many-homes (Hard Rule 10 risk):** (a) `head-tail` ≈ the board's injected "ROUND-TRIPS" efficiency block; (b) `session-rotation` ≈ `chrono-vault:compact-now` on the registry-liveness/atomic-write facts; (c) `wirework-reflect` ≈ the injected per-packet memory policy ≈ `session-rotation` step 6. Each pair/triple maintains the same fact in ≥2 places that will age independently.
- **Catalog/registry drift:** all 17 are in `skill-tool-registry.tsv`, but `multi-stance-audit-fanout`, `scope-decomposition`, and `requirements-elicitation` are **absent from `catalog.txt`** (catalog=0, registry=1). Minor, but the two inventories disagree.
- **Description quality is bimodal:** 10 of 17 carry a `description:`; 7 do not (`agent-prompt-engineering`, `dimensional-analysis-check`, `dual-level-retrieval`, `layered-analysis-loop`, `multi-stance-audit-fanout`, `scope-estimation`, `terminology-memory`). Of the 10 that have one, two (`scope-decomposition`, `requirements-elicitation`) are **workflow summaries**, the anti-pattern their own sibling `skill-description-trigger-authoring` forbids. (This 10/17 ratio is notably *better* than the library-wide 114/135-missing figure — the process/method batch is more curated than the domain average.)

## Domain coverage gaps (process/method domain, against our specialists and workflows)

Named skills that should exist and do not:
1. **`dispatch-packet-authoring`** — the single most error-prone process we have (memory carries: `send-task.sh` required-frontmatter gotchas, heredoc-backticks-eat-content, packet-size ceiling, `write_scope` must cover coupled invariants). `scope-decomposition` produces the *units*; nothing teaches turning a unit into a valid packet (frontmatter fields, `return_artifact`, `verification_contract`, held-category authority). **Largest gap.**
2. **`review-settlement` / `verdict-echo`** — settling a cross-family review needs the reviewer to echo `reviews:` and a bare APPROVE/REJECT, and Codex verdict-string drift breaks `--settle-review` (both in memory). No skill covers the settle contract.
3. **`cross-family-review-routing`** — anti-affinity reviewer selection (author_family excluded) is a repeated house rule with no skill.
4. **`mode-selection`** — choosing free/project/bounty mode (and the `mode: project` timeout-halving gotcha) is judgment with no skill.
5. **`lane-budget-estimation`** — `scope-estimation` sizes a *corpus*; nothing sizes a *dispatch* in tokens/lane-slots/poll-budget, despite repeated memory notes on poll budgets and family caps.
6. **`de-ai-before-delivery`** — stripping phase-refs/tmp-paths/AI-tells before any external hand-off is a recorded pre-submit step (`de-AI bounty submissions`) with no skill; `vibecheck` C7 touches register but not external-delivery scrubbing.

## Anything that surprised me

- **Zero workflow-layer consumers for all 17.** They are registry-inventoried and (mostly) catalogued, yet not one is referenced in any mode, protocol, routing table, specialist brief, or the tool-trigger map. The library is *stored*, not *wired* — consistent with the packet's note that most of it was unreachable until recently.
- **`head-tail` re-teaches guidance the board injects into every packet** (including this one). A skill whose main content is already in the dispatch boilerplate and in durable memory.
- **The cure is in the batch.** `skill-description-trigger-authoring` is precisely the method that would fix the 7 no-description and 2 workflow-summary-description skills sitting next to it — and two of those defective descriptions are on its own siblings.
- **The batch is cleanly bimodal in quality** — roughly 11 long-form, house-aware, gotcha-rich skills with Acceptance/Failure-mode sections and worked examples, versus 6 short generic checklists. The polished ones read as authored by someone who had felt the failure; the thin ones read as placeholders.
- **`session-rotation` is the highest-quality file in the batch** (precise file paths, a settled decision table, a runnable liveness query) and also the one most entangled with a wired sibling (`compact-now`) — quality and duplication are correlated here, because both were written by people who cared about the same fact.

## Technique-debt table

The target of this dispatch is **17 markdown skill documents**, not executable code, a contract, a binary, or a deployed system. The offensive/hunting technique classes are therefore factually inapplicable, not merely unused.

| Technique class | Status | Basis |
|---|---|---|
| source-review | **USED** | All 17 files + 8 comparison skills read in full. |
| static-pattern-scan | **USED** | `rg`/`grep` for cross-references, consumers, retired-sibling links, catalog/registry membership. |
| property-fuzzing | **INAPPLICABLE** | No executable target; a markdown skill file has no invariants to fuzz. |
| coverage-guided-fuzzing | **INAPPLICABLE** | No binary/harness to instrument. |
| symbolic-execution | **INAPPLICABLE** | No code paths to solve; target is prose. |
| concrete-harness | **INAPPLICABLE** | Nothing to execute; the skills are unexecuted docs (registry `verified_state: authored`). |
| differential-variant | **INAPPLICABLE** | No code/CVE surface; cross-doc comparison was done as source-review, not variant analysis. |
| bytecode-census | **INAPPLICABLE** | No compiled artifact. |
| deployed-state | **INAPPLICABLE** | Nothing deployed. |
| economic-composition | **INAPPLICABLE** | No economic/on-chain system (and we hold no capability in this class regardless). |
| supply-chain | **INAPPLICABLE** | No dependency manifest in scope; skill files pull no packages. |

## Memory / telemetry

Per the packet's best-effort memory aperture: recalled once at task start (5 notes; all prior-batch skill-audit context, which confirmed this is batch C of a 6-batch effort and supplied the 114/135-missing-description figure). Artifact and envelope written first; `record` and `record_usage` issued afterward as telemetry, non-gating. No tool failed, so no `## needs_tool` section is owed.

`subagents: 0` — solo. This is a read-and-judge audit over one coherent corpus that needs a single consistent rubric applied across all 17 (the OVERLAP and REDUNDANCY fields specifically require holding the whole set in one context to spot inter-skill collisions); there were no independent sub-domains whose parallel investigation would not have fragmented that judgment.
