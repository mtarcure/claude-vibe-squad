# Security arsenal guide

Checked 2026-07-18. Commands below are starting points, not authorization: use active scanners, fuzzers, RPC calls, and exploit helpers only against assets explicitly covered by the current program rules. Start read-only, pin a block or local fixture, cap concurrency, and retain the command/output log.

## Smart-contract audit

| Tool | What it is / when to reach for it | Exact starting command |
|---|---|---|
| `forge` | Foundry build/test runner; start here for unit tests, invariant tests, and executable PoCs. | `forge test -vvv` |
| `cast` | RPC and ABI utility; use it to read state or encode/decode calldata before writing a PoC. | `cast call "$TARGET" "$FUNCTION_SIG" --rpc-url "$RPC_URL"` |
| `anvil` | Local EVM; use a pinned fork for deterministic reproduction. | `anvil --fork-url "$RPC_URL" --fork-block-number "$BLOCK_NUMBER"` |
| `chisel` | Solidity REPL; use it for a quick arithmetic or ABI experiment. | `chisel` |
| `slither` | Fast static analyzer; run before manual review to inventory common Solidity patterns. | `slither .` |
| `myth` (Mythril) | Symbolic EVM analyzer; use after static triage to test whether a suspicious path is reachable. | `myth analyze contracts/Target.sol` |
| `echidna` | Stateful property fuzzer; use when you can express the security claim as a Solidity property. | `echidna test/TargetEchidna.sol` |
| `medusa` | Parallel coverage-guided Solidity fuzzer; use alongside Echidna to diversify state exploration. | `medusa fuzz` |
| `halmos` | Symbolic Foundry-test runner; use when bounded proof is more useful than additional random inputs. | `halmos --root .` |
| `aderyn` | Fast Rust static analyzer; use for a low-friction first sweep and SARIF/Markdown handoff. | `aderyn .` |
| ItyFuzz container | Hybrid EVM/MoveVM fuzzer. The pinned image is verified, but this Mac has no supported native release; begin by confirming the image, then build a campaign-specific layer containing Foundry or the required artifacts. | `docker run --platform linux/amd64 --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 512m --cpus 1 vibe-ityfuzz:nightly-35b7f089 --version` |

Recommended sequence: `forge test` → `aderyn .` and `slither .` → targeted `myth`/`halmos` → invariant campaign with `echidna` plus `medusa`. Add ItyFuzz after its campaign image has the target's exact compiler/Foundry dependencies; its current verified image is not evidence that a project campaign has run.

## OSINT, recon, code, and web security

### Passive and low-impact discovery

