# Adapter Capability Home Schema

Status: canonical schema for per-role, per-lane capability declarations

Schema: `specialist-lane-capabilities/v1`

Authoring source: `model-lanes/specialist-lane-capabilities.v1.json`

Validator: `scripts/python/validate_capability_homes.py`

Policy: `model-lanes/adapter-capability-policy.json`

Canonical specialist briefs own role, method, safety, input, and output behavior.
Concrete runtime capabilities are authored once in the versioned specialist ×
lane source. Adapters and `generated-specialist-capabilities.json` are derived
projections and must never be edited as capability authorities.
Lane-wide ceilings remain in `model-lanes/lane-capabilities.tsv`; they are not
copied into every role. The cross-cutting index is generated from the source and
must never be hand-authored.

## Structured fields

Each source entry declares `specialist`, `lane`, `coverage`, `limitations`, and
the following capability fields. Every routed pair must have an entry; primary
lanes require `full` coverage, while a `partial` lane requires at least one
explicit limitation.

| field | meaning |
|---|---|
| `skills` | Exact skill directory / registry identifiers available to this role on this lane. |
| `tools` | Exact adapter-native tool or executable identifiers available to this role on this lane. |
| `mcps` | Exact MCP server identifiers available to this role on this lane. |

Each capability is an object with `id`, `requirement` (`required` or
`preferred`), `availability` (`available`, `harness-only`, `mcp-operation`, or
`uninstalled`), and non-empty `evidence`. Only `available` capabilities are
projected into adapter arrays. Known unavailable capabilities remain visible in
the generated index and can preserve migration parity, but can never satisfy a
required primary execution plan.

`primary_requirement_policy` types every runtime-map `required_tools` entry,
including provider-native aliases and explicit cross-lane handoffs. All 71
primary plans are materialized during source loading. A local requirement is
projected into its typed adapter field; a handoff records the exact provider
lane and is accepted only when that provider exposes the same typed capability.
Backup coverage alone never satisfies a primary requirement.

Generated Gemini adapters use `tools` as the complete
adapter-native allowlist. For adapters explicitly marked
`generated_by: lane-capability-registry/v1`, or legacy Gemini adapters whose
structured values are all exact subsets of the Gemini TSV surface, the native
allowlist remains separate from role capabilities. Gemini role projections use
`capability_skills`, `capability_tools`, and `capability_mcps`; this preserves
native `tools` byte-for-byte during round trips.

Codex TOML uses native arrays:

```toml
skills = ["sandbox-provision-discipline"]
tools = ["forge", "slither"]
mcps = ["chrono-vault"]
```

Claude and Gemini Markdown frontmatter use one-line JSON-compatible arrays:

```yaml
---
name: security-analyst
skills: ["security-threat-model", "supply-chain-audit"]
tools: ["semgrep", "trivy"]
mcps: ["chrono-vault"]
---
```

Kimi YAML adapters use the same one-line JSON-compatible arrays as top-level
keys when a per-role capability applies. Lead-broker MCP identifiers remain
lane-wide unless a role needs a narrower declaration.

## Validator contracts

`base-boundary`

- Scans the full current body of every canonical specialist brief.
- Scans non-exempt frontmatter values; only the reviewed schema metadata keys
  and `requires_approval` are exempt. `required_tools` and `preferred_tools`
  remain scan-eligible.
- Allows exactly one byte-exact generic adapter-pointer line from the policy.
- Rejects reviewed identifiers plus extensible regex rules for command flags
  and source-schema references such as `tool.py:16-22`.
- Emits deterministic JSON diagnostics containing check, path, line, kind, and
  identifier.

`migration-parity`

- Uses exact git commit
  `be0354823d51f93d47f4833b8bfafd2a6b204dcd` as the pre-strip baseline.
- Extracts reviewed skill identifiers and scans the full pinned body for the
  explicit reviewed tool lexicon. Tool sections use the same lexicon and never
  infer a bullet's first word, so prose labels such as `Process audit`, `Date`,
  `amount`, and `draft` are not executables. Ambiguous words such as `find`,
  `perf`, and `requests` require inline-code context outside a tool section.
- Requires every baseline tool and skill to appear in the authored source on
  at least one lane from that specialist's primary/backup/escalate/review/
  throughput routes.
- Does not treat lane-wide TSV entries as per-role migration evidence.

`source-existence`

- Available MCPs must exist in lane inventory or the verified shared registry.
- Skills must exist in the lane registry or a lane-reachable installed skill
  root (repo-owned lane roots plus that CLI's user plugin/skill roots).
- Tools must exist in the lane's adapter-native inventory, a conservative exact
  `verified: yes` API-catalog identifier scoped to that lane, or the current
  `PATH` when that lane declares a shell surface.
- Catalog headings are never split into arbitrary words, so generic tokens such
  as `api`, `model`, `codex`, and `claude` cannot certify a declaration.
- Missing, renamed, or invented declarations fail closed.

`source-coverage`, `adapter-source-sync`, and `required-primary`

- Prove exact coverage of all routed specialist × lane pairs.
- Prove capability-bearing adapters match the source pointer, hash, and arrays.
- Require each runtime-map `required_tools` identifier to be available in the
  primary execution plan; backup lanes cannot silently satisfy it.

`index-freshness`

- Regenerates `model-lanes/generated-specialist-capabilities.json` from the
  authored source and records its SHA-256.
- Subtracts exact lane-wide TSV values from explicitly generated native mirrors
  and legacy Gemini mirrors before emission; manually authored role
  restrictions remain. Each row is therefore specialist × lane → per-role
  skills/tools/MCPs, not a copy of native lane allowlists.
- Compares the exact deterministic bytes; a missing or stale file fails.
- Records the pinned baseline and policy SHA-256 so policy drift is visible.

## Commands and honesty-gate wiring

Generate the tracked index after an intentional adapter change:

```bash
python3 scripts/python/validate_capability_homes.py --only index --write-index
```

Run the strict semantic gate:

```bash
python3 scripts/python/validate_capability_homes.py
```

`bin/validate-specialists.sh` runs the established specialist validator and
then this semantic gate. The live-flow addition is reversibly bypassable only
with `SQUAD_SKIP_CAPABILITY_HOME_GATE=1`; the wrapper prints an explicit `SKIP`
diagnostic to stderr and does not disguise that bypass as a capability-home
pass.

During the all-specialist migration campaign the strict repository gate is
expected to remain red until each historical capability is moved to a valid
adapter and each base is reduced to the exact generic pointer. Unit tests prove
the mechanisms independently; repository acceptance output proves the known
rejected batch is caught.
