---
id: bounty/binary-firmware
mode: bounty
title: Binary / malware / firmware vulnerability research (authorized)
capability_state: needs_tool
state_reason: No reverse-engineering toolchain is registry-verified — there is no disassembler, unpacker, debugger, or emulator row (ghidra/radare2/binwalk/gdb/qemu absent; `manticore` is `none·no`). The load-bearing static-RE, unpacking, and dynamic/sandbox steps therefore cite `catalog-absent` probe targets → derived `needs_tool`. Only dependency/known-CVE scanning (`osv-scanner`) and OSINT/memory tools are live. Isolation is required for any sample execution. The offensive/detonation gate is runtime-metadata-only, NOT machine-enforced.
state_evidence: registry — no ghidra/radare2/rizin/binwalk/gdb/objdump/qemu tool row (checked 2026-07-17); `manticore` = `none·no`; `osv-scanner` = `local·yes·—`; `chrono-recon`/`chrono-vault`/`chrono-obsidian` = `all·yes·subscription`. `sandbox-provision-discipline` = invokable `(SKILL.md)`. `offensive_execution`/`malware_detonation` are present in runtime metadata only (enum + validator reconciliation pending) → manual hard hold.
overlays: [review, impact, memory]
gates: [public_release]
cost_note: The one live analysis tool (`osv-scanner`) is free-local (cost `—`); chrono-* MCPs are subscription. The S1 OSINT passthrough (`perplexity_search_web`, `Brave Search`, `Serper`) is `metered` (API-key billed) and needs a budget/rate-limit guard — a hit limit is a typed `needs_tool`/degraded result; `Google Search grounding` (gemini) is subscription-tier, not metered. The load-bearing RE/emulation toolchain is `catalog-absent` (cost `unknown`) → `needs_tool`. Sample handling requires an isolated environment (operator-provisioned).
---

**When to use:** authorized research against a binary, malware sample, or firmware image. Heightened-risk,
isolation-required. **Currently `needs_tool`** — the static-RE / unpack / dynamic-analysis toolchain is not
cataloged; admit only once a disassembler + unpacker + sandboxed emulator are registry-verified. Unknown-sample
execution requires verified isolation; outputs are analytical evidence, never weaponized derivatives.

| Step | Specialists | Tools `(lane · state · cost_tier)` | Skills `(type)` | Gate / Overlay |
|---|---|---|---|---|
| **S0** Intake/Admit | `Chrono` | `chrono-vault` (all · yes · subscription) | `sandbox-provision-discipline` (SKILL.md) | memory overlay (recall); target authorization + isolation precheck |
| **S1** Frame (target intel + scope) | `scout`, `research` | `chrono-recon` (all · yes · subscription), `perplexity_search_web` (claude · lane-live · metered), `codex --search` (codex · yes · subscription), `Brave Search` (codex · yes · metered), `Serper` (codex · yes · metered), `Google Search grounding` (gemini · yes · subscription) | `audit-context-prep` (stub), `program-rubric-lookup` (stub) | operator target-engage gate; `Google Search grounding` = CVE/advisory source-fact grounding, not a substitute for the RE analysis |
| **S2** Design (analysis plan + isolation) | `threat-modeler`, `reverse-engineer` | `chrono-vault` (all · yes · subscription) | `attack-coverage-map` (authored), `sandbox-provision-discipline` (SKILL.md) | isolation required (operator-provisioned) |
| **S3** Produce (static RE / unpack / dynamic) | `reverse-engineer`, `exploit-developer` | `ghidra` (unknown · catalog-absent · unknown), `radare2` (unknown · catalog-absent · unknown), `binwalk` (unknown · catalog-absent · unknown), `qemu` (unknown · catalog-absent · unknown), `osv-scanner` (local · yes · —), `codex --sandbox` (codex · yes · subscription), `claude --worktree` (claude · yes · subscription) | `data-flow-trace` (stub) | heightened-risk; **manual hold: `offensive_execution` / `malware_detonation` (NOT machine-enforced)**; no out-of-scope execution; `codex --sandbox`/`claude --worktree` are workspace/runner controls only — they do NOT satisfy the malware-grade sample-isolation precondition (operator-provisioned isolation still required) |
| **S4** Verify (impact + repro in isolation) | `impact-validator`, `skeptic`, `cross-family-reviewer` | `gdb` (unknown · catalog-absent · unknown) | `evidence-chain-preservation` (stub) | impact G1–G4 overlay; repro only inside the isolated environment |
| **S5** Review/Gate (submission) | `skeptic`, `cross-family-reviewer`, `operator` | `codex review` (codex · yes · subscription), `claude --from-pr` (claude · yes · subscription) | — | review overlay (review tools MECHANICS ONLY — never replace the independent cross-family reviewer); **final Submit = per-report operator "go"** (irreversible) |
| **S6** Ship/Deliver (report) | `technical-writer`, `security-analyst` | `chrono-obsidian` (all · yes · subscription) | `citation-audit` (authored), `evidence-chain-preservation` (stub) | public disclosure gate |
| **S7** Capture | `Chrono`, `memory-curator` | `chrono-vault` (all · yes · subscription) | `evidence-chain-preservation` (stub) | memory overlay (record; `restricted` sensitivity) |

**Notes.** Derived state is `needs_tool`: the S3/S4 RE toolchain (disassembler, unpacker, emulator, debugger)
is named as `catalog-absent` probe targets, not claimed live — cataloging + verifying a real RE toolchain
(and its isolation story) is the precondition for going live. `osv-scanner` covers firmware dependency /
known-CVE scanning today (live). The `offensive_execution` / `malware_detonation` gates named for
`reverse-engineer` / `exploit-developer` are **manual hard holds** — present in runtime metadata but not in
the machine `operator_gate` enum, so do not claim machine enforcement. Safety-refusal invariant applies; a
genuine refusal surfaces and is never cross-family re-dispatched.
