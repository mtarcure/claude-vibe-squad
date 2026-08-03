# Auditware Radar install and canary rig

Task: `TASK-2026-08-04-0300-W1D-radar`

Status: prepared but not live. Installation and every scan were blocked before Radar execution because no Docker daemon was available and Colima could not resolve GitHub to obtain its VM image.

## Scope

- Allowed scan target (read-only): `<repo-root>/_state/bounty/svmgw-2026-08-02/repo/contracts/svm-gateway`
- Required target pin: `5a23518e934cae186c3929f5e5bb736e7e11b574`
- Writable rig: `_state/bounty/rigs/radar/`
- No submission, external delivery, project contact, or target mutation is authorized.

## Initial liveness evidence

```console
$ command -v docker
/opt/homebrew/bin/docker
$ docker --version
Docker version 29.4.0, build 9d7ad9ff18
$ docker info --format '{{json .ServerVersion}}'
""
failed to connect to the docker API at unix://<home>/.colima/default/docker.sock; check if the path is correct and if the daemon is running: dial unix <home>/.colima/default/docker.sock: connect: no such file or directory
```

The Docker CLI is installed, but the configured Colima daemon was not running at the initial probe.

## Verdict

Radar did **not** install or run in this lane. No report file exists, no detector count was observed, and neither the built-in nor custom detector was shown firing. This is an install/runtime failure, not a zero-finding scan.

The terminal bootstrap error was:

```text
error getting qcow image: error during image download: error resolving download URL 'https://github.com/abiosoft/colima-core/releases/download/v0.10.1/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2': resolve redirect failed for 'https://github.com/abiosoft/colima-core/releases/download/v0.10.1/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2': DNS lookup failed for host 'github.com'. Check your network connection or DNS settings
```

See `action-log.md` for commands, full outputs, and exit statuses.

## Why the upstream installer was not executed verbatim

The returned upstream scripts contain cleanup operations forbidden by this packet: repository `git clean -fd`/`reset --hard`, `docker compose down -v`, and a timeout fallback to `docker system prune -f --volumes`. The local scripts use the same official Radar image names but never prune, remove volumes, overwrite reports, or publish host ports.

## Prepared local installation

Prerequisite: a working Docker daemon that can pull from GHCR. The dedicated Colima profile keeps its config/cache beneath this rig and mounts the target read-only.

```bash
radar_rig="$PWD/_state/bounty/rigs/radar"
COLIMA_HOME="$radar_rig/colima" \
XDG_CACHE_HOME="$radar_rig/xdg-cache" \
DOCKER_CONFIG="$radar_rig/docker-config" \
colima start radar-canary \
  --runtime docker --cpus 2 --memory 4 --disk 12 --root-disk 10 \
  --vm-type vz --activate=false --ssh-config=false \
  --mount <repo-root>/_state/bounty/svmgw-2026-08-02/repo/contracts/svm-gateway \
  --mount "$radar_rig:w"

"$radar_rig/bin/install-local.sh"
```

The first successful install must record the returned image digests; upstream compose references mutable `:main` tags.

## Target canary command

The runner rejects existing output files and mounts `TARGET` read-only.

```bash
radar_rig="$PWD/_state/bounty/rigs/radar"
target=<repo-root>/_state/bounty/svmgw-2026-08-02/repo/contracts/svm-gateway
"$radar_rig/bin/scan-local.sh" \
  "$target" \
  "$radar_rig/reports/target.json"
```

Acceptance requires all three observables: a non-zero finding count, named detectors, and a non-empty JSON report. None was produced in this execution.

## Positive and negative controls

The isolated vulnerable fixture intentionally performs an SPL token transfer with an arbitrary `AccountInfo` authority and no `seeds`/`bump` constraint. The fixed fixture adds canonical seeds/bump constraints and signer seeds. They are outside the target.

```bash
radar_rig="$PWD/_state/bounty/rigs/radar"
"$radar_rig/bin/scan-local.sh" \
  "$radar_rig/fixtures/vulnerable" \
  "$radar_rig/reports/positive-control.json" \
  "$radar_rig/templates/positive-control-pda-sharing.yaml"

"$radar_rig/bin/scan-local.sh" \
  "$radar_rig/fixtures/fixed" \
  "$radar_rig/reports/custom-rule-negative.json" \
  "$radar_rig/templates/missing-pda-seeds-canary.yaml"
```

These commands were attempted but stopped at the absent Docker socket. Syntax validity is not detection evidence.

## Adding and running the custom Python rule

Radar templates embed Python DSL statements under `rule: |`. The task-authored rule is `templates/missing-pda-seeds-canary.yaml`; it requires a token transfer plus an `AccountInfo` and fires only when the same source has no `seeds`/`bump` account attribute.

```bash
radar_rig="$PWD/_state/bounty/rigs/radar"
"$radar_rig/bin/scan-local.sh" \
  "$radar_rig/fixtures/vulnerable" \
  "$radar_rig/reports/custom-rule.json" \
  "$radar_rig/templates/missing-pda-seeds-canary.yaml"
```

To add another rule, copy the YAML shape, keep the required metadata fields, write DSL logic against `ast`, and print only nodes converted with `.to_result()`. Validate it with a vulnerable and fixed fixture before using it on a target.

## Limits found

- Docker CLI presence is not daemon liveness.
- This Codex lane cannot resolve GitHub from shell/Colima, so neither the VM image nor Radar/GHCR images could be obtained.
- The upstream launcher performs destructive cleanup and suppresses significant Docker output; it is unsuitable under a no-delete evidence contract without a wrapper.
- Radar image references are mutable `:main` tags until a successful pull yields recorded digests.
- The local fixtures/templates pass static parsing/format checks only; no end-to-end claim is made.
- Gemini-lane availability is **not proven**. No Gemini worker or CLI was authorized in this packet, and repository policy forbids inferring a lane capability without a live lane probe.
- The failed Colima attempt left a sparse task-created data disk under `colima/_lima/_disks/`; it is retained because deletion was not authorized.

## Files

- `compose.yaml` — isolated non-pruning Radar topology.
- `bin/install-local.sh` and `bin/scan-local.sh` — fail-closed local runners.
- `fixtures/vulnerable/` and `fixtures/fixed/` — positive/negative Anchor controls.
- `templates/positive-control-pda-sharing.yaml` — pinned upstream built-in.
- `templates/missing-pda-seeds-canary.yaml` — task-authored custom Python-DSL rule.
- `evidence/` — scope, reproduction, no-submit, no-self-inflicted, and truth gates.
- `action-log.md` — literal commands and outputs.
- `provenance.md` — source pin and GPL provenance.
