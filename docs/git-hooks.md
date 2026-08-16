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

> **Precedence note.** `core.hooksPath` *replaces* `.git/hooks` — while it is set, any script in `.git/hooks/` (including a locally installed one) no longer runs. That costs nothing here: `.githooks/pre-commit` itself runs the private-memory **leak guard** first, then the specialist + format checks the local hook had, capability validation, and the moat Tier-A check — a strict superset of the local hook. See "Composing with the leak guard" below.

## What the pre-commit hook does

It runs five checks, in order:

1. **Private-memory leak guard** — **always first, and blocking.** Runs `scripts/hooks/pre-commit`, which rejects staged private-memory artifacts (restricted-sensitivity notes, `_state/bounty/` paths, legacy `chrono-kg` database blobs). This is the one failure that cannot be undone once pushed, so it gates before every other check — and a *missing* guard script also blocks rather than passing silently.
2. **Capability validation** — only when the commit stages files under `shared/capabilities/` or `shared/registries/`. Runs `bin/validate-capabilities.sh` and its `--self-test`; **blocks the commit (exit 1)** if either fails.
3. **Specialist and live capability-home validation** — **on every commit**, whatever is staged, so live host drift is caught even when no specialist brief changed. Runs `bin/validate-specialists.sh --quiet` with host-independent mode forced off; **blocks the commit (exit 1)** on failure.
4. **Format checks** — **warnings only, never blocking.** Flags shell scripts missing a `set -` safety line and `shared/dispatch-toolkit.sh` missing the no-delete-rule marker.
5. **moat Tier-A boundary check** — **only fires when the commit stages files under `moat/`** (non-moat commits skip it entirely). Runs the public, data-free Layer-1 leak-boundary scanner exactly as documented in [`moat/boundary/README.md`](../moat/boundary/README.md):

   ```sh
   git diff --cached --name-only -z --diff-filter=ACMR -- moat/ \
     | xargs -0 node moat/boundary/tier-a.mjs --staged
   ```

   It **blocks the commit (exit 1)** if the scanner reports a boundary violation. It **fails open with a note** (does not block) if `node` or `moat/boundary/tier-a.mjs` is unavailable — so a clone lacking node can still commit non-moat work. To enable it, install the scanner's dependency once with `npm ci --prefix moat` and make sure `node` is on your `PATH`.

The retired Spec-1.5 **auto-snapshot** check is intentionally absent: current dispatch deliberately leaves git untouched, so there is no snapshot to require.

## Composing with the leak guard

`scripts/hooks/pre-commit` is a separate Python **leak guard** that rejects staged private-memory artifacts. It is orthogonal to Tier-A: the leak guard blocks private-file *presence*; Tier-A checks Layer-1 *contents* for capability/provenance/secret issues.

`.githooks/pre-commit` invokes the leak guard itself, as its first and unconditional check, so setting `core.hooksPath .githooks` gives you both from a single tracked file. The guard also remains usable standalone: a clone that does not set `core.hooksPath` can still install it as a local `.git/hooks/pre-commit`.

## Scope

`.githooks/pre-commit` is the public Layer-1 gate. Private exact-target matching (Tier-B) belongs in private pre-push / CI enforcement, not this public pre-commit — see [`moat/boundary/README.md`](../moat/boundary/README.md).
