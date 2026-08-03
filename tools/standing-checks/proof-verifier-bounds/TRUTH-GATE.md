# Rule 8 truth gate

Date window: **task-scoped** — the operator packet, cited incident artifact, exact pinned source revisions, and outputs returned during TASK-2026-08-04-1300-mmrinv2 on 2026-08-02.

## Claim map

| ID | Class | Load-bearing claim/premise | Returned citation/evidence | Resolution |
|---|---|---|---|---|
| C-01 | fact | The supplied incident class is an out-of-range leaf omitted from MMR peak reconstruction while a proof element becomes the returned root. | Task packet; cited `departments/shared/outbox/TASK-2026-08-04-0700-substrate3-response.md` Part 2; `tests/CalculateRootRegression.t.sol`. | Resolved locally; runtime model reproduces the stated mechanism. |
| C-02 | fact | There is one vulnerable/fixed pair for each of five invariants in Solidity and Rust/Anchor, and every vulnerable member reports only its named invariant while its fixed twin reports none. | `fixtures/`; `results/control-output.txt` final run (`CONTROL_SUMMARY total=20 passed=20 failed=0`). | Resolved locally. |
| C-03 | fact | All ten Solidity and ten Rust/Anchor fixture files compile. | `results/control-output.txt` (`SOLIDITY_COMPILE_SUMMARY compiled=10 failed=0`; `RUST_COMPILE_SUMMARY compiled=10 failed=0`). | Resolved locally. |
| C-04 | fact | The runtime CalculateRoot control reproduces root substitution, fixed rejection, and valid-input acceptance. | `results/control-output.txt`, three named Forge tests, direct exit 0. | Resolved locally. |
| C-05 | fact | No qualifying candidate was recognized in 21 project-owned EVM production Solidity files or 19 project-owned Rust/Anchor program files. | `results/evm-project.json`; `results/svm-project.json`; `results/rust-field-census-output.txt`. | Resolved as bounded source-census fact; explicitly not generalized to target cleanliness. |
| C-06 | fact | Chainlink's vendored multiproof explicitly closes real leaf and proof cursors. | Pinned `MerkleMultiProof.sol:66-96`; `results/chainlink-merkle-multiproof.json`. | Resolved locally. |
| C-07 | inference | OpenZeppelin v5.1 accepted non-empty multiproofs exhaust leaves: `F=L+P-1`; `F` hashes consume `2F` operands; explicit proof exhaustion consumes `P`, leaving `2F-P=2L+P-2` main-queue operands, exactly `L+F-1`, all leaves plus all non-root generated hashes. | Pinned `MerkleProof.sol:212-242`; explicit proof guard at 239-242. | Arithmetic reproduced; premises resolved locally. |
| C-08 | inference | OpenZeppelin v4.8 accepted execution exhausts leaves even though proof exhaustion is not checked: every loop consumes at least one main-queue item; if `P>=1`, `F=L+P-1>=L`; if `P=0`, avoiding proof OOB requires main-queue selection and `2F=2L-2>=L` for `L>=2`; `L=1` is the direct-return case. | Pinned v4.8 `MerkleProof.sol:131-160`. | Case analysis reproduced; limited to accepted/in-bounds execution. |
| C-09 | fact | Chainlink and default OpenZeppelin pair hashing are commutative/sorted, so the library does not locally authenticate left/right position. | Chainlink `MerkleMultiProof.sol:108-111`; OpenZeppelin `Hashes.sol:17-18`. | Resolved locally; caller-owned binding remains separately classified. |
| C-10 | fact | The production source paths remained unchanged and no external submission was attempted. | Direct target `git diff --exit-code` results in `CORPUS.md`; `ACTION-LOG.md`; packet external-delivery prohibition. | Resolved locally for actions taken by this attempt. |

Backgrounded motivation: the **$237,000** label is supplied by the operator packet and cited research response. The deliverable does not independently re-estimate loss and does not rely on the amount for detector correctness.

```yaml
rule8_truth_gate:
  result: PASS
  claim_to_citation: true
  date_window: task-scoped
  reject_unsupported: true
  claims_checked: 10
  load_bearing_inferences_checked: 2
  citations_resolved: 10 / 10
  unverifiable: []
```
