# Board-spawned MCP surface

Status: canonical measurement record and canary contract

A live probe inside a board-spawned gpt-codex systems-engineer worker established
that the worker has **four callable MCP tool namespaces**. Three are the
Vibe Squad role projection—`chrono-research-arsenal`, `chrono-vault`, and
`sequential-thinking`—and the fourth is the platform-global `codex_apps`
connector bridge. The often-repeated “3 vs 9” is therefore not a comparison of
two runtime measurements: three is the role projection, while nine is a static
lane declaration. A standalone Codex process currently lists eleven configured
servers, which is a third, different surface.

Canary contract (runtime prefixes): `["chrono_research_arsenal","chrono_vault","codex_apps","sequential_thinking"]`

## Live probe

This probe ran inside the board-spawned systems-engineer worker. It enumerated
the tool manifest supplied to that process; it did not read TOML, TSV, JSON, an
adapter, or a child process's configuration.

Literal expression:

```javascript
const actualMcpServers = [...new Set(
  ALL_TOOLS
    .map(x => x.name)
    .filter(name => name.startsWith("mcp__"))
    .map(name => name.split("__")[1])
)].sort();
text("LIVE MCP SERVER PREFIXES EXPOSED TO THIS PROCESS\n" + actualMcpServers.join("\n"));
```

Literal output:

```text
LIVE MCP SERVER PREFIXES EXPOSED TO THIS PROCESS
chrono_research_arsenal
chrono_vault
codex_apps
sequential_thinking
```

Visibility was followed by one bounded live call through each namespace:

| Runtime namespace | Bounded operation | Observed result |
|---|---|---|
| `chrono_research_arsenal` | `arxiv_search(query="all:\"Model Context Protocol\"", max_results=1)` | returned `isError: false` and `ok: true` |
| `chrono_vault` | `recall(query="board spawn MCP surface projection canary", limit=5)` | returned `isError: false`, a recall ID, and five aperture-bounded results |
| `sequential_thinking` | one-thought bounded liveness request | returned `isError: false`, `thoughtNumber: 1`, and `nextThoughtNeeded: false` |
| `codex_apps` | `github_get_user_login({})` | returned `isError: false` (account fields are intentionally not copied into this repository) |

The callable count for this worker is therefore four. The role-projected count
is three. The extra namespace is real and callable, but it is not sourced from
the repository's specialist projection.

## Why the other counts differ

The gpt-codex row in [`model-lanes/lane-capabilities.tsv`](../model-lanes/lane-capabilities.tsv)
declares a nine-server lane ceiling:

```text
chrono-vault, chrono-obsidian, chrono-research-arsenal, chrono-media-studio,
chrono-recon, sequential-thinking, github, playwright, chrome-devtools
```

That row describes the lane inventory, not what every specialist receives. The
generated systems-engineer adapter at
[`model-lanes/gpt-codex/.codex/agents/systems-engineer.toml`](../model-lanes/gpt-codex/.codex/agents/systems-engineer.toml)
projects exactly three:

```toml
mcps = ["chrono-research-arsenal","chrono-vault","sequential-thinking"]
```

### Directed control-flow map

| Typed edge | Producer anchor | Consumer anchor | Evidence |
|---|---|---|---|
| config → generator | `model-lanes/specialist-lane-capabilities.v1.json:9878` identifies the role/lane and `:9912–9931` supplies its three MCP records | `scripts/python/lane_adapter_registry.py:191–207` loads the source and renders available arrays | observed |
| generator → generated | `lane_adapter_registry.py:203–207` serializes `mcps` | `model-lanes/gpt-codex/.codex/agents/systems-engineer.toml:5–9` carries the generated block and source hash | observed |
| config → launch consumer | `systems-engineer.toml:8` declares the three-name array | `bin/board-supervisor.sh:1927–1944` reads and normalizes that array | observed |
| allowlist → CLI overrides | `board-supervisor.sh:1976–2005` computes authorized/disabled servers and constructs replacement overrides | `board-supervisor.sh:2996–3008` passes those arguments to the worker launch | observed |
| launched worker → runtime evidence | the bound worker receives its tool manifest | the live `ALL_TOOLS` expression above enumerated four prefixes and all four bounded calls returned without error | observed outside the repository |
| host bridge → runtime evidence | no repository producer was found for `codex_apps` in the Codex projection/config path | the live manifest and successful app-bridge call prove it reached the worker | endpoint observed; injection edge inferred |

