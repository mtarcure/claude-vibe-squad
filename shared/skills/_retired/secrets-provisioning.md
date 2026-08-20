---
name: secrets-provisioning
retired: "merged into wirework-preflight — credential inventory fires on the same pre-task moment preflight already probes; absent-vs-invalid distinction + never-read-values rule folded into the survivor."
status: authored
description: Use when a plan has been approved and is about to start executing work that needs credentials — inventory every required credential by name against what is actually available, and pause before starting rather than failing part-way through.
---

# Secrets Provisioning

Inventory the credentials a task requires against the credentials actually reachable from the runtime
that will use them, and **pause before the work starts** if any are missing. A task that dies at its
third external call has already spent its context, produced partial state, and left the operator to
work out which half completed.

The gate is a **presence check on names**. It never reads, echoes, logs, stores, or forwards a
credential value.

## When to use
- A plan is approved and about to begin work that touches an external provider, API, or authenticated service.
- A packet names a tool whose use requires a key.
- A previous run failed on an authorization error and the cause has not been established.

## Steps
1. **Derive the required set from the plan, one entry per credential.** For each: the variable name, what
   it is for, and which step first needs it. A credential nobody can attribute to a step is either
   unnecessary or a sign the plan is underspecified.
2. **Inventory what is available, by name only.** The operator convention is `~/.config/shell/secrets.zsh`;
   extract the exported *names*. Do not read the values, do not print the file, and do not include a value
   in any output, artifact, log, or downstream context.
3. **Establish availability in the runtime that will actually use the credential — not in the operator's
   shell.** These are different environments and the difference is the usual cause of surprise: a board
   worker does not inherit the operator's ambient environment, so a name present in the operator's secrets
   file may simply be absent where the work runs. Where the credential is load-bearing, confirm with one
   bounded authenticated call from that runtime.
4. **Distinguish absent from present-but-invalid.** A missing name and an expired, revoked, or
   wrong-scoped key produce entirely different fixes. Only a real call separates them; presence alone
   cannot, and reporting "credential present" for a key that returns 401 sends the operator to the wrong
   place. Note also that one operation's success does not vouch for its siblings — providers scope keys
   per-endpoint.
5. **If anything is missing or invalid, pause and report.** Do not improvise around the gap: do not
   substitute a different provider, do not fall back to an unauthenticated path that silently returns
   degraded results, and do not proceed hoping the credential appears. State, per missing credential: the
   name, its purpose, the step that needs it, and what the operator must do.
6. **Never provision the credential yourself.** Adding, changing, or rotating a credential is an operator
   gate under Hard Rule 6. Surface the need and stop.
7. **When all credentials are accounted for, say what was verified and how.** "Present by name" and
   "confirmed by a live call" are different assurances and the difference belongs in the report.

## What the pause report contains
- Each missing or invalid credential: variable name, purpose, and the step blocked on it.
- For each, whether it was **absent by name** or **present but rejected by a live call** — these route
  differently.
- The action required of the operator, and where.
- An explicit statement that no work was started and no partial state exists.

## Security rules
- Only names are ever checked, reported, or recorded. Values are never read, logged, echoed into a
  transcript, written to an artifact, or passed into a subagent's context.
- A credential's *value* never appears in memory notes, response envelopes, or task artifacts.
- Where a live call is used to validate a key, the call's *outcome* is recorded — never its authorization
  header, and never a response body that might echo the credential.

## Acceptance
- Every required credential is enumerated with its purpose and the step that needs it.
- Availability was established for the runtime that will use the credential, not merely for the operator's shell.
- Absent is distinguished from present-but-invalid, and load-bearing credentials were confirmed by a real call.
- No credential value was read, logged, or carried anywhere.
- On any gap, the task paused before starting work and no credential was provisioned without the operator.
