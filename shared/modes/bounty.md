---
name: bounty
version: 1.0
primary_lead: security
status: active
phases: 12
---

# Mode: Bounty

## Phases at a glance

| Phase | Name | Lead | Specialists |
|---|---|---|---|
| 0 | Discovery + Target Selection | Chrono direct + operator | none |
| 1 | Target OSINT | Research | Kimi `Agent(subagent_type=research)`, `Agent(subagent_type=large-context-analyst)`, `Agent(subagent_type=synthesizer)` |
| 2 | Program Scope | Security / Claude | `scout`, `security-analyst` |
| 2.5 | Scope-clarity check | Security / Claude | `scout`, `security-analyst` |
| 3 | Recon | Security / Claude | `scout` |
| 4 | Threat Modeling | Security / Claude | `threat-modeler`, `security-analyst` |
| 5 | Focused Analysis | Security / Claude | `security-analyst` |
| 6 | Individual Exploit Dev | Security / Claude | `exploit-developer` plus GPT/Codex read-only review when code-heavy |
| 7 | Variant Hunt | Security / Claude | `exploit-developer`, `security-analyst` |
| 8 | Chain Construction | Security / Claude | `exploit-developer`, `skeptic` |
| 9 | Synthesis + Skeptic Review | Security + Research | Research `synthesizer`, Security `skeptic`, `security-analyst` |
| 10 | Validation | Security / Claude | `impact-validator` |
| 11 | Report / Disclosure | Security + Content | Content `technical-writer`, Security `skeptic` |

For bug bounty work — discovering a target, hunting, exploiting, validating, and submitting findings. Phase 0 is Chrono direct with the operator because candidate discovery spans the operator's authenticated bounty-platform tabs and preference filtering. Phase 1 belongs to Research for target OSINT. Phase 2 and Phase 2.5 belong to Security for program scope and scope clarity. Phases 3-11 belong to Security as the primary Lead for bounty execution. coding namespace is invoked for PoC harnesses; research namespace may be invoked again for supplemental OSINT.

**Why Phase 1 and Phase 2 split across Leads.** Industry firms (Trail of Bits, OpenZeppelin, Sherlock, Code4rena, Least Authority) typically combine "understanding the target" and "understanding the engagement scope" into one phase owned by one team. The squad splits these because they require different capabilities (external OSINT vs authenticated platform access), different toolchains (`chrono-research-arsenal` vs raw-CDP browser attach at port 9222), and different expertise (ecosystem research vs program-rules extraction). The squad's distributed, mailbox-driven, multi-CLI architecture justifies the finer split. A single co-located audit team would not need it.

## Triggers

```yaml
url_patterns:
  - "*hackerone.com/*"
  - "*bugcrowd.com/*"
  - "*intigriti.com/*"
  - "*hackenproof.com/*"
  - "*code4rena.com/*"
  - "*immunefi.com/*"

intent_phrases: ["let's hunt", "audit this", "find vulns", "this bounty", "find me a bounty", "look through bounties"]
file_types: [".sol", ".vy", ".rs"]  # weak signal — confirm
negative_triggers: ["explain bounties", "how do bounties work", "what are bounties"]
```

Engagement requires explicit operator yes (or `/bounty` slash command). "Find me a bounty" starts Phase 0 only after that consent; it does not dispatch to Security or Research yet.

## Lead ownership

- primary_lead: security (Phase 2.5 and Phases 2-11)
- discovery_owner: chrono + operator (Phase 0)
- target_osint_owner: research (Phase 1)
- backup_lead: none
- allowed_cross_leads: [coding, research, content]

## Phases (12 total — restructured Phase 5 bounty workflow with Phase 0 discovery, Phase 1 Target OSINT, Phase 2 Program Scope, Phase 2.5 scope-clarity sub-step, and Phases 3-11 Security execution)

