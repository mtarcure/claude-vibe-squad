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
