#!/bin/bash
# dispatch-toolkit.sh — emit source-namespace context and executing model-lane
# tool expectations as a markdown snippet that send-task.sh appends to every
# dispatched task.
#
# This implements the rule from chrono memory:
#   "every brief must enumerate chrono MCPs; voices default to WebFetch when
#    brief omits them."
#
# Without this, dispatched model lanes default to whatever is first in their
# context. With this, every lane sees the source namespace roster, the expected
# model-lane surface, and the rule to verify live tool availability before use.
#
# Per-pane MCP enumeration is sourced from:
#   _state/capability-inventory-2026-05-02.md (verified per-pane install state)
#   _state/incident-2026-05-03-claude-mcp-tilde.md (post-fix Claude MCP set)
#   gemini mcp list -d (post-Hybrid-Path-A install on 2026-05-03)
#
# Provider availability changes over time, so the status block below is rendered
# from the canonical skill/tool registry on every dispatch.
#
# Usage:  bash shared/dispatch-toolkit.sh <compatibility-namespace> <to-model>

set -euo pipefail

NAMESPACE="${1:-}"
TO_MODEL="${2:-unknown}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL_REGISTRY="${REPO_ROOT}/shared/registries/skill-tool-registry.tsv"

# Emit the security toolchain: the repo's own rigs plus the analysers installed on
# this host. Added because the toolkit told every lane about MCPs and nothing about
# either -- a 25KB briefing with zero occurrences of slither, halmos, echidna, forge,
# cast, or any rig. That is the probable mechanism behind twelve Trail of Bits plugins
# sitting installed, available, and unused for a whole campaign: the reliable channel
# carried MCPs, and the analysers depended on Chrono remembering to name them.
#
# Design choices, each paid for by a measured failure:
#   1. Rigs are selected by `type == repo-rig`, NOT by a hardcoded name list, so a rig
#      registered later appears here with no edit to this file.
#   2. Analysers are ALSO selected from the registry and probed with `shutil.which` in
#      the same pass. An earlier version curated ten names by hand and shipped 9 of 44.
#      Worse, writing each name twice (once in bash, once in python) let `mythril`
#      diverge from the real binary `myth`: the probe recorded `absent`, the registry
#      lookup missed, and the tool fell out of BOTH the list and the drift report while
#      the smart-contract card mandated it every engagement. Deriving names from the
#      registry writes them zero times and cannot drift.
#   3. The selector is `purpose == hunting`, a statement about what a tool is FOR --
#      not `type == local-cli`, which is a statement about how it is PACKAGED. Selecting
#      on packaging shipped `Vercel`, a deployment connector, to security lanes, and
#      could not answer "which of these read EVM?" at all. `purpose`, `hunting_type` and
#      `target_class` are registry columns; see shared/registries/skill-tool-registry.tsv.
#   4. Output is grouped by `hunting_type` with EVERY class printed, including empty
#      ones. A class we cannot cover on this host is the most valuable thing this block
#      can tell a lane, and omission cannot say it -- an absent tool and an unexamined
#      one print identically as nothing.
#   5. A registry that says `yes` for a binary not on PATH is drift, and the block
#      reports it rather than passing the stale claim to a lane as fact.
emit_registry_security_toolchain() {
    python3 - "$TOOL_REGISTRY" "$TO_MODEL" <<'PYEOF'
import csv
import shutil
import sys
from pathlib import Path

registry = Path(sys.argv[1])
to_model = sys.argv[2] if len(sys.argv) > 2 else "unknown"

# The canonical technique-class vocabulary, in roughly the order a hunt walks them.
# This list is the same vocabulary the technique-debt table below asks for, and the
# same one the registry's `hunting_type` column is constrained to.
HUNTING_TYPES = [
    "source-review",
    "static-pattern-scan",
    "property-fuzzing",
    "coverage-guided-fuzzing",
    "symbolic-execution",
    "concrete-harness",
    "differential-variant",
    "bytecode-census",
    "deployed-state",
    "economic-composition",
    "supply-chain",
]

with registry.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
by_name = {r["name"]: r for r in rows}
rigs = [r for r in rows if r.get("type") == "repo-rig"]


def lane_eligible(row):
    """`local` means any lane with a host shell. A row naming lanes explicitly is
    available on those lanes and nowhere else -- so the executing lane counts too.
    Without this, every Solana capability we own (anchor, trident, solana) is scoped
    `claude|codex` and would report as zero coverage on the lane that can run it."""
    lanes = row.get("lanes") or ""
    return lanes == "all" or "local" in lanes or to_model in lanes.split("|")


probe_names = sorted(
    r["name"] for r in rows
    if r.get("record_kind") == "tool"
    and r.get("purpose") == "hunting"
    and lane_eligible(r)
)
probed = {n: ("present" if shutil.which(n) else "absent") for n in probe_names}


def caveat(row):
    """First sentence of the registry `notes`, truncated. A rig delivered as a bare
    name is hazardous when its notes say things like 'NEVER quote a Radar finding
    count as a result' -- carry the warning with the capability."""
    note = (row.get("notes") or "").strip()
    if not note or note == "—":
        return "—"
    first = note.split(". ")[0].rstrip(".")
    return first if len(first) <= 90 else first[:87].rstrip() + "…"

print("## Security toolchain available to this dispatch\n")

if rigs:
    print("**This repository's own rigs and standing checks.** These are ours; nobody else has them.\n")
    print("| Rig | Verified | Invocation | Caveat |")
    print("|---|---|---|---|")
    for r in sorted(rigs, key=lambda x: x["name"]):
        print(f"| `{r['name']}` | {r['verified_state']} | `{r['invocation']}` | {caveat(r)} |")
    print()

# `shutil.which` is only a meaningful test for rows that claim to BE a host binary.
# A repo rig runs through its own entrypoint, an MCP is reached over a transport, a
# `native-cli-subcommand` is two words, and `libfuzzer` is a compiler flag -- none of
# them are on PATH under their own name and none of them are missing. Selecting on
# `purpose` widened this set beyond the old `type == local-cli` selector, so absence
# has to be judged against the row's delivery mechanism, not against PATH alone.
# Reporting those as drift told a lane that nine capabilities we own were unavailable,
# three lines under a rig table asserting the opposite.
PATH_DELIVERED = "local-cli"

present, off_path, drift = [], [], []
for name in probe_names:
    state = probed.get(name, "unknown")
    row = by_name.get(name) or {}
    claim = row.get("verified_state")
    if state == "present":
        present.append(name)
        if claim is not None and claim not in ("yes", "—"):
            drift.append(f"`{name}` is on PATH but the registry records `{claim}`")
    elif row.get("type") == PATH_DELIVERED:
        if claim == "yes":
            drift.append(f"`{name}` is recorded `yes` in the registry but is NOT on PATH here")
    else:
        off_path.append(name)


def render(name, annotate_delivery=False):
    row = by_name[name]
    target = row.get("target_class") or "—"
    if annotate_delivery:
        return f"`{name}` ({target} · via {row.get('type') or 'unknown'})"
    return f"`{name}` ({target})"


print(
    f"**Hunting capabilities by technique class.** {len(present)} of the "
    f"{len(probe_names)} registry rows with `purpose=hunting` reachable from lane "
    f"`{to_model}` are live on PATH; {len(off_path)} more are delivered by another "
    "mechanism (rig entrypoint, MCP transport, subcommand) and are marked `via`. The "
    "parenthesised `target_class` is what the capability can actually read — a scanner "
    "that cannot parse your target is not coverage of it.\n"
)
for hunting_type in HUNTING_TYPES:
    def in_class(n):
        return hunting_type in (by_name[n].get("hunting_type") or "").split(",")

    members = [render(n) for n in present if in_class(n)]
    members += [render(n, True) for n in off_path if in_class(n)]
    if members:
        rendered = ", ".join(members)
    else:
        rendered = "**nothing here — we hold no executable capability in this class**"
    print(f"- `{hunting_type}` — {rendered}")

unclassed = [
    n for n in present + off_path
    if (by_name[n].get("hunting_type") or "—") == "—"
]
if unclassed:
    print(
        "- _(no technique class recorded)_ — "
        + ", ".join(f"`{n}`" for n in unclassed)
    )
print()

if drift:
    print("**Registry drift detected — trust the probe, not the row:**\n")
    for d in drift:
        print(f"- {d}")
    print()

print(
    "Presence on PATH is not liveness. `--version` succeeding is not liveness either. A tool is live "
    "for you only when a real invocation returns a real result on real target code, **in your lane** — "
    "plugin-backed tools exist for some families and return exit 127 for others. If a tool you need is "
    "missing, report its literal error and fall back to a positive-controlled manual method, labelled "
    "as the fallback; do not let an absent tool read as a clean scan.\n"
)
print(
    "Before concluding a capability is absent, check the **subcommands** of tools you already have. "
    "`cast selectors` recovers a contract's full ABI with argument types and payability straight from "
    "deployed bytecode, and a lane was nearly dispatched to evaluate installing six reverse-engineering "
    "tools for exactly that.\n"
)
print(
    "**This list is complete and live-probed, not a recommendation. It is the map, not the route.**\n\n"
    "For every **load-bearing question** — one that consumes material hunt time or supports a positive "
    "or negative verdict — write the falsifiable **QUESTION** and the observable **ORACLE** before "
    "choosing an executable. Then choose the best-fit **TECHNIQUE CLASS** from the list above, and only "
    "then pick a capability, filtered by target compatibility and lane liveness.\n\n"
    "Return a **technique-debt** table: one row per class, `USED | INAPPLICABLE | DEFERRED | "
    "UNAVAILABLE`. `INAPPLICABLE` requires a factual incompatibility naming the target fact and the "
    "absent capability (\"we own no symbolic engine targeting Anchor\"); \"not useful\" is `DEFERRED`, "
    "not `INAPPLICABLE`. A missing row is `UNEXAMINED`. **`DEFERRED`, `UNAVAILABLE` and `UNEXAMINED` "
    "cannot support an absence claim.**"
)
PYEOF
}