Phase 1 (Target OSINT) and Phase 2 (Program Scope) execute in parallel after Phase 0 completes. They use separate toolchains: Research uses public research surfaces, while Security uses raw CDP against the operator's authenticated Chrome at port 9222. Both must complete before Phase 3 (Recon) begins. If either phase surfaces information that invalidates the other, the owning Lead issues a NUDGE to the other Lead for realignment.

### Phase 0: Discovery + Target Selection

Owner: Chrono direct + operator
Specialists: none — this is not a Lead or specialist dispatch
Browser: operator's persistent Chrome at `127.0.0.1:9222` via raw CDP per `reference_authed_chrome_cdp.md`
Input: operator intent, bounty-platform sessions, known operator preferences
Pre-discovery state check: read Security outbox/archive, browser keep-alive log, and chrono-vault recall before presenting candidates
Activity: scan the 5 configured bounty platforms, compare candidates at triage depth, and surface payout / reputation / scope shape / KYC-payment constraints / platform fit / deadline metadata. Operator picks the target.
Constraint: Phase 0 and Phase 2 must not run concurrently in the same run because both attach to the same port-9222 Chrome session and could race on tab enumeration or selection.

Candidate filter, in order:
1. Platform-identity guard — only `*.hackerone.com`, `*.bugcrowd.com`, `*.intigriti.com`, `*.hackenproof.com`, `*.code4rena.com`. Cross-platform referrals drop here.
2. Privacy-classifier guard — read platform UI markers (private/public/NDA). If private/NDA, require `operator-explicit-token-required` or mark private and skip detail vault-write.
3. Activity-check guard — drop unless >=1 submission accepted/paid in last 90d OR scope edit in last 30d.
4. Self-hosted-detection guard — if scope description points to external email/Discord rather than platform's own scope/asset structure, mark `bounty_management: external` and surface only with operator tag.

Trust-boundary defenses:
- Hard gate: `phase_discovery_to_target_osint_gate` requires skeptic verification on `target-selection.md`; skeptic verifies Chrono synthesis against `raw_scope_claims` and checks for prompt-injection drift.
- Tab allowlist: Chrono enumerates only the 5 platform program-listing pages and refuses `select_page` on any tab outside that allowlist. Violations are surfaced as NOTIFY to Chrono.
- Raw quotes: `target-selection.md` keeps verbatim `raw_scope_claims` separate from Chrono synthesis so later phases can audit source drift.
- Capability discipline: Chrome MCPs remain deferred. Phase 0 lazy-loads only the needed raw-CDP helper capability through Tool Search, then drops it after Phase 0 exits.
- Skill wrapper: Phase 0 should be wrapped as `chrono-vault:bounty-discovery` so the invocation is discrete and audit-tagged.

Required `target-selection.md` schema:

```yaml
target_name: <e.g., "K2-protocol">
target_type: protocol | contest | infrastructure | tooling | other
target_description: <1-3 lines>
program_platform_url: <full URL>
primary_platform: hackerone | bugcrowd | intigriti | hackenproof | code4rena
secondary_references: [<URLs of github, docs, ...>]
payout_tier_observed: <e.g., "Critical $50k, High $10k">
KYC_status: required | optional | not_required
finding_visibility: public | private | NDA
program_privacy: public | private | NDA
scope_sketch: <1-3 lines>
known_disqualifiers: <operator preference notes>
vault_recall_summary: <result of chrono-vault recall per lifecycle.md rule 10>
raw_scope_claims: |
  <verbatim quote from program page, separate from Chrono synthesis>
```

Output: `target-selection.md`
Operator gate: SOFT selection gate — operator chooses the target before Research or Security begins
Advance when: `target-selection.md` is written, all 4 candidate-filter guards have run, operator selection is recorded, and skeptic verification returns PASS.

### Phase 1: Target OSINT

