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

Generated adapters, stale handoffs, old specs, and runtime logs are not source of truth.

## Hard Rules

1. No mode or external action starts without explicit operator consent.
2. Chrono chooses mode, specialist, write scope, model lane, and review gate.
3. `source_namespace` chooses mailbox/specialist location; `to_model` chooses the runtime window.
4. Model leads do not talk to the operator directly.
5. Reviewers are read-only unless Chrono serializes a later write packet.
6. Deletes, credential changes, public release changes, cleanup actions, live outreach/email sends, paid media generation, and production mutations (mutating a live production system that is not itself a public release; operator-ratified 2026-07-13) require explicit operator approval.
7. Write shared state atomically with temp + fsync/sync + rename.
8. Verify before claiming done. No fabricated citations or unverifiable provider claims. Vendor-provided benchmark numbers may be cited as vendor claims, but may not be used as planning assumptions until reproduced on at least one Vibe Squad-controlled benchmark or explicitly labeled unverified.

## Session Resume

Read live state only:

1. `_state/active-tasks.json` if present
2. `chrono/current.md`
3. `departments/*/current.md`
4. response files only for task IDs still pending or in-flight

`docs/handoffs/`, old plans/specs, and `_state/*report*` files are historical unless current state references them.
