# Moat capability

`moat/` is the public-safe Layer-1 skeleton for evidence-driven bounty work. It contains reusable schemas, boundary enforcement, synthetic fixtures, and declarative isolation profiles. It contains no engagement findings, real target identifiers, payloads, or private corpora.

## Boundary

Layer 1 accepts target-specific data only through a future approved external-input adapter backed by `$CHRONO_BOUNTY_ROOT` or the private vault. Layer-2 descriptors, corpora, fixtures, advisories, findings, and verdicts stay outside this tree.

The standalone Tier-A check enforces the public boundary without private target data:

```sh
node moat/boundary/tier-a.mjs path/to/staged-file ...
node moat/boundary/tier-a.mjs --self-check
```

Tier A reports `MOAT_BOUNDARY_*` error classes distinct from the existing leak guard. It checks capability imports, external-input provenance, schema/path/content-class validity, non-reserved external identifiers, encoded identifiers, and credential-shaped/high-entropy strings. The established `gitleaks` scanner runs fail-closed through the declared process adapter; the local entropy checks supplement it. Loopback, RFC-reserved examples, and reviewed generic protocol constants are permitted. Exact engagement strings remain a private Tier-B responsibility and are not implemented here.

Synthetic deny and invalid-schema fixtures are exact-hash allowlisted only for `--self-check`, allowing the scanner to test itself without making arbitrary fixture paths exempt. Direct staged-file scans never honor that allowlist.

## Development

```sh
cd moat
npm test
```

The test output records the legitimate-corpus false-positive rate. The isolation profile is configuration only; Phase 1 does not provision containers or make network requests.

## Manual slice and ledger

Phase 2 adds the sole external-input adapter, a real chrono-vault FTS5/BM25 recall bridge, a normalized public-advisory manifest, and a synthetic end-to-end slice:

```text
reviewed GuardAnnotation
  → canonical InvariantDescriptor
  → generated thin index with drift rejection
  → positive/negative external fixtures
  → calibrated oracle
  → evidence-referenced Verdict
```

Private JSON is addressed by logical `fixture:`, `manifest:`, and `descriptor:` references and resolved beneath `$CHRONO_BOUNTY_ROOT`. Vault recall requires both `$CHRONO_VAULT_ROOT` and an explicit `$CHRONO_VAULT_CLEARANCE`; missing configuration and recall/query errors return `recall_unavailable`, never `net_new`. The Python bridge imports the repository's real `plugins/chrono-vault/recall.py`; it does not implement a second search path.

The public manifest file is an empty normalized template. Real advisory entries and prior finding content stay in Layer 2. Tier A remains standalone and non-enforcing during this phase.