emit_registry_research_guidance() {
    python3 - "$TOOL_REGISTRY" <<'PYEOF'
import csv
import sys
from pathlib import Path

registry = Path(sys.argv[1])
wanted = ("Brave Search", "Apify", "Serper")
with registry.open(encoding="utf-8", newline="") as handle:
    rows = {row["name"]: row for row in csv.DictReader(handle, delimiter="\t")}
missing = [name for name in wanted if name not in rows]
if missing:
    raise SystemExit(f"dispatch registry guidance missing rows: {', '.join(missing)}")
rendered = "; ".join(
    f"`{name}` ({rows[name]['lanes']} · {rows[name]['verified_state']} · {rows[name]['cost_tier']})"
    for name in wanted
)
print("## Registry-derived research add-ons\n")
print(rendered + ".")
print("\nRegistry `yes` records availability, not permission to spend. Apply the row's invocation constraints and any task budget/authorization gate before use.")
PYEOF
}

cat <<EOF

## Dispatch Context

- Source mailbox namespace: \`${NAMESPACE}\`
- Executing model lane: \`${TO_MODEL}\`

EOF

cat <<'EOF'
## Verdict discipline — a kill is a claim and carries the same burden as a finding

If you conclude something is NOT exploitable, NOT reachable, or NOT a defect, that verdict is a
claim about the program and it needs evidence, exactly like a positive result does.

- **Refute the claim AS STATED.** Restate the question verbatim, then show the guard kills *that*
  claim — not an easier neighbour. Measured failures: "finalized ballots are removed" was used to
  conclude "ballots do not accumulate" (never-finalized ones persist); "the signer must be a bonded
  validator" became "the head is privileged" (the attacker was the event emitter, not the signer);
  "no gas-exhaustion terminus" became "no volume attack" (the absent gas limit was the *enabling*
  condition). All three were wrong and all three were reopened.
- **Quote the guard.** Name the production code or the program rule that prevents it, with file and
  line. A refutation without a quoted guard is not a refutation.
- **If your evidence only bounds the claim, say BOUNDED, not REFUTED.** Bounded work stays in the
  pool. Only a verdict that kills the stated claim removes anything.
- **A null result needs a positive control.** Show your harness *can* detect the thing you are
  reporting absent — a tool that silently failed to run and a tool that found nothing print the same
  empty output.
- **You have no authority to exclude on scope, severity, impact or payability grounds.** That is the
  adjudicator's job at the end. Bank what you find with the concern attached, and continue.

A clean refutation is a valuable outcome and costs you nothing. An overclaimed one costs a lead.

## Execution efficiency — the cost unit is ROUND-TRIPS, not tool calls

Measured across 57 board lanes on 2026-08-01. Lanes that ignored this took **~37 minutes** for work
that batching lanes finished in **~15**, with equal or lower yield. A live four-lane probe confirmed
every family can do all of the following — the slow lanes simply did not, unprompted.

1. **Batch independent operations into one round-trip.** This is the single largest lever. A lane
   that issued 7 tool calls in 4 *parallel* round-trips beat one that issued 146 *sequential*
   commands. Before each step ask: "which of these do not depend on each other?" and fire those
   together.
2. **Read a whole file in ONE operation.** Every lane can: claude `Read` (2,000-line ceiling), kimi
   `ReadFile` (1,000), codex and gemini via a single shell read. **Do not page a file in 260-line
   windows** — the measured default on some lanes, and it costs ~8x the round-trips on a large file.
3. **Do not re-read what you have already read.** A native read stays in your context; chunked shell
   output scrolls away, which is *why* chunking lanes re-read the same file three and four times.
   If you paged a file, you will pay for it again — so do not page it.
4. **Exclude generated code at the tool level, not in your head.** Use
   `rg --glob '!*.pb.go' --glob '!*.pb.gw.go' --glob '!*_generated.go' --glob '!vendor/'`. One lane
   read protobuf **24 times** despite its brief naming those files as generated: a prose instruction
   does not filter a search, a glob does.
5. **Front-load orientation into one batch.** A single combined listing/count/search beats forty
   incremental probes. In the slowest lane measured, **93% of commands were orientation and only 7%
   executed anything.**

None of this asks you to look at less. Read *more* of the target, in *fewer* operations.

EOF

emit_registry_research_guidance
emit_registry_security_toolchain

case "${NAMESPACE}" in
    coding)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `backend-engineer` · APIs, async pipelines, server-side
- `frontend-engineer` · React/Vue/Svelte, Tailwind, perf
- `ui-engineer` · component design, design-token alignment
- `code-reviewer` · spec compliance, severity ladder, adversarial review
- `test-engineer` · unit + integration test design
- `qa-tester` · property-based tests, mutation campaigns, fuzz harnesses
- `devops-engineer` · Docker, K8s, Terraform, CI/CD
- `performance-optimizer` · benchmark, profile, flamegraph triage
- `refactor-cleaner` · AST rewrites, dead-code elimination
- `ai-engineer` · LLM applications, RAG, agent tools
- `smart-contract-engineer` · EVM/Solana audits
- `scraping-engineer` · browser-based extraction, stealth
- `systems-engineer` · cross-arch builds, NUMA/SIMD
- `e2e-runner` · Playwright suites, visual diffs, flaky-test hunting

**Routing reminder:** for OSINT / vendor research / library exploration, ask Chrono for a research-namespace dispatch. Use only tools supported by the registry-derived status block and verified in the current runtime.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless the packet explicitly asks for cross-lane review or parallel work.
EOF
        ;;
    security)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `scout` · bounty target selection, program reconnaissance, scope analysis, platform intel
- `security-analyst` · SAST, supply-chain audits, code review for security
- `threat-modeler` · STRIDE, attack-tree, risk ranking
- `exploit-developer` · PoC construction, payload crafting, sandbox-safe reproduction
- `impact-validator` · CVSS v4 scoring, sanity check on findings, dedup vs CVE/known-issue DBs
- `privacy-steward` · PII / data-flow concerns, GDPR/CCPA review

**Bounty program context:**
- A bounty-program API token may be available in env for direct REST API queries on API-enabled programs
- Other authorized programs are browser-only; attach via the persistent CDP Chrome (see `shared/lifecycle.md`)
- Only engage programs the operator has explicitly authorized; do not suggest programs outside that authorized set

**Routing reminder:** for OSINT / vendor research that doesn't fit `scout`'s platform-intel scope, ask Chrono for a research-namespace dispatch. Use only tools supported by the registry-derived status block and verified in the current runtime.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    content)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `writer` · prose drafting, brand-voice content
- `technical-writer` · changelogs, ADRs, post-spec handoffs
- `editor` · pass for clarity, length, voice
- `designer` · design tokens, Figma fidelity, a11y
- `brand-voice` · operator voice consistency check
- `video-editor` · video trim/edit/captions

**Research tools:** `gemini-3.1-pro-preview` carries native Google Search grounding. For other research tools, use the registry-derived status block and verify the current runtime.

**Routing reminder:** for deeper multi-source synthesis beyond a quick grounded check, hand off to research namespace.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    sysmgmt)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `doctor` · system health checks, CLI auth, MCP reachability
- `dreamer` · KG synthesis, pattern observation
- `archiver` · cold-storage policies, run lifecycle
- `memory-curator` · KG hygiene, contradiction detection, stale-knowledge purge
- `knowledge-librarian` · vault organization, link integrity
- `harness-optimizer` · audit the squad's own configuration
- `finance-analyst` · subscription cost tracking
- `personal-ops` · operator's daily routines + reminders
- `loop-operator` · long-running iteration with checkpoints + stall detection

**Routing reminder:** for any external research (CLI changelogs, vendor docs, frontier-tool freshness checks), hand off to research namespace — they own `chrono-research-arsenal`.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    research)
        cat <<'EOF'

## Source Namespace Context

**Related specialist briefs in this namespace:**
- `research` · deep investigation, multi-source synthesis, claim validation
- `synthesizer` · aggregate parallel findings, preserve outliers
- `large-context-analyst` · 1M-2M context full-codebase / multi-doc analysis
- `scraper` · structured data extraction from web pages
- `learner` · study plans, drills, spaced repetition, reading ladders
- `data-extraction-engineer` · PDF parsing, table extraction, dataset wrangling

**This namespace is the squad's web-research home.** Other namespaces route research tasks here; you own the live `chrono-research-arsenal` wrapper.

**Research capability rule:** use the registry-derived status block, then verify the current runtime with a live probe. Treat absence from the callable runtime schema as an availability error, declare `capability_gap`, and use the approved fallback.

**NOT YOUR DOMAIN:** Bounty target selection (that's security namespace `scout`). Vulnerability discovery (that's security namespace `security-analyst`). Implementation work (that's coding namespace specialists).

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    *)
        echo ""  # unknown namespace, no toolkit injection
        ;;
esac

case "${TO_MODEL}" in
    gpt-codex)
        cat <<'EOF'

## Expected Model Lane Tool Surface

GPT/Codex lane is expected to have repo shell commands, file edits, tests, `chrono-research-arsenal`, `chrono-vault`, `chrono-obsidian`, `chrono-media-studio` when relevant, and `sequential-thinking`.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    claude)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Claude lane is expected to have `chrono-research-arsenal`, `chrono-vault`, `chrono-obsidian`, and local shell where allowed by the task. Context7 and sequential thinking are optional conveniences only when the live Claude runtime exposes them. Use Playwright/CDP only when the packet explicitly allows browser work.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    gemini)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Gemini lane is expected to have native Gemini grounding, `chrono-research-arsenal`, `chrono-media-studio`, `chrono-vault`, `chrono-obsidian`, `sequential-thinking`, and media/design tools when the packet allows them. `chrono-media-studio` currently exposes wrapper tools such as `generate_image`, `generate_video`, and `generate_audio`; ElevenLabs/Higgsfield child tool names are not available in this lane unless the live schema exposes them.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    kimi)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Kimi lane is expected to have `chrono-research-arsenal`, `chrono-vault`, `chrono-obsidian`, `chrono-media-studio` when relevant, and `sequential-thinking`. Use the registry-derived status block for research add-ons and verify the current runtime before invocation.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
esac

# ── completion contract: lanes emit BOTH return_artifact AND outbox envelope ──
# Appended to every dispatched brief. bin/outbox-watcher.sh + registry_reconciler
# key on departments/<ns>/outbox/<id>-response.md; without it finished work sits
# in-flight until Chrono hand-reconciles. This is the primary path; the
# reconciler's work-done-no-envelope flag is only the backstop.

cat <<'COMPLETION_EOF'

---

## Completion contract — write BOTH outputs when you finish

On finishing this task you MUST write TWO files:

1. **Your work** → the `return_artifact` path in the packet frontmatter.

   **Write it RELATIVE TO YOUR WORKTREE ROOT (your cwd), never to an absolute path.** You are running
   inside a per-attempt git worktree. `return_artifact` is a repo-relative path and the rail validates
   and promotes it **from inside your worktree**. If you resolve it against an absolute path such as
   `/Users/<you>/<repo>/_state/...` — which is easy to do when the packet gives you absolute paths for
   *reading* the target — the file lands outside your worktree, prevalidation finds nothing to promote,
   and your task settles `blocked` with `failure_class: request_validation` **even though you finished
   the work**. Absolute paths are for reading inputs. The artifact is written relative to cwd.
2. **The outbox completion envelope** → `departments/<compatibility_namespace>/outbox/<id>-response.md`, where `<id>` is this packet's `id` and `<compatibility_namespace>` is the department mailbox this packet was read from (`departments/<X>/inbox/<id>.md` → use `<X>`; authoritative even when the packet omits a `compatibility_namespace` field). The live `bin/outbox-watcher.sh` keys on this envelope to auto-reconcile the registry and surface your result to Chrono. Without it, finished work sits `in-flight` until it is hand-reconciled.

The envelope is markdown — this frontmatter, then a short summary body (its first paragraph is surfaced as the summary):

```
---
id: <id>-response
in_response_to: <id>
from: <lane>          # gpt-codex | claude | gemini | kimi
to: chrono
type: RESULT
status: complete      # complete | needs_review | needs_human | blocked
return_artifact: <the return_artifact path>
---

