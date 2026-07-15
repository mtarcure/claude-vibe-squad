---
name: bounty
version: 1.1
primary_mode_namespace: security
status: active
phases: 12
---

# Mode: Bounty

For bug bounty and vulnerability research. Chrono owns target selection, safety gates, dispatch, review, and operator-facing decisions.

## Flow

| Phase | Work | Likely specialists |
|---|---|---|
| 0 | Target discovery and operator selection | Chrono direct |
| 1 | Target OSINT | `scout`, `research`, `data-extraction-engineer` |
| 2 | Scope and rules | `scout`, `security-analyst` |
| 3 | Recon | `scout` |
| 4 | Threat model | `threat-modeler`, `security-analyst` |
| 5 | Focused analysis | `security-analyst` |
| 6 | PoC mechanics | `exploit-developer`, `backend-engineer`, `test-engineer` when code-heavy |
| 7 | Variant hunt | `exploit-developer`, `security-analyst` |
| 8 | Chain validation | `impact-validator`, `skeptic` |
| 9 | Report draft | `technical-writer`, `security-analyst` |
| 10 | Final review | `skeptic`, `vibecoding-check` |
| 11 | Capture verified findings, KILLs, and process learnings | Chrono direct, contributing specialists |

## Phase 11 — Capture Learnings

After final review, Chrono records through chrono-vault `record`: every verified finding whether submitted or not, each KILL and why that attack class did not pan out, and reusable process learnings. All bounty-derived notes use `sensitivity: restricted` and retain source-task and evidence provenance. Outbox auto-capture already ingests response verdicts as `candidate` notes; this phase deduplicates and curates the important notes, promoting reviewed candidates to `verified` rather than creating parallel memory.

## Dispatch Notes

- Bounty work does not imply one model lead. Chrono dispatches each specialist per `shared/specialist-runtime-map.tsv` on capability; see `shared/routing.md` for the model.
- PoC and harness mechanics route to codex (`gpt-5.6-sol`) with claude (`claude-fable-5`) review; judgment/security-reasoning (`security-analyst`, `threat-modeler`, `impact-validator`, `scout`) is claude-primary with codex backup.
- Target research and synthesis route to claude or codex on capability — **not kimi** (kimi is the throughput-only lane, 0 primaries).
- Report wording routes to the assigned writer's lane (`technical-writer` = claude/Fable).
- **Safety-refusal invariant:** a genuine safety refusal on any lane surfaces to the operator and is NEVER cross-family re-dispatched in either direction. The offensive-security specialists here (`security-analyst`, `exploit-developer`, `scout`, `impact-validator`, `smart-contract-engineer`, `threat-modeler`) run under heightened-risk defaults — a refused request is never shopped to a more permissive lane.

## Gates

- Operator approval before engaging a target, touching authenticated scope, contacting a program, or writing private bounty details to durable public-facing files.
- **Submission gate (operator-ratified 2026-07-14):** Chrono/specialists MAY drive the full submission workflow — navigate the authed platform session, fill the report form, attach the PoC, stage everything — up to but NOT including the final Submit click. The **final Submit click is a hard per-report gate requiring explicit operator "go"** (it is irreversible and costs a submission fee + reputation). Never click Submit without that per-report approval; staging the form without submitting needs no separate approval.
- **Pre-submit G1–G4 gate (`impact-validator` owns it):** no finding is submitted unless it clears G1 impact-realized · G2 third-party-reproduced · G3 dedup'd · G4 in-scope defended-boundary, plus its per-class add-on — any FAIL is no-submit. Full gate: `departments/security/specialists/impact-validator.md` → "Pre-Submit Gate (G1–G4)".
- Mandatory multi-model review for exploitability, impact, privacy, auth, and final report claims.
- No destructive testing, rate-limit abuse, persistence, credential use, or out-of-scope probing.
- Run `vibecoding-check` before final operator summary.

## Toolchain & audit skills (use by default — do not rediscover)

The local CLI toolchain is well-stocked; specialists have shell access and MUST use it, not just grep:
- **Go:** `gosec -severity=medium`, `staticcheck`, `golangci-lint`, `semgrep --config=p/gosec --config=p/golang`, `osv-scanner --lockfile go.mod`, `go test -race`, `go test -fuzz`.
- **EVM:** `slither`, `myth`, Foundry (`forge`/`cast`/`anvil` fork-and-replay + fuzz), `echidna`, `halmos`, `aderyn`.
- **Rust/Solana:** `cargo-audit`, `clippy`, `cargo-geiger`, `cargo-fuzz`, `anchor`, `solana`.
- **General:** `trivy`, `grype`, `gitleaks`/`trufflehog` (secret scan is operator-gated for a target org).

**Apply the domain audit-checklist skills on task start** (they encode the classes that convert):
- Blockchain L1 / bridge / appchain → profile `blockchain-l1`; skills `cross-chain-bridge-audit`, `cosmos-sdk-audit-checklist`, `known-advisory-backport-check`.
- Solidity/Rust contracts → profile `smart-contract`; skills `solana-anchor-audit-checklist` (Solana/Anchor), `known-advisory-backport-check` (forked deps).
- All bounties → `chain-impact-rescore` (offensive chaining + reachability/terminus discipline).

**Dynamic testing is mandatory for logic/nonce/reorg/concurrency bugs** — extract the logic into a hermetic harness (mock RPC + latest/safe/finalized heads), run `-race`, and include a negative control. Static isolation-review misses shared-predicate and concurrency bugs (it wrongly killed a real finalized-nonce bug for 5 waves until dynamic testing caught it).

**PoC reproduction gate (before ANY submission):** the PoC author is not the validator. A **different-model-family agent** must independently **reproduce the runnable PoC from scratch** (clone/run it fresh, confirm it passes AND that the harness faithfully maps to the real in-scope code file:line — not a mis-modeled test), and **multiple models must concur** (the cross-family reproducer + `skeptic` + `impact-validator`). Chrono coordinates this fan-out and reads the verdicts — Chrono does NOT run the PoC itself (that's specialist work and a single-model check). A PoC only counts as reproduced when ≥2 model families have independently run it and agreed it proves the claim.

**Swarm it:** run specialists in parallel across lanes — a claude panel (security-analyst + threat-modeler) concurrent with codex (smart-contract-engineer / exploit-developer). Namespace is only the mailbox; each specialist routes to its best-fit model.
