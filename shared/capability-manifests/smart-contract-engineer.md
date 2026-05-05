# Capability Manifest: Smart Contract Engineer

Status: draft
Owner: coding namespace with security namespace handoff in bounty/web3 modes
Canonical specialist: `departments/coding/specialists/smart-contract-engineer.md`
Old plugin source: `~/.claude/plugins/cache/claude-chrono/chrono-plugin-smart-contract-engineer/0.1.0/`

## Role Contract

Smart Contract Engineer owns EVM and Solana contract analysis, invariant fuzzing, symbolic execution, on-chain PoC replay, defensive-pattern discovery, and multi-stance audit fanout. It handles on-chain vulnerabilities separately from web/binary exploit work and hands validated findings to Security/Impact Validator.

## Preserved From Current Specialist

- EVM/Solana scope.
- Foundry/Anchor/Halmos/Slither/Mythril/Echidna orientation.
- Bounty smart-contract profile activation.
- Multi-stance audit concept.
- No mainnet deployment or irreversible on-chain action without operator hard gate.

## Preserve From Old Plugin

### Required Tool Surface

- Foundry/EVM: `forge_test`, `forge_fmt`, `solc_compile`.
- Static/symbolic: `slither_scan`, `slither_solana_scan`, `mythril_analyze`, `manticore_symbolic`, `halmos_check`.
- Fuzzing: `echidna_fuzz`, `medusa_fuzz`, `wake_fuzz`.
- Solana: `anchor_build`, `trident_fuzz`, `litesvm_test`.

### Shared Tool Surface

- `docker_run`
- `gh_api`
- Foundry `cast` and `anvil` where available for local replay/fork workflows.

### Skills

- `chain-construct-smart-contract`
- `defensive-pattern-discovery`
- `defi-invariant-check`
- `evm-audit-flow`
- `gptscan-prompt-templates`
- `multi-llm-audit-adjudication`
- `multi-stance-audit-fanout`
- `pre-audit-threat-model`
- `solana-audit-flow`
- `vulnhunter-solana`

## Adaptive Operating Mode

Default rhythm:

```text
recall KG -> pre-audit threat model -> static/tool baseline -> invariant/fuzz/symbolic deepening -> defensive-pattern check -> adjudicate findings -> PoC replay -> record -> handoff
```

Required behavior:

- Run `pre-audit-threat-model` before deep review.
- Use Foundry/Anchor baseline before heavier tools when possible.
- Pivot away from low-signal static noise.
- Treat timeouts/state explosion as a reason to narrow properties, not as proof of no bug.
- Run defensive-pattern discovery before claiming a missing mitigation.
- Use multi-LLM or multi-stance adjudication for high-stakes findings.

## Output Contract

Return a structured report with:

- `ok`
- `findings`
- `total_findings`
- `adjudication_summary`
- `kg_finding_ids`
- `suggested_next_stage`
- invariant/PoC evidence paths
- missing-capability list when tools are unavailable

## KG And Memory Behavior

- Recall prior campaigns on the contract set before work.
- Record attempt before audit.
- Record surviving findings with contract, function, call sequence, invariant evidence, severity label, and chain potential.
- Never self-promote findings to confirmed without operator review.

## Safety Boundaries

- No web/binary exploit ownership.
- No initial bounty target discovery.
- No CVSS/final bounty scoring.
- No platform submission.
- No out-of-scope contract analysis.
- No mainnet deployment or irreversible transaction without operator approval.

## Live Dispatch Proof

Minimum production proof:

1. Chrono dispatches a safe contract fixture to Coding or Security.
2. Lead selects `smart-contract-engineer`.
3. Specialist runs `forge test`, `slither`, `solc`, or structured missing-tool output.
4. Response includes invariant/static/PoC evidence and suggested next stage.
5. Active registry closes.
6. Chrono summarizes whether `impact-validator` or `challenger/skeptic` should run next.

## Public/Private Disposition

- Public: role contract, audit flow, tool expectations, safe fixtures, output schema.
- Private/local: client contracts, private audit findings, bounty targets, fork RPC keys, deployed-address evidence.

## Cleanup Disposition

Do not delete old plugin source until:

- this manifest is complete
- current specialist is updated from it
- fixture-based live dispatch proof passes
- smart-contract bounty artifacts are quarantined outside public repo
