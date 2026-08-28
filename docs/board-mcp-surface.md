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

+## Live `codex_apps` bridge inventory

A second live probe inside a board-spawned gpt-codex worker enumerated the
bridge's complete callable tool manifest on 2026-08-28. This is runtime evidence,
not a configuration-derived inventory.

Literal expression:

```javascript
const codexAppTools = ALL_TOOLS
  .map(x => x.name)
  .filter(name => name.startsWith("mcp__codex_apps__"))
  .sort();
text(JSON.stringify(codexAppTools));
```

Observed total: **125 tools**.

| Tool family | Count |
|---|---:|
| `codex_document_control` | 3 |
| `github` | 89 |
| `hotline` | 1 |
| `plugin_management` | 4 |
| `safety_settings` | 5 |
| `sites` | 23 |
| **Total** | **125** |

The positive control called `mcp__codex_apps__github_get_user_login({})`.
It returned `isError: false` with text and structured content. Account values
are intentionally omitted from this public record.

### `codex_document_control` (3)

```text
mcp__codex_apps__codex_document_control_execute_d_7437ad2e4ffa
mcp__codex_apps__codex_document_control_get_docum_83c7f0565c0f
mcp__codex_apps__codex_document_control_list_document_sessions
```

### `github` (89)

```text
mcp__codex_apps__github_add_comment_to_issue
mcp__codex_apps__github_add_issue_assignees
mcp__codex_apps__github_add_issue_labels
mcp__codex_apps__github_add_reaction_to_issue_comment
mcp__codex_apps__github_add_reaction_to_pr
mcp__codex_apps__github_add_reaction_to_pr_review_comment
mcp__codex_apps__github_add_review_to_pr
mcp__codex_apps__github_compare_commits
mcp__codex_apps__github_convert_pull_request_to_draft
mcp__codex_apps__github_create_blob
mcp__codex_apps__github_create_branch
mcp__codex_apps__github_create_commit
mcp__codex_apps__github_create_file
mcp__codex_apps__github_create_issue
mcp__codex_apps__github_create_pull_request
mcp__codex_apps__github_create_tree
mcp__codex_apps__github_delete_file
mcp__codex_apps__github_dismiss_pull_request_review
mcp__codex_apps__github_download_user_content
mcp__codex_apps__github_download_workflow_artifact
mcp__codex_apps__github_enable_auto_merge
mcp__codex_apps__github_fetch
mcp__codex_apps__github_fetch_blob
mcp__codex_apps__github_fetch_commit
mcp__codex_apps__github_fetch_commit_workflow_runs
mcp__codex_apps__github_fetch_file
mcp__codex_apps__github_fetch_issue
mcp__codex_apps__github_fetch_issue_comments
mcp__codex_apps__github_fetch_pr
mcp__codex_apps__github_fetch_pr_comments
mcp__codex_apps__github_fetch_pr_file_patch
mcp__codex_apps__github_fetch_pr_patch
mcp__codex_apps__github_fetch_workflow_job_logs
mcp__codex_apps__github_fetch_workflow_job_steps
mcp__codex_apps__github_fetch_workflow_run_artifacts
mcp__codex_apps__github_fetch_workflow_run_jobs
mcp__codex_apps__github_get_commit_combined_status
mcp__codex_apps__github_get_issue_comment_reactions
mcp__codex_apps__github_get_pr_diff
mcp__codex_apps__github_get_pr_info
mcp__codex_apps__github_get_pr_reactions
mcp__codex_apps__github_get_pr_review_comment_reactions
mcp__codex_apps__github_get_profile
mcp__codex_apps__github_get_repo
mcp__codex_apps__github_get_repo_collaborator_permission
mcp__codex_apps__github_get_user_login
mcp__codex_apps__github_get_users_recent_prs_in_repo
mcp__codex_apps__github_label_pr
mcp__codex_apps__github_list_installations
mcp__codex_apps__github_list_installed_accounts
mcp__codex_apps__github_list_pr_changed_filenames
mcp__codex_apps__github_list_pull_request_review_threads
mcp__codex_apps__github_list_pull_request_reviews
mcp__codex_apps__github_list_recent_issues
mcp__codex_apps__github_list_repositories
mcp__codex_apps__github_list_repositories_by_affiliation
mcp__codex_apps__github_list_repositories_by_installation
mcp__codex_apps__github_list_user_org_memberships
mcp__codex_apps__github_list_user_orgs
mcp__codex_apps__github_lock_issue_conversation
mcp__codex_apps__github_mark_pull_request_ready_for_review
mcp__codex_apps__github_merge_pull_request
mcp__codex_apps__github_remove_issue_assignees
mcp__codex_apps__github_remove_issue_label
mcp__codex_apps__github_remove_pull_request_reviewers
mcp__codex_apps__github_remove_reaction_from_issue_comment
mcp__codex_apps__github_remove_reaction_from_pr
mcp__codex_apps__github_remove_reaction_from_pr_review_comment
mcp__codex_apps__github_reply_to_review_comment
mcp__codex_apps__github_request_pull_request_reviewers
mcp__codex_apps__github_rerun_failed_workflow_run_jobs
mcp__codex_apps__github_rerun_workflow_job
mcp__codex_apps__github_resolve_review_thread
mcp__codex_apps__github_search
mcp__codex_apps__github_search_branches
mcp__codex_apps__github_search_commits
mcp__codex_apps__github_search_installed_reposito_be740b6e4965
mcp__codex_apps__github_search_installed_repositories_v2
mcp__codex_apps__github_search_issues
mcp__codex_apps__github_search_prs
mcp__codex_apps__github_search_repositories
mcp__codex_apps__github_unlock_issue_conversation
mcp__codex_apps__github_unresolve_review_thread
mcp__codex_apps__github_update_file
mcp__codex_apps__github_update_issue
mcp__codex_apps__github_update_issue_comment
mcp__codex_apps__github_update_pull_request
mcp__codex_apps__github_update_ref
mcp__codex_apps__github_update_review_comment
```

