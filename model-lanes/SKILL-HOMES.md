# Skill homes across the board lanes (canonical decision)

**Decided:** 2026-08-18 (TASK-2026-08-18-1633-3c7b63ef). **Enforced by:**
`scripts/python/validate_skill_wiring.py`.

## The problem

Each CLI discovers project skills from a *different convention directory*, and no
single physical directory can serve all four lanes:

| Lane | process cwd | reads skills from |
|------|-------------|-------------------|
| claude | worktree root | `<cwd>/.claude/skills/` |
| gpt-codex | worktree root | `<cwd>/.agents/skills/` |
| gemini | `model-lanes/gemini` | `<cwd>/.agents/skills/` (cwd-relative, **not** `--include-directories`) |
| kimi | worktree root | dirs passed via `--skills-dir` (no cwd auto-discovery) |

All four paths were enumerated **live** on 2026-08-18 (see the task response). Gemini
is the only lane whose cwd is not the worktree root, so its `<cwd>/.agents/skills`
does not exist unless bridged.

## The decision (Hard Rule 10: one fact, one home)

- **`.claude/skills/` is the canonical home** for cross-lane skills. It holds the real
  skill directories and is claude's proven load path. **It is the winner.**
- **`.agents/skills/` is the shared home for the non-claude lanes.** Every cross-lane
  specialist skill appears there as a **byte-identical regular-file copy** at
  `.agents/skills/<name>/SKILL.md`. Symlinks are forbidden because launch hygiene refuses
  to start a worker when one exists in the writable tree. The validator enforces identity
  against the canonical `.claude/skills/<name>/SKILL.md` so copied mirrors cannot drift.
- **Gemini reaches the shared home through a cwd bridge:**
  `model-lanes/gemini/.agents/skills` is a tracked regular-directory materialization.
  Its loadable entries must correspond to skills in the shared `.agents/skills` home;
  symlinked, empty, malformed, or unrelated bridge content fails validation. Without this
  cwd-relative bridge gemini enumerates only its built-in skills.
- **Kimi** is wired in `bin/board-supervisor.sh` with `--skills-dir <worktree>/.agents/skills`
  (the superset — passing `.claude/skills` too would surface each mirrored skill twice).
- **`probe-canary` is intentionally NOT mirrored:** it is a distinct per-path canary in
  each home (`.claude/skills/probe-canary` proves the claude path; `.agents/skills/probe-canary`
  proves the `.agents` path). Each is a real directory with its own body.
- **The three gate skills are dual-homed cross-lane skills:** `rule6-rights-gate`,
  `rule8-truth-gate`, and `visual-regression-baseline` live canonically in
  `.claude/skills/`, with byte-identical regular-file mirrors in `.agents/skills/`.
  The validator enforces their identity just like every other same-name mirror.

## Audience routing (who a skill is FOR)

A cross-lane home answers *where* a skill lives; **`audience:` answers *who reaches for it*.**
Every wired skill declares one of:

- **`audience: chrono`** — an action only the controller ever performs: board dispatch,
  registry settlement, reviewer/lane routing, lane failover, budget gates.
- **`audience: specialist`** — work a lane specialist performs: audit flows, offensive
  bench work, generation craft, verification gates.

The test is **not** "could a specialist read this" (they can read anything) but **"does a
specialist ever PERFORM this action?"** A `chrono` skill mirrored into the specialist home is
pure trigger noise: it competes for match attention against skills the specialist can act on,
and it can never fire for them. So:

- **`audience: chrono` skills live in `.claude/skills/` ONLY** — they are NOT mirrored into
  `.agents/skills/`.
- **`audience: specialist` skills MUST be mirrored** into `.agents/skills/` (else
  codex/gemini/kimi cannot reach them).
- `probe-canary` is exempt: a per-path infra canary deliberately present in both homes.

> **On-disk form:** the projector materialises regular-file copies. Keep the canonical and
> mirrored `SKILL.md` bytes identical when editing a `specialist` skill; the validator rejects
> both drift and symlinks.

## What the validator enforces

Run: `python3 scripts/python/validate_skill_wiring.py --root <repo>` (or `--self-test`).

- **Audience routing (3 hard conditions):** every wired skill declares a valid `audience:`;
  no `audience: chrono` skill is mirrored into `.agents/skills/`; every `audience: specialist`
  skill IS mirrored there. Chrono mirrors that predate this rule and cannot be removed without
  operator-authorized deletion are carried in the validator's `PENDING_DEMOTION` as a loud note
  (not a hard failure) until the operator deletes them.
- **Mirror integrity:** every same-name `.agents/skills/<name>/SKILL.md` mirror must be a
  byte-identical regular-file copy of `.claude/skills/<name>/SKILL.md`; symlinks, missing files,
  and byte drift are hard failures. `.agents`-native skills and the distinct per-path
  `probe-canary` are not identity mirrors.
- **Gemini bridge:** `model-lanes/gemini/.agents/skills` must be a nonempty regular materialized
  bridge whose loadable entries all correspond to shared-home skills.
- **Kimi launcher:** `bin/board-supervisor.sh` must pass `--skills-dir`.
- **Per-lane reach report:** how many skills each lane can enumerate, plus coverage gaps
  (`audience: chrono` skills are intentionally not mirrored, so they are not counted as gaps).

## Adding a new cross-lane skill

1. Create `.claude/skills/<name>/SKILL.md` (the real home) with an `audience:` field.
2. **If `audience: specialist`,** copy the directory to `.agents/skills/<name>` (byte-identical).
   **If `audience: chrono`,** do NOT mirror it — it stays in `.claude/skills/` only.
3. Re-run the validator; it will show the new skill reachable by the correct lanes.
