---
name: supply-chain-audit
audience: specialist
description: "Use when auditing whether anything outside the project can silently alter a build or published release—inventory dependencies, base images, binaries, generators, CI actions, install hooks, secret exposure, and publisher controls; verify pins, digests or signatures, reproducibility, and one artifact's end-to-end provenance. Use dependency-health-triage for advisory reachability alone; this owns build and release integrity."
---

# Supply Chain Audit

Audit everything that enters a build or a release without being written by the project, and everything that can modify the release on its way out.

## Steps
1. Inventory inputs: package dependencies, base images, downloaded binaries and installers, CI actions and plugins, and build-time code generators.
2. Check pinning and integrity for each input — exact versions, lockfile presence, checksum or digest verification, and signature verification where the ecosystem supports it. A floating tag is an unpinned input.
3. Audit the CI/CD pipeline as attacker surface: who can trigger a build, what secrets each job can read, whether pull-request builds from forks get privileged tokens, and whether build steps can be influenced by the code they are building.
4. Check third-party CI actions specifically — pinned to a commit SHA rather than a mutable tag, and reviewed for the permissions they request.
5. Look for typosquat and confusion risk: internal package names resolvable from a public registry, recently-renamed or transferred packages, and single-maintainer packages with sudden ownership changes.
6. Verify the release path: who can publish, whether publishing requires review, whether artifacts are signed, and whether the published artifact can be reproduced from the tagged source.
7. Check install-time execution — post-install scripts, build hooks, and container entrypoint fetches — as these run with developer or build privilege.
8. Trace the provenance chain end to end for at least one artifact, and record every point where the chain relies on trust rather than verification.
9. Rank findings by whether they permit silent modification of shipped code; that class outranks everything else here.

## Acceptance
- All build inputs are inventoried with their pinning and integrity-verification state.
- CI permissions, fork-build behavior, and third-party action pinning are checked and recorded.
- Dependency-confusion and ownership-change risks are examined for internal names.
- The release path is traced end to end, with every trust-not-verification point named.
- Findings that permit silent modification of shipped artifacts are ranked highest.
