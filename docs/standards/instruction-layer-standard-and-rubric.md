# The Instruction-Layer STANDARD and audit RUBRIC

Task: `TASK-2026-08-09-0020-md-standard-rubric` · specialist `prompt-engineer` · lane `claude`
Scope: **author only.** No instruction file is edited here. This document is the standard another
author writes to, and the checklist another auditor applies line by line.

Governing principle: **one fact lives at exactly one level.** Lower levels *point up* to the
canonical statement; they never restate it. A fact that appears at two levels is, by construction,
a defect — redundant at best, contradictory at worst — **with the single exception named by root
`CLAUDE.md` Hard Rule 10: an *enforced* duplicate, where a validator pins the copies identical and a
named file states which wins, is legitimate.** Root `CLAUDE.md` is the canonical L1 (`AGENTS.md:3`), so
where this standard and Hard Rule 10 disagree, Hard Rule 10 governs; every *un*enforced cross-level
duplicate is the defect this standard hunts.

Everything below is grounded in the tree as it stands on 2026-08-08. Where the packet's framing of a
level diverges from what is physically on disk, that divergence is called out — it is itself an
instance of the drift this standard exists to prevent.

---

## Part 0 — The one rule that assigns a fact to a level (the invariance test)

Before the per-level tables, the single decision procedure that the whole standard reduces to:

> **A fact belongs at the level whose audience is exactly the set over which the fact does not vary.**

Ask: *across what set is this fact constant?*

| The fact is constant across… | …so it belongs at | and varies by |
|---|---|---|
| every namespace, role, lane, and dispatch | **L1** root policy | nothing |
| every role inside one namespace, but differs between namespaces | **L2** namespace lead | namespace |
| every lane a role runs on, but differs between roles | **L3** specialist brief | role |
| — but differs when the same role runs on another model family | **L4** lane overlay | model family |
| only this one task | **L5** dispatch injection | per task |

Two corollaries the rest of the document enforces:

1. **Exception ⇒ demote.** If a candidate fact is *almost* always true at a level but has an
   exception there, it does not belong at that level. Either it moves down to the level where it is
   exceptionless, or it splits into the general part (higher) and the exception (lower). **The one
   standing counter-example is enforced, not a defect:** the single Kimi-MCP-brokering caveat in the
   shared *Tools available to me* paragraph ("Kimi subagents cannot hold MCP …") rides in the L3 base
   of every brief, pinned identical by `scripts/python/validate_capability_homes.py` against the
   approved text in `model-lanes/adapter-capability-policy.json`. Under Hard Rule 10 (a validator pins
   the identity, a named file states the text) that makes it a legitimate enforced duplicate and *not*
   a demote target — even though a lane-varying capability fact normally is. The runtime enforces this
   L3 placement, so it wins over the demote rule here.
2. **Reusable + inlined = pointer.** If a block is constant across dispatches yet is physically
   injected on every dispatch, it is misplaced at L5. Its canonical home is a file one level up, and
   L5 should carry a one-line pointer to it. This is the single largest source of unearned token cost.

**A sixth stratum sits above L1 for one lane — the Codex boot adapter, `AGENTS.md` (call it L0).** It
is a *loader*, not a fact home: it names root `CLAUDE.md` canonical and mandates the orientation reads,
so every Codex worker loads it before L1. It places no fact of its own, so it takes no row in the
invariance table above; audit it under Pass 1 only — does it still name the live canon? With L0 named,
the taxonomy covers the six live strata a worker actually experiences (L0 boot · L1 · L2 · L3 · L4 · L5).

---

## Deliverable 1 — THE STANDARD

### L1 — root `CLAUDE.md` (project policy)

- **Belongs:** system-wide invariants true for every namespace, role, lane, and dispatch — the Hard
  Rules, the controller model (Chrono is the sole controller and only operator-facing voice), the
  operator-gate *principle*, the canonical-source pointer list, the session-resume contract.
- **Never:** per-specialist behaviour; tool inventories; capability claims; a role/lane/namespace-**specific**
  tool, flag, or lane; or any procedure that a validator, the routing TSV, or a lower level already
  encodes. (Naming a **system-wide** canonical source is allowed and expected — the canonical-source
  pointer list above names `chrono-vault`/`record`/`recall`, the routing TSV, and `shared/protocol.md`,
  because those names are invariant across every namespace, role, and lane. The prohibition is on
  *role/lane-varying* names, not on the canonical pointers L1 exists to carry.) If deleting one
  namespace, role, or lane would make the sentence false or irrelevant, it is not an L1 fact.