<one-paragraph summary of the outcome.>
```

- `status` must be exactly one of `complete`, `needs_review`, `needs_human`, or `blocked` (the reconciler canonicalizes `completed`→`complete`). Nothing else settles. In escalation order:
  - `complete` — finished **and verified**; nothing is owed.
  - `needs_review` — finished, but a reviewer/Chrono must look before it counts. Use this when the packet sets `mandatory_review: true`, or when you are surfacing a `## NEEDS FROM CHRONO`.
  - `needs_human` — you **stopped pending an operator decision** (an approval, an operator gate, the no-delete rule below). Stronger than `needs_review`: it is a question, not a deliverable. Say exactly what decision you need.
  - `blocked` — you could not proceed and there is no usable result.
- `cancelled` is **controller-only** — never author it. Chrono/the reconciler cancels a task; a worker does not cancel itself.
- The reconciler matches on the `<id>-response.md` filename and reads `status` plus the summary body; the remaining fields are provenance.
- **Panel / fan-out MEMBERS do NOT write an envelope** — only the panel coordinator writes the single outbox envelope for the parent task.
COMPLETION_EOF

# ── SPEC 1.5 ITEM 4: hard no-delete rule ─────────────────────────────────────
# Appended to every dispatched brief regardless of namespace.
# Prevents destructive ops by dispatched agents without operator approval.

