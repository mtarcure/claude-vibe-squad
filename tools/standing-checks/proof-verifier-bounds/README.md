# Proof-verifier bounds standing check

This check finds missing source-level evidence for five Merkle/MMR verifier invariants in Solidity and Rust/Anchor. It was calibrated against the `CalculateRoot` failure shape in Polytope Labs' `solidity-merkle-trees`: an out-of-range leaf can remain outside every MMR peak while a proof element is accepted as the reconstructed root.

The check is intentionally conservative. A hit is a review lead, not a vulnerability. A detected guard is a `present_signal`, not a proof that the guard dominates every accepting path. `no_candidates` is never reported as clean.

## The five invariants

| ID | Invariant | Required condition | What a hit means |
|---|---|---|---|
| I1 | Strict index bounds | Every submitted index is checked with `index < leafCount` before use. For signed inputs, the lower bound must also be established. | No supported full-input bound signal was found. Test `index == leafCount` first; also establish that the supplied count is the canonical count for the committed root. |
| I2 | Exhaustive leaf consumption | Every original leaf reaches reconstruction, and the real cursor/iterator is empty at every accepting sink. | A supplied leaf may remain outside the reconstructed peaks/tree. Appending a sorted, in-range tail leaf is the primary witness. |
| I3 | Strict order and uniqueness | For every adjacent original input pair, `leaves[i].index > leaves[i-1].index`. | Duplicate or non-canonical index order may be accepted. Sorting a copy is not equivalent to rejecting a non-canonical proof. |
| I4 | Total proof consumption | Every original proof element reaches reconstruction, and the real proof cursor/iterator is empty at acceptance. | A trailing proof tail may be ignored, making the accepted encoding non-canonical or malleable. |
| I5 | Positional binding | If the application relies on absolute position, the checked position must affect the authenticated leaf/path or be compared with a trusted expected position before use. | Only set membership may have been established. Trace callers before deciding whether this is missing, caller-owned, or reviewed position-insensitive semantics. |

For I5, range and order are not positional authentication. Acceptable patterns include a domain-separated commitment over canonical `(index, value)` bytes, non-commutative path orientation derived from checked index bits, or an application caller that binds the verified index to the exact destination slot. A parameter named `position`, an error/log use, or commutative sorted-pair hashing does not establish absolute position.

## Components

- `check.py` is the primary no-dependency source checker. It strips comments, strings, literal-false blocks, and Rust `#[cfg(test)]` functions before recognizing a deliberately small set of canonical guard forms.
- `semgrep-solidity.yml` is an auxiliary Solidity evidence census. Its rules find guard signals; they do not emit PASS.
- `rust-field-census.sh` is the required positive-controlled `rg` fallback for Rust/Anchor field access.
- `fixtures/solidity/` and `fixtures/rust_anchor/` contain one vulnerable/fixed pair per invariant per language: 20 controls total. Each vulnerable member omits only its named invariant.
- `tests/CalculateRootRegression.t.sol` reproduces the incident shape in a sandboxed model and includes rejection plus valid-input negative controls.
- `results/` preserves machine-readable fixture and corpus output.
- `CORPUS.md` records the bounded pinned-corpus classification.

## Run

Run every static control, compile all 20 fixtures, and execute the three-test CalculateRoot regression:

```bash
bash tools/standing-checks/proof-verifier-bounds/run-controls.sh
```

Scan Solidity or Rust/Anchor source:

```bash
python3 tools/standing-checks/proof-verifier-bounds/check.py \
  --language solidity path/to/contracts

python3 tools/standing-checks/proof-verifier-bounds/check.py \
  --language rust path/to/programs
```

Restrict a library with many overloads to configured entrypoints and preserve JSON:

```bash
python3 tools/standing-checks/proof-verifier-bounds/check.py \
  --language solidity \
  --entrypoint '^processMultiProof' \
  --json-out result.json \
  path/to/MerkleProof.sol
```

Run the Rust/Anchor field-access fallback. The first stage must find the checked-in positive control before the requested source is censused:

```bash
bash tools/standing-checks/proof-verifier-bounds/rust-field-census.sh path/to/rust/source
```

