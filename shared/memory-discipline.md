# Memory Discipline — Universal Rules

How every memory in this system is written, verified, superseded, and archived.

This is the single source of truth for cross-cutting memory rules. Each namespace `memory.md` cites this file and may add source-specific rules on top. Specialists inherit both layers.

---

## The three memory layers

This system has three distinct persistence layers. Knowing which to use is rule #1.

| Layer | Path | Scope | When to use |
|-------|------|-------|-------------|
| **Auto-memory** | `~/.claude/projects/<repo-name>/memory/` | Cross-session for the controller (Chrono / Claude Code) | User profile, feedback, project context, references — anything that needs to survive across sessions outside the vault |
| **Squad memory.md** | `departments/<source_namespace>/memory.md` | Namespace-specific durable knowledge | Distilled learnings: "Library X has issue Y," "This bounty program requires Z," "Research source A is authoritative for topic B" |
| **chrono-vault** | Private Markdown + disposable FTS5/BM25 index (chrono-vault MCP) | Cross-squad durable notes | Typed attempts/findings/learnings that should be recalled across tasks. Explicit links are preserved in Markdown; graph expansion is benchmark work, not current runtime truth. |

**Status of the Squad `memory.md` layer (verified against `.gitignore` and `git ls-files`).** This layer is
**operator-local and gitignored — not tracked, not shared.** `.gitignore:86` excludes
`departments/*/memory.md` (alongside `:85` `departments/*/current.md` and `:88` `chrono/memory.md`), so these
files are never committed, never published in a clone or export, and never travel to another machine or lane.
They are created on demand and **may not exist at all** — at this writing none do. There is also **no
`departments/shared/memory.md`**: the shared namespace has no `memory.md` file, consistent with shared
specialists having no `departments/shared` mailbox (`shared/protocol.md` § Lifecycle). Treat this layer as a
private, per-machine scratch of distilled learnings — anything that must survive a clone or reach another lane
belongs in `chrono-vault`.

**Never duplicate truth across layers.** A memory belongs in one authoritative layer. Other layers may point to it. When two durable notes overlap, preserve provenance and mark the older note `superseded` or `archived`; do not delete it.

**Graduation rule**: a memory in `memory.md` graduates to `chrono-vault` when more than one namespace would benefit from it, it would be more useful with wiki-link context, or it is referenced by 3+ tasks. Memory-curator handles graduations weekly.

---

## Universal rules every memory must obey

### 1. Timestamp + source citation required

Every memory entry includes the date written and the source it was derived from (task ID, URL, file path, conversation ref). Missing provenance is a curation defect: quarantine or surface it for review rather than silently deleting it.

```markdown
- **2026-05-03**: a target program requires KYC for payouts (source: engagement task record)
```

Not:
```markdown
- The target program needs KYC
```

### 2. Verify before relying on memory > 2 weeks old

Memory captures what was true *when written*. Before acting on a memory older than 2 weeks, verify against current state — read the file, check the live API, query the source. If verification contradicts a chrono-vault note, record the corrected note and mark the old one `invalidated` or `superseded` with provenance. Never erase the historical signal.

Domain rules can override this universal default (e.g., Security may keep findings indefinitely; see per-model-lane overrides below).

### 3. Resolve contradictions through lifecycle state

For chrono-vault, do not remove or rewrite a wrong note. Record the corrected note, then use the compare-and-swap lifecycle transition to mark the old note `invalidated` or `superseded`. A reviewer can see both the original claim and why it stopped being active.

For a namespace `memory.md` — operator-local and gitignored (see the layer status above), not a tracked file — correct the prose in place and leave a concise supersession reason when the old statement was load-bearing. Do not keep two unlabeled active claims.

### 4. Don't substitute memory for current-state verification

Memory primes hypotheses. Memory does NOT prove current state. Before recommending a file, function, flag, or path that lives in memory: read the file, grep the symbol, run the command. If the user is about to act on the recommendation, verification is mandatory, not optional.

The phrase "the memory says X exists" is not the same as "X exists now."

### 5. Memory taxonomy

Every memory is one of four types. Apply the type label in the file structure (a section heading or per-entry tag).

| Type | What it is | Example |
|------|-----------|---------|
| **Fact** | An objective statement about the world or codebase | "The target API rate-limits at 60 req/min" |
| **Preference** | The operator's stated style, taste, or process choice | "Operator prefers terse responses, no trailing summaries" |
| **Project state** | Active work, in-flight tasks, near-term goals | "Bounty target selection deferred until firsthand survey returns" |
| **Reference** | Pointer to where authoritative information lives | "Working tabs in the persistent Chrome at port 9222" |

