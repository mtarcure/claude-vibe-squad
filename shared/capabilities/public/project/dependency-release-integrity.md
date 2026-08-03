---
id: project/dependency-release-integrity
mode: project
title: Dependency / release integrity (supply-chain · advisory · signing evidence)
overlays: [review, memory]
gates: [credential_change, public_release, delete]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

**When to use:** dependency trust, supply-chain review, advisory triage, and release-integrity evidence. The
live scope is AUDITING (SCA, secret scanning, advisory backport, provenance review); producing cryptographic
signatures / attestations / SBOMs is `needs_tool` (see Profiles). Credential changes, public release, and
deletes are operator-gated.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono`, `triage` | `chrono-vault` | — | memory overlay (recall) |
| **S1** Frame (trust scope + policy) | `product-manager`, `software-supply-chain-engineer` | — | `scope-decomposition` | — |
| **S2** Design (dep graph + advisory plan) | `software-supply-chain-engineer`, `security-analyst` | — | `dependency-cycle-audit` | — |
| **S3** Produce (SCA + secret + advisory audit) | `software-supply-chain-engineer`, `security-analyst` | `osv-scanner`, `gitleaks`, `trufflehog`, `trivy`, `semgrep`, `codex --search` | `known-advisory-backport-check`, `secret-rotation-discipline` | `credential_change` (secret rotation) |
| **S4** Verify (integrity + provenance) | `software-supply-chain-engineer`, `skeptic` | `plugin:github:github` | — | signing / attestation / SBOM = `needs_tool` (no verified signing tool) |
| **S5** Review/Gate (approval) | `code-reviewer`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); `credential_change`, `public_release`, `delete` |
| **S6** Ship/Deliver (release evidence) | `software-supply-chain-engineer`, `technical-writer` | `plugin:github:github` | — | `public_release` |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | — | memory overlay (record) |

**Notes.** Dependency-trust auditing (SCA, secret/vuln scanning, advisory backport, GitHub provenance review)
is live and covers the honest evidence-gathering scope.

**Needs-tool profile (NOT part of the live claim):** producing cryptographic signatures, in-toto/SLSA
attestations, or a generated SBOM is `needs_tool` — no signing/attestation tool (cosign / syft / SLSA / in-toto
/ sigstore) is registry-verified. Do not claim signed/attested release artifacts until such a tool is cataloged
and verified for the lane; the card audits and cites signing evidence, it does not produce signatures. Dependency
trust changes and secret rotation require operator approval (`credential_change`).