Semgrep's experimental Rust analysis is not used for field-access conclusions: the measured ground truth supplied with this task was 106 relevant fields, three experimental matches, and zero field-access matches. A Semgrep zero on Rust is therefore a tool limitation, not clean evidence.

### Exit codes

| Exit | Meaning |
|---|---|
| `0` | Candidate(s) found with all five supported source signals, or all controls passed. Manual dominance and caller review remain required. |
| `1` | One or more candidate functions have review hits. This is not a finding exit. |
| `2` | Invocation/input/configuration error. |
| `3` | No candidate function was recognized. This is explicitly not a clean scan. |

Never hide these codes behind an unchecked pipe. Capture the check's own exit status.

## Positive-control contract

`check.py --self-test` requires exactly one candidate per fixture. Every vulnerable fixture must report exactly its named missing invariant; its paired fixed fixture must report no missing signal. The test fails if either member drifts.

The auxiliary Solidity Semgrep layer has its own five-pair control in `semgrep-controls.py`: the named guard rule must be present in the fixed member and absent in its vulnerable twin. Rust/Anchor field discovery is separately positive-controlled by `rust-field-census.sh`.

The runtime regression asserts three observable predicates:

1. With `leafCount = 1`, `leaf.index = 1`, and `proof[0] = storedRoot`, the vulnerable model returns `storedRoot` without incorporating the submitted leaf.
2. The fixed model rejects byte-equivalent proof/leaf/count input with `LeafIndexOutOfBounds`.
3. The fixed model accepts the valid negative control `leafCount = 1`, `leaf.index = 0`, empty proof.

## Interpretation workflow

1. Treat every `missing_signal` as a source-review lead.
2. Identify the original leaf/proof collections, real reconstruction cursors, and every accepting sink.
3. Resolve internal helpers, Solidity modifiers, Rust/Anchor macros/account constraints, and all reachable callers.
4. Confirm that a guard concerns the original value, precedes narrowing/index-derived access, and dominates every acceptance path.
5. Confirm that each cursor increment is tied to a root-producing read. Validation traversal or a dummy cursor is not consumption.
6. Classify I5 as local, caller-owned closed-world, reviewed position-insensitive, or unknown. Do not infer application semantics from the library alone.
7. Reproduce the suspected missing invariant with a negative control before promotion. The standing check never assigns severity, CVSS, exploitability, or submission status.

## Known limits

- This is canonical-form source analysis, not compiler CFG/MIR must-analysis. Assembly, dynamic dispatch, unresolved modifiers/macros, trait calls, helper aliases, shadowing, and non-canonical iterator algebra can require manual review.
- A guard after an unconditional return, a decoy cursor assigned to `.length`, a helper whose result is ignored, or a check on only one branch can create a false present signal. Comments, strings, literal-false blocks, Rust `debug_assert!`, and `#[cfg(test)]` functions are excluded from the recognized forms, but general reachability is not proven.
- Implicit mathematical proofs are intentionally not promoted by the source checker. For example, a multiproof shape equation plus a proof-exhaustion guard can imply leaf exhaustion even when no terminal `leafPos` comparison exists; that needs a written derivation.
- Safe newtypes, delta encoding, bitmaps, validated constructors, iterator combinators, or library-hidden position binding may produce false review hits.
- I1 only bounds an index against the supplied count. It does not prove that the count corresponds to the stored root.
- I5 is partly an application property. A library that accepts pre-hashed leaves cannot prove how the caller built the preimage, and a commutative tree cannot authenticate left/right position without additional binding.
- Candidate discovery requires proof/witness plus leaf terminology and verifier/hash semantics. `no_candidates` bounds only the files and vocabulary examined.
- Generated code, bytecode-only deployments, off-chain verifiers, non-vendored dependencies, and unscanned call sites remain outside a source-only result.

The appropriate long-term upgrade is compiler-AST/CFG analysis for Solidity and expanded HIR/MIR analysis for Rust/Anchor with effective modifier/macro expansion and caller-closure modeling. Until then, `present_signal` and `missing_signal` are deliberately narrower than PASS/FAIL.
