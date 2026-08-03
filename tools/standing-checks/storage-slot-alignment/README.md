# Storage-slot alignment standing check

This check runs `forge inspect <Contract> storage-layout --json` for each declared proxy and implementation, converts every layout field to a byte interval, and diffs the intervals per deployment target. It flags packed-field collisions as well as whole-slot collisions and calls out any overlap involving slots 0 or 1 or initialization/version labels.

## Run

Create a tab-separated manifest:

```text
deployment	proxy	implementation
ethereum-mainnet	src/MyProxy.sol:MyProxy	src/MyImplementation.sol:MyImplementation
l2-mainnet	src/L2Proxy.sol:L2Proxy	src/L2Implementation.sol:L2Implementation
```

For a contract whose source root differs from the project's configured `src`, prefix the contract name with `relative/contracts/root::`. For example, `lib/openzeppelin-contracts/contracts::TransparentUpgradeableProxy` makes the literal Forge invocation add `--contracts <project>/lib/openzeppelin-contracts/contracts` and inspect `TransparentUpgradeableProxy`.

Then run:

```sh
python3 check.py /path/to/foundry/project \
  --manifest /path/to/deployments.tsv \
  --work-dir /writeable/evidence/directory
```

The target project is only read. All Forge `out`, cache, command, stdout, stderr, and exit-status files are written beneath a new numbered directory in `--work-dir`. Forge runs with `--offline` and skips tests and scripts.

The command emits exactly one Markdown table and one `VERDICT` line:

- `FAIL` — at least one proxy field overlaps an implementation field.
- `PASS` — Forge returned both layouts for every pair and no declared field byte ranges overlap.
- `ERROR` — a manifest, Forge, or JSON/layout step failed.

Exit status is `0` for `PASS`, `1` for `FAIL`, and `2` for `ERROR`.

## Positive and negative controls

```sh
python3 check.py fixtures --manifest fixtures/vulnerable.tsv --work-dir work
python3 check.py fixtures --manifest fixtures/good.tsv --work-dir work
```

The vulnerable proxy has an `initialized` flag and address fields packed into slots 0 and 1, overlapping the implementation. It must return status `1` and `VERDICT: FAIL`. The EIP-1967-style proxy declares no ordinary storage fields and must return status `0` and `VERDICT: PASS`.

## What a hit means

An overlap means delegate-called implementation code and proxy code can read or write the same bytes. Initialization-flag and slot-0/slot-1 hits deserve immediate deployment-history review, especially when the same implementation is redeployed across chains or L2s.

## Known limits

- Forge reports compiler-declared storage. Unstructured assembly slots, diamonds, custom VM storage, and runtime-selected slots need a separate constants/bytecode review.
- A collision is a storage primitive, not by itself a proven exploit. Confirm the deployed proxy type, initialization transaction, upgrade history, and implementation bytecode.
- `PASS` covers only the manifest's exact deployment pairs. It is not a claim about undeclared chains, historical implementations, or live deployed state.
- Namespaced storage libraries may not appear as ordinary top-level fields. Inspect their slot constants separately when the proxy itself uses namespaced state.
