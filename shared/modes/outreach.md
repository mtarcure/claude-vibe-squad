---
name: outreach
version: 1.0
primary_lead: research
status: active
phases: 6
---

# Mode: Outreach

For finding potential businesses/clients, qualifying fit, drafting outreach, and preparing an approval-gated digest. This restores the legacy Chrono/Wirework-style freelance/outreach workflow without allowing automatic sends.

## Phase ownership at a glance

| Phase | Name | Lead / runtime | Specialists |
|---|---|---|---|
| 0 | Scope + Approval Frame | Chrono + operator | none |
| 1 | Lead Discovery | Research / Kimi | `research`, `data-extraction-engineer` |
| 2 | Qualification + DNC | Claude | `privacy-steward`, `personal-ops` if personal CRM/email state is involved |
| 3 | Offer + Drafts | Content / Gemini | `content-creator`, `brand-voice`, `editor` |
| 4 | Digest Package | Content + SysMgmt | `technical-writer`, `knowledge-librarian` |
| 5 | Operator Approval Gate | Chrono + operator | none |
| 6 | Manual Send / Hold | SysMgmt / Claude | `personal-ops` only after explicit approval |

## Triggers

```yaml
intent_phrases:
  - "find businesses"
  - "businesses in <area> that need AI"
  - "find leads"
  - "draft outreach"
  - "email these businesses"
negative_triggers:
  - "explain outreach"
  - "write a generic sales email"
```

Engagement requires explicit operator confirmation. Email/send actions require a second explicit approval after drafts are visible.

## Phases

### Phase 0: Scope + Approval Frame
Owner: Chrono + operator.
Output: `outreach-scope-card.md` with geography, target business type, offer, exclusion rules, max lead count, approval path, and send policy.
Advance when: operator confirms the target area/business type and whether this is research-only, draft-only, or approval-gated send prep.

### Phase 1: Lead Discovery
Owner: research namespace. Specialists: research, data-extraction-engineer.
Output: `lead-candidates.md` with sources, contact surfaces, why each lead might need help, and confidence.
Advance when: candidate list is sourced, deduped, and each lead has provenance.

### Phase 2: Qualification + DNC
Owner: Claude runtime through Security/SysMgmt compatibility paths. Specialists: privacy-steward, personal-ops when private email/contact state is needed.
Output: `qualified-leads.md`, `dnc-check.md`, and blocked/rejected lead reasons.
Advance when: DNC, privacy, source legitimacy, and operator-specific exclusions are checked.

### Phase 3: Offer + Drafts
Owner: content namespace. Specialists: content-creator, brand-voice, editor.
Output: `outreach-drafts.md` with one draft per approved lead, written as draft text only.
Advance when: drafts are specific, non-spammy, cite why the business is relevant, and avoid unsupported claims.

### Phase 4: Digest Package
Owner: Content + SysMgmt. Specialists: technical-writer, knowledge-librarian.
Output: `outreach-digest.md` with lead, source, reason, draft, suggested channel, and approve/edit/skip line.
Advance when: the operator can review without opening raw research files.

### Phase 5: Operator Approval Gate
Owner: Chrono + operator.
Hard gate: no send, post, DM, or external contact until the operator approves specific lead(s) and exact draft(s).
Advance when: each candidate is marked approve/edit/skip.

### Phase 6: Manual Send / Hold
Owner: sysmgmt namespace. Specialist: personal-ops.
Output: `send-log.md` or `held-log.md`.
Advance when: approved messages are sent manually or explicitly held. If no send channel is verified, this phase produces instructions only.

## Legacy Pipeline Reference

Private/local reference implementation: `<private-outreach-repo>`.

Vibe Squad may use it for dry-run proof and design reference, but the public repo must not copy private lead data, credentials, SQLite databases, raw emails, or operator-specific voice files.

Safe bridge command:

```bash
bash bin/outreach-dry-run.sh
```

This command must run fixture/dry-run mode only and must not send email.

## Completion

```yaml
completion: "digest reviewed + approved sends logged or held"
hard_gate: "operator approval required before every external send"
pre_completion: "vibecoding-check outreach extension"
```