Owner: research namespace
Specialists: research namespace invokes Kimi `Agent(subagent_type=research)`, `Agent(subagent_type=large-context-analyst)`, and `Agent(subagent_type=synthesizer)`
Browser: no bounty-platform auth; use public research surfaces only
Input: `target-selection.md` plus public target identifiers
Activity: research the thing being audited: codebase, product architecture, tech stack, prior public disclosures, ecosystem context, docs, repos, papers, and public payout or bug history. This phase builds target familiarity, not program-rule authority.
Output: `target-intel.md`
Multi-model: optional, for contested or high-stakes target interpretation
Advance when: `target-intel.md` covers attack-surface history and ecosystem context, then is delivered to Security inbox for Phase 3 consumption.

### Phase 2: Program Scope

Owner: security namespace
Specialists: security namespace dispatches `scout` for authenticated program reading and `security-analyst` for safe-harbor/legal-risk interpretation; Research cross-Lead uses `research` as needed.
Browser: operator's persistent Chrome at `127.0.0.1:9222` via raw CDP
Input: `target-selection.md`, bounty platform URL or program description; `target-intel.md` may arrive in parallel but is not required to start Phase 2
Activity: read the bounty program rules from the authenticated platform tab: in-scope assets, out-of-scope assets, accepted vuln classes, payout tiers, safe-harbor / rate-limit / testing constraints, disclosure rules, and submission format. Phase 2 is about what the program permits and pays for; it gates active recon.
Output: `program-intel.md`, `scope.md`, `assets.md`, `rules.md`, `testing-rules.md`, `out-of-scope.md`, `submission-format.md`, `program-behavior.md`
Multi-model: yes (Claude + Gemini for thorough reading)
Operator gate: HARD if scope, authorized methods, or program rules are ambiguous
Advance when: all 8 outputs are written and Phase 2.5 has enough source material to produce `scope-clarity.md`.

`program-behavior.md` captures triage SLA, AI-tooling disqualification rules, retest policy, KYC depth, dispute-resolution norms, and response-tone heuristics. `testing-rules.md` captures authorized testing methods, rate limits, VPN/IP restrictions, static-IP allowlists, account provisioning, OOS test types, and disclosed-class exclusions. `out-of-scope.md` must be a structured list with entries shaped as `{type: asset|vuln-class|method|population|other, pattern: <regex/url/asset-name>, source_quote: <verbatim>}`.

### Phase 2.5: Scope-clarity check

Owner: security namespace
Specialists: security namespace dispatches `scout` and `security-analyst`.
Input: all Phase 2 outputs plus `target-selection.md`
Activity: verify that scope, authorized methods, program rules, testing limits, and out-of-scope patterns are concrete enough for active recon.
Output: `scope-clarity.md` with verdict PASS / AMBIGUOUS / FAIL
Operator gate: HARD if verdict is AMBIGUOUS or FAIL
Advance when: `scope-clarity.md` verdict = PASS. Phase 3 cannot start without PASS.

### Phase 3: Recon

Owner: security namespace
Specialists: security namespace dispatches `scout`.
Input: `target-selection.md`, `target-intel.md`, all Phase 2 outputs, `scope-clarity.md` PASS
Multi-model: yes (Claude + Codex independent recon — different perspectives on attack surface)
Output: `recon.md`, `attack-surface.md`
Advance when: `recon.md` and `attack-surface.md` map authorized assets and exclude OOS targets.

### Phase 4: Threat Modeling

Owner: security namespace
Specialists: security namespace dispatches `threat-modeler` and `security-analyst`.
Multi-model: yes (Claude + Gemini for breadth, Codex if code/API artifacts)
Output: `hypotheses.md` ranked by exploitability/impact/scope-fit
Advance when: hypotheses are ranked, tied to in-scope assets, and ready for focused analysis.

### Phase 5: Focused Analysis / Reproduction

Owner: security namespace
Specialists: security namespace dispatches `security-analyst`.
Cross-Lead: coding namespace may be invoked for harnesses, fuzz scaffolds, test fixtures via Codex prompt-driven agents such as `backend_engineer`, `systems_engineer`, or `test_engineer`
Output: `finding-candidates.md`, `repro-notes.md`
Advance when: each candidate has precondition + affected asset + likely impact + repro path.