### `hotline` (1)

```text
mcp__codex_apps__hotline_get_local_hotline
```

### `plugin_management` (4)

```text
mcp__codex_apps__plugin_management_get_app_permissions
mcp__codex_apps__plugin_management_get_plugin_dependencies
mcp__codex_apps__plugin_management_uninstall_app
mcp__codex_apps__plugin_management_update_app_permissions
```

### `safety_settings` (5)

```text
mcp__codex_apps__safety_settings_get_family_info
mcp__codex_apps__safety_settings_get_parental_controls
mcp__codex_apps__safety_settings_get_trusted_contact
mcp__codex_apps__safety_settings_prepare_parental_02db6ffaefc6
mcp__codex_apps__safety_settings_update_parental_control
```

### `sites` (23)

```text
mcp__codex_apps__sites_add_custom_domain
mcp__codex_apps__sites_change_site_slug
mcp__codex_apps__sites_create_site
mcp__codex_apps__sites_create_source_repository_w_7e7b8ba6ef73
mcp__codex_apps__sites_deploy_private_site_version
mcp__codex_apps__sites_deploy_site_version
mcp__codex_apps__sites_generate_siwc_bypass_token
mcp__codex_apps__sites_get_deployment_status
mcp__codex_apps__sites_get_environment_variables
mcp__codex_apps__sites_get_site
mcp__codex_apps__sites_get_site_version
mcp__codex_apps__sites_get_site_worker_logs
mcp__codex_apps__sites_list_custom_domains
mcp__codex_apps__sites_list_site_versions
mcp__codex_apps__sites_list_sites
mcp__codex_apps__sites_read_database_overview
mcp__codex_apps__sites_read_database_table_rows
mcp__codex_apps__sites_refresh_custom_domain_status
mcp__codex_apps__sites_remove_custom_domain
mcp__codex_apps__sites_save_site_version
mcp__codex_apps__sites_update_environment_variables
mcp__codex_apps__sites_update_site_access
mcp__codex_apps__sites_update_site_metadata
```

## Per-server disable experiment

Status: **MEASURED — the override suppresses the bridge.** `observed_at=2026-08-28T21:40Z`,
run by Chrono from the main checkout, because the observing worker is prohibited from starting a
second Codex CLI.

| run | `mcp__codex_apps__*` tools visible |
|---|---|
| with `-c 'mcp_servers.codex_apps={enabled=false,command="/usr/bin/false"}'` | **0** (`[]`) |
| **positive control** — same command, override removed | **125** |

The positive control is what makes the zero mean anything: an empty array alone is equally
consistent with a probe that never had the bridge. Same binary, same flags, same prompt, same
shell; only the override differs. The 125 also reproduces the board worker's independently
measured count exactly.

Per the interpretation fixed **before** the run: an empty array means the existing override
suppresses the bridge. `codex_apps` is therefore an ordinary configurable MCP server, not an
unconditional platform-global bridge, and the existing allowlist seam at
`board-supervisor.sh:1976–2005` can govern it.

The installed CLI and the official [Developer commands](https://developers.openai.com/codex/cli/reference)
document the repeatable `-c key=value` override, while the official
[Configuration reference](https://developers.openai.com/codex/config-reference)
documents `mcp_servers.<id>.enabled`. They do not establish whether the
platform-global bridge is implemented as a configurable MCP server. Chrono can
run the required live control exactly as follows:

```bash
codex exec --ephemeral --sandbox read-only --skip-git-repo-check --json \
  -c 'mcp_servers.codex_apps={enabled=false,command="/usr/bin/false"}' - <<'PROMPT'
Use functions.exec exactly once. From this process's live ALL_TOOLS manifest,
sort every complete tool name beginning mcp__codex_apps__ and print only the
JSON array. Do not inspect configuration, start a child process, or call any
codex_apps tool. If ALL_TOOLS is unavailable, print exactly NOT_MEASURED.
PROMPT
```

An empty array establishes that the existing override can suppress the bridge.
A non-empty array establishes that the bridge bypasses that configuration seam
and is a vendor property to document. `NOT_MEASURED` remains the only valid
result if the live manifest cannot be enumerated.


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

### Surviving request-evidence oracle

Successful dispatch consumes the inbox packet, and the active registry retains
task metadata rather than the packet bytes. The controller-built
`_state/board-dispatch/<task>.<attempt>.context.json` persists after successful
settlement and carries the exact assembled `task_prompt`. The canary resolves
that file from the registry's delivery attempt, rejects symlinks, and requires
the context schema plus task, attempt, and generation bindings to match before
using the prompt as proof of what the worker was asked to do.

If that persisted source is absent or invalid, the result is `NOT MEASURED`.
The response artifact is never used to infer the ask: output that mentions a
skill or marker does not prove the packet requested it.

The `mcp_surface` result is:

- `PASS` only when the visible namespaces and successful-call namespaces both
  equal the four-prefix canary contract above and the report carries a sorted,
  non-empty inventory of complete `mcp__codex_apps__*` tool names;
- `FAIL` on a missing namespace, an unexpected namespace, or a visible namespace
  whose bounded call fails;
- `NOT MEASURED` when no suitable board task ran or its evidence is absent or
  malformed, including a visible `codex_apps` bridge with no tool inventory.

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
