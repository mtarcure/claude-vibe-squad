---
id: project/personal-operations
mode: project
title: Personal operations (routines · reminders · notifications — local/draft)
overlays: [review, privacy, memory]
gates: [live_outreach]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** author and track the operator's personal routines, reminders, and draft notifications.
**Live scope is local authoring + storage + draft**; actually delivering a notification or writing to a
calendar is `needs_tool` and operator-gated (see Profiles).

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (routine / reminder spec) | `personal-ops` | — | `scope-decomposition` | privacy overlay (personal data) |
| **S3** Produce (author routines + draft reminders/notifications) | `personal-ops` | `chrono-vault` | — | privacy overlay |
| **S4** Verify (schedule sanity + draft review) | `personal-ops`, `skeptic` | — | — | notification-send + calendar-write = `needs_tool` (partial connectors) |
| **S5** Review/Gate (send approval) | `personal-ops`, `operator` | — | — | review overlay; **`live_outreach` — per-action operator "go"**; send/calendar-write is `needs_tool` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** The live deliverable is authored routines + reminders + drafted notifications, stored in the vault.

**Needs-tool profile (NOT part of the live claim):** delivering a notification (local or external) or writing
to a calendar is `needs_tool` — `local summary notifications` and `Gmail` are `partial`, and `Google Calendar` is smoked only on the `chrono`
controller lane — available at the account level but not citable as a squad-lane
card tuple (lane `chrono` is not a model lane), so squad-lane calendar-write is still `needs_tool` pending
squad-lane wiring; there is no verified squad-lane send/write route. Any real
send/write is additionally `live_outreach`-gated (per-action operator approval). Personal data fires the
privacy overlay (`privacy-steward`); minimize retained personal data.
