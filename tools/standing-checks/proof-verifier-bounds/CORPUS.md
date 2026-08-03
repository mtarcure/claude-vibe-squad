# Pinned corpus calibration

Verdict: **BOUNDED**. The check found no project-owned proof-verifier surface in either production tree. Real vendored Solidity multiproof implementations supplied positive corpus controls. This was a read-only source census, not a target audit and not an exploitability conclusion.

## Scope lock

Allowed read-only targets:

- `<repo-root>/_state/bounty/evmgw-2026-08-02/repo` at `80f7a208bcd484601a86d55e5a3891727e7f0ef9`
- `<repo-root>/_state/bounty/svmgw-2026-08-02/repo` at `5a23518e934cae186c3929f5e5bb736e7e11b574`

Forbidden: target writes/checkouts, live or production interaction, authenticated scope, network probing, external delivery, bounty submission, and public release.

## Project-owned production source

Literal EVM command and output:

```text
$ python3 tools/standing-checks/proof-verifier-bounds/check.py --language solidity <repo-root>/_state/bounty/evmgw-2026-08-02/repo/contracts/evm-gateway/src
FILES_SCANNED 21
CANDIDATE_FUNCTIONS 0
DISPOSITION no_candidates (not a clean scan)
[exit 3]
```

The independent tracked-source census covered all 21 production Solidity files; the broader 88-file tracked Solidity tree contained no project-owned proof implementation or call site. A recursive dependency census found the real verifier controls below, proving the surface search was not silently empty.

Literal Rust/Anchor checker output:

```text
$ python3 tools/standing-checks/proof-verifier-bounds/check.py --language rust <repo-root>/_state/bounty/svmgw-2026-08-02/repo/contracts/svm-gateway/programs
FILES_SCANNED 19
CANDIDATE_FUNCTIONS 0
DISPOSITION no_candidates (not a clean scan)
[exit 3]
```

Required Rust field-access fallback, with its positive control:

```text
$ bash tools/standing-checks/proof-verifier-bounds/rust-field-census.sh <repo-root>/_state/bounty/svmgw-2026-08-02/repo/contracts/svm-gateway/programs
FALLBACK rust-positive-control
COMMAND rg -n -i --glob '*.rs' --glob '!target/**' -e '<proof/leaf/field pattern>' .../fixtures/rust_anchor/strict_index_bounds_fixed.rs
27:        if leaves[i].index >= leaf_count {
33:        if leaves[i].index <= leaves[i - 1].index {
42:        let index_bytes = leaves[leaf_pos].index.to_le_bytes();
48:    if leaf_pos != leaves.len() {
51:    if proof_pos != proof.len() {
EXIT 0
CONTROL_PASS ripgrep detected known Rust field/proof surface
FALLBACK rust-corpus-census
COMMAND rg -n -i --glob '*.rs' --glob '!target/**' -e '<same pattern>' .../contracts/svm-gateway/programs
[no matches]
EXIT 1
CENSUS_RESULT bounded_empty_not_clean
[script exit 0]
```

The closest Rust cryptographic function is TSS ECDSA validation, not a proof verifier: `instructions/tss.rs:113-124` rebuilds a message hash, recovers a public key, and compares the derived address with stored TSS state. It accepts no leaves, indices, proof nodes, proof bytes, or Merkle root. Account-list validation at `utils/validation.rs:21-30` positionally zips equal-length account lists but is likewise not a Merkle/MMR verifier.

## Real verifier matrix

`Yes` means the guard is established for the verifier's own API. `No local` means the library does not enforce it; that is not automatically a defect because index/position semantics may be absent or caller-owned.

| Real verifier | I1 bounds | I2 leaf exhaustion | I3 order/unique indices | I4 proof exhaustion | I5 absolute position |
|---|---|---|---|---|---|
| Chainlink `MerkleMultiProof.merkleRoot` (`67887b84…`) | No local index API | **Yes, explicit** | No local index API | **Yes, explicit** | No local; sorted pairs |
| OpenZeppelin v5.1 multiproof (`e4f70216…`) | No local index API | **Yes, derived** from shape + queue + proof exhaustion | No local index API | **Yes, explicit** | No local for default commutative hasher |
| OpenZeppelin v4.8 multiproof (`0a25c194…`) | No local index API | **Yes, derived** from accepted queue/shape execution | No local index API | **No terminal guard** | No local; sorted pairs |
| Project-owned SVM gateway | No qualifying verifier | No qualifying verifier | No qualifying verifier | No qualifying verifier | No qualifying verifier |