- **Deciding rule:** *"Would this be equally true if I deleted any single namespace, role, or lane?"*
  Yes → L1. Names a concrete role/tool/lane → not L1.
- **Target length:** policy + pointers only, ~150–220 lines. Every concrete procedure is a pointer to
  its canonical file, not an inlined copy. (The current file already models this well — e.g. the
  resume contract points at `bin/chrono-resume-capsule.sh` and `chrono/CLAUDE.md` rather than inlining
  the capsule logic.)

### L2 — per-namespace lead / roster context

- **Belongs:** the roster of specialists that live in this mailbox namespace, and cross-namespace
  routing reminders ("for OSINT/vendor research, hand off to the research namespace"). Because a
  namespace is a **mailbox/storage location only** (root `CLAUDE.md`, Hard Rule 3), L2 carries mailbox
  facts and routing pointers — never model choice.
- **Never:** model/lane binding (that is the routing TSV and L4); specialist behaviour (L3); system
  policy (L1).
- **Deciding rule:** *"Does this vary from one namespace to the next, yet hold for every role inside
  the namespace?"* → L2.
- **Target length:** ~15–35 lines per namespace: roster list + routing reminders, nothing more.
- **⚠ Grounding note (a live level-collision).** There is currently **no `departments/*/CLAUDE.md`
  file** — `rg --files -g 'CLAUDE.md'` returns only root, `chrono/`, and `model-lanes/claude/`. The L2
  content is instead emitted at dispatch time by `shared/dispatch-toolkit.sh` (its `## Mailbox
  Namespace Context` blocks, e.g. the `coding)` case at `dispatch-toolkit.sh:~333`). That means a
  fact invariant *per namespace* is physically injected *per dispatch* (L5): every dispatch re-pays
  its tokens, and the roster cannot be edited as one unit. Under this standard, L2's canonical home is
  one file (or one data row) per namespace, which L5 references by pointer. The packet's own framing —
  "`departments/*/CLAUDE.md` (per-namespace lead prompts, 14 of them)" — describes files that do not
  exist and a count (14) that does not match the five namespaces on disk; treat that as the target
  state, and as Exhibit A for the OUTDATED rubric class below.

### L3 — specialist brief (`departments/*/specialists/*.md`, `shared/specialists/*.md`)

- **Belongs:** the role's identity and judgment — what this specialist does and does **not** do, when
  to fan out, when to escalate, its input/output contract, and craft-level style. Facts that vary by
  **role** but hold on every lane the role can run on.
- **Never:** tool/MCP/skill names or capability claims (they vary by lane → L4; the canonical base is
  explicitly designed to "name no tool, MCP, or skill" — see any brief's *Tools available to me*
  paragraph, whose **one** validator-enforced exception is the Kimi-MCP-brokering caveat noted under
  *Exception ⇒ demote* above); model/lane routing (TSV); board-orchestration mechanics such as "invoke
  X via the `Task` tool" (a controller action, and a capability no board lane has — see the calibration
  appendix); system policy (L1).
- **Deciding rule:** *"Is this true of this role on every lane, and false for at least one other
  role?"* → L3. If it changes when you switch the model family → L4. If it is true of all roles →
  L1 or L5.
- **Target length:** ~40–90 lines. Identity + fan-out/escalate + do-not list + I/O contract.

### L4 — per-model lane overlay / adapter (`model-lanes/*`)

- **Belongs:** the lane binding ("you are the `X` specialist running inside the `claude` model lane"),
  the capability projection (the `mcps`/tools this role actually receives on *this* lane, inside the
  `# BEGIN SPECIALIST CAPABILITY PROJECTION` block), a pointer back to the canonical L3 brief, and
  genuinely lane-specific execution notes ("Kimi subagents cannot hold MCP"). Facts that vary by
  **model family**.
