<p align="center">
  <img src="assets/hero/vibe-squad-hero.svg" alt="Vibe Squad — one coordinator (Chrono) routes work across 4 frontier model lanes and 69 role-based specialists" width="900">
</p>

# Vibe Squad

**One request in. The right model, specialist, and review path out.**

Vibe Squad is a markdown-first orchestration system that runs four frontier AI models — **GPT‑5.6 Sol**, **Claude Fable‑5**, **Gemini 3.5**, and **Kimi K2.7** — as live "model lanes" in a single tmux session. You talk to one coordinator, **Chrono**; it turns your request into a scoped, inspectable task packet, routes it to whichever of **69 role‑based specialists** fits best, and sends the risky work to a *different* model family for review before you ever see the result. No servers, no dashboards — the entire dispatch board is plain markdown files on disk.

> **In plain English:** it makes four different AIs behave like one coordinated team, with a built‑in second opinion on anything that matters.
> **Under the hood:** capability‑fit routing over a canonical 69‑row map, typed markdown task packets, bounded write scopes, cross‑family review gates, and a git checkpoint before every dispatch.

It was built *through itself*: the squad's own refactors — including the 69‑specialist redesign described below — were drafted and cross‑reviewed by these model lanes. The `auto-snapshot` commits in this repo's history are the system checkpointing its own work.

---

## Why it's interesting (the two things to notice)

### 1. A *different* model family reviews the risky work

An LLM is the worst judge of its own output — same‑model self‑review reproduces the same blind spots. So every high‑stakes specialist carries a `review_model` from a **different** model family, and the dispatcher refuses to send a `safety_level: high` job without one. Independent models are structurally pitted against each other's work.

**The redesign *is* the proof.** The current roster/model overhaul was executed *by the squad*: frontier model leads drafted **69 specialist definitions** (Fable authored the judgment/security/content set, Sol the engineering/systems set) and then **cross‑reviewed each other in two rounds**. The reviews caught concrete, non‑obvious defects, for example:

- a reviewer lane accidentally set to the **same family as the author** (broke review independence) — flagged and repointed;
- three high‑safety roles missing their mandatory **escalation floor** — flagged and corrected;
- research/recon roles **mis‑pinned to a lane by folder name** rather than capability — re‑derived;
- a specialist brief that **contradicted the routing map** on tool ownership — caught at final acceptance.

All of it is git‑verifiable in `departments/*/outbox/` and the commit trail — not a claim, a paper trail.

### 2. The whole thing is git‑verifiable dogfooding

The coordination substrate is `grep`‑able text and a terminal multiplexer — deliberately, for transparency and recovery, in a field drowning in message buses and daemons.

- **Every dispatch starts from a checkpoint.** Before any task goes out, the dispatcher commits an auto‑snapshot. At the time of writing, **99 of this repo's 231 commits** are `auto-snapshot: before TASK-… dispatch`. Verify it yourself: `git log --grep 'auto-snapshot' --oneline`.
- **One writer owns a path at a time.** The dispatcher parses each packet's `write_scope` and refuses to dispatch if it overlaps an in‑flight task.
- **The dispatch board is the filesystem** — `inbox/TASK-*.md` in, `outbox/TASK-*-response.md` out — every job human‑readable and diffable, no network service on the path.

---

## How it works

```
Operator ──one voice──▶  Chrono (coordinator)
                              │  chooses mode · specialist · model lane · write scope · reviewer
                              ▼
                   typed markdown task packet   ──inbox/TASK-*.md
                              │  capability-fit routing (the 69-row map)
        ┌─────────────────────┼─────────────────────┬─────────────────────┐
        ▼                     ▼                     ▼                     ▼
   gpt-codex               claude                gemini                 kimi
  (GPT-5.6 Sol)         (Claude Fable-5)      (Gemini 3.5)          (Kimi K2.7)
  implementation        judgment / safety     content / media       throughput
        └─────────────────────┴───────┬─────────────┴─────────────────────┘
                                       │  high-stakes → cross-family reviewer
                                       ▼
                          outbox/TASK-*-response.md ──▶ Chrono ──▶ Operator
```

1. You ask **Chrono** for something in plain language.
2. Chrono picks the **mode**, the **specialist**, the **model lane**, the **write scope**, and — if the work is high‑stakes — a **cross‑family reviewer**.
3. It writes a **markdown task packet** to that namespace's `inbox/` (after a git snapshot + write‑scope check).
4. The target **model lane** reads the packet and its specialist brief, does the work, and writes a response to the `outbox/`.
5. Chrono runs any required **review**, then surfaces the result to you.

