# Tier-A public boundary check

Tier A parses JavaScript, TypeScript, and TSX with the TypeScript compiler API. It resolves bounded constant expressions before checking imports and values that flow into capability sinks. JSON provenance fields, logical references, content classes, and calibrated secret scanning remain part of the same standalone check.

Run the complete public Layer-1 check:

```sh
node moat/boundary/tier-a.mjs --self-check
```

Run an explicit staged-file list:

```sh
node moat/boundary/tier-a.mjs --staged moat/path/to/staged-file.mjs
```

Proposed pre-commit composition, intentionally **not applied** by this phase:

```sh
git diff --cached --name-only -z --diff-filter=ACMR -- moat/ | xargs -0 node moat/boundary/tier-a.mjs --staged
```

The check is enforcement-ready as a data-free public control. Private exact target, repository, advisory, and hostname matching remains Tier B and belongs in private pre-push/CI enforcement.

## Tier-B private exact-target boundary

Tier B loads `descriptor:target-denylist` through the external-input adapter. The private descriptor lives under `$CHRONO_BOUNTY_ROOT/descriptors/target-denylist.json`; its hostnames, repository names, advisory IDs, and target paths are never committed to Layer 1. When any Layer-1 file is supplied, an unavailable or malformed descriptor blocks the operation. Non-Layer-1-only changes do not require private state.

Tier B reports only its `MOAT_BOUNDARY_TIERB_*` class, Layer-1 file, and line. It never includes the matched denylist token or a private loader error in output.

Proposed private pre-push wiring, intentionally unapplied (the hook reads Git's standard ref-update line):

```sh
while read -r _ local_sha _ remote_sha; do node moat/boundary/tier-b.mjs --range "$remote_sha..$local_sha" || exit 1; done
```

Proposed mandatory private CI wiring, intentionally unapplied:

```sh
node moat/boundary/tier-b.mjs --range "$BASE_SHA..$HEAD_SHA"
```

The controls compose orthogonally:

1. The shipped leak guard blocks private-file presence and restricted paths.
2. Public Tier A checks Layer-1 capabilities, provenance, schemas, and secrets without private data.
3. Private Tier B checks Layer-1 contents against exact engagement targets at pre-push and mandatory CI, failing closed when its expected descriptor is unavailable.

The public pre-commit remains data-free; no Tier-B wiring is applied here.
