---
name: evm-audit-flow
status: authored
---

# evm-audit-flow

Stateful EVM audit pipeline from raw contract source through confirmed-finding delivery. Use
when you have a Foundry or Hardhat project with Solidity/Vyper contracts. Every step runs a
**native host CLI** or a **guarded MCP** (`guarded-slither`, `guarded-semgrep` — Trail-of-Bits
mcp-context-protector, schema-pinned and fail-closed); there is no `tool_wrappers` layer and no
retired KG. Start from `pre-audit-threat-model` if an x-ray does not already exist.

## Order of ops

1. **Static analysis pass.** Run `slither .` (or the `guarded-slither` MCP for structured,
   fail-closed queries — `list_detectors`, `run_detectors`, `get_function_source`). Classify
   detectors: HIGH-signal (`reentrancy-eth`, `arbitrary-send`, `controlled-delegatecall`,
   `suicidal`, `unprotected-upgrade`) vs NOISE (naming-convention, too-many-digits,
   solc-version). Do NOT dismiss `reentrancy-eth` as a false positive without tracing the call
   stack. `solc-select` is available for pinning the compiler, but do **not** pass
   `--always-install` (no silent network downloads); confirm the version is already present.

2. **Pattern/taint pass (the static analog of symbolic execution).** Run project-specific
   Semgrep rules via the `guarded-semgrep` MCP (`semgrep_scan_with_custom_rule`) — taint
   sources = external/`msg.sender`-reachable inputs, sinks = value transfers,
   `delegatecall`, storage writes. Author rules with `semgrep-rule-author`; a reachable sink
   with no realized impact is a lead, not a finding.

   **Pass `code_files[].path` as a RELATIVE path.** An absolute path is rejected with
   `Untrusted path must be relative`. The sibling tool `semgrep_scan` takes the opposite
   convention (absolute only) and then fails anyway -- it fetches its ruleset from the
   registry and 401s -- so treat `semgrep_scan_with_custom_rule` as the only working MCP
   entry point, with the `semgrep` CLI as the fallback. Both failure modes return an empty
   result that reads as a clean scan, so **confirm your rule fires on a known positive
   before believing a zero.** (Measured 2026-08-02.)

3. **Symbolic execution.** Run `myth analyze <contract> --execution-timeout 600` on every
   contract flagged HIGH by step 1, plus any contract with external calls, `delegatecall`, or
   `selfdestruct`. Surface: integer overflow, unchecked return values, `tx.origin`
   access-control bypass, ether-locking. For proxies, resolve the implementation address
   first — `myth` cannot follow `delegatecall` to a separate contract by default.

4. **Invariant authoring + fuzzing.** Author/refresh Echidna or Medusa invariants (token
   conservation, access-control, CEI reentrancy) in `test/invariants/`. Run
   `echidna . --contract <Test> --config echidna.yaml` for an initial pass; if coverage
   plateaus switch to `medusa fuzz --config medusa.json` (coverage-guided). For DeFi, apply
   `defi-invariant-check`. Minimum meaningful campaign: 30 minutes.

5. **Formal verification (critical paths only).** Run `halmos --function <prop> --loop <N>` on
   high-value properties Echidna found hard to falsify in bounded time. Halmos gives unbounded
   symbolic verification for simpler properties; do not throw the whole suite at it (it times
   out on complex state machines or unbounded loops).

6. **Lint + compile regression.** `forge build` (or `solc` on modified contracts) to confirm
   no compilation regression; `forge fmt --check` for style.

7. **Final test run.** `forge test` to confirm the suite passes; record any new failure.

## When to pivot

- **Slither false-positive flood:** narrow with `--detect <high-signal list>` and add a
  `.slither.config.json` suppression for known project FPs.
- **`myth` times out on complex contracts:** `--execution-timeout 300 --create-timeout 60`,
  and focus on functions with external calls and value transfers.
- **Echidna coverage plateau:** add a corpus dir (`--corpus-dir`) or switch to Medusa's
  coverage-from-corpus mode.
- **Halmos timeouts on loop-heavy code:** bound with `--loop`; Halmos is not for unbounded
  loops.

## Anti-patterns

- Do NOT report Slither medium/low findings without confirming exploitability via a call
  sequence or `myth` evidence.
- Do NOT run Echidna/Medusa without invariant tests — property-less fuzzing yields nothing.
- Do NOT run `myth` on a proxy without resolving the implementation first.
- Do NOT skip Slither for "simple" contracts — over half of historical EVM findings are in
  contracts under 200 lines.
- Do NOT invoke any dead `tool_wrappers/*` name (`slither_scan`, `mythril_analyze`,
  `echidna_fuzz`, `halmos_check`, `forge_test`); those wrap a container library that no longer
  exists — use the native CLIs above.

## Example

```bash
# Step 1: static analysis (native)
slither . --exclude naming-convention,solc-version

# Step 3: symbolic execution on a flagged contract
myth analyze src/Vault.sol --execution-timeout 600

# Step 4: fuzzing (30-min minimum for DeFi)
echidna . --contract InvariantTest --config echidna.yaml --test-limit 500000

# Step 7: final test run
forge test
```

## Recording (chrono-vault)

After the full audit, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="attempt", fields={"title": "evm-audit-flow on <project>", "body": "finding_count=<n>; high=<n>; medium=<n>; invariant_violations=<n>; tools=slither,semgrep,myth,echidna/medusa,halmos,forge", "target": "<project>", "attack_class": "evm-audit", "source_task": "<task-id>"})`.
Record each confirmed finding as `note_type="finding"` with its specific `attack_class` AFTER
cross-family review and the impact gate. A memory error is logged in one line and never blocks
the audit.
