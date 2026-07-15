# The moat — a self-improving, leak-safe security-research engine

**AI that runs scanners is a commodity. The edge is accumulated, executable target-memory** — invariants, corpora, and impact oracles that make each engagement start ahead of the last. `moat/` is the reusable, public-safe **"harness bones"** for exactly that: a research engine whose value compounds instead of resetting to zero every time.

It does three honest things well:

1. **Finds better variants** — turns a fixed vulnerability into an executable invariant and hunts the sibling code the fix didn't cover.
2. **Proves or refutes impact** — stands a candidate up against a real, isolated deployment and returns an objective, evidence-referenced verdict.
3. **Compounds** — checks what's already known *before* a deep-dive, so effort never repeats itself.

> **What it is not.** This is not a "critical-producing machine," and it doesn't claim to be. It raises the quality of variant discovery, it *measures* impact instead of asserting it, and it remembers. A clean, coverage-complete **FAIL** is a first-class, honest outcome — the point is a trustworthy verdict, not a guaranteed finding. That honesty is the feature.

Everything in this directory is **Layer 1**: generic, framework-agnostic, and safe to publish. It contains **no** engagement findings, target identifiers, payloads, or private corpora — by construction and by an enforced, fail-closed boundary (below). The engine works on **JavaScript/TypeScript and smart-contract codebases**; nothing here is specific to any target or program.

---

## Architecture

### Two layers, one hard boundary

| Layer | Contents | Where it lives |
|------|----------|----------------|
| **Layer 1 (this repo)** | The generic engine: schemas, boundary scanners, the ledger client, the patch-graph, the measurement pipeline, and the isolation runner. | Public, here in `moat/`. |
| **Layer 2 (never here)** | Target-specific invariants, corpora, fixtures, advisories, findings, and verdicts. | Private only — behind `$CHRONO_BOUNTY_ROOT` and the off-repo vault. |

Layer-1 code touches target data only through a single external-input adapter, addressed by logical `fixture:` / `manifest:` / `descriptor:` references and resolved beneath `$CHRONO_BOUNTY_ROOT` with **both lexical and realpath containment** — a symlink can't redirect a read outside that root.

### The leak boundary — three fail-closed controls

Keeping private target data out of a public repo is the whole ballgame, so it's defended in depth. Each control has a distinct error namespace and none weakens another:

1. **Presence guard** *(shipped repo-wide leak guard)* — blocks restricted files and private paths from being committed at all.
2. **Tier-A — capability & provenance** *(public, data-free)* — parses JS/TS/TSX with the TypeScript compiler API, folds bounded constant expressions, and flags private-capability imports, values that flow into network/process/filesystem **sinks**, schema/path/content-class violations, and credential-shaped material (via `gitleaks`, fail-closed). It **fails closed** when a sink receives a value the evaluator can't prove constant, and emits `MOAT_BOUNDARY_TOOL_UNAVAILABLE` rather than crashing if its parser or scanner is missing.
3. **Tier-B — exact private targets** *(private pre-push + mandatory CI)* — loads a restricted denylist through the external-input adapter (never committed) and matches exact hostnames, repositories, advisory IDs, and paths against Layer-1 file text, AST-evaluated strings, and base64/base64url-decoded strings. It reports only class, file, and line — **never** the matched token — and **fails closed** when its denylist is unavailable or malformed.

The public pre-commit path stays data-free; exact-target matching is deliberately private. Composable one-line hook wirings are documented in [`boundary/README.md`](boundary/README.md) and intentionally left un-applied for the operator to gate.

### The self-improving ledger

Before any deep-dive, the ledger asks: *have we already seen this?* It queries the squad's private markdown memory through a bridge to the real vault recall implementation (FTS5/BM25) and returns a conservative classification:

- **`prior_kill`** only on a reviewer-confirmed hit, or an automatic hit that clears a score threshold **and** carries a structured target/attack-class/component filter;
- **`needs_review`** for weaker hits;
- **`net_new`** only after an error-free, genuinely empty search **at effective `restricted` clearance** — because an empty *clearance-blind* search is not evidence of an empty vault.

Clearance is enforced at three independent points (adapter, bridge, and ledger), and every failure mode — unset root, insufficient clearance, query error, malformed output — resolves to a non-clean state, **never** silently to `net_new`. This is what lets a "no prior work" result actually be trusted, and it plugs the engine directly into the squad's `record → recall → apply` learning loop.

### The patch-graph / N-day engine

Incomplete fixes are net-new by construction. The patch-graph turns a shipped fix into a variant hunt:

```
full-history mirror ─▶ ingest a manual fix ref + commit
                    ─▶ confidence-scored GuardCandidate   (heuristic; tree-sitter/difftastic signals)
                    ─▶ human-reviewed GuardAnnotation      (authoritative — a candidate can never emit an invariant)
                    ─▶ canonical InvariantDescriptor + a generated, drift-checked index
                    ─▶ syntactic sibling search            (returns sink-reaching sites the guard doesn't cover)
```

The reviewed annotation is the source of truth: automated extraction only ever *proposes* candidates, and the schema refuses to emit an invariant from anything that isn't human-reviewed.

### Objective impact measurement — `WaveResult`