## Quick start

```bash
bin/vibe-squad          # thin passthrough to `bin/squad`; alias: `squad up`
```

Starts (or re‑attaches) a tmux session named `squad` with six windows: `chrono` (the coordinator you talk to), the four model lanes, and a watchers/status window.

```
Ctrl-b 0 → chrono      Ctrl-b 3 → gemini
Ctrl-b 1 → gpt-codex   Ctrl-b 4 → kimi
Ctrl-b 2 → claude      Ctrl-b 5 → watchers/status
Ctrl-b d → detach (lanes keep running)
```

Lifecycle: `squad up | stop | status | doctor | attach | detach`.
Prerequisites: macOS, tmux, logged‑in Claude Code / Codex / Gemini / Kimi CLIs, Python 3.11+ (for the MCP servers and the optional daemon).

## The model lanes

Chrono is the only operator‑facing voice; the four lanes are interchangeable *execution* engines. **Roles are stable; models are replaceable lanes** — which model runs a specialist is a capability decision in one map, not something hidden in prompts or implied by a folder.

| Lane | Model (pinned) | Best‑fit work |
|------|----------------|---------------|
| `gpt-codex` | `gpt-5.6-sol` | implementation, tests, PoC mechanics, code‑review mechanics, graphics/runtime |
| `claude` | `claude-fable-5` | judgment, planning, safety/security reasoning, defensive security, research & synthesis |
| `gemini` | `gemini-3.5-flash` | content, design, media/multimodal, search‑grounded work |
| `kimi` | `kimi-k2.7-code` | **throughput‑only lane** — bulk/mechanical passes under a strict gate; holds zero primary roles |

> **Routing is `specialist → model`, never `namespace → model`.** A specialist's `source_namespace` is only a mailbox/storage label. Two specialists in the same folder can run on different lanes; the same kind of work can span namespaces. Every routing decision — primary lane, a cross‑family backup, an escalation profile, and a separate reviewer — is one explicit row in `shared/specialist-runtime-map.tsv`, foreign‑keyed into versioned profile and policy registries.

<details>
<summary><b>Routing &amp; the specialist map</b> — the 28‑column source of truth, profiles, and policies</summary>

`shared/specialist-runtime-map.tsv` is the canonical routing table: **69 rows, 28 columns**, one row per specialist. Rather than duplicating raw model IDs across every row, each routing slot references a **profile** (`codex.sol.high`, `claude.fable.xhigh`, `gemini.flash.default`, `kimi.k2.7.bulk`, …) that resolves — in `shared/registries/profiles.tsv` — to an exact model + effort + flags. Failover, escalation, and throughput behaviour are likewise **versioned policy IDs** (`shared/registries/policies.tsv`), not per‑row prose.

Each specialist declares a single `capability_class` (implementation · judgment · code_review · security_reasoning · security_defense · content_text · media_production · research_synthesis · extraction · game_design), a `safety_level`, and — for media roles — a `tool_profile` that pins the lane to whichever pane hosts the required generation tools (model choice is secondary there).

- `bin/validate-specialists.sh` fail‑closes on schema, foreign‑key, sort, and rule violations — it enforces, among others, "kimi holds no primary roles," "high/heightened‑risk roles get the safety‑floor escalation policy and never a throughput downshift," and "code review runs cross‑family" (`anti_affinity: author_family`). The current roster passes **69/69**.
- Adding a specialist = one TSV row + a markdown brief under `departments/<namespace>/specialists/`, then `bin/validate-specialists.sh`. `model-lanes/ROSTER.md` is a generated per‑lane view.

Full details: `shared/routing.md` (narrative source of truth) and `docs/architecture.md`.
</details>

<details>
<summary><b>The safety model</b> — refusal invariant, operator gates, and pre‑publication gates</summary>

Capability is separated from authorization — "can do" is not "may do."

