# known-advisory-backport-check

For any target that **forks** or **pins** a dependency (a forked cosmos/evm, an old cosmos-sdk/cometbft, a vendored library): known upstream vulnerabilities the target failed to patch are reachable, low-effort findings. Run this early — it's the cheapest high-value pass and it's what the 52-competitor crowd's `osv-scan` finds first.

## Steps
1. **Enumerate pinned versions.** Read `go.mod`/`Cargo.toml`/`package.json` including `replace`/`=>` directives (the replace wins — audit the ACTUAL resolved version, e.g. `cosmos/evm => pushchain/evm v1.0.0-rc2...`).
2. **Pull the advisory set.** `osv-scanner --lockfile <lock>` for the dep graph; `gh api repos/<upstream>/security-advisories` for published GHSAs; the upstream `SECURITY.md` / release notes / advisory index (Hacken, Cosmos ASA, etc.).
3. **For each Critical/High advisory:** get `affected` + `first_patched_version` (`gh api /advisories/<GHSA>`), compare to the pinned version. Behind the fix = candidate.
4. **Reachability + config.** Is the vulnerable module/function actually WIRED and reachable at no privilege in THIS target's config? (e.g. is `x/group` registered + in EndBlock? is the ICS20 precompile activated? is the affected code path called?) A vuln in an unused code path doesn't pay.
5. **Fork-diff for missing backports.** If it's a fork of a release-candidate (`-rcN`) or a frozen branch, the upstream may have shipped a security fix AFTER the fork point. Diff the fork vs upstream for the fix's presence — a code-pattern fix (e.g. a snapshot/journal wrap, a signer check) can be silently dropped in a merge even when the version looks recent. Confirm the guard is present at the pinned commit.

## The scope/dedup reality (be honest — protect the rep)
- Known public CVEs are usually **dedup-dead** and often ruled **"known / out-of-scope / third-party"** — `osv-scan` is the crowd's first move. Do NOT submit a stock reachable-CVE as-is expecting payment; it's a near-certain rejection + rep penalty.
- **What DOES convert:** (a) a fix that is genuinely MISSING/INCOMPLETE in the fork at the pinned commit (novel to this deployment), or (b) a Push-/target-SPECIFIC elevation where custom code makes the generic bug reachable/impactful in a way the advisory didn't cover. Novelty + a runnable PoC is the bar.
- Either way: **report the reachable-known ones to the project as free remediation** (goodwill), and only SUBMIT the novel/incomplete-fix ones. Feed the decision to `impact-validator` (G3 dedup, G4 scope). Related: [[chain-impact-rescore]].