A "wave" measures a candidate against a real deployment and returns one of **`PASS` / `FAIL` / `INCONCLUSIVE`** — never a vibe. The verdict is schema-validated and every claim carries an evidence reference. A result can only read:

- **`PASS`** — the calibration (known-vulnerable) control fires, the negative (patched) control stays clean, coverage saturates, every declared transition and guard branch is exercised, shrinking is deterministic, the finding is `net_new`, and an independent reviewer confirms intrinsic impact and novelty;
- **`FAIL`** — the campaign is coverage-complete and no candidate reaches default-reachable impact (each recorded with a kill reason);
- **`INCONCLUSIVE`** — any completeness requirement is missing. A null result can't masquerade as a clean FAIL.

The shipped pipeline exercises this whole path end-to-end against a **synthetic twin app** (a known-vulnerable build vs. its patched counterpart) driven by property-based request-state fuzzing (`fast-check`) with V8 coverage accounting; real targets enter only through Layer 2. Coverage-guided fuzzing (`Jazzer.js`) is a **conditional escalation** — invoked only to resolve an `INCONCLUSIVE` slice, never as an always-on platform.

### Isolated execution — no-egress, canary-gated

Impact runs happen inside a VM-backed container (`macOS → Colima/Lima/Docker Desktop → Linux`) launched `--network none` with hardening: non-root, read-only rootfs, all capabilities dropped, `no-new-privileges`, pids/memory/CPU/file-size limits, `noexec` tmpfs, and cleared proxy environment. Before the target runs, a **pre-flight canary** must pass: the loopback control has to succeed while every external class — IPv4, IPv6, DNS, proxy-environment, host-gateway, and TCP/TLS — is confirmed **blocked**. Any unexpected external success aborts the run. No canary, no execution.

### Hostile test doubles (held private)

Adversarial capability testing uses framework-agnostic hostile server doubles (e.g. redirect/rebinding and provider doubles) that run only inside a canary-passed, network-`none` lab. The concrete hostile implementations are operator-gated and kept **private** — they are not part of this public repository; the lab loads them from a private location when configured.

---

## How the pieces compose

```
ledger.check ──(net_new?)──▶ patch-graph ──▶ reviewed invariant ──▶ differential harness
                                                                          │
                                             isolated, canary-gated wave ─┘
                                                                          ▼
                                                     signed WaveResult (PASS / FAIL / INCONCLUSIVE)
```

1. **Ask memory first.** `ledger.check` decides whether the surface is already known, needs review, or is genuinely new.
2. **Derive an invariant.** The patch-graph proposes candidates from a fix; a human reviews one into an authoritative annotation and invariant.
3. **Differentiate.** A harness runs the candidate against known-vulnerable and patched builds with property-based inputs and coverage accounting.
4. **Measure under isolation.** A canary-gated, no-egress wave produces an evidence-referenced verdict.

---

## Security & safety posture

- **Fail-closed everywhere.** Unresolvable sink flows, unavailable tools, missing clearance, and unavailable/malformed denylists all block rather than pass silently.
- **Least privilege for memory.** Recall runs only at explicit `restricted` clearance; a clearance-blind empty result can never be read as "nothing known."
- **Isolation is proven, not assumed.** Every impact run is gated on a passing egress canary; hostile doubles refuse to run outside it.
- **Untrusted data stays quoted.** Vault snippets and external content are handled as untrusted throughout; no matched private token is ever echoed into output.
- **The boundary is testable and composable.** Tier-A is enforcement-ready as a data-free public check; Tier-B belongs in private pre-push/CI. Hook compositions are documented and left for the operator to wire.

---

## Run it

```sh
cd moat
npm ci            # installs the pinned TypeScript parser used by Tier-A
npm test          # 88/88

node boundary/tier-a.mjs --self-check                 # public Layer-1 boundary self-check
node boundary/tier-a.mjs --staged <file>...           # scan an explicit staged list
```

## Layout

```
boundary/    Tier-A (capability/provenance AST) + Tier-B (exact private targets) + policy
schemas/     InvariantDescriptor · GuardAnnotation · Verdict · WaveResult (+ a fail-closed validator)
ledger/      the recall bridge client + normalized public-advisory manifest
patchgraph/  fix ingest · guard-candidate extraction · syntactic sibling search
pipeline/    manual slice · invariant index (drift-checked) · WaveResult · synthetic wave
twinlab/     synthetic vulnerable/patched app template + provisioning
oracle/      loopback recorder kit (http, redirects, protected access, actions, egress, guards)
fuzz/        fast-check request-state model · V8 coverage · conditional Jazzer.js escalation
isolation/   VM-backed no-egress container runner + negative-canary suite
adapters/    the single external-input adapter + filesystem/process boundaries
```

**Status:** feature-complete across nine commits, 87/87 tests green. Every security-critical control — the leak boundary, the clearance-gated ledger, the isolation canary — was hardened through adversarial, **cross-family** review (built by one model family, pressure-tested by another).

---

<sub>Built as a durable capability of the Vibe Squad: specified across multiple frontier models and hardened through the squad's own cross-family review discipline, with every dispatch checkpointed in this repository's git history.</sub>