Project state decays fastest (days). Preference is durable until contradicted. Fact decays per #2. Reference rarely decays but verify before each use.

### 6. Privacy / redaction baseline

No raw secrets in memory. Redact these classes when writing to any persistent surface: emails, OpenAI/Anthropic/xAI/Perplexity/Google API keys, GitHub PATs (classic + fine-grained), AWS access keys, Slack tokens, JWTs, HuggingFace, Stripe, Apify, bearer-in-URL.

If a memory needs to reference a secret-bearing artifact (e.g., "the .env at path X has the deploy key"), reference the *location*, not the value.

### 7. Conflict resolution between universal and namespace rules

When a namespace rule contradicts a universal rule, the namespace rule wins for that source domain, but memory-curator must surface the conflict to the operator instead of silently auto-applying. Examples that should always surface:

- Security namespace says findings retain indefinitely; universal says "verify >2wk old." Retention wins, and verification still happens. No namespace rule authorizes physical deletion.
- Research namespace says "primary sources only"; universal says "any sourced citation OK." Namespace rule wins.

Never let a contradiction live silently. Either reconcile or surface.

---

## Namespace Overrides

Each namespace `memory.md` may add source-specific rules. Common shapes:

| Namespace | Likely overrides | Why |
|------|------------------|-----|
| Security | Findings never auto-decay; redaction includes per-program disclosure rules; severity classification required per entry | Bug bounty work has long tails; findings retained until paid + 1y |
| Content | Brand-voice anchors override style universals; audience-specific patterns kept indefinitely | Brand learnings compound over time |
| Research | Source-tier rules (primary > secondary > tertiary); citation freshness per topic; authoritative sources by domain | Source quality varies by field |
| Coding | Distilled-knowledge-not-transcripts (already enforced); library-version-specific notes | Avoid memory bloat with debug session logs |
| SysMgmt | Routine timing notes; environmental quirks; system invariants | Mac/launchd-specific |

Each namespace `memory.md` opens with:

```markdown
## Memory discipline

This memory follows `shared/memory-discipline.md` for universal rules.

Domain overrides:
- <override 1>
- <override 2>
```

---

## Triggers for memory-curator action

Memory-curator (under SysMgmt) handles three sweeps:

1. **Nightly light**: structural hygiene (orphan notes, broken links, duplicates, empties) via `brain_cleanup.py`. Proposals only — operator approves.
2. **Weekly deep**: contradiction detection (semantic, not structural — currently unimplemented; tracked as gap), confidence-decay sweep (entries with confidence <0.3 and age >180d), graduation candidates (memory.md → chrono-vault).
3. **On-demand**: when a model lead reports "memory contradicted by current state," memory-curator proposes exact lifecycle transitions for the affected notes.

All curation runs write proposals to `_state/cleanup-logs/<date>-brain.md`. **Auto-deletion is forbidden.** A model may propose `superseded`, `invalidated`, or `archived`; the canonical writer applies reviewed transitions. Physical removal requires the separate deletion gate and is never implied by contradiction or age.

---

## Anti-patterns (what NOT to do)

- ❌ Leave two contradictory notes active instead of invalidating or superseding the old one
- ❌ Save a memory of "I just looked at X" — that's session state, not durable knowledge
- ❌ Copy a memory across multiple memory.md files — pick one home, cite from elsewhere
- ❌ Save a memory without source citation
- ❌ Treat a memory written 6+ months ago as canonical without re-verifying
- ❌ Save a memory that's already in the code/file (`# my-flag is at config.yaml:42` — code is the source of truth, memory just rots)
- ❌ Save secrets, tokens, or unredacted PII

---

## Audit hooks

- `bin/doctor.sh` should validate every memory.md has the discipline cite at the top (added in Phase 4).
- **Not wired:** `vibecoding_check.py` has no timestamp+source check on new memory entries. Verified 2026-08-17 against `scripts/python/vibecoding_check.py` — no such `check_*` function exists, and the "added in Phase 3 wire-in" note this bullet used to carry was never true. Treat timestamp+source as a discipline the author owes, not a gate that catches them. What the gate does enforce is stated once, in `shared/lifecycle.md` rule 14.
- Memory-curator's nightly proposals include a "no-citation" category for retroactive cleanup.

---

## Why this discipline exists

Memory is fast and feels like investigation. It isn't. It's a hypothesis primer with decay characteristics. Treat it as such: verify before relying, preserve corrections, cite when writing, and override deliberately. The system that flooded itself with stale "facts" six months ago is the same system that recommends nonexistent functions today.
