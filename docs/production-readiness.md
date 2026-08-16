# Production Readiness

Supported platform is macOS first.

## Release Checklist

The maintainer installation is in daily use, but a public release is not called
ready until this checklist passes from a fresh checkout with private state kept
outside the clone.

This is the maintainer's release checklist. Items marked **(maintainer checkout
only)** cannot pass in a public clone and are not expected to: they read
private inputs the public projection deliberately withholds — private history
and the identifier denylist — or they audit the maintainer's live host state.
In a public clone, `squad doctor` reports the withheld private inputs as NOT
APPLICABLE and `.github/workflows/public-validate.yml` validates what the
public tree actually carries.

This paragraph is the one home of how the two validators behave outside the
maintainer checkout; `.github/workflows/public-validate.yml` points here.
`validate-specialists.sh` **passes in both trees**, on different check sets. In a
public clone the private registry is absent, so it selects
`index,source,required,existence` and excludes `boundary,parity`; the pinned
baseline is loaded **only** for those two checks
(`scripts/python/validate_capability_homes.py`, the `enabled & {"boundary","parity"}`
guard), so `require_baseline_commit` never runs and its missing commit never
arises. Measured on a registry-free fresh-history archive: **exit 0, 68 passed**,
announcing the public subset rather than skipping quietly. The subset is not
vacuous — an injected generated-index defect exits 1 on `index-freshness`.
It refuses in exactly one shape: registry **present** and baseline **absent**,
where it exits 2 naming the missing commit.
`validate-capabilities.sh` is the mirror case: with the registry absent and
untracked it emits a typed `registry-not-published` / `not-applicable` result
and exits 0, so it passes registry-free — vacuously; a tracked-but-missing
registry still fails closed.

- `bash -n bin/*.sh scripts/*.sh shared/*.sh`
- `python3 -m py_compile scripts/python/*.py bin/*.py`
- `bash bin/validate-specialists.sh` (passes in a public clone too, on the
  reduced `index,source,required,existence` set — degradation detail above.
  Only this checkout exercises `boundary,parity` and the baseline)
- `bash bin/validate-capabilities.sh` (exits 0 in a public clone with a typed
  `registry-not-published` skip; only this checkout exercises the registry)
- `bash bin/test` (maintainer checkout only)
- `bash bin/doctor.sh`
- `bash bin/mcp-audit.sh` (maintainer checkout only — audits the maintainer's
  live CLI and MCP state)
- `bash bin/product-hygiene.sh --public-export` (maintainer checkout only —
  requires the private identifier denylist)
- Dispatch smoke test in a temporary checkout
- Fresh clone setup test
- Validate an external `CHRONO_VAULT_ROOT` and prove no note or credential is
  written into the checkout
- Complete bounded native-CLI and required-tool probes for all four model lanes
- Confirm no runtime/private file patterns are staged

## Public Commands

- `squad up` launches the stack after a first-run autonomy warning and a
  pre-flight `doctor` health gate that blocks the launch on failure.
- `squad up --safe` skips that warning and that health gate. It changes no
  permission setting for the coordinator or for board-spawned workers; the two
  commands differ only in whether the pre-flight check runs.
- `squad stop` writes a handoff and stops the tmux session.
- `squad status` prints canonical live state.
- `squad doctor` runs health checks.

## Script Policy

Keep public entrypoints stable even when implementation moves:

- `bin/squad` is the main user interface.
- `scripts/send-task.sh` remains Chrono's compatibility entrypoint.
- `bin/send-task.sh` remains the hardened dispatch primitive.
- Tiny shell wrappers are acceptable when they give a stable command name around a larger Python implementation.
- One-off migration scripts should move to `tools/` or `docs/legacy/` after they are no longer needed at runtime.

## Known Limitations

- V4 fresh-clone acceptance and complete fresh-worker tool parity are still
  release gates. A maintainer-local success is not treated as public proof.
- MCP audit can verify stdio server usability, but CLI-specific MCP invocation quality still depends on each CLI's current implementation.
- Kimi has no per-directory auto-load convention, so a board-spawned Kimi specialist is given an explicit role-read instruction in its task packet rather than inheriting one from its working directory.
- Kimi subagents cannot hold MCP, so any MCP work on a Kimi-routed specialist must be brokered rather than performed in-subagent.
- Public CI cannot validate private OAuth state or local Chrome CDP sessions.