### Chainlink guard

`MerkleMultiProof.sol:66-96` initializes real cursors, advances them only on queue reads, and rejects unless all three reconstruction queues close:

```solidity
(uint256 leafPos, uint256 hashPos, uint256 proofPos) = (0, 0, 0);
// ... root-producing queue reads ...
if (!(hashPos == totalHashes - 1 && leafPos == leavesLen && proofPos == proofsLen)) revert InvalidProof();
```

This supports I2 and I4 on every non-early accepted path; the `totalHashes == 0` path returns the sole leaf and has an empty proof by `totalHashes = leavesLen + proofsLen - 1` plus non-empty leaves. The library accepts pre-hashed `bytes32[] leaves`, not indexed leaf records, so it cannot locally enforce I1/I3.

Pair orientation is erased at `MerkleMultiProof.sol:108-111`:

```solidity
return a < b ? _hashInternalNode(a, b) : _hashInternalNode(b, a);
```

The CCIP caller hashes `message.header.sequenceNumber` into leaf content (`Internal.sol:103-123`) and enforces committed sequence intervals (`OffRamp.sol:829-843`), but that binds application sequence semantics, not `hashedLeaves[i]` to absolute tree position `i`. I5 therefore remains non-local/caller-semantic rather than satisfied by the multiproof library.

### OpenZeppelin v5.1 guards

The v5.1 multiproof requires at `MerkleProof.sol:215-218`:

```solidity
if (leavesLen + proof.length != proofFlagsLen + 1) {
    revert MerkleProofInvalidMultiproof();
}
```

It consumes queue elements at lines 231-236 and explicitly rejects residual proof at lines 239-242. On an accepted non-empty path, the shape equation plus complete `proofFlags` loop and proof exhaustion accounts for every original leaf; this is the manual I2 derivation that the conservative checker intentionally does not infer. Default pair hashing is commutative at `Hashes.sol:17-18`, so I5 is not local.

### OpenZeppelin v4.8 bounded contrast

The v4.8 multiproof checks `leavesLen + proof.length - 1 == totalHashes` at lines 134-135 and runs the queue at lines 148-151, supporting leaf exhaustion on accepted in-bounds execution. It returns at lines 154-160 without any terminal `proofPos == proof.length` guard. This establishes absence of an explicit I4 guard in that multiproof implementation; it does **not** by itself prove an exploitable or reportable defect. Its single-proof functions separately iterate over every proof element and are not covered by that observation.

## Pin and no-self-inflicted evidence

```text
$ git -C <evm> rev-parse HEAD
80f7a208bcd484601a86d55e5a3891727e7f0ef9
$ git -C <evm> diff --exit-code HEAD -- contracts/evm-gateway/src
[no output; exit 0]

$ git -C <svm> rev-parse HEAD
5a23518e934cae186c3929f5e5bb736e7e11b574
$ git -C <svm> diff --exit-code HEAD -- contracts/svm-gateway/programs
[no output; exit 0]
```

Both target worktrees already contained unrelated untracked worker artifacts. They were observed before the census, were not read as production evidence, and were not modified. No target checkout, reset, clean, build, or write command was run.

## Limits and disposition

- The project-owned results refute only the claim “a tracked on-repo production Solidity or Rust/Anchor Merkle/MMR verifier exists in the enumerated source at these pins.” They do not refute verifiers in off-chain services, generated binaries, non-vendored dependencies, other languages, or excluded untracked artifacts.
- The library matrix is source-level and local. Callers can add or omit application binding.
- No finding, CVSS, exploitability kill, scope exclusion, or submission was produced. External delivery and submission were not attempted.
- The packet says no target is audited, so the smart-contract full-arsenal/fork requirement was not invoked. Consequently the corpus result remains BOUNDED, not an exhausted negative audit.