cat <<'NODELETE'

---

<!-- spec-1.5-no-delete-rule: do not remove this block -->
## Hard constraint: no file deletion

You may NOT delete existing files in your write scope or working directory
without an explicit operator-approved instruction in this task's frontmatter.

**What counts as a destructive op (requires operator approval):**
- `rm`, `unlink`, or `os.remove` on any tracked or untracked file
- Overwriting a file wholesale where diff would show net loss of lines
- Moving a file out of the repo tree (equivalent to deletion)
- Running `git clean -f` or `git checkout -- .`
- **Destroying SHARED HOST STATE outside the repo entirely** — `go clean -cache` /
  `-modcache` / `-testcache`, `cargo clean`, `rm -rf ~/.cache/*`, docker/image prunes, or any
  equivalent. This is not your scratch space: it is shared with every other lane and with the
  operator, deleting it slows every subsequent build, and it is not recoverable from the repo. A
  lane ran `go clean -cache` and destroyed ~10 GB of host cache while believing the no-delete rule
  covered only files in the target tree. It does not — it covers **anything you did not create**.
  Need disk space? Report it under `## NEEDS FROM CHRONO` and stop.

**If your task appears to require deletion:**
1. Do NOT delete. Pause.
2. Write to your outbox with `status: needs_human`
3. Include: which files, why deletion seems required, proposed alternative
4. Wait for operator approval before proceeding.

