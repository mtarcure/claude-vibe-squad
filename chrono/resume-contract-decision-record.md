# Decision record — the session-resume contract

Chrono-only history. The one-line contract lives at root `CLAUDE.md` § Session Resume; the
operational steps live in `chrono/CLAUDE.md` § Start Of Session. This file records **how the
contract was settled and what it cost**, relocated here from root `CLAUDE.md` so every board worker
stops paying ~2.4 KB of context for history only Chrono consults. Settled 2026-08-03 by probing
which files are actually written, not by comparing documents; the repair was cross-family APPROVED
(`TASK-2026-08-05-0240`) after two rejections.

> **How this was settled, and what it cost.** Two documents disagreed: root `CLAUDE.md` listed
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

## Direct-query filter (if the capsule is unavailable)

`_state/active-tasks.json` holds ~1,300 records of which ~20 are live (4.9 MB, measured 2026-08-03).
Never bulk-read it; if you must query it directly, filter for the live slice:

```bash
python3 -c "import sys;sys.path.insert(0,'scripts/python')
from chrono_state.registry import registry_view
v=registry_view();print(len(v['live']),'live',len(v['deferred']),'deferred',v['unclassified'] or 'none')"
```
