# Standing checks: proof bounds and proxy storage alignment

Task: `TASK-2026-08-04-0300-W1B-checks`

| Check | Runner | Positive control | Good control | Pinned-target result |
| --- | --- | --- | --- | --- |
| Proof-verifier bounds (Solidity + Rust/Anchor) | `proof-verifier-bounds/check.py` | Solidity and Rust vulnerable fixtures: `FAIL` / exit 1 | Solidity and Rust guarded fixtures: `PASS` / exit 0 | SVM and EVM application roots: `EMPTY` (coverage-bounded, not an audit verdict) |
| Proxy/implementation storage alignment | `storage-slot-alignment/check.py` | Slot-0/slot-1 vulnerable proxy: `FAIL` / exit 1 | EIP-1967-style proxy: `PASS` / exit 0 | Six EVM deployment/upgrade pairs: `PASS` for compiler-declared byte-range overlap |

Each runner prints a Markdown table followed by a single `VERDICT` line. Each check has its own README, deliberately vulnerable fixture, guarded fixture, repeated control output, target output, and known-limits section.

No bounty finding was declared, no target was modified, no external system was contacted, and no submission was attempted.

## Evidence map

- Proof controls: `proof-verifier-bounds/reports/final-controls.md`
- Proof target output: `proof-verifier-bounds/reports/pinned-targets.md`
- Storage controls: `storage-slot-alignment/reports/final-controls.md`
- Storage target output: `storage-slot-alignment/reports/evmgw-80f7a208.md`
- Raw Forge command/output hashes: `storage-slot-alignment/reports/raw-forge-evidence.sha256`
- Target-integrity check: `target-integrity.md`
- Method/contract verification: `verification-evidence.md`
- Primitive ledger: `primitive-ledger.md`
- Action log: `action-log.md`

`storage-slot-alignment/work/` is scratch/build evidence, not part of the canonical deliverable list. Its final raw Forge evidence is bound by `raw-forge-evidence.sha256`.
