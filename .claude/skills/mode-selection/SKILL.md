---
name: mode-selection
audience: chrono
description: Use when choosing the operator-approved `mode` (`project` versus `bounty`) before launch—approval of the work does not approve that workflow. Not for constructing fields or reviewer routing.
---

# Mode Selection

House procedure for choosing a dispatch mode before authoring the packet. The mode is a separate
operator decision from the work itself, and the wrong mode silently changes the wall, the
verification contract, and the gates a lane runs under. Verify every claim here against the current
scripts — do not trust this doc over the code.

## Name the mode and get approval — it is its own consent
- `chrono/CLAUDE.md` Dispatch step 1 requires opening the chosen file under `shared/modes/`, stating
  which mode the work will run under, and waiting for the operator to agree. Hard Rule 1 forbids a
  mode starting without explicit consent.
- **Approving the work is not approving the mode.** Measured 2026-08-21: an operator approved a
  bounty campaign and 34 of 38 lanes dispatched as `mode: project` — nobody was told. Say the mode
  word out loud; never infer it from "yes, go".

## Both dispatch paths preserve an explicit choice
- Generated packets use `scripts/send-task.sh ... --mode project|bounty`. The wrapper rejects an
  omitted or invalid value, writes the exact choice into frontmatter, and never supplies a default.
- Prepared packets carry `mode: project|bounty` in frontmatter and dispatch with
  `bin/send-task.sh <packet-file>`, which carries the packet's own `mode` into the compiled contract
  (`MODE_VALUE` -> `"mode"`).
- The wrapper survives because it still assembles standard frontmatter, resolves lanes and review
  metadata, and routes through the hardened dispatcher. Retire it only if those conveniences move
  elsewhere; do not retain or reintroduce a mode default as its reason to exist.

## Verify the mode that LANDED, never the one you intended
- The dispatch context carries the landed mode as a real field. Read it from the **exact attempt you
  dispatched**, never from a glob — attempt ids are UUIDs, so glob order is not chronological and
  `head -1` can hand you a previous attempt's mode after a retry:
  ```bash
  python3 -c 'import json,sys; a=json.load(open(sys.argv[1]))["authority"]; \
    p=a.get("mode_profile"); m=(a.get("memory_context") or {}).get("mode"); \
    print(p if p==m else f"MISMATCH profile={p} memory={m}")' <context_path>
  ```
  `mode_profile` and `memory_context.mode` must agree; if they disagree, stop — do not pick one.
- A wrapper `--dry-run` echoes `Packet mode: <mode>` and derives that mode's contract. It proves the
  generated packet's choice but not a landed attempt; a green prepared-packet dry-run likewise does
  not replace the exact-attempt check.
- If the landed mode differs from what the operator approved, stop and say so before the lane works.

## The mode changes the contract, not just the wall
- Walls come from `timeout_budget_for_mode()` in `dispatch_context_builder.py`: a flat 2700s for
  `project`, 3600s for `bounty`. Scope to the emitted number; do not infer it from a ratio.
- `verification_contract.py` sets a different contract per mode. `project` requires
  `project_tests`/`recipient_contract` and mandatory recall+record. `bounty` swaps in
  `scope_gate`/`no_self_inflicted`/`poc_reproduction`, an exact target allowlist, forbids
  submission-attempted, and makes recall OPTIONAL (a cold lane cannot recall without inheriting other
  runs' conclusions).
- `project` and `bounty` both carry a `plan_review_policy` with `anti_affinity: author_family` — an
  independent-family plan check is part of the contract. That is the controller's plan review and is
  separate from the deliverable's own `review_model`; a `project` packet with `review_model: none`
  still launches.
