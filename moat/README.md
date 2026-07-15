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
