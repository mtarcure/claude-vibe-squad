---
id: bounty/binary-firmware
mode: bounty
title: Binary / malware / firmware vulnerability research (authorized)
capability_state: needs_tool
state_reason: Static reverse engineering is now genuinely available through registry-verified `radare2` (`local·yes`), and GDB is installed for offline binary parsing (`local·partial`). The broad binary/firmware contract still requires unpacking, emulation/dynamic reproduction, and malware-grade isolation: `binwalk` and `qemu` are absent (`ghidra` is now installed, 2026-07-26 Wave 3); GDB target execution failed its host smoke; workspace sandboxes are not malware containment. Those load-bearing gaps keep the derived state honestly `needs_tool`. The offensive/detonation gate is runtime-metadata-only, NOT machine-enforced.
state_evidence: 2026-07-21 probes — `radare2 6.1.4` analyzed `/bin/ls` read-only and identified Mach-O ARM64 metadata; `gdb 17.1` parsed a thin Mach-O but `start` returned `Don't know how to run`; `command -v` found no binwalk/qemu variants (`ghidra` installed 2026-07-26, Wave 3). Registry rows now encode `radare2=local·yes·—`, `gdb=local·partial·—`, `ghidra=codex·yes·—`, and the two genuine absences (binwalk/qemu) as `none·no·—`. `osv-scanner` remains `local·yes·—`; `sandbox-provision-discipline` is invokable. Unknown-sample execution still requires operator-provisioned isolation.
overlays: [review, impact, memory]
gates: [public_release]
cost_note: `radare2`, GDB, `osv-scanner`, and the absence probes are free-local (cost `—`); chrono-* MCPs are subscription. The S1 OSINT passthrough (`perplexity_search_web`, `Brave Search`, `Serper`) is `metered` and needs a budget/rate-limit guard; `Google Search grounding` (gemini) is subscription-tier. Missing unpacking/emulation plus unverified debugger execution keep the broad route at `needs_tool`. Sample handling requires an operator-provisioned isolated environment.
---

**When to use:** authorized research against a binary, malware sample, or firmware image. Heightened-risk,
isolation-required. **Currently `needs_tool`** — static inspection is live through radare2, but unpacking,
emulation, host-executable debugging, and malware-grade isolation are not all available. Unknown-sample execution
requires verified isolation; outputs are analytical evidence, never weaponized derivatives.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | `sandbox-provision-discipline` (SKILL.md) | memory overlay (recall); target authorization + isolation precheck |
| **S1** Frame (target intel + scope) | `scout`, `research` | `chrono-recon` (all · yes · subscription), `perplexity_search_web` (claude · lane-live · metered), `codex --search` (codex · yes · subscription), `Brave Search` (codex · yes · metered), `Serper` (codex · yes · metered), `Google Search grounding` (gemini · yes · subscription) | `audit-context-prep` (stub), `program-rubric-lookup` (authored), `dedup-prior-art-check` (authored) | operator target-engage gate; **prior-art/dedup runs BEFORE effort** (`dedup-prior-art-check` — CVE/advisory DBs + `chrono-dedup`); `Google Search grounding` = CVE/advisory source-fact grounding, not a substitute for the RE analysis |
| **S2** Design (analysis plan + isolation) | `threat-modeler`, `reverse-engineer`, `experimental-attacker` | `chrono-vault` (all · yes · subscription) | `systematic-attacking` (authored), `attack-coverage-map` (authored), `sandbox-provision-discipline` (SKILL.md) | isolation required (operator-provisioned); governing method: this card is the binary/firmware domain branch of `systematic-attacking` (Phase 2 attack-surface + impact model); **impact-class first** — pre-register HIGH/CRIT termini in the payout classes (RCE/memory-corruption · auth-bypass · privilege-escalation); **dedicated novel-attack ideation pass every engagement** (Phase 2b) — `experimental-attacker` (kimi) generates broad/novel hypotheses (leads only) fanning out to heavy-hitter (Sol / Opus 5) validation; push past known + known-advisory classes, full-arsenal distance is the FLOOR; leads re-enter the verification spine, never ship unproven |
| **S3** Produce (static RE / unpack / dynamic) | `reverse-engineer`, `exploit-developer` | `radare2` (local · yes · —), `ghidra` (codex · yes · —), `binwalk` (none · no · —), `qemu` (none · no · —), `osv-scanner` (local · yes · —), `codex --sandbox` (codex · yes · subscription), `claude --worktree` (claude · yes · subscription) | `data-flow-trace` (authored) | static inspection may use radare2; unpacking/emulation remain blocked; heightened-risk; **manual hold: `offensive_execution` / `malware_detonation` (NOT machine-enforced)**; no out-of-scope execution; workspace controls do NOT satisfy malware-grade isolation; **exhaustive-arsenal every engagement** — the standard is to CLOSE the gap, not skip: symbolic (`angr`) + multi-fuzzer (AFL++/honggfuzz/libfuzzer) + unpack/emulate (`binwalk`/`qemu`/`ghidra`) run as Linux builds inside an operator-provisioned isolated container (colima/docker present), never marked "couldn't run" |
| **S4** Verify (impact + repro in isolation) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `gdb` (local · partial · —) | `systematic-attacking` (authored), `multi-agent-evidence-gating` (authored), `evidence-chain-preservation` (stub) | offline parsing only; host target execution failed; impact G1–G4 overlay; **evidence-gate to ≥0.85 confidence** (`multi-agent-evidence-gating`) inside isolation before a candidate reaches the operator / heavy-hitter lane; repro only inside an operator-provisioned isolated environment; runs `systematic-attacking`'s Phase 4 chaining (chain-strike v2) → Phase 6 impact-bar spine |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored), `evidence-chain-preservation` (stub) | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record; `restricted` sensitivity) |

