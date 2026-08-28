# Publish provenance fence

Every projector run compares the latest `source_sha` in the existing export ledger with the requested source. On the source branch's first-parent line, it reports commits whose first-parent diff touches `scripts/python/**`, `bin/**`, `plugins/**`, `tools/**`, or `shared/dispatch-toolkit.sh` and has no matching integrated board receipt.

A receipt binds a commit only when its `worktree_integration` or `work_recovery` record names that exact integration commit and target, and its `integrated_paths` cover the protected paths. `Worker-Head` and `Worker-Base` trailers are cross-checked when present, but are not required: a valid fast-forward integration has a receipt and no merge trailers. First-parent traversal counts the integration commit once instead of separately accusing worker-side merge ancestry.

The fence does not judge whether a diff is good, inspect docs or runtime state, or block publication. Findings print to stderr before normal projection output and the projector continues; if the provenance query itself is unavailable, that diagnostic also reports without changing the projector's existing exit behavior. Each finding includes its protected paths and a ready remediation-lane dispatch command. Silence means no protected first-parent commit in the publish range lacked a binding, not that every repository surface was reviewed.
