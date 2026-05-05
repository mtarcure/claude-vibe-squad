# Memory Discipline — Universal Rules

How every memory in this system is written, verified, decayed, and purged.

This is the **single source of truth for cross-cutting memory rules**. Each Lead's `memory.md` cites this file and adds domain-specific rules on top. Specialists inherit both layers.

---

## The three memory layers

This system has three distinct persistence layers. Knowing which to use is rule #1.

| Layer | Path | Scope | When to use |
|-------|------|-------|-------------|
| **Auto-memory** | `~/.claude/projects/-Users-chrono/memory/` | Cross-session for the controller (Chrono / Claude Code) | User profile, feedback, project context, references — anything that needs to survive across sessions outside the vault |
| **Squad memory.md** | `departments/<lead>/memory.md` | Lead-specific durable knowledge | Distilled domain learnings: "Library X has issue Y," "This bounty program requires Z," "Research source A is authoritative for topic B" |
| **chrono-vault** | Obsidian + KG (chrono-vault MCP) | Canonical semantic graph | Facts that need wiki-link cross-referencing, attempts/findings/decisions that should be queryable by other Leads, anything benefiting from graph navigation |

**Never duplicate across layers.** A memory belongs in exactly one layer. If the same fact lives in two places, one is stale or obsoletes the other — purge the duplicate.

**Graduation rule**: a memory in `memory.md` graduates to `chrono-vault` when (a) more than one Lead would benefit from it, OR (b) it would be more useful with wiki-link context, OR (c) it's referenced by 3+ tasks. Memory-curator handles graduations weekly.

---

## Universal rules every memory must obey

### 1. Timestamp + source citation required

Every memory entry includes the date written and the source it was derived from (task ID, URL, file path, conversation ref). Memories without provenance are stripped on next purge.

```markdown
- **2026-05-03**: HackenProof requires KYC for payouts (source: TASK-2026-05-03-1524)
```

Not:
```markdown
- HackenProof needs KYC
```

### 2. Verify before relying on memory > 2 weeks old

Memory captures what was true *when written*. Before acting on a memory older than 2 weeks, verify against current state — read the file, check the live API, query the source. If verification contradicts memory, **purge the stale entry, don't append a new contradicting one**.

Domain rules can override this universal default (e.g., Security may keep findings indefinitely; see per-Lead overrides below).

### 3. Purge in place — don't accumulate contradictions

When a memory is wrong, REMOVE the wrong entry. Don't add a contradicting line below it. Stale knowledge that accumulates is a vibecoding failure mode.

If the wrong memory was load-bearing for past decisions, leave a 1-line `# superseded YYYY-MM-DD: <reason>` marker in commit history, not in memory.md.

### 4. Don't substitute memory for current-state verification

Memory primes hypotheses. Memory does NOT prove current state. Before recommending a file, function, flag, or path that lives in memory: read the file, grep the symbol, run the command. If the user is about to act on the recommendation, verification is mandatory, not optional.

The phrase "the memory says X exists" is not the same as "X exists now."

### 5. Memory taxonomy

Every memory is one of four types. Apply the type label in the file structure (a section heading or per-entry tag).

| Type | What it is | Example |
|------|-----------|---------|
| **Fact** | An objective statement about the world or codebase | "HackenProof requires KYC" |
| **Preference** | The operator's stated style, taste, or process choice | "Operator prefers terse responses, no trailing summaries" |
| **Project state** | Active work, in-flight tasks, near-term goals | "Bounty target selection deferred until firsthand survey returns" |
| **Reference** | Pointer to where authoritative information lives | "Bounty platform tabs in Chrome at port 9222" |

Project state decays fastest (days). Preference is durable until contradicted. Fact decays per #2. Reference rarely decays but verify before each use.

### 6. Privacy / redaction baseline

No raw secrets in memory. Reuse `scripts/python/dream_light.py` SECRET_PATTERNS list — emails, OpenAI/Anthropic/xAI/Perplexity/Google API keys, GitHub PATs (classic + fine-grained), AWS access keys, Slack tokens, JWTs, HuggingFace, Stripe, Apify, bearer-in-URL.

If a memory needs to reference a secret-bearing artifact (e.g., "the .env at path X has the deploy key"), reference the *location*, not the value.

### 7. Conflict resolution between universal and per-Lead rules

When a per-Lead rule contradicts a universal rule, the per-Lead rule wins for that Lead's domain — but **memory-curator must surface the conflict to the operator** instead of silently auto-applying. Examples that should always surface:

- Security says "never auto-purge findings"; universal says "verify >2wk old." → Lead rule wins, no auto-purge, but verification still happens (manually or by memory-curator's nightly nudge).
- Research says "primary sources only"; universal says "any sourced citation OK." → Lead rule wins.

Never let a contradiction live silently. Either reconcile or surface.

---

## Per-Lead overrides

Each Lead's `memory.md` may add domain-specific rules. Common shapes:

| Lead | Likely overrides | Why |
|------|------------------|-----|
| Security | Findings never auto-decay; redaction includes per-program disclosure rules; severity classification required per entry | Bug bounty work has long tails; findings retained until paid + 1y |
| Content | Brand-voice anchors override style universals; audience-specific patterns kept indefinitely | Brand learnings compound over time |
| Research | Source-tier rules (primary > secondary > tertiary); citation freshness per topic; authoritative sources by domain | Source quality varies by field |
| Coding | Distilled-knowledge-not-transcripts (already enforced); library-version-specific notes | Avoid memory bloat with debug session logs |
| SysMgmt | Routine timing notes; environmental quirks; system invariants | Mac/launchd-specific |

Each LEAD.md or per-Lead `memory.md` opens with:

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
3. **On-demand**: when a Lead reports "memory contradicted by current state," memory-curator runs a focused purge on the affected category.

All purges write proposals to `_state/cleanup-logs/<date>-brain.md`. **Auto-deletion is forbidden** — purges always go through operator approval, except the universal "purge stale entry on contradiction" which is performed by the contradiction-finder Lead inline (rule #3).

---

## Anti-patterns (what NOT to do)

- ❌ Append a contradiction below the wrong entry instead of replacing it
- ❌ Save a memory of "I just looked at X" — that's session state, not durable knowledge
- ❌ Copy a memory across multiple memory.md files — pick one home, cite from elsewhere
- ❌ Save a memory without source citation
- ❌ Treat a memory written 6+ months ago as canonical without re-verifying
- ❌ Save a memory that's already in the code/file (`# my-flag is at config.yaml:42` — code is the source of truth, memory just rots)
- ❌ Save secrets, tokens, or unredacted PII

---

## Audit hooks

- `bin/doctor.sh` should validate every memory.md has the discipline cite at the top (added in Phase 4).
- `vibecoding_check.py` should fail mode-end if any new memory entry was written without timestamp+source (added in Phase 3 wire-in).
- Memory-curator's nightly proposals include a "no-citation" category for retroactive cleanup.

---

## Why this discipline exists

Memory is fast and feels like investigation. It isn't. It's a hypothesis primer with decay characteristics. Treat it as such: verify before relying, purge when wrong, cite when writing, override deliberately. The system that flooded itself with stale "facts" 6 months ago is the same system that recommends nonexistent functions today.
