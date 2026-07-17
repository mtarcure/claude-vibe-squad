---
id: maintenance/dependency-release-integrity
mode: maintenance
title: Dependency / release integrity (supply-chain · advisory · signing evidence)
capability_state: live
state_reason: Dependency-trust AUDITING is live — `osv-scanner`/`gitleaks`/`trufflehog`/`trivy` (`local·yes·—`) for SCA / secret / vuln scanning, `plugin:github:github` (claude·lane-live) for release/PR provenance, `chrono-vault` (all·yes). **Cryptographic signing / attestation / SBOM generation is `needs_tool`** — no signing tool (cosign / syft / SLSA / in-toto) is registry-verified; the live scope is auditing + gathering evidence, NOT producing signatures.
state_evidence: registry rows — osv-scanner/gitleaks/trufflehog/trivy = `local·yes·—`; plugin:github:github = `claude·lane-live·subscription`; chrono-vault = `all·yes·subscription`. No cosign/syft/SBOM/SLSA/in-toto tool exists in the registry (→ signing/attestation is `needs_tool`, see Profiles).
overlays: [review, memory]
gates: [credential_change, public_release, delete]
cost_note: free-local SCA CLIs (cost `—`) + github plugin / chrono-vault (subscription). No metered provider; no signing tool is billed because none is cataloged.
---

**When to use:** dependency trust, supply-chain review, advisory triage, and release-integrity evidence. The
live scope is AUDITING (SCA, secret scanning, advisory backport, provenance review); producing cryptographic
signatures / attestations / SBOMs is `needs_tool` (see Profiles). Credential changes, public release, and
deletes are operator-gated.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` (all · yes · subscription) | — | memory overlay (recall) |
| **S1** Frame (trust scope + policy) | `product-manager`, `software-supply-chain-engineer` | — | `scope-decomposition` (stub) | — |
| **S2** Design (dep graph + advisory plan) | `software-supply-chain-engineer`, `security-analyst` | — | `dependency-cycle-audit` (stub) | — |
| **S3** Produce (SCA + secret + advisory audit) | `software-supply-chain-engineer`, `security-analyst` | `osv-scanner` (local · yes · —), `gitleaks` (local · yes · —), `trufflehog` (local · yes · —), `trivy` (local · yes · —) | `known-advisory-backport-check` (untyped), `secret-rotation-discipline` (stub) | `credential_change` (secret rotation) |
| **S4** Verify (integrity + provenance) | `software-supply-chain-engineer`, `skeptic` | `plugin:github:github` (claude · lane-live · subscription) | — | signing / attestation / SBOM = `needs_tool` (no verified signing tool) |
| **S5** Review/Gate (approval) | `code-reviewer`, `cross-family-reviewer`, `operator` | — | — | review overlay; `credential_change`, `public_release`, `delete` |
| **S6** Ship/Deliver (release evidence) | `software-supply-chain-engineer`, `technical-writer` | `plugin:github:github` (claude · lane-live · subscription) | — | `public_release` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | — | memory overlay (record) |

**Notes.** Dependency-trust auditing (SCA, secret/vuln scanning, advisory backport, GitHub provenance review)
is live and covers the honest evidence-gathering scope.

**Needs-tool profile (NOT part of the live claim):** producing cryptographic signatures, in-toto/SLSA
attestations, or a generated SBOM is `needs_tool` — no signing/attestation tool (cosign / syft / SLSA / in-toto
/ sigstore) is registry-verified. Do not claim signed/attested release artifacts until such a tool is cataloged
and verified for the lane; the card audits and cites signing evidence, it does not produce signatures. Dependency
trust changes and secret rotation require operator approval (`credential_change`).
