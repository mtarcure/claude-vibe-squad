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

Read live state only:

1. `_state/active-tasks.json` if present
2. `chrono/current.md`
3. `departments/*/current.md`
4. response files only for task IDs still pending or in-flight

`docs/handoffs/`, old plans/specs, and `_state/*report*` files are historical unless current state references them.