This constraint fires even if files look like drafts, temp files, or
prior-run artifacts. The operator decides what's ephemeral.

Violation of this rule is treated as a task failure requiring immediate
operator review. This constraint applies regardless of repository state or
available recovery mechanisms.
NODELETE

# ── coordination rule: workers surface needs; Chrono orchestrates ─────────────
# Appended to every dispatched brief. A worker never self-launches, spawns, or
# coordinates with another specialist — it surfaces the need to Chrono (the sole
# controller), who orchestrates. Prevents the exit-75 launch trap and preserves
# the swarm's independent cross-model check.

cat <<'ORCHESTRATE'

---

<!-- orchestration-rule: do not remove this block -->
## Coordination: you are a worker; Chrono is the orchestrator

Do NOT create board tasks, launch a model CLI (`claude`/`codex`/`gemini`/`kimi`), run
`send-task.sh`, or coordinate with another board worker directly. Your sandbox denies
model-CLI exec, so the attempt fails your task; and cross-worker coordination is
Chrono's job — you are one independent worker in a swarm Chrono controls.

**That prohibition is about the BOARD, not about your own parallelism.** Inside your own
process you are a full CLI and you should work like one: **use your native subagents, plan
and fan out independent work, and batch parallel tool calls.** Reading four modules, running
three analysers, or checking five call sites are independent operations — do them
concurrently, not one at a time. Three lanes in one campaign reported that their specialist
brief *required* fan-out while this block appeared to forbid it, and each worked serially as
a result; that ambiguity is what this paragraph removes.

