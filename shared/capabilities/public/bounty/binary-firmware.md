---
id: bounty/binary-firmware
mode: bounty
title: Binary / malware / firmware vulnerability research (authorized)
overlays: [review, impact, memory]
gates: [public_release]
---

> **Method, not inventory.** This card describes how an engagement of this kind
> runs — the steps, the roles that own them, the skills each step draws on, and
> the gates that must clear. It deliberately carries **no liveness, lane or cost
> annotation**: whether a tool works on our machine is not a fact about yours.
> Establish capability locally with a real invocation returning a real result on
> real target code, and see `shared/registries/recommended-toolchain.tsv` for
> what to install by technique class and target class.

## Availability in a fresh clone

A zero-key checkout gets this protocol and its validation metadata as documentation; automated dispatch is `needs_tool`. To make it runnable, install and authenticate the selected model CLI, configure every MCP declared by the dispatched specialists, bind the private vault (`CHRONO_VAULT_ROOT`; Kimi also requires its exact vault context), install any required host-local binaries, and provide approved credentials plus a bounded budget for any metered provider named below. After setup, re-run the production role planner and validators on that host; availability remains subject to the narrower gaps and operator gates documented in this card.

**When to use:** authorized research against a binary, malware sample, or firmware image. Heightened-risk,
isolation-required. **Currently `needs_tool`** — static inspection is live through radare2, but unpacking,
emulation, host-executable debugging, and malware-grade isolation are not all available. Unknown-sample execution
requires verified isolation; outputs are analytical evidence, never weaponized derivatives.

| Step | Specialists | Tools `` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` | `sandbox-provision-discipline` | memory overlay (recall); target authorization + isolation precheck |
| **S1** Frame (target intel + scope) | `scout`, `research` | `chrono-recon`, `perplexity_search`, `codex --search`, `Brave Search`, `Serper`, `Google Search grounding` | `audit-context-prep`, `program-rubric-lookup`, `dedup-prior-art-check` | operator target-engage gate; **prior-art/dedup runs BEFORE effort** (`dedup-prior-art-check` — CVE/advisory DBs + `chrono-dedup`); `Google Search grounding` = CVE/advisory source-fact grounding, not a substitute for the RE analysis |
| **S2** Design (analysis plan + isolation) | `threat-modeler`, `reverse-engineer`, `experimental-attacker` | `chrono-vault` | `systematic-attacking`, `attack-coverage-map`, `sandbox-provision-discipline` | isolation required (operator-provisioned); governing method: this card is the binary/firmware domain branch of `systematic-attacking` (Phase 2 attack-surface + impact model); **impact-class first** — pre-register HIGH/CRIT termini in the payout classes; **dedicated novel-attack ideation pass every engagement** (Phase 2b) — `experimental-attacker` (kimi) generates broad/novel hypotheses (leads only) fanning out to heavy-hitter (Sol / Opus 5) validation; push past known + known-advisory classes, full-arsenal distance is the FLOOR; leads re-enter the verification spine, never ship unproven |
| **S3** Produce (static RE / unpack / dynamic) | `reverse-engineer`, `exploit-developer` | `radare2`, `ghidra`, `binwalk`, `qemu`, `osv-scanner`, `codex --sandbox`, `claude --worktree` | `data-flow-trace` | static inspection may use radare2; unpacking/emulation remain blocked; heightened-risk; **admission-enforced declaration holds: `offensive_execution` / `malware_detonation`**; admission authenticates declarations but does not remove underlying tool capability or add action-time enforcement; no out-of-scope execution; workspace controls do NOT satisfy malware-grade isolation; **exhaustive-arsenal every engagement** — the standard is to CLOSE the gap, not skip: symbolic (`angr`) + multi-fuzzer (AFL++/honggfuzz/libfuzzer) + unpack/emulate (`binwalk`/`qemu`/`ghidra`) run as Linux builds inside an operator-provisioned isolated container (colima/docker present), never marked "couldn't run" |
| **S4** Verify (impact + repro in isolation) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `gdb` | `systematic-attacking`, `multi-agent-evidence-gating`, `evidence-chain-preservation` | offline parsing only; host target execution failed; impact G1–G4 overlay; **evidence-gate to ≥0.85 confidence** (`multi-agent-evidence-gating`) inside isolation before a candidate reaches the operator / heavy-hitter lane; repro only inside an operator-provisioned isolated environment; runs `systematic-attacking`'s Phase 4 chaining (chain-strike v2) → Phase 6 impact-bar spine |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review`, `claude --from-pr` | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` | `citation-audit`, `evidence-chain-preservation` | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` | `evidence-chain-preservation` | memory overlay (record; `restricted` sensitivity) |

