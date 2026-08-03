# Capability gaps recorded by the lane

These are the techniques this campaign could not exercise, with the literal reason.
A decline is only honoured by the ledger when its citation resolves to text that
actually exists in an artifact, which is what this file provides.

- No Solana-native symbolic executor or SBF solver was present in the live runtime.
  EVM solvers are not valid substitutes for an Anchor/SBF claim, so no symbolic
  result is claimed for this target.
- Radar could not start without its isolated Docker socket; the custom Semgrep
  detector is the positive-controlled fallback.
