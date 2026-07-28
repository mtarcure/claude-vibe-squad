# Git hooks

Vibe Squad ships a **tracked, opt-in** pre-commit hook at [`.githooks/pre-commit`](../.githooks/pre-commit). Tracked hooks reach clones; the classic `.git/hooks/` directory does not, so this is how a clone gets the squad's commit-time checks.

## Enable it (one-time, per clone)

```sh
git config core.hooksPath .githooks
```

That points git at the tracked `.githooks/` directory instead of `.git/hooks/`. It is **opt-in** and **per-clone local config** — it is never set for you, and it is not committed.

Disable again with:

```sh
git config --unset core.hooksPath
```

> **Precedence note.** `core.hooksPath` *replaces* `.git/hooks` — while it is set, any script in `.git/hooks/` (including a locally installed one) no longer runs. `.githooks/pre-commit` carries over the same specialist + format checks the local hook had, and adds the moat Tier-A check, so switching is a strict superset for those. If you also rely on the separate private-memory **leak guard** (`scripts/hooks/pre-commit`), see "Composing with the leak guard" below.

## What the pre-commit hook does

It runs three checks, in order:

1. **Specialist validation** — only when a staged file is a specialist brief (`departments/*/specialists/*.md`, `shared/specialists/*.md`, or `.claude/agents/*.md`). Runs `bin/validate-specialists.sh`; **blocks the commit (exit 1)** if validation fails. Fast, no network.
2. **Format checks** — **warnings only, never blocking.** Flags shell scripts missing a `set -` safety line, task packets missing required frontmatter, and `shared/dispatch-toolkit.sh` missing the no-delete-rule marker.
3. **moat Tier-A boundary check** — **only fires when the commit stages files under `moat/`** (non-moat commits skip it entirely). Runs the public, data-free Layer-1 leak-boundary scanner exactly as documented in [`moat/boundary/README.md`](../moat/boundary/README.md):

   ```sh
   git diff --cached --name-only -z --diff-filter=ACMR -- moat/ \
     | xargs -0 node moat/boundary/tier-a.mjs --staged
   ```

   It **blocks the commit (exit 1)** if the scanner reports a boundary violation. It **fails open with a note** (does not block) if `node` or `moat/boundary/tier-a.mjs` is unavailable — so a clone lacking node can still commit non-moat work. To enable it, install the scanner's dependency once with `npm ci --prefix moat` and make sure `node` is on your `PATH`.

The retired Spec-1.5 **auto-snapshot** check is intentionally absent: current dispatch deliberately leaves git untouched, so there is no snapshot to require.

## Composing with the leak guard

`scripts/hooks/pre-commit` is a separate Python **leak guard** that rejects staged private-memory artifacts (restricted-sensitivity notes, `_state/bounty/` paths, KG database blobs). It is orthogonal to Tier-A: the leak guard blocks private-file *presence*; Tier-A checks Layer-1 *contents* for capability/provenance/secret issues.

Because `core.hooksPath` runs a single `pre-commit`, you cannot have both files active as `pre-commit` at once. To run both, either:

- add a `node moat/boundary/tier-a.mjs`-style call into your own wrapper, or
- keep the leak guard as your local `.git/hooks/pre-commit` and do **not** set `core.hooksPath` (then wire Tier-A manually), or
- extend `.githooks/pre-commit` to also invoke `scripts/hooks/pre-commit`.

Pick one deliberately; this repo ships the tracked hook and the leak guard as separate, composable pieces rather than forcing a combination.

## Scope

`.githooks/pre-commit` is the public Layer-1 gate. Private exact-target matching (Tier-B) belongs in private pre-push / CI enforcement, not this public pre-commit — see [`moat/boundary/README.md`](../moat/boundary/README.md).