**Notes.** Derived state remains `needs_tool`: radare2 makes the static-inspection slice live, but the broad
S3/S4 contract still lacks a verified unpacker, emulator, executable debugger path, and malware-grade isolation.
`osv-scanner` covers firmware dependency / known-CVE scanning today. The `offensive_execution` /
`malware_detonation` gates named for
`reverse-engineer` / `exploit-developer` are enforced at worker admission: the supervisor denies an
authenticated declaration whose `action_scope` includes either held category. Admission authenticates
declarations; it does not remove underlying tool capability or provide a per-action gate. Safety-refusal invariant applies; a
genuine refusal surfaces and is never cross-family re-dispatched.

**Depth standard (operator).** Full-arsenal distance is the FLOOR, not the ceiling — and here the arsenal is the
gap. `radare2` covers static disassembly and `gdb` offline parsing, but the
load-bearing depth tools are absent from the enforced registry and host PATH: **symbolic execution** (`angr`),
**multiple fuzzers** (AFL++, honggfuzz, libFuzzer), and **unpack/emulate** (`binwalk`, `qemu`, `ghidra`). The
operator standard is to CLOSE the macOS→Linux gap — install and run those as Linux builds inside an
operator-provisioned isolated container (colima + docker present) — never to accept "couldn't run"; that container
also supplies the malware-grade isolation workspace controls do not. Each engagement additionally runs a
**dedicated novel/innovative-attack ideation pass** past known + known-advisory classes (leads re-enter
`systematic-attacking`'s verification spine, never ship unproven). Go **beyond commodity tools+chaining**
(AI+SAST is table stakes): custom detector queries, purpose-built fuzz/symbolic harnesses, patch-diff N-day
analysis, and dynamic weaponization inside isolation. Impact-bar discipline holds — only intrinsic-impact
deterministic findings convert; reachability/disclosure never pays; never resubmit a
non-reproducible finding. These depth gaps are exactly why the derived state stays `needs_tool` until the
container arsenal is provisioned and registry-verified.

**Impact-class targeting (operator).** S2 pre-registers termini only in the payout classes — **RCE/
memory-corruption · auth-bypass · privilege-escalation**. Reachability/crash-without-control is at most a
lead. `experimental-attacker` runs the novel-attack ideation pass as **leads
only** at S2/S3, fanning out to heavy-hitter (Sol / Opus 5) validation and gated to ≥0.85 confidence by
`multi-agent-evidence-gating` at S4 — inside operator-provisioned isolation, no laxer bar than known-class
hypotheses (`systematic-attacking` Phase 3b).

**Elite tooling — prose/`needs_tool` (not live tuples).** Beyond the absent `angr`/AFL++/`binwalk`/`qemu`/
`ghidra` container arsenal already noted, two corpus-C LLM-driven harnessing methodologies are a noted
follow-up skill set: `state-machine-fuzz-harnessing` (SynapseFlow — structural-flow-graph + function-triplet
harness synthesis) and `firmware-rehosting-recovery` (FirmPilot — multi-agent NVRAM/boot-script/network
reconstruction for QEMU rehosting). Both are authored later and run only inside the operator-provisioned
Linux container; neither carries a live tuple.