- **Never:** a re-statement of the role's judgment or behaviour — the adapter must *point* to L3
  ("Canonical specialist instructions live at `shared/specialists/...`. Read that file at task start
  and follow it over this adapter") and never fork it; system policy; per-task rails.
- **Deciding rule:** *"Does this change when the same role runs on a different model family?"* → L4.
- **Target length:** ~15–40 lines. A thin binding + capability block + a pointer — never a second copy
  of the brief. (`model-lanes/claude/.claude/agents/prompt-engineer.md`, 22 lines, is the model.)

### L5 — dispatch-time injection (`shared/dispatch-toolkit.sh` + the completion contract + the packet)

- **Belongs:** only what is **both** universal to every dispatch **and** genuinely per-task — the
  completion/envelope contract, the write-scope and no-delete rails, the read-only runtime envelope,
  and the task packet itself (its `id`, scope, deadline, verification contract). Content that must
  ride with the task because it encodes *this* task's identity or a per-attempt harness requirement.
- **Never:** anything invariant across dispatches that could be a pointer instead — reusable doctrine,
  rosters, tool catalogs, multi-paragraph essays. Every token here is paid on **every** dispatch, so
  this is where unearned cost accumulates fastest and where the "reusable + inlined = pointer"
  corollary bites hardest.
- **Deciding rule:** *"Does this change per task **and** does the worker need it in-context to finish
  **this** task?"* Yes → L5. Same on every dispatch → move to a canonical file and inject a pointer.
- **Target length:** the packet + envelope contract + rails; keep all dispatch-invariant doctrine
  behind pointers. The current injection is large (the toolkit alone renders well over 25 KB per
  dispatch); the standard's target is to relocate every dispatch-invariant block (verdict-discipline
  essay, execution-efficiency essay, namespace rosters) to canonical files and inject one-line
  pointers, reserving inline text for what is truly per-task.

### The master principle, restated for authors

Lower levels **point up**; they never restate. When you are about to write a fact, run the invariance
test, find its one home level, and — if you are not editing that home — write a pointer instead of a
copy. If you cannot point because there is no canonical home, you have found the missing file; create
it at the right level rather than inlining the fact where you happen to be.

---

## Deliverable 2 — THE RUBRIC

A line-by-line checklist. It assumes the auditor has the repo checked out and can run `rg`, `ls`, and
`sed`. It produces findings in one schema (bottom of this section). Every pass names the concrete
check, the decision test, and a calibration hit proving the pass catches a known defect.

### How to run it (the mechanical loop)

1. **Pass 0 once per file** to establish ground truth.
2. Then walk the file **top to bottom, one line (or one bullet/block) at a time.** For each line, run
   Passes 1–5 in order. The first pass that fires produces a finding; keep going (a line can trip more
   than one class — e.g. a Task-tool claim is both *conflicting* and *unearned cost*).
3. Emit findings most-severe first (see ordering) using the finding schema.

### Pass 0 — Establish ground truth (before line 1)

- **0a. Fix the file's level.** From its path: root `CLAUDE.md` → L1; `departments/*/` lead file or
  the `dispatch-toolkit.sh` namespace block → L2; `*/specialists/*.md` → L3; `model-lanes/*` → L4;
  `dispatch-toolkit.sh` rails + the completion contract + the packet → L5. Write the level down; every
  later test is relative to it.
- **0b. List the canonical home for each fact-type**, so Passes 2–3 have something to compare against:
  routing/model choice → `shared/specialist-runtime-map.tsv` + `shared/routing.md`; capability/tools →
  the adapter's `SPECIALIST CAPABILITY PROJECTION` + `model-lanes/lane-capabilities.tsv`; lifecycle →
  `shared/lifecycle.md`; operator gates → `shared/lane-policy.tsv`; system policy → root `CLAUDE.md`.
- **0c. Prove your resolver works** (positive control for Pass 1): resolve one reference you *know* is
  valid and confirm it lands. An `rg` that finds nothing because of a bad glob is indistinguishable
  from a true absence — a silently-failed search and a true-negative print the same empty output.

### Pass 1 — OUTDATED (does the referent still exist and still behave this way?)