### Phase 6: Individual Exploit Development

Owner: security namespace
Specialists: security namespace dispatches `exploit-developer`; code-heavy independent attempts can request GPT/Codex specialists with explicit read/write ownership.
Output: `pocs/<finding-id>/` with PoC code + evidence
Multi-model: yes (independent attempts to reduce anchoring)
Advance when: each retained candidate has a sandbox-safe PoC or a documented reason it cannot be reproduced.

### Phase 7: Variant Hunt

Owner: security namespace
Specialists: security namespace dispatches `exploit-developer`; `security-analyst` checks adjacent variants when needed.
Activity: for each individual finding, scan adjacent surfaces for same vuln class
Output: `variants.md`, additional `pocs/<variant-finding-id>/`
Advance when: adjacent in-scope surfaces have been checked and variants are linked or ruled out.

### Phase 8: Chain Construction

Owner: security namespace
Specialists: security namespace dispatches `exploit-developer` for chain construction and `skeptic` for chain-atomicity verification.
Activity: map findings as dependency graph, build end-to-end chain PoCs, rescore impact
Output: `chain-graph.md`, `chains/<chain-id>/`, `chain-impact.md`
Advance when: chains are either proven atomic with impact evidence or explicitly ruled out.

### Phase 9: Synthesis + Skeptic Review

Owner: security namespace
Specialists: research namespace dispatches `synthesizer` for cross-source synthesis; security namespace dispatches `skeptic` and `security-analyst` for scope and finding confidence.
Activity: dedupe findings, mark each as confirmed/weak/duplicate/out-of-scope, dupe disclosure check
Output: `findings.md` (final set with confidence stamps)
Multi-model: yes
Operator gate: HARD (operator reviews complete finding set before validation)
Advance when: final finding set is deduped, scope-checked, confidence-stamped, and ready for operator review.

### Phase 10: Validation

Owner: security namespace
Specialists: security namespace dispatches `impact-validator`, which owns CVSS scoring, program-fit checks, duplicate checks, and self-inflicted assessment.
Activity: CVSS v4 scoring, program-fit (is this an accepted vuln class?), self-inflicted detection
Output: `validation.md`, `cvss.md`, `routing-decisions.md` (submit / drop-OOS / drop-self-inflicted / escalate)
Multi-model: yes on severity disputes only
Advance when: every finding has validation status, CVSS where applicable, and a routing decision.

### Phase 11: Report / Disclosure Package

Owner: security namespace
Specialists: content namespace dispatches `technical-writer`; security namespace dispatches `skeptic` for adversarial review of submission narrative.
Activity: draft submission per platform format, fill form on persistent browser session, capture confirmation ID
Output: `submission.md`, `executive-summary.md`, `repro-steps.md`, `attachments/`, `confirmation-<id>.md`
Multi-model: yes (skeptic adversarial on the submission itself)
Operator gate: HARD before each submission sent (operator reviews populated form, approves send)
Advance when: each approved submission is sent or explicitly held, and confirmation artifacts are captured.

## Phase 1 vs Phase 2 Boundary

Phase 1 is about the target: the product, protocol, codebase, ecosystem, prior public disclosures, and technical context of the thing being audited. Its normal sources are public search, repositories, docs, papers, package indexes, and public vulnerability history. Phase 1 must not leak private/NDA bounty-platform text into external research tools; `program_privacy` in `target-selection.md` gates Research MCP usage.

Phase 2 is about the bounty program: what assets are in scope, which techniques are authorized, what is out of scope, what severity and payout rules apply, and how the platform expects submissions. Its source of authority is the authenticated bounty-platform tab attached through the operator's persistent Chrome session via raw CDP. Phase 2 and Phase 2.5, not Phase 1, are the scope gates before active recon.

If a concept appears in both phases, classify by source and purpose. Public prior bug history and ecosystem context belong in Phase 1; platform-specific payout tiers, private scope notes, and program-visible submission rules belong in Phase 2.

