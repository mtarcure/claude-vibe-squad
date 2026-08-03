# Radar image digests — first successful pull

The rig's README requires this: *"The first successful install must record the returned image digests;
upstream compose references mutable `:main` tags."* Until now no pull had succeeded, so the rig ran
against tags that could change under it without notice.

**Pulled 2026-08-02**, `--platform linux/amd64`, via colima (Docker 29.2.1 server):

```
ghcr.io/auditware/radar-controller@sha256:0894c6c4c73af363b4422abc4e4b31709514c0e530985487ee07b3695214dea0
ghcr.io/auditware/radar-api@sha256:0c652ca684cc6f7a4bdf48346772f49c3d7241fa2869663a58092fc29e7d875b
```

`compose.yaml` is derived from Auditware/radar's `docker-compose.yml` at commit
`2327887cd47a2bcc71b7a6d0f88f60c9db026436`, with host port publication and global `container_name`
values removed for task isolation.

## What this does and does not unblock

**Cleared:** the original blocker was *"no Docker daemon was available and Colima could not resolve
GitHub."* Both are gone — colima is running, DNS resolves (`github.com` → 140.82.116.4), an HTTPS
fetch to the GitHub API succeeded from inside a container, and both images pulled.

**Still outstanding — Radar has never actually scanned anything here.** `verified_state` stays `no`
until a scan produces real output against a known-vulnerable fixture *and* a clean control. Pulling an
image is not running a detector, and a Solana/Anchor scanner that silently matches nothing looks
exactly like a clean target.

**Deliberately not done:** the upstream install scripts were not run. The prior lane recorded that they
contain `git clean -fd`, `git reset --hard`, and `docker compose down -v` — destructive operations that
would take out uncommitted work across every worktree in this repo, and which require explicit operator
approval regardless. `bin/install-local.sh` and `bin/scan-local.sh` in this rig are the sanctioned path
and contain none of them.

**Note on isolation:** `bin/install-local.sh` expects a dedicated `radar-canary` colima profile socket
at `colima/radar-canary/docker.sock`. This pull used the default colima profile instead, to avoid
running a second VM on a 16 GB host. Before a real scan, either start the `radar-canary` profile as the
README specifies, or consciously accept the shared-daemon deviation and record it.