| Tool | What it is / when to reach for it | Exact starting command |
|---|---|---|
| `chrono-recon` MCP | Shared passive DNS, WHOIS, crt.sh, Wayback, and GitHub leaked-secret search. Prefer it for evidence-backed recon that should be available across lanes. | Call one MCP tool: `dns_enumerate_tool`, `whois_lookup_tool`, `crt_sh_certificates_tool`, `wayback_snapshots_tool`, or `github_leaked_secrets_tool` (the last requires the lane's approved `GH_TOKEN`). |
| `subfinder` | Passive subdomain enumeration; use for the first host inventory. | `subfinder -d "$DOMAIN" -silent` |
| `amass` | Deeper attack-surface discovery; use after Subfinder when broader OSINT coverage is worth the time. | `amass enum -passive -d "$DOMAIN"` |
| `dnsx` | DNS validation/enrichment; use to resolve an enumerated host list. | `dnsx -l hosts.txt -silent` |
| `httpx` | Live-host and HTTP metadata probe; use after DNS resolution. | `httpx -l hosts.txt -silent -status-code -title -tech-detect` |
| `katana` | Web crawler; use to map routes on an explicitly in-scope application. | `katana -u "$TARGET_URL" -silent` |
| `gau` | Historical URL collector; use to find old endpoints and parameters. | `gau "$DOMAIN"` |
| `waybackurls` | Focused Wayback URL collector; use when only archive-backed URLs are needed. | `printf '%s\n' "$DOMAIN" | "$HOME/go/bin/waybackurls"` |
| `naabu` | Port scanner; use only where the program permits active port discovery and rate limits. | `naabu -host "$TARGET" -rate 50` |
| `nuclei` | Template scanner; use only after confirming template classes and target scope. | `nuclei -u "$TARGET_URL" -severity low,medium,high,critical -rate-limit 5` |
| `ffuf` | Content/parameter fuzzer; use for a narrow wordlist-driven hypothesis, not indiscriminate crawling. | `ffuf -u "$TARGET_URL/FUZZ" -w wordlist.txt -rate 5` |
| `interactsh-client` | Out-of-band callback listener; use to prove blind SSRF/RCE impact where callbacks are allowed. | `"$HOME/go/bin/interactsh-client"` |

### Source, dependency, secret, and active checks

| Tool | What it is / when to reach for it | Exact starting command |
|---|---|---|
| `semgrep` | Pattern-based SAST; run local rules first. The same binary also contains an MCP server, but no lane wiring was changed. | `semgrep scan --config auto .` |
| `osv-scanner` | Dependency vulnerability scanner; use on lockfiles/SBOM-aware repositories. | `osv-scanner scan source -r .` |
| `gitleaks` | Secret detector for working trees and history; use early, and treat findings as sensitive. | `gitleaks git . --redact` |
| `trufflehog` | Secret detector with verification capabilities; use only when live-secret validation is permitted. | `trufflehog filesystem . --no-update` |
| `trivy` | Filesystem, container, dependency, and IaC scanner; use for a broad supply-chain baseline. | `trivy fs .` |
| `nikto` | Noisy web-server scanner; use only on an authorized live target with program-safe tuning. | `nikto -h "$TARGET_URL"` |
| `sqlmap` | High-impact SQLi validation/exploitation tool; use only for a specific in-scope hypothesis and stop before data extraction unless rules allow it. | `sqlmap -u "$TARGET_URL_WITH_PARAMETER" --batch --level=1 --risk=1` |

## LLM and agent security

These candidates were evaluated, not installed or wired. Their model calls can incur provider cost and can transmit prompts/results; use synthetic fixtures and approved keys in an isolated pilot.

| Candidate | Best use | Adoption decision / eventual starting command |
|---|---|---|
| Promptfoo | Repeatable LLM evals, red-team probes, and CI regression tests; useful both for bounty targets and swarm defense. | Highest-priority pilot. Community CLI is MIT and free within its documented limits: `npx promptfoo@latest init`. |
| garak | Broad CLI vulnerability scan of a model endpoint; best for a quick bounty or release baseline. | High-priority pilot in an isolated Python environment: `python -m pip install -U garak`, then `garak --list_probes`. |
| PyRIT | Programmable multi-turn attacks, converters, scorers, and target orchestration; best for deeper specialist campaigns. | Second-stage pilot after Promptfoo/garak; use a pinned virtual environment following the official PyRIT docs. |
| PentestGPT | Autonomous/interactive pentest orchestration over existing tools. | Do not wire globally. Pilot only in a dedicated lab with telemetry disabled: clone, `make install`, then `LANGFUSE_ENABLED=false pentestgpt --list-sessions`. |
| HexStrike AI | MCP-to-offensive-tool orchestration with a very large command surface. | Do not wire globally. If reviewed, run its API and MCP adapter in a dedicated network-restricted security VM; never accept its self-reported benchmark numbers as local evidence. |
| Semgrep MCP | Structured local SAST tools supplied by the installed Semgrep binary. | Best MCP pilot: stdio command `/opt/homebrew/bin/semgrep mcp`; mount the repo read-only, omit cloud tokens, and log calls. |
| FuzzingLabs `medusa-mcp` | MCP wrapper around Medusa, which is already installed. | Low incremental value; pilot only if orchestration improves a measured workflow. Do not deploy the full MCP hub. |
| E2B | Hosted Firecracker sandboxes for untrusted agent code. | Defensive infrastructure, not a scanner. Requires an account/API key and usage spend; evaluate separately from the local sandbox policy. |
| RIFT-Bench | June 2026 agent red-team research benchmark. | Research lead only: the cited arXiv preprint exists, but the named Fujitsu GitHub repository was empty on 2026-07-18. |
| AgentFuzz | Research implementation for taint-style agent vulnerabilities. | Research lead only: reproducibility is heavy, there is no repository license or release, and it requires CodeQL, two old Python environments, instrumentation, and an LLM key. |

### Installed local pilots (no provider campaigns)

| Tool | What it is / when to reach for it | Exact command |
|---|---|---|
| Promptfoo 0.121.19 | Repeatable synthetic prompt/eval regression harness. Reach for it after defining approved fixtures and provider/data-flow limits. | `_state/tooling-arsenal-2026-07-18/tools/promptfoo/node_modules/.bin/promptfoo --version` |
| garak 0.15.1 | Broad LLM vulnerability scanner. Use only for an explicitly authorized target/provider baseline. | `_state/tooling-arsenal-2026-07-18/tools/garak/bin/garak --list_probes` |
| PyRIT 0.14.0 | Programmable multi-turn risk-identification framework. Use after simpler evals justify a reviewed scenario. | `_state/tooling-arsenal-2026-07-18/tools/pyrit/bin/python -c 'import pyrit; print(pyrit.__version__)'` |
| Snyk Agent Scan 0.5.15 (`mcp-scan` lineage) | Inventory/scan agent components. Current verification requires Snyk authorization and may transmit component metadata; it is not an MCP stdio proxy. | `_state/tooling-arsenal-2026-07-18/tools/mcp-scan/bin/snyk-agent-scan --help` |
| LlamaFirewall 1.0.3 | Self-hostable scanner framework. Package/CLI is installed, but model-backed PromptGuard/AlignmentCheck enforcement is not configured. | `_state/tooling-arsenal-2026-07-18/tools/llamafirewall/bin/llamafirewall --help` |

Do not run Promptfoo, garak, or PyRIT against a provider merely because the CLI exists. A campaign needs target authorization, prompt/data-flow review, provider credentials, and a spend ceiling. Do not run Snyk Agent Scan over MCP configs without reviewing each command: scanning starts configured stdio servers.

## Smart-contract pilots added 2026-07-18

| Tool | What it is / when to reach for it | Exact command |
|---|---|---|
| Heimdall-rs | Pinned macOS/arm64 bytecode disassembler/decompiler. Reach for it when verified Solidity source is unavailable. | `_state/tooling-arsenal-2026-07-18/bin/heimdall decompile --help` |
| Kontrol | Formal verification from Foundry tests. | Not installed: pinned `kup` cannot start without Nix; provision only in a separate disk-budgeted pilot. |

The official Heimdall release asset checksum matched, but its `0.9.3` asset prints `heimdall 0.9.2`; preserve that provenance caveat in evidence. Never use its unencrypted-HTTP bootstrap. Kontrol's official route has no release binary and documents a 30–60 minute Nix/kup build, so the failed prerequisite is an honest capability gap rather than a host-level Nix mutation.

## Restart-gated security MCP stack

Claude and gpt-codex have non-live staged files at `model-lanes/claude/.mcp.security-arsenal.staged.json` and `model-lanes/gpt-codex/.codex/security-arsenal.staged.toml`. Both put Trail of Bits `mcp-context-protector` in front of:

1. `/opt/homebrew/bin/semgrep mcp` with the cloud token explicitly empty.
2. The pinned `slither-mcp` entry point with metrics disabled.

Run `python3 plugins/security-mcp-stack/validate_staged.py` first. Then, during the reviewed cutover, use Snyk Agent Scan only after approving its credential/data-flow terms and manually approving each known downstream command. Review/pin Context Protector's tool schemas, merge the staged snippets into the active provider configs, and perform the one coordinated lane restart. Post-restart, require `tools/list`, a read-only synthetic fixture smoke, context-protector pin enforcement, and host tool-call logs before declaring either server live.

`solodit-mcp` built from a pinned commit but is held in `plugins/security-mcp-stack/held-solodit.json`: upstream requires `SOLODIT_API_KEY`, and its install-time dependency audit returned eight high and five moderate advisories. Do not merge it until credential authorization, advisory remediation/review, and Claude approval. LlamaFirewall is also not inline yet; model download/license and AlignmentCheck provider data flow need separate approval.

## Planned only

- **HexStrike AI:** dedicated allowlisted VM only; loopback bind, deny-by-default egress, exact target/CIDR allowlist, zero ambient credentials, narrow tool allowlist, CPU/memory/process/time limits, immutable base image, action log, and per-active-call operator approval. Do not install or wire on the host.
- **Google Model Armor:** separate GCP procurement task covering account/project, API enablement, key/service-account custody, region/data retention, free-tier/overage ceiling, synthetic prompt smoke, and rollback. No key was created here.
- **E2B:** separate procurement/privacy decision for hosted metered sandboxes, including account, API key, data residency, spend cap, egress policy, retention, and a containment denial test. No SDK/account was installed or created here.

The authoritative installed versions and verification commands remain in `shared/api-catalog.md` §12. Staged files are deliberately not active runtime config and Gemini/Kimi remain deferred.
