# chrono-dedup

`chrono-dedup` is the prior-art gate for systematic-attacking Phase 1. It checks
one target-scoped finding or composite attack chain and returns structured hits,
the similarity basis for each hit, source availability, and one of:

- `duplicate` — an exact target-scoped dedup key was returned.
- `likely-duplicate` — no exact key matched, but similarity met the `0.72`
  threshold.
- `novel` — no exact or high-similarity result was returned. This verdict is
  explicitly provisional when `sources_consulted` contains an unavailable
  source.

The `chrono-dedup` MCP server and its `prior_art_check` operation are registered
in the project marketplace, shared tool registry, and specialist capability
source. The capability projection assigns Kimi the lead-broker path and the
other assigned bounty specialists the local MCP; a Chrono-side canary remains
the reachability proof after the selected lane has loaded the project plugin.

## Sources

The default source list is pluggable and degrades per source:

| Source | Lookup |
|---|---|
| HackerOne Hacktivity | Public Hacktivity search page, filtered to report links |
| Immunefi | Public Explore search, filtered to bounty/blog disclosure links |
| Solodit | Cyfrin Solodit findings API, authenticated with the Chrono-brokered `SOLODIT_API_KEY` |
| GitHub Security Advisories | Global advisory REST API, using affected package/version |
| CVE | NVD CVE 2.0 keyword search, retaining affected CPE component/version data |
| OSV | OSV query API using package, ecosystem when supplied, and version |
| Target program history | A target/item `disclosed_reports_url` or `program_history_url`, when supplied |
| `chrono-vault` | Target-filtered local recall over prior findings/KILL records |

HackerOne, Immunefi, NVD, OSV, and target-history requests are unauthenticated.
GitHub will use `GITHUB_TOKEN` or `GH_TOKEN` if already present, but no key is
required or hardcoded. Solodit requires `SOLODIT_API_KEY`; the plugin reads it
only from the inherited environment and never stores or returns it. The vault
adapter invokes the sibling local `chrono-vault` recall implementation and
inherits its fail-closed root and clearance checks.

## Runtime availability

Board workers are network-isolated. On that path, `prior_art_check` still runs
and reports each web-backed source as unavailable, while the local
`chrono-vault` source remains usable. HackerOne, Immunefi, GitHub, NVD, OSV,
target-history URLs, and Solodit are queried only when Chrono invokes the tool
with network access; Solodit additionally receives its credential through
Chrono's environment broker. A `novel` result remains provisional whenever any
source is unavailable.

Every source implements:

```python
source.name: str
source.search(target, item, query) -> iterable[record]
```

Pass `sources=[...]` to `prior_art_check` to replace the defaults, which keeps
tests hermetic and permits future provider-specific adapters.

## Composite-chain key

A finding key hashes:

```text
target + affected component + affected version + weakness
```

A composite key hashes:

```text
target + terminus + complete canonical link set
```

Link order does not change the key. Removing a link, adding a link, or changing
the terminus does. Individual known bugs do not make a new composite chain a
duplicate; only a prior chain with the same key is `duplicate`, while a prior
chain with sufficiently overlapping terminus and link set may be
`likely-duplicate`.

## Python API

```python
from chrono_dedup import prior_art_check

result = prior_art_check(
    "acme-bridge",
    {
        "title": "Signature replay bypasses nonce validation",
        "component": "bridge-relayer",
        "version": "2.4.1",
        "weakness": "signature replay",
        "keywords": ["nonce", "replay"],
    },
)
```

The result includes `dedup_key`, `verdict`, `rationale`, `hits`, and
`sources_consulted`. Source exceptions are reduced to their exception class;
provider response bodies and credentials are not returned.

## CLI and MCP

From this directory, pass an item on stdin:

```sh
printf '%s\n' '{"component":"bridge-relayer","version":"2.4.1","weakness":"signature replay"}' \
  | python3 -m chrono_dedup.cli acme-bridge
```

Or use `--item-json` / `--item-file`. `mcp_server.py` exposes the same operation
as the `prior_art_check(target, item)` FastMCP tool. CLI/MCP calls use the
default sources, subject to the runtime availability boundary above; tests
always inject mocks and never make live provider calls.

## Tests

```sh
python3 -m unittest discover -s plugins/chrono-dedup/tests -p 'test_*.py' -v
```