**Notes.** Derived state remains `needs_tool`: radare2 makes the static-inspection slice live, but the broad
S3/S4 contract still lacks a verified unpacker, emulator, executable debugger path, and malware-grade isolation.
`osv-scanner` covers firmware dependency / known-CVE scanning today. The `offensive_execution` /
`malware_detonation` gates named for
`reverse-engineer` / `exploit-developer` are **manual hard holds** — present in runtime metadata but not in
the machine `operator_gate` enum, so do not claim machine enforcement. Safety-refusal invariant applies; a
genuine refusal surfaces and is never cross-family re-dispatched.

**Depth standard (operator).** Full-arsenal distance is the FLOOR, not the ceiling — and here the arsenal is the
gap. `radare2` (`local·yes`) covers static disassembly and `gdb` (`local·partial`) offline parsing, but the
load-bearing depth tools are absent from the enforced registry and host PATH: **symbolic execution** (`angr`),
**multiple fuzzers** (AFL++, honggfuzz, libFuzzer), and **unpack/emulate** (`binwalk`, `qemu`, `ghidra`). The
operator standard is to CLOSE the macOS→Linux gap — install and run those as Linux builds inside an
operator-provisioned isolated container (colima + docker present) — never to accept "couldn't run"; that container
also supplies the malware-grade isolation workspace controls do not. Each engagement additionally runs a
**dedicated novel/innovative-attack ideation pass** past known + known-advisory classes (leads re-enter
`systematic-attacking`'s verification spine, never ship unproven). The moat is **beyond commodity tools+chaining**
(AI+SAST is table stakes): custom detector queries, purpose-built fuzz/symbolic harnesses, patch-diff N-day
analysis, and dynamic weaponization inside isolation. Impact-bar discipline holds — only intrinsic-impact
deterministic findings convert (~1/21 lifetime); reachability/disclosure never pays; never resubmit a
non-reproducible finding. These depth gaps are exactly why the derived state stays `needs_tool` until the
container arsenal is provisioned and registry-verified.

**Impact-class targeting (operator).** S2 pre-registers termini only in the payout classes — **RCE/
memory-corruption · auth-bypass · privilege-escalation**. Reachability/crash-without-control is at most a
lead. `experimental-attacker` (kimi `primary_exception`) runs the novel-attack ideation pass as **leads
only** at S2/S3, fanning out to heavy-hitter (Sol / Opus 5) validation and gated to ≥0.85 confidence by
`multi-agent-evidence-gating` at S4 — inside operator-provisioned isolation, no laxer bar than known-class
hypotheses (`systematic-attacking` Phase 3b).

**Elite tooling — prose/`needs_tool` (not live tuples).** Beyond the absent `angr`/AFL++/`binwalk`/`qemu`/
`ghidra` container arsenal already noted, two corpus-C LLM-driven harnessing methodologies are a noted
follow-up skill set: `state-machine-fuzz-harnessing` (SynapseFlow — structural-flow-graph + function-triplet
harness synthesis) and `firmware-rehosting-recovery` (FirmPilot — multi-agent NVRAM/boot-script/network
reconstruction for QEMU rehosting). Both are authored later and run only inside the operator-provisioned
Linux container; neither carries a live tuple.
