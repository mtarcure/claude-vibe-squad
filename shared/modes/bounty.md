---
name: bounty
version: 1.0
primary_lead: security
status: active
phases: 10
---

# Mode: Bounty

For bug bounty work — hunting, exploiting, validating, submitting findings. Primary Lead is Security (Claude). Coding Lead frequently invoked for PoC harnesses; Research Lead for OSINT.

## Triggers

```yaml
url_patterns:
  - "*hackerone.com/*"
  - "*bugcrowd.com/*"
  - "*intigriti.com/*"
  - "*hackenproof.com/*"
  - "*code4rena.com/*"
  - "*immunefi.com/*"

intent_phrases: ["let's hunt", "audit this", "find vulns", "this bounty"]
file_types: [".sol", ".vy", ".rs"]  # weak signal — confirm
negative_triggers: ["explain bounties", "how do bounties work", "what are bounties"]
```

Engagement requires explicit operator yes (or `/bounty` slash command).

## Lead ownership

- primary_lead: security
- backup_lead: none
- allowed_cross_leads: [coding, research, content]

## Phases (10 total — Option B from operator: strict sequence with explicit chain construction)

### Phase 1: Bounty Intelligence

Owner: Security Lead
Specialists: scout, research (cross-Lead), scope-checker, legal-guard
Browser: persistent CDP-attached session (5 platforms logged in)
Input: bounty platform URL or program description
Output: `program-intel.md`, `scope.md`, `assets.md`, `rules.md`, `out-of-scope.md`, `submission-format.md`
Multi-model: yes (Claude + Gemini for thorough reading)
Operator gate: HARD if scope ambiguous

### Phase 2: Recon

Owner: Security Lead
Specialists: scout
Multi-model: yes (Claude + Codex independent recon — different perspectives on attack surface)
Output: `recon.md`, `attack-surface.md`

### Phase 3: Threat Modeling

Owner: Security Lead
Specialists: threat-modeler, security-analyst
Multi-model: yes (Claude + Gemini for breadth, Codex if code/API artifacts)
Output: `hypotheses.md` ranked by exploitability/impact/scope-fit

### Phase 4: Focused Analysis / Reproduction

Owner: Security Lead
Specialists: security-analyst, code-auditor (specialty of security-analyst)
Cross-Lead: Coding Lead may be invoked for harnesses, fuzz scaffolds, test fixtures
Output: `finding-candidates.md`, `repro-notes.md`
Advance when: each candidate has precondition + affected asset + likely impact + repro path

### Phase 5: Individual Exploit Development

Owner: Security Lead
Specialists: exploit-developer (multi-model — Codex AND Claude independent)
Output: `pocs/<finding-id>/` with PoC code + evidence
Multi-model: yes (independent attempts to reduce anchoring)

### Phase 6: Variant Hunt

Owner: Security Lead
Specialists: exploit-developer, variant-analyst (skill of skeptic)
Activity: for each individual finding, scan adjacent surfaces for same vuln class
Output: `variants.md`, additional `pocs/<variant-finding-id>/`

### Phase 7: Chain Construction

Owner: Security Lead
Specialists: chain-constructor (skill of exploit-developer), skeptic (chain-atomicity-verify)
Activity: map findings as dependency graph, build end-to-end chain PoCs, rescore impact
Output: `chain-graph.md`, `chains/<chain-id>/`, `chain-impact.md`

### Phase 8: Synthesis + Skeptic Review

Owner: Security Lead
Specialists: synthesizer, skeptic (cross-cutting), scope-checker
Activity: dedupe findings, mark each as confirmed/weak/duplicate/out-of-scope, dupe disclosure check
Output: `findings.md` (final set with confidence stamps)
Multi-model: yes
Operator gate: HARD (operator reviews complete finding set before validation)

### Phase 9: Validation

Owner: Security Lead
Specialists: impact-validator (multi-model), cvss-scorer, program-fit-check, self-inflicted-detector
Activity: CVSS v4 scoring, program-fit (is this an accepted vuln class?), self-inflicted detection
Output: `validation.md`, `cvss.md`, `routing-decisions.md` (submit / drop-OOS / drop-self-inflicted / escalate)
Multi-model: yes on severity disputes only

### Phase 10: Report / Disclosure Package

Owner: Security Lead
Specialists: technical-writer, skeptic (adversarial review of submission narrative)
Activity: draft submission per platform format, fill form on persistent browser session, capture confirmation ID
Output: `submission.md`, `executive-summary.md`, `repro-steps.md`, `attachments/`, `confirmation-<id>.md`
Multi-model: yes (skeptic adversarial on the submission itself)
Operator gate: HARD before each submission sent (operator reviews populated form, approves send)

## Cross-Lead routing

```yaml
exploitation_phase:
  to: coding
  topic: PoC harness / fuzz scaffold / exploit script
  mailbox: shared/mailbox/security-to-coding/
  return_artifact: shared/mailbox/coding-to-security/RESP-<id>.md

osint_phase:
  to: research
  topic: target background / market context / disclosure history
  mailbox: shared/mailbox/security-to-research/
  return_artifact: shared/mailbox/research-to-security/RESP-<id>.md
```

## Hard gates

```yaml
- phase_1_to_2: HARD if scope ambiguous (auto-skipped if scope clear)
- phase_8_to_9: HARD (operator reviews findings before validation)
- phase_10_each_submission: HARD (operator approves each populated submission form)
```

3 gates total across 10 phases. Average 75-100 specialist dispatches between gates.

## Termination

```yaml
completion: "all findings reach terminal state (submitted / dropped / escalated)"
explicit_stop: "operator says stop / /exit"

NOT termination conditions:
  - wall-clock time
  - operator absence  
  - dispatch count

after_completion: state = COMPLETED, run stays in runs/ — does NOT auto-archive
post_completion: 
  - re-test capability (after fix deployed, run PoC again)
  - response monitoring (watch platform inbox for triage replies)
```

## Persistent browser session usage

```
~/.claude-vibe-squad/browser-sessions/bounty-platforms/
  Used in: Phase 1 (Intelligence reads program pages)
           Phase 10 (Submission fills + sends forms)
  
  Fresh session (NOT persistent) used in:
           Phase 4-7 (testing exploits — isolated to prevent auth bleed)
```

## KG writes (required on completion)

```yaml
- vault/security/findings/<F-NN>-<title>.md (one per submitted finding)
- vault/security/programs/<program-name>.md (bounty program intelligence)
- vault/security/techniques/<technique>.md (reusable techniques surfaced)
- vault/instincts/security-insights.jsonl (per-Lead learnings)
```

## F-NN naming convention

Findings get IDs: F-01, F-02, F-03 ... per chrono memory convention. Phase 8 Synthesis assigns IDs. Phase 10 Report uses IDs. KG entries reference F-NN for cross-linking.

## Profiles

See `shared/mode-profiles/bounty/`:
- `web-app.md` — traditional web (XSS, SQLi, IDOR, SSRF, auth bypass)
- `smart-contract.md` — Solidity / Vyper / Rust contracts
- `web3.md` — DeFi protocols (contracts + frontend)
- `llm-app.md` — prompt injection, agent jailbreaks, tool abuse
- `mobile-app.md` — iOS / Android
- `api-service.md` — REST / GraphQL APIs
- `crypto-protocol.md` — cryptographic implementations
