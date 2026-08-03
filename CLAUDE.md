# Vibe Squad Root Instructions

Vibe Squad is markdown-first:

```text
Operator -> Chrono -> gpt-codex | claude | gemini | kimi -> specialists
```

Chrono is the only controller and the only operator-facing voice. Model leads execute scoped markdown task packets. Source namespaces under `departments/` are mailbox/storage locations only; they do not determine model choice.

## Canonical Sources

- Routing: `shared/specialist-runtime-map.tsv`
- Dispatch protocol: `shared/protocol.md`
- Runtime rules: `shared/routing.md`
- Mode workflows: `shared/modes/*.md`
- Specialist behavior: `departments/*/specialists/*.md` and `shared/specialists/*.md`
- Model lead prompts: `model-lanes/*`
- Durable memory: private markdown vault via `chrono-vault` (`record`/`recall`); see `plugins/chrono-vault/README.md`

Generated adapters, stale handoffs, old specs, and runtime logs are not source of truth. The `chrono-vault` `record`/`recall` loop is the durable cross-session learning store; the legacy in-repo KG SQLite and the `recall` LIKE-stub it replaced are retired.

## Hard Rules

1. No mode or external action starts without explicit operator consent.
2. Chrono chooses mode, specialist, write scope, model, and review gate.
3. `source_namespace` chooses mailbox/specialist location; `to_model` chooses the model/CLI that runs it.
4. Model leads do not talk to the operator directly.
5. Reviewers are read-only unless Chrono serializes a later write packet.
6. Deletes, credential changes, public release changes, cleanup actions, live outreach/email sends, paid media generation, and production mutations (mutating a live production system that is not itself a public release; operator-ratified 2026-07-13) require explicit operator approval.
7. Write shared state atomically with temp + fsync/sync + rename.
8. Verify before claiming done. No fabricated citations or unverifiable provider claims. Vendor-provided benchmark numbers may be cited as vendor claims, but may not be used as planning assumptions until reproduced on at least one Vibe Squad-controlled benchmark or explicitly labeled unverified.
9. **Capability is proven by a live probe, never by a config file.** Declared (capability source) ≠ delivered (generated adapter) ≠ actual (what the runtime exposes) — only *actual* counts. Before any routing/architecture decision that rests on what a lane or specialist can do, dispatch a bounded probe that reports the literal command and its literal result. Agreement between documents that share an origin is not corroboration. A capability is not available until a real board dispatch demonstrates it (2026-07-30: three config sources agreed a lane had no shell; the probe found shell plus 42 working tools).

## Session Resume

**This section is the single resume contract. `chrono/CLAUDE.md` implements it.** Settled 2026-08-03 by
probing which files are actually written, not by comparing documents. The capsule was then repaired and
the repair cross-family APPROVED (`TASK-2026-08-05-0240`) after two rejections — see the note below.

**Regenerate, then read. These are ONE step, never separated:**

```bash
bash bin/chrono-resume-capsule.sh     # non-fatal: on failure continue, note the file's mtime, warn
```

then read the capsule it just wrote:

1. `_state/chrono/resume.md` — **primary.** ~500-750 tokens, derived from `_state/chrono/decisions.jsonl`
   plus the **live** board registry. Trustworthy *only because you just regenerated it*: a capsule read
   without regenerating is stale by construction, which is exactly how it once sat ten days old while
   rendering cleanly.
2. `_state/chrono-queue.md` — response-completion records from the watcher.
3. `departments/*/current.md` — live mailbox state per namespace.
4. Response files, only for task IDs still pending or in-flight.

The capsule carries **live** tasks itemised, **deferred** work itemised with IDs and next actions
(`blocked`, `needs_review`, `needs_human`, `needs_rework`, `timed_out`, `work-done-no-envelope`), a
declared count for anything the token bound drops, and a loud marker naming any status the partition
does not know. **Nothing owed is silently absent** — that property is the whole point and is canary-tested.

**`chrono/current.md` is an ARCHIVE, not a resume source.** Open it only for a specific prior turn or
task the operator names; never bulk-read it.

**Never bulk-read `_state/active-tasks.json`.** It holds ~1,300 records of which ~20 are live (4.9 MB,
measured 2026-08-03). The capsule extracts the live slice for you. If you must query it directly, filter:

```bash
python3 -c "import sys;sys.path.insert(0,'scripts/python')
from chrono_state.registry import registry_view
v=registry_view();print(len(v['live']),'live',len(v['deferred']),'deferred',v['unclassified'] or 'none')"
```

`docs/handoffs/`, old plans/specs, and `_state/*report*` files are historical unless current state references them.

> **How this was settled, and what it cost.** Two documents disagreed: this file listed
> `active-tasks.json` → `current.md`, while `chrono/CLAUDE.md` made the bounded `resume.md` capsule
> primary and demoted `current.md` to an archive. The paths were probed rather than ranked by recency.
>
> `chrono/CLAUDE.md` was **right about `current.md`** — it is an archive. It was **wrong that the
> capsule was live**, though not because the capsule was a bad idea. `chrono_state/resume.py` existed
> and worked, but was disconnected twice: `render_capsule()` had **no callers**, so nothing wrote the
> file, and it read `_state/tasks/active.json`, a bounded registry the live board no longer fed. Two
> registries had diverged silently, so it faithfully regenerated two-week-old truth.
>
> **It was repaired rather than retired**, over three rounds and two cross-family REJECTs, and the
> rejections are the useful part:
>
> - Round 1 shipped a detector for unknown statuses that **production never called**, and tests that
>   exercised the library function instead of the production path — so four defects hid behind green
>   tests. *A test that does not traverse the production path proves nothing about it.*
> - Round 2 tried to order a compaction snapshot against the capsule by **file mtime**. An exact tie
>   silently favoured the stale snapshot, and a copied file carries a newer mtime with older content.
>   **mtime is not a causality signal.**
> - Round 3 **deleted** that comparison rather than repairing it a third time. Precedence now needs no
>   timestamps: explicit turn wins, else an existing capsule line is kept, else the snapshot fills the
>   vacuum. The cost — a genuinely fresher snapshot no longer beats an older capsule line — is pinned
>   by a test asserting the *losing* behaviour, so anyone who "fixes" it later gets a red build and has
>   to read why.
>
> Two method notes worth keeping. The first probe here grepped for the filename and concluded no
> generator existed; it writes through a path variable — **a grep miss is not an absence proof.** And a
> claim that "nothing reads the capsule" was withdrawn after review: the search had excluded `chrono/`,
> where the one reader always lived.
>
> This is Hard Rule 9 applied to documentation: recency and agreement between documents are not
> evidence — only what the runtime does counts.
