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

## Lane environment contract

The existing `cli`, `auth_policy`, and `child_mcp_policy` columns are the lane
environment authority. Provider keys are dropped for subscription/managed-login
workers; `gemini-api-key-only` is the sole model-key exception. Any direct or
lead-brokered `chrono-vault` surface requires `CHRONO_VAULT_ROOT`; its validity is
defined only by `plugins/chrono-vault/vaultroot.py`, not by a second lane table.

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
`preferred`), `availability` (`available`, `installed-skill-root`,
`harness-only`, `mcp-operation`, `pending-restart-activation`, `probe-failed`,
or `uninstalled`), and non-empty `evidence`. Operation-level `tools` also
declare `provided_by`. The source-level sorted `servers` array declares the
reciprocal `provides` list. A provider used by an entry must also have a usable
`mcps` assignment in that same specialist × lane entry.

Availability has two usable evidence classes:

- **Tool-backed:** `available` means the tool or MCP resolves through its
  lane-native inventory, verified registry/catalog entry, MCP surface, or a
  live executable probe where the lane exposes a shell. `$PATH` probes apply to
  tool identifiers, not knowledge skills.
- **Knowledge:** `installed-skill-root` means a skill is usable because its
  `SKILL.md` exists in a lane-reachable in-repo or installed skill root. This
  state is valid only for `skills` with `installed-skill-root` evidence.

Both evidence classes are projected into adapter arrays and may satisfy a
`required` primary execution plan. `mcp-operation` is an operation-level
declaration whose usable transport is its assigned `provided_by` server; the
operation remains visible in the generated index without pretending that its
name is itself a server. Other states are unavailable and can never satisfy a
required primary execution plan.

The runtime map's `required_tools` and `preferred_tools` fields are generated
server summaries, not an authoring surface. The generator reads the primary
lane entry, projects usable MCP assignments plus operation-provider closure,
normalizes lead-broker aliases, and lets `required` dominate `preferred`.
Standalone CLI/tool assignments remain in capsource and adapters; they are not
duplicated into the routing summary.

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
keys. MCP identifiers must use `lead:<server>`; bare/direct role MCP entries
are invalid. Projection strips `lead:` into an exact sorted `brokered_mcps`
surface, requires every named local template dependency to exist, and
materializes a per-task config containing only that allowlist for the main Kimi
lead. The config uses four controller-owned local templates. `chrono-vault`,
`chrono-dedup`, and `chrono-research-arsenal` use the authenticated repo root's
`.venv/bin/python` plus their exact in-repo `plugins/<server>/mcp_server.py`;
`sequential-thinking` uses the exact Homebrew executable. Missing or escaping
dependencies deny the launch.

Kimi never reads or copies host MCP configuration, commands, arguments, URLs,
headers, arbitrary environment, or auth values. FastMCP's default subprocess
environment omits the vault root and signed aperture context, so the
`chrono-vault` template carries exactly `CHRONO_VAULT_ROOT` and
`CHRONO_VAULT_CONTEXT` from the already-validated worker environment. Every
other template remains environment-free. Credential-bearing remote routes are
unavailable and credential-requiring operations remain unproven.

Kimi native `Agent(...)` subagents remain MCP-free. The child-argv-bound board
prompt names the main-lead allowlist without exposing configuration fields or
values.
Receipts report that actual allowlist as `authorized_mcps` while the signed
capability surface continues to record the same names as `brokered_mcps`.

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
- Require runtime-map tool columns to byte-match their generated capsource
  projection.
- Require each projected requirement to close through a usable primary-lane
  assignment, a typed provider relation, a verified registry record, and the
  generated adapter. Backup lanes cannot silently satisfy it.

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

Regenerate the runtime-map tool summary after an intentional capsource change:

```bash
python3 scripts/python/gen_runtime_tool_summary.py --write
```

Run the strict semantic gate:

```bash
python3 scripts/python/validate_capability_homes.py
```

`bin/validate-specialists.sh` runs the established specialist validator and
then this semantic gate. There is no full bypass: the `SQUAD_SKIP_CAPABILITY_HOME_GATE`
escape hatch was removed on 2026-08-13 because nothing set it and it disabled the
whole gate. The narrower, purposeful escape remains — `SQUAD_CI_HOST_INDEPENDENT=1`
runs a defined subset (`boundary,parity,index,source,required`) and announces which
subset it used, so a host-independent CI run is never mistaken for a full pass.

During the all-specialist migration campaign the strict repository gate is
expected to remain red until each historical capability is moved to a valid
adapter and each base is reduced to the exact generic pointer. Unit tests prove
the mechanisms independently; repository acceptance output proves the known
rejected batch is caught.
