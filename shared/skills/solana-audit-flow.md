---
name: solana-audit-flow
status: authored
---

# solana-audit-flow

Stateful Solana program audit pipeline from Anchor/Rust source through confirmed-finding
delivery. Use for a Rust/Anchor workspace or a bare `solana_program` program. Every step runs
a **native host tool** (`anchor`, `cargo`, `trident`, `cargo-fuzz`, `solana`) or a target-
project dev-crate (`litesvm`, run via `cargo test`). There is **no static-analysis step**:
Slither has zero Solana detectors, so any "slither Solana scan" is a fabricated capability —
manual review (`vulnhunter-solana`) plus dynamic fuzzing is the coverage model on Solana.

## Order of ops

1. **Build and lint.** `anchor build` (or `cargo build-sbf` for a bare program) to confirm a
   clean compile. Surface ALL compiler warnings — Rust warnings on Solana programs often
   indicate logic bugs (unused return values, dead paths). Never dismiss `#[allow(unused)]`
   without checking what it suppresses. Confirm the toolchain version is already installed;
   do **not** run `avm use <version>` blindly — it can trigger an `agave-install` network
   download (no silent installs). If a version mismatch blocks the build, surface it as a
   `## NEEDS FROM CHRONO` item rather than auto-installing.

2. **Manual vuln-pattern review (primary coverage).** Apply `vulnhunter-solana`: account
   ownership checks (`account.owner != program_id`), discriminator validation on deserialized
   accounts, signer checks on privileged instructions, CPI signer validation (caller-controlled
   `signer_seeds`), SPL token math overflow, PDA seed collision, unchecked `data.borrow_mut()`.
   This is step 2 (not a late step) because there is no static tool to lean on first.

3. **Unit test run.** Run the existing suite with `cargo test` (LiteSVM-backed tests are
   preferred over `solana-program-test` for speed; both run under `cargo test`). A failing test
   in a security-sensitive instruction is often a direct finding.

4. **Coverage-guided fuzzing.**
   - **Trident** for Anchor-aware, IDL-driven fuzzing: `trident fuzz run <target>`. Trident
     generates fuzz instructions from the IDL and checks invariants; write custom
     `FuzzInstruction` impls for complex state-machine properties.
   - **cargo-fuzz** (libFuzzer) for bare parsing/deserialization surfaces and non-Anchor
     programs: `cargo fuzz run <target>`.

5. **Runtime/environment probing (optional).** Use the `solana` CLI (`solana --version`,
   `solana program dump`, localnet via `solana-test-validator`) to reproduce on a controlled
   local cluster when a finding needs on-chain state. Keep it local; no mainnet writes.

6. **Finding triage.** Feed combined manual + fuzzing output to the **multi-model-fanout**
   false-positive filter (Chrono dispatches a second model / skeptic stance), then to
   `impact-validator` for the G1–G4 impact gate. Focus triage on missing-check findings
   (confirm the instruction's security model — some privileged instructions are intentionally
   permissionless) and arithmetic findings (often protected by runtime `checked_*`).

## When to pivot

- **`anchor build` fails on version mismatch:** read the declared CLI version in `Anchor.toml`;
  surface the mismatch (do not auto-`avm use`, do not modify `Anchor.toml`) unless the operator
  instructs. Never trigger a network install.
- **LiteSVM absent/stale:** confirm via `cargo tree` that `litesvm` is a dev-dependency; if the
  project uses `solana-program-test` instead, run those tests via `cargo test`.
- **Trident coverage too low:** add explicit `FuzzInstruction` variants for underrepresented
  state-transition sequences; or drop to `cargo-fuzz` for the raw deserialization surface.
- **Program is very large (>5k LOC):** prioritize CPI-adjacent code and privileged instruction
  handlers — highest attack-surface density.

## Anti-patterns

- Do NOT cite any Solana static-analysis detector — `slither_solana_scan` / `slither --detect solana` does not exist; it is the fabricated capability this recreation removes.
- Do NOT skip manual review (`vulnhunter-solana`) — it is the primary coverage, not a supplement.
- Do NOT test Anchor programs with a plain unit runner that lacks CPI/PDA semantics — use LiteSVM or `solana-program-test`.
- Do NOT report a "missing signer check" without confirming the instruction's intended security model.
- Do NOT fuzz without a passing test suite — Trident relies on correct IDL deserialization; test failures indicate IDL drift.
- Do NOT invoke dead `tool_wrappers` names (`anchor_build`, `litesvm_test`, `trident_fuzz`, `slither_solana_scan`); use the native tools above.

## Example

```bash
# Step 1: build and surface warnings
anchor build

# Step 3: unit tests (LiteSVM-backed run through cargo)
cargo test

# Step 4: Anchor-aware fuzzing
trident fuzz run fuzz_0
# ...and the raw deserialization surface
cargo fuzz run parse_ix
```

## Recording (chrono-vault)

After the full audit, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="attempt", fields={"title": "solana-audit-flow on <program>", "body": "finding_count=<n>; missing_check=<n>; arithmetic=<n>; test_failures=<n>; tools=anchor,cargo-test/litesvm,trident,cargo-fuzz,solana", "target": "<program>", "attack_class": "solana-audit", "source_task": "<task-id>"})`.
Record each confirmed finding as `note_type="finding"` with its specific `attack_class` AFTER
the FP-filter and impact gate. A memory error is logged in one line and never blocks the audit.
