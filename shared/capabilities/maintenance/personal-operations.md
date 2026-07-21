---
id: maintenance/personal-operations
mode: maintenance
title: Personal operations (routines · reminders · notifications — local/draft)
capability_state: live
state_reason: Authoring and storing personal routines, reminders, and draft notifications is live via `chrono-vault` (`all·yes`) + the lane shell. **Notification DELIVERY (local or external) and calendar WRITE are `needs_tool`** — `local summary notifications` and `Gmail` are `partial`; `Google Calendar` is smoked only on the `chrono` controller lane (`chrono·yes·subscription`) — available at the account level but NOT citable as a squad-lane card tuple (lane `chrono` is not a model lane), so calendar-write stays `needs_tool`; any real send/write is operator-gated (`live_outreach`) and NOT claimed live.
state_evidence: registry rows — chrono-vault = `all·yes·subscription`; local summary notifications = `local·partial`, Google Calendar = `chrono·yes·subscription` (controller-session smoke only — no squad model lane can cite lane `chrono`), Gmail = `claude·partial` (→ notification-send + calendar-write are `needs_tool`, see Profiles).
overlays: [review, privacy, memory]
gates: [live_outreach]
cost_note: subscription lane-native (chrono-vault) + local shell for drafting/storage. No metered provider on the live path; external send / calendar-write is `needs_tool`/operator-gated, not billed here.
---

**When to use:** author and track the operator's personal routines, reminders, and draft notifications.
**Live scope is local authoring + storage + draft**; actually delivering a notification or writing to a
calendar is `needs_tool` and operator-gated (see Profiles).

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (routine / reminder spec) | `personal-ops` | — | `scope-decomposition` (stub) | privacy overlay (personal data) |
| **S3** Produce (author routines + draft reminders/notifications) | `personal-ops` | `chrono-vault` (all · yes · subscription) | — | privacy overlay |
| **S4** Verify (schedule sanity + draft review) | `personal-ops`, `skeptic` | — | — | notification-send + calendar-write = `needs_tool` (partial connectors) |
| **S5** Review/Gate (send approval) | `personal-ops`, `operator` | — | — | review overlay; **`live_outreach` — per-action operator "go"**; send/calendar-write is `needs_tool` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** The live deliverable is authored routines + reminders + drafted notifications, stored in the vault.

**Needs-tool profile (NOT part of the live claim):** delivering a notification (local or external) or writing
to a calendar is `needs_tool` — `local summary notifications` and `Gmail` are `partial`, and `Google Calendar` is smoked only on the `chrono`
controller lane (`chrono·yes·subscription`) — available at the account level but not citable as a squad-lane
card tuple (lane `chrono` is not a model lane), so squad-lane calendar-write is still `needs_tool` pending
squad-lane wiring; there is no verified squad-lane send/write route. Any real
send/write is additionally `live_outreach`-gated (per-action operator approval). Personal data fires the
privacy overlay (`privacy-steward`); minimize retained personal data.