**Anti-drift rule.** research namespace MUST NOT interact with authenticated bounty-platform pages during Phase 1. security namespace MUST NOT run web-research queries on the target's ecosystem, prior audits, or tech stack during Phase 2. Either activity is a boundary violation and must be escalated to Chrono as a routing error.

## Cross-Lead routing

```yaml
target_osint_dispatch:
  from: chrono
  to: research
  phase: 1
  topic: target technical context / public prior disclosures / ecosystem background
  input: target-selection.md
  mailbox: departments/research/inbox/
  return_artifact: target-intel.md

target_research_phase:
  from: research
  to: security
  phase: 1_to_3_sync
  topic: target-intel.md (for Phase 3 consumption)
  mailbox: shared/mailbox/research-to-security/
  return_artifact: none

exploitation_phase:
  from: security
  to: coding
  phase: 5-8
  topic: PoC harness / fuzz scaffold / exploit script
  mailbox: shared/mailbox/security-to-coding/
  return_artifact: shared/mailbox/coding-to-security/RESP-<id>.md

supplemental_osint_phase:
  from: security
  to: research
  phase: 3-10
  topic: supplemental OSINT after scope classification / disclosure history / market context
  mailbox: shared/mailbox/security-to-research/
  return_artifact: shared/mailbox/research-to-security/RESP-<id>.md
```

## Hard gates

```yaml
- phase_discovery_to_target_osint_gate: HARD skeptic verification on target-selection.md
- phase_program_intel_to_recon_gate: HARD if scope ambiguous
- phase_findings_to_validation_gate: HARD operator review of finding set
- phase_submission_send_gate: HARD per submission
```

4 gates total across 12 phases plus the Phase 2.5 sub-step. Average 75-100 specialist dispatches between post-scope gates.

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

## Cleanup declarations

Durable / ephemeral declarations are inherited from `shared/mode-cleanup.md` Bounty Mode defaults.

```yaml
durable_artifacts:
  - F-NN findings
  - program intel
  - reusable technique notes
  - submission narratives
  - payout records

ephemeral_artifacts:
  - cloned target repos in scratch/
  - spawned Playwright/chrome-devtools profiles
  - sandbox containers tagged with run_id
  - PoC scratch artifacts under /tmp/poc-*
  - test exploit outputs

operator_decision_artifacts:
  - disclosed PoCs
  - public writeups
```
~/.claude-vibe-squad/browser-sessions/bounty-platforms/
  Used in: Phase 0 (Discovery + target selection across logged-in platforms via raw CDP)
           Phase 2 (Program Scope reads authenticated program pages via raw CDP)
           Phase 11 (Submission fills + sends forms via raw CDP)

  Fresh session (NOT persistent) used in:
           Phase 5-8 (testing exploits — isolated to prevent auth bleed)
```

## KG writes (required on completion)

```yaml
- vault/security/findings/<F-NN>-<title>.md (one per submitted finding)
- vault/security/programs/<program-name>.md (bounty program intelligence)
- vault/security/techniques/<technique>.md (reusable techniques surfaced)
- vault/instincts/security-insights.jsonl (per-Lead learnings)
```

Pre-completion: vibecoding-check (universal + bounty extension) must pass or be explicitly overridden before Bounty Mode can declare done.

## F-NN naming convention

Findings get IDs: F-01, F-02, F-03 ... per chrono memory convention. Phase 9 Synthesis assigns IDs. Phase 11 Report uses IDs. KG entries reference F-NN for cross-linking.

## Profiles

See `shared/mode-profiles/bounty/`:
- `web-app.md` — traditional web (XSS, SQLi, IDOR, SSRF, auth bypass)
- `smart-contract.md` — Solidity / Vyper / Rust contracts
- `web3.md` — DeFi protocols (contracts + frontend)
- `llm-app.md` — prompt injection, agent jailbreaks, tool abuse
- `mobile-app.md` — iOS / Android
- `api-service.md` — REST / GraphQL APIs
- `crypto-protocol.md` — cryptographic implementations
