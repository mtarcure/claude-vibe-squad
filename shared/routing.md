# Claude-Vibe-Squad Routing — Mode Triggers and Cross-Lead Rules

How Chrono decides which mode to engage and which Lead to route to.

## Mode invocation paths (3 ways, all operator-driven)

### 1. Concrete artifact pasted (suggest, await consent)

| Artifact | Suggested mode |
|----------|---------------|
| URL on hackerone.com / bugcrowd.com / intigriti.com / hackenproof.com / code4rena.com | Bounty |
| Sentry alert URL | Triage (Incident if active error) |
| GitHub Issue URL | Triage |
| Stack trace + words "broken" / "down" / "failing" | Incident |
| `.sol` / `.vy` / `.rs` (in audit context) | Bounty (smart-contract profile) |
| `.swift` / Xcode project | Project (ios-app profile) |
| `.tsx` / `package.json` (web context) | Project (web-app profile) |

Chrono never auto-engages — always asks "engage X mode?" first. Operator says yes or redirects.

### 2. Operator says it (engage on explicit signal)

- "let's go" / "let's do it" / "okay start" → Chrono picks the most relevant mode based on conversation context, asks "Mode X?"
- "let's hunt this target" → Bounty Mode
- "let's build X" → Project Mode
- "let's clean up" → Maintenance Mode
- "back to that bounty" → resume paused Bounty Mode
- "we're done" / "let's wrap" → exit current mode (mode goes DORMANT, not deleted)

### 3. Slash command (escape hatch, for power users)

- `/bounty` `/project` `/content` `/maintenance` `/incident` `/research` `/triage`
- `/exit` — leave current mode (DORMANT)
- `/archive` — explicit cleanup of completed run
- `/status` — current mode + active phase + next checkpoint

### What Chrono NEVER does

- ❌ Auto-engage on conversational phrases ("research", "build", "fix", "clean up")
- ❌ Switch modes silently mid-conversation
- ❌ Decide for the operator

## Lead routing (which Lead owns what)

Once a mode is engaged, Chrono routes work to the Lead that owns the domain:

| Mode | Primary Lead | Cross-Lead handoffs |
|------|--------------|---------------------|
| Bounty | Security | Coding for PoC harnesses, Research for OSINT |
| Project | Coding | Security for auth/crypto, Research for unfamiliar libs, Content for docs/UX copy |
| Content | Content | Research for fact-finding, Coding if technical content |
| Maintenance | SysMgmt (or Coding) | depends on what's being maintained |
| Incident | SysMgmt | Security if auth/secrets touched, Coding for the patch |
| Research | Research | All others can be requested for domain expertise |
| Triage | Coordinator-only (no Lead) | Routes outward to whichever mode triage suggests |

## Cross-Lead handoff rules

1. **Async by default.** Sender writes to recipient's inbox, continues with non-dependent work.
2. **One handoff = one message file.** No multi-step nested handoffs in a single file.
3. **Reply lands in sender's outbox-equivalent.** Each Lead's `inbox/` receives both fresh tasks and replies.
4. **Operator copy on cross-cutting decisions.** Important cross-Lead decisions get appended to `shared/decisions.md`.
5. **Handoff must specify return_artifact path.** Otherwise sender can't find the reply.

## Pathology safety net

Beyond hard gates, modes pause if pathology detected:

| Pattern | Detection | Action |
|---------|-----------|--------|
| Same specialist dispatched 3x with same prompt | repeat-detector | Pause, surface to operator |
| Specialist returned errors 3x in a row | error-streak | Pause, surface error |
| MCP tool retry-loop | retry-spike | Kill the loop, pause, surface |
| No new artifacts for N specialist turns | no-output | Pause, surface |
| Same Lead → Lead handoff bouncing 3+ times | bounce-loop | Pause, surface (escalation rule unclear) |

## Nightly autonomous routines

Triggered by launchd (`launchd/com.claudevibesquad.nightly.plist`):

- Daily 03:00: doctor + cleanup + dream + content sweep + daily morning brief
- Sunday 04:00: weekly deep run (deep KG cleanup, deep dream, subscription audit, weekly brief)

These run regardless of whether any tmux panes are active. State is in `_state/`.