The line is simple: **anything inside your process is yours; anything that reaches another
board worker, another model CLI, or the registry is Chrono's.** This rule exists for exactly
two reasons — it prevents the exit-75 launch trap (your sandbox denies model-CLI exec, so the
attempt fails your whole task) and it preserves the swarm's independent cross-model check
(Chrono chooses the opposing family; a worker picking its own destroys that). **Neither reason
applies to your own subagents**, which cannot exec a CLI and do not change which model family
you are.

**When you do fan out internally, the packet's rails travel with it.** Every subagent you
start inherits your scope, your target allowlist, your `dry_run` status and your prohibitions
— restate them in the subagent's instructions rather than assuming they carry. A subagent that
does not know the target list can act outside it, and that is your task's failure, not its own.

One clarification, because it has cost real time: where a specialist brief says
"multi-model" or "Codex AND Claude attempt independently", that describes **Chrono's dispatch
pattern, not your job**. You are one side of it. Do not attempt to produce the other side.

**Three limits, because in-process parallelism has real failure modes:**

1. **Keep the fan-out small — single digits, not dozens.** The board's admission control counts
   registry entries and **cannot see your subagents**, so several lanes each fanning out widely
   multiplies host load invisibly. Disk and CPU are shared with every other running lane; a
   campaign has already had every Go link fail for hours because the volume filled. If you need
   heavy parallelism, say so under `## NEEDS FROM CHRONO` rather than taking it.