- **Global safety‑refusal invariant.** A genuine safety refusal on *any* lane surfaces to the operator and is **never cross‑family re‑dispatched in either direction** — the system will not shop a refused request to a more permissive model. (Operational failures like an overloaded lane *may* fail over; refusals may not.)
- **Operator gates (Hard Rule 6).** A closed set of actions require explicit operator approval before execution: `delete · cleanup · credential_change · public_release · paid_media · live_outreach · production_mutation`. Specialists declare which gates apply; the `requires_approval` field is limited to actual tool names, so domain approvals can't hide there.
- **Pre‑publication gates.** Two specialists act as machine‑checkable gates before anything ships: `content-verifier` (a fact/citation truth gate) and `asset-provenance-and-rights-auditor` (a license/consent/rights gate). Each emits a hash‑bound PASS/HOLD/FAIL record; a non‑PASS or a stale content hash blocks publication.
- **Cross‑family mandatory review** is a dispatch‑time contract: high‑safety specialists must carry a reviewer from another family; same‑family reviews run in‑lane before "done," cross‑family reviews are Chrono‑coordinated after the response lands (`shared/protocol.md`).
</details>

<details>
<summary><b>The failover control plane</b> — cross-family reviewed, opt-in, and currently <i>dormant</i></summary>

The redesign specifies a full resilience layer: a per‑specialist **cross‑family backup** chain, Claude's native in‑lane fallback (`--fallback-model`), a **conservative‑first** auto‑failover policy (act only on hard signals — dispatch‑ack failure, confirmed process‑exit, typed provider error — and otherwise surface, never guess), a minimal **attempt ledger** with generation fencing, and a **lease/lock** so the native and Chrono‑coordinated paths can't double‑dispatch the same packet.

**Honest status:** this control plane is *built and cross-family reviewed but opt-in and currently gated off (dormant).* It ships inert because `_state/**` is ignored and no enable sentinel is present in a public checkout. Dispatch today is Chrono‑coordinated; automatic failover is **not** live. It is described here as an architecture the operator can explicitly enable, not a feature that runs by default.
</details>

<details>
<summary><b>Dispatch protocol &amp; repo tour</b> — packet schema, lifecycle, and where things live</summary>

Every dispatch is a markdown file with the frontmatter schema in `shared/protocol.md` (`to_model`, `specialist`, `source_namespace`, `write_scope`, `review_model`, `mandatory_review`, `operator_approved`, `return_artifact`, …). `source_namespace` selects the specialist markdown; `compatibility_namespace` selects the mailbox folder; `to_model` selects the runtime lane. Dispatch is asynchronous — senders don't block on lane‑to‑lane work.

| Path | Purpose |
|------|---------|
| `bin/squad`, `bin/launch-squad.sh` | Lifecycle CLI + tmux launcher (six windows) |
| `scripts/send-task.sh`, `bin/send-task.sh` | Dispatch: frontmatter generation + hardened writer (snapshot, write‑scope check, nudge) |
| `shared/specialist-runtime-map.tsv` | Canonical routing (69 rows) + `shared/registries/*.tsv` (profiles, policies) |
| `shared/routing.md`, `shared/protocol.md` | Routing model + packet schema/lifecycle/review behaviour |
| `shared/modes/*.md` | Operator‑approved workflows (project, bounty, incident, content, research, …) |
| `departments/*/specialists/`, `shared/specialists/` | Specialist markdown briefs |
| `departments/*/inbox/`, `departments/*/outbox/` | The dispatch board (packets + responses) |
| `bin/validate-specialists.sh` | Fail‑closed schema/routing validator |
| `daemon/` | Optional FastAPI service (status, summaries, triggers) — **not** on the dispatch path |

MCP tools (knowledge graph/vault, research, content generation, recon) are registered **directly per CLI** — `~/.claude/settings.json`, `~/.codex/config.toml`, `~/.kimi/mcp.json`, `~/.gemini/settings.json` — with no proxy layer; `shared/api-catalog.md` tracks a `verified:` state per capability, and a specialist may only cite verified entries.
</details>

## What's shipped vs. what isn't

- **Shipped:** the tmux + markdown‑mailbox runtime; the 69‑specialist canonical map with profile/policy registries and a fail‑closed validator (69/69); per‑CLI MCP tooling; auto‑snapshot + write‑scope dispatch rails; the safety/approval model.
- **Dormant (built, reviewed, gated off):** the automatic failover control plane described above.
- **Historical design:** an earlier Ink‑TUI + FastAPI‑daemon dispatch-spine proposal was not implemented and is retained only as a curated narrative under `docs/design/`. The shipped spine is the markdown mailbox.

## License

AGPL‑3.0. See [LICENSE](./LICENSE).

*This README, and the roster redesign it describes, were produced through the squad's own multi‑model workflow.*
