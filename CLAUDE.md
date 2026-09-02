# Vibe Squad Root Instructions

Vibe Squad is markdown-first:

```text
Operator -> Chrono -> gpt-codex | claude | gemini | kimi | grok -> specialists
```

Chrono is the only controller and the only operator-facing voice. Model leads execute scoped markdown task packets. Source namespaces under `departments/` locate specialist/role markdown only; they do not determine model choice.

## Canonical Sources

- Routing: `shared/specialist-runtime-map.tsv`
- Dispatch protocol: `shared/protocol.md`
- Runtime rules: `shared/routing.md`
- Mode workflows: `shared/modes/*.md`
- Specialist behavior: `departments/*/specialists/*.md` and `shared/specialists/*.md`
- Model lead prompts: `model-lanes/*`
- Durable memory: private markdown vault via `chrono-vault` (`record`/`recall`); see `plugins/chrono-vault/README.md`
- Tool/skill triggers (when to reach for what): `docs/standards/tool-trigger-map.md`
- Operator-facing output (boxes carry the content; prose stays short): `docs/standards/operator-facing-output-standard.md`

Generated adapters, stale handoffs, old specs, and runtime logs are not source of truth. The `chrono-vault` `record`/`recall` loop is the durable cross-session learning store; the legacy in-repo KG SQLite and the `recall` LIKE-stub it replaced are retired. The `chrono-kg` MCP namespace remains live as a compatibility alias backed by those canonical Markdown-vault operations; it does not revive SQLite.

## Versions — three numbering systems, all real

Confusing these is the single most common source of "is this doc out of date?" in this repo.

- **`V1.1.4` is the current release version.** Git tags `v1.1.0` through `v1.1.4`; the next
  upgrade would be `V1.1.5`. This is the version of the system as a product.
- **`V3` / `V4` are architecture generations**, not old release numbers. Git tags `v3-final` and
  `v4-baseline-2026-08-07`. The dispatcher still runs a **live V3 compatibility bridge**, so
  `shared/protocol.md` saying "the staged V4 boundary" is current, not stale. Renaming these to
  `V1.1.1` would destroy a real distinction.
- **`contract/v1`, `dispatch-preflight/v1` and friends are schema identifiers** that code parses.
  Never touch them.

Bounty mode's internal `v2` → `v3` (`shared/modes/bounty.md`) is a fourth, mode-local axis
describing why that mode dropped its gates. Also not a release number.

## Hard Rules

1. No mode or external action starts without explicit operator consent.
2. Chrono chooses mode, specialist, write scope, model, and review gate.
3. `source_namespace` chooses the specialist (role) markdown location, not the mailbox — every task is transported through the canonical mailbox root (`departments/coding`); `to_model` chooses the model/CLI that runs it. (Home: `shared/protocol.md` § board-native transport, enforced by `dispatch_context_builder.py` `CANONICAL_MAILBOX_ROOT`.)
4. Model leads do not talk to the operator directly.
5. Reviewers are read-only unless Chrono serializes a later write packet.
6. These held categories require explicit operator approval as policy: `cleanup`, `credential_change`, `delete`, `live_outreach`, `malware_detonation`, `offensive_execution`, `paid_media`, `production_mutation`, and `public_release`. `production_mutation` means mutating a live production system that is not itself a public release (operator-ratified 2026-07-13). Ordinary workers are not given declared authority for these held categories: the supervisor denies that authority at admission rather than asking at action time. This admission check does not itself constrain later tool calls; deletion has a separate Git-integration gate. `scripts/python/tests/test_held_action_gate.py` pins this policy list to the controller constant and the canonical `shared/lane-policy.tsv` vocabulary. See `shared/protocol.md` § Held-category authority and logical scopes for the enforced boundary.
7. Write shared state atomically with temp + fsync/sync + rename.
8. Verify before claiming done. No fabricated citations or unverifiable provider claims. Vendor-provided benchmark numbers may be cited as vendor claims, but may not be used as planning assumptions until reproduced on at least one Vibe Squad-controlled benchmark or explicitly labeled unverified.
9. **Capability is proven by a live probe, never by a config file.** Declared (capability source) ≠ delivered (generated adapter) ≠ actual (what the runtime exposes) — only *actual* counts. Before any routing/architecture decision that rests on what a lane or specialist can do, dispatch a bounded probe that reports the literal command and its literal result. Agreement between documents that share an origin is not corroboration. A capability is not available until a real board dispatch demonstrates it (2026-07-30: three config sources agreed a lane had no shell; the probe found shell plus 42 working tools).
10. **One fact, one home.** When you copy a file, or restate a fact that already lives somewhere, either delete the original in the same change or record which copy wins and what keeps the copies in agreement. An unenforced copy is not a backup — it is a second answer that ages independently, and the next reader cannot tell which one is true. A duplicate is legitimate only when a validator enforces the identity and a named file states the winner. Duplication accumulates from caution, not carelessness — a backup before an edit, a mirror before a cutover, a tracked copy so a worker could read it — which is why it hides (2026-08-10: nine plan files, four claiming to describe current work and three of those wrong; a standard copied to a reachable path with the unreachable original left tracked).

## Session Resume

**There is a single resume contract, and it is Chrono's to execute** — no board worker runs it.
At session start Chrono **regenerates, then reads** the bounded capsule `_state/chrono/resume.md`
(one step, never separated) as the **primary** source. The capsule itemises live and deferred work
with a loud marker for any status the partition does not know, so **nothing owed is ever silently
absent** (canary-tested). A capsule read without regenerating is stale by construction; never
bulk-read the multi-MB `_state/active-tasks.json` monolith — the capsule extracts the live slice, and
`chrono/current.md` is an archive, not a resume source.

- Operational steps (regenerate command, read order, direct-query filter): `chrono/CLAUDE.md`
  § Start Of Session.
- How the contract was settled, and what its two rejections cost:
  `chrono/resume-contract-decision-record.md`.

`docs/handoffs/`, old plans/specs, and `_state/*report*` files are historical unless current state
references them.