2. **You are the only writer.** Subagents return their results to you; **you** write the artifact
   and the harness files. Never let two processes append to the same file — you are told to write
   incrementally, and concurrent incremental appends interleave into corruption. Give each
   subagent a read task or a scratch path of its own, never the return artifact.
3. **Kimi subagents do not inherit MCP.** On that lane, perform MCP work in the lead and pass the
   result into the subagent as context. Claude, Codex and Gemini subagents do inherit it. Verify
   in your own runtime rather than trusting this sentence.

**Report what you actually used.** In your response envelope, state how many subagents you
started and what each one did in a few words — or `subagents: 0` if you worked solo. Chrono
cannot see inside your process; a count from you is the only accurate record of how wide the
work went, and it is what tells us whether this permission is being used at all or quietly
ignored.

If your native subagent surface is absent or fails, say so under `## NEEDS FROM CHRONO` — do
not substitute a model-CLI launch for it.

**If mid-task you need something beyond your scope** — a live canary/probe that requires
launching a CLI, another specialist's help, a wider write scope, a follow-up dispatch, or
you are blocked on a dependency — do NOT attempt it. Instead, add this section to your
response and let Chrono act:

## NEEDS FROM CHRONO
- <exactly what you need — e.g. "canary: run `claude -p --mcp-config … 'list mcp tools'`
  to prove the guarded trio connects", "dispatch a reviewer for X", "widen write_scope to
  include Y", "blocked on Z until …">

Return `status: needs_review` (or `blocked` if you cannot proceed further). Chrono reads
`## NEEDS FROM CHRONO` on every landed response and orchestrates it. Doing the work you
CAN do and clearly surfacing the need always beats attempting an out-of-scope launch.
ORCHESTRATE