- **How to spot it.** For every path, filename, tool, flag, function name, or `file:line` reference on
  the line: resolve it. `ls`/`rg --files` the path; `rg -n '<symbol>'` the identifier; check a named
  tool is actually on PATH/in the registry. For a reference to a *behaviour* ("X does Y", "the flag is
  `--z`"), verify the current code/rule still matches — a reference can point at a file that still
  exists while describing behaviour that changed.
- **Decision test.** Referent absent, moved, renamed, or behaving differently → OUTDATED. If your
  search returns empty, apply 0c before concluding absence (a grep miss is not an absence proof).
- **Finding fix.** Update the reference to the live target, or delete it if the referent is gone for
  good.
- **Calibration hits.**
  - **(resolved 2026-08-09 — retained as the pass's worked example.)**
    `departments/sysmgmt/specialists/memory-curator.md:100` **used to** say *"Allowlist of paths to
    scan (in `_state/dream-config.yaml`)."* — a pointer at a config with zero live readers: the file
    did not exist, and nothing read it as a dream-scan allowlist. Commit `8c83b1fe` removed both the
    brief's line and the export-allowlist entry; today the brief has zero `dream-config` hits, and
    the only `dream-config` mentions left under `tools/export/` are regression tests
    (`tests/test_projector.py`, `tests/test_product_hygiene.py`) pinning its removal.
  - The packet's L2 description, "`departments/*/CLAUDE.md` (… 14 of them)" — zero such files exist;
    the count and the path are both stale.

### Pass 2 — REDUNDANT (is this fact already stated at its canonical level?)

- **How to spot it.** For each assertion, name its canonical home level (from 0b). If the current file
  is **not** that level yet states the fact anyway — rather than pointing to it — it is redundant. Also
  scan for **intra-file** repetition: the same instruction in two sections of one file.
- **Decision test.** Fact is fully determined elsewhere (canonical file, or an earlier section of this
  file) and is re-asserted here in prose → REDUNDANT. (Contrast with a deliberate pointer, which is
  *not* redundant — a one-line "see `shared/routing.md` §9" is correct.)
- **Finding fix.** Replace the restatement with a one-line pointer to the canonical source, or delete.
- **Calibration hit (resolved 2026-08-13 — retained as the pass's worked example).**
  `departments/coding/specialists/architect.md` **used to** state the multi-model routing rule twice —
  once in *When to fan out* and again in a *Multi-model when needed* section — and the two copies drifted
  into disagreement. That duplication was removed; the brief now states the fan-out rule once (`:23–:28`)
  and has no second multi-model section. Pass 2 fires whenever a file restates a fact its canonical level
  owns instead of pointing to it — do not file this against the current `architect.md`, whose referent is
  gone.

### Pass 3 — CONFLICTING (does it contradict another level, or itself?)

- **How to spot it.**
  - *Cross-level:* compare the assertion against the canonical fact (0b) and against the dispatch rail
    the worker also receives. Flag anything a worker could not simultaneously obey.
  - *Self:* scan the file for two lines that share a **trigger** but give different **verdicts**.
- **Decision test.** Two instructions in force at once cannot both be satisfied → CONFLICTING. Record
  which one the canonical source says is correct.
- **Finding fix.** Cite both `file:line` refs, state the incompatibility, name the authoritative side,
  and reword or delete the other.
- **Calibration hits.**
  - *"solo as multi-model" — resolved in `architect.md` 2026-08-13; the sibling instance resolved 2026-08-12.*
    `architect.md` **used to** tell a solo worker to "handle solo as multi-model with Codex+Claude" and
    to "invoke as multi-model" both sides itself — internally incoherent (a single running worker cannot
    *be* multi-model) and cross-level conflicting: the dispatch rail states the worker is "one side of it,
    never all three" and that "multi-model / Codex AND Claude independently … describes **Chrono's dispatch
    pattern, not your job**." Those lines were corrected to "handle solo" plus "Chrono dispatches the
    council as separate packets," so do not file this against the current `architect.md`. **The same class
    also surfaced at** `smart-contract-engineer.md:26` — *"handle solo with … the multi-stance audit flow
    below"* — **and was resolved 2026-08-12**: the flow it points to now scopes its stances as *"in-process
    analytical stances under one worker"* with cross-family review handed to a separate Chrono dispatch
    (`smart-contract-engineer.md:70`), so a solo worker can run it and Pass 3 no longer fires. Do not file
    this against the current brief.
  - *Worker told to dispatch — resolved in `architect.md`.* The brief **used to** say *"dispatch `skeptic`
    in council mode,"* which contradicted the orchestration rail ("Do NOT create board tasks … cross-worker
    coordination is Chrono's job"); it now says Chrono dispatches the council. Pass 3 (and Pass 5) still
    fire on any brief that instructs a worker to dispatch another specialist.

### Pass 4 — UNCLEAR (could a competent worker act two different ways?)

- **How to spot it.** Apply the **two-worker test** to each instruction: could two competent workers
  read this line and correctly do different things? The usual sources are (a) a term with two
  referents live in the same context, (b) a pronoun/antecedent with no unambiguous target, and (c) an
  instruction with no observable oracle ("handle appropriately", "as needed").
- **Decision test.** More than one defensible action → UNCLEAR.
- **Finding fix.** Name the ambiguous token, give the two readings, and pick one term per referent —
  applied globally, not just at this line.
- **Calibration hit — the word "lane" carries two referents in one injected rail.** As *model family /
  vehicle*: `dispatch-toolkit.sh:269` — *"Executing model lane: `${TO_MODEL}`."* As *a single running
  worker / attempt*: `dispatch-toolkit.sh:299` — *"Measured across 57 board lanes … Lanes that ignored
  this took ~37 minutes"* — and the process-isolation rail's *"several lanes run on this host at
  once."* A worker told "your lane" cannot tell which is meant. Fix: reserve **lane** for the model
  family and use **attempt** (or **worker**) for a running instance, then sweep every occurrence.

### Pass 5 — UNEARNED COST (does the worker pay tokens for text it never uses?)

- **How to spot it.** For each block ask: *does completing **this** task require this in-context, and
  is it not already available behind a pointer?* If the block is reusable, dispatch-invariant, and
  inlined, it is unearned cost — and it bites hardest at L5, which is paid on every dispatch.
- **Decision test.** Reusable + dispatch-invariant + inlined → move to a canonical file, inject a
  pointer. Also flag any capability claim that names a tool/mechanism **no lane has**: it costs tokens
  *and* misleads, so it is unearned cost compounded with a Pass-3 conflict.
- **Finding fix.** Relocate to the canonical file and inject a one-line pointer, or delete.
- **Calibration hits.**
  - *A capability no lane has, repeated 11×.* Briefs instruct invoking another specialist "via the
    `Task` tool with `subagent_type: …`" — `scout.md:27,43`, `security-analyst.md:31,32,48`,
    `threat-modeler.md:27,43`, `impact-validator.md:65`, `privacy-steward.md:27`
    (`Agent(subagent_type=research)`), and `shared/specialists/skeptic.md:84`. A board worker cannot
    invoke another *board* specialist this way — cross-specialist handoff is Chrono's, and the
    sandbox denies model-CLI exec (the exit-75 trap). The text costs tokens on every dispatch of those
    roles and points a worker at an action it must not take.
  - *Dispatch-invariant essays inlined at L5.* The verdict-discipline and execution-efficiency
    sections of `dispatch-toolkit.sh` are identical on every dispatch; under the standard they are
    canonical files referenced by pointer, not re-injected wholesale each time.

### The finding schema (one shape for every pass)

```
[CLASS] path:line — <one-line claim of the defect>
  Quote:  "<the exact offending text>"
  Ground: <canonical fact / absent referent / contradicting path:line — the evidence>
  Fix:    <exact proposed edit: delete | replace-with-pointer(<target>) | reword to "<text>">
  Conf:   CONFIRMED | PLAUSIBLE  (if PLAUSIBLE: what single check would confirm it)
```

- **CLASS** ∈ {OUTDATED, REDUNDANT, CONFLICTING, UNCLEAR, UNEARNED-COST}.
- **Every finding quotes its ground.** A CONFLICTING finding names the other side's `path:line`; an
  OUTDATED finding shows the absent/renamed target; a REDUNDANT finding names the canonical home. A
  finding without a quoted ground is not yet a finding — it is a hunch (mark it PLAUSIBLE and state the
  confirming check).
- **Ordering / severity** (emit most-severe first): CONFLICTING and OUTDATED first — they make a
  worker act *wrong* (wrong action, dead path). UNCLEAR next — a worker may act wrong. REDUNDANT and
  UNEARNED-COST last — a worker acts right but the layer pays maintenance and token cost. When one
  line trips several classes, report it once under its most-severe class and list the others in the
  claim.

---

## Calibration appendix — the known defects mapped to the passes that catch them

Proof the rubric catches every defect the task named, each with the pass and the live citation.

| # | Known defect (as stated in the task) | Rubric pass | Live citation |
|---|---|---|---|
| 1 | Multi-model check claimed "in-lane / solo / no dispatch" | Pass 3 CONFLICTING (self + cross-level) | Resolved in `architect.md` 2026-08-13 (was `:28` "handle solo as multi-model", `:69` "invoke as multi-model"); also surfaced at `smart-contract-engineer.md:26` "handle solo with … the multi-stance audit flow", resolved 2026-08-12 (`:70` scopes the stances to one worker; cross-family review handed to Chrono) |
| 2 | Multi-model check "via the `Task` tool / subagent" — a capability no lane has | Pass 5 UNEARNED-COST + Pass 3 CONFLICTING | `scout.md:27,43`; `security-analyst.md:31,32,48`; `threat-modeler.md:27,43`; `impact-validator.md:65`; `privacy-steward.md:27`; `skeptic.md:84` |
| 3 | Injected rail labels the **compatibility** namespace under the word **Source** | Pass 1 OUTDATED (comment ⇄ code drift) | emitted text is already fixed to "Mailbox namespace (compatibility)" at `dispatch-toolkit.sh:268`, but the header comments still mislabel it — `dispatch-toolkit.sh:2` "emit source-namespace context" and `:11` "every lane sees the source namespace roster", while the code takes `<compatibility-namespace>` (`:22`) |
| 4 | "lane" meaning both a model family and a single running worker | Pass 4 UNCLEAR | `dispatch-toolkit.sh:269` (family) vs `:299` and the process-isolation rail (running worker) |
| 5 | `memory-curator.md:100` points at `_state/dream-config.yaml` as a live allowlist; zero readers | Pass 1 OUTDATED | Resolved in `memory-curator.md` 2026-08-09, commit `8c83b1fe` (was `:100` "Allowlist of paths to scan (in `_state/dream-config.yaml`)"); the file remains absent and the only `dream-config` mentions left under `tools/export/` are regression tests pinning its removal |

Note on #3: the calibration example describes the *emitted* mislabel, which has since been corrected in
the rendered output. The residue survives in the script's comments. This is why Pass 1 treats a file's
comments and its code as **one surface**: a corrected output beneath a stale comment still misleads the
next editor, who trusts the comment. A rubric that only read rendered output would miss it.

---

## Technique-debt table (per the dispatch rail)

This is a documentation-authoring task (`capability: none`, target = markdown instruction files). The
security technique classes are factually inapplicable; recording why, per the rail's requirement that
an absence claim name the target fact and the absent capability.

| Technique class | Status | Reason |
|---|---|---|
| source-review | USED | Read the instruction files directly (`architect.md`, `dispatch-toolkit.sh`, `memory-curator.md`, briefs, lane overlays) to ground every finding. |
| static-pattern-scan | USED | `rg` over the tree to enumerate `Task`/`subagent_type` claims, `dream-config` readers, and "lane" referents. |
| static-pattern-scan (SAST: semgrep/slither/aderyn) | INAPPLICABLE | No source code or contract in scope — the targets are markdown/`bash` instruction text; SAST engines parse code, not doctrine. |
| property-fuzzing / coverage-guided-fuzzing | INAPPLICABLE | No executable under test; there is no program state to fuzz in an instruction corpus. |
| symbolic-execution | INAPPLICABLE | No contract/bytecode; nothing for a symbolic engine to explore. |
| concrete-harness / deployed-state | INAPPLICABLE | No deployed system in scope; the deliverable is a standard and a rubric, not a live probe. |
| bytecode-census / differential-variant | INAPPLICABLE | No bytecode and no code variants; the "variant" work here (finding all 11 Task-tool sites) was done with `rg`, which is the right tool for text. |
| supply-chain / economic-composition | INAPPLICABLE | No dependency graph or economic protocol in scope. |

---

## Load-bearing questions and oracles (per the dispatch rail)

The verdicts in the calibration appendix are claims; each was settled by an observable oracle, not by
document agreement.

- **Q:** Does `_state/dream-config.yaml` have any live reader? **Oracle:** `ls` the path (absent) +
  `rg -l dream-config` excluding `.md` (hits only `tools/export/` fixtures). **Verdict:** REFUTED that
  it is a live allowlist — quoted guard is the absence of the file and of any non-test reader.
- **Q:** Can a board worker invoke another specialist via the `Task` tool / `subagent_type`?
  **Oracle:** the dispatch rail's own text ("Do NOT create board tasks … Your sandbox denies
  model-CLI exec") plus Hard Rule 4 (model leads do not talk to the operator / each other).
  **Verdict:** the capability is not a worker capability — the briefs that instruct it are defective.
- **Q:** Does the emitted rail still label the compatibility namespace "Source"? **Oracle:**
  `dispatch-toolkit.sh:268` renders "(compatibility)". **Verdict:** BOUNDED, not REFUTED — the emitted
  text is fixed, but the mislabel survives in comments (`:2`, `:11`); the defect class is still live.