The traversal-backed conclusion is: capability source → generated three-name
adapter → supervisor three-name allowlist → per-spawn CLI overrides → a live
worker with those three namespaces, followed by an additional host-provided
`codex_apps` namespace outside that path.

The main cut points are the capability source (regenerating it can affect every
native adapter), `board-supervisor.sh` (its Codex branch affects every Codex
board launch), and the host's platform-tool injection (it can add tools to every
worker independently of repository policy). `systems-engineer.toml` has the
narrower blast radius of this specialist/lane pair only.

Two apparent orphans are intentional and resolved. `model-lanes/lane-capabilities.tsv`
is the lane-ceiling declaration, not an input edge to this role allowlist.
`scripts/python/lane_capability_enforcement.py:1007–1215` contains the shared
equivalent policy, while the live Codex supervisor branch duplicates the launch
construction directly; it is corroborating implementation, not the consumer on
this specific traversal.

The board supervisor makes that projection an allowlist. It reads the adapter's
`mcps` array ([`bin/board-supervisor.sh`](../bin/board-supervisor.sh), around
lines 1927–1944), enumerates the configured Codex servers, and then applies:

```python
authorized_mcps = capability_projection["mcps"]
disabled_mcps = sorted(set(configured_mcps) - set(authorized_mcps))
```

For each configured server outside the projection, the launch arguments replace
its table with `{enabled=false,command="/usr/bin/false"}` (same file, around
lines 1984–2005). The shared implementation records this mechanism as
`codex-cli-mcp-table-replacement-overrides/v1` in
[`scripts/python/lane_capability_enforcement.py`](../scripts/python/lane_capability_enforcement.py),
around lines 1124 and 1151–1169. This is deliberate role projection; it is not
failed inheritance and it is not a denial based on whether a lane capability is
`required` or `preferred`.

As a negative control, the literal command `codex mcp list` was also run from
inside the worker. It started a new Codex process and listed these eleven host
configuration entries:

```text
chrono-dedup
chrono-kg
chrono-media-studio
chrono-obsidian
chrono-recon
chrono-research-arsenal
chrono-vault
guarded-semgrep
guarded-slither
guarded-solodit
sequential-thinking
```

That command is useful for explaining configured-versus-declared drift, but it
is not proof of the parent worker's callable surface: the child does not inherit
the parent's per-spawn `-c mcp_servers.…` launch overrides or its already-bound
tool manifest. Neither the nine-row declaration nor the eleven-entry child
configuration is the answer to the runtime question.

The live `codex_apps` namespace is outside both lists. Based on the observed tool
manifest and the supervisor code, it is injected by the host platform after (or
outside) the repository's native Codex MCP allowlist. That causal placement is
an inference; the facts established here are that the namespace was visible and
that a bounded call succeeded.

## Non-rotting measurement

[`bin/canary.sh`](../bin/canary.sh) owns the executable guard. Its
`--emit-mcp-packet` packet targets `systems-engineer@gpt-codex`, asks the worker
to enumerate its live tool manifest without quoting the expected answer, and
requires one bounded read-only call through every reported namespace. The
artifact returns a strict `MCP_SURFACE_JSON:` record. The pre-existing
`--emit-packet` transport/skills route remains `backend-engineer@claude`; Chrono
can adjudicate the two task IDs together with `--task` and `--mcp-task`.

The `mcp_surface` result is:

- `PASS` only when the visible namespaces and successful-call namespaces both
  equal the four-prefix canary contract above;
- `FAIL` on a missing namespace, an unexpected namespace, or a visible namespace
  whose bounded call fails;
- `NOT MEASURED` when no suitable board task ran or its evidence is absent or
  malformed.

`bash bin/canary.sh --self-test` includes both a missing-namespace inversion and
a working positive control. `scripts/python/tests/test_canary_suite.py` pins the
same behavior and verifies that this document's contract matches the executable
expectation. This file remains the prose home for the measurement; the shell
constant is its enforced gate, not a second narrative source.

## Follow-up boundary

No MCP wiring was changed by this measurement task. A separate board item should
decide whether platform-global `codex_apps` tools are intentionally outside the
specialist capability boundary. If they are meant to be scoped, that item must
design and test host-level enforcement; changing lane configs or adapters here
would exceed this task's measure-and-record scope.
