#!/bin/bash
# dispatch-toolkit.sh — emit mailbox-namespace context and executing model-lane
# tool expectations as a markdown snippet that send-task.sh appends to every
# dispatched task.
#
# Naming: the first argument is the COMPATIBILITY (mailbox) namespace, not the
# source namespace. The emitted text was corrected on 2026-08-08; these comments
# still said "source" until 2026-08-09, which is worse than a stale output --
# the next editor trusts the comment and reintroduces the mislabel.
#
# This implements the rule from chrono memory:
#   "every brief must enumerate chrono MCPs; voices default to WebFetch when
#    brief omits them."
#
# Without this, dispatched model lanes default to whatever is first in their
# context. With this, every lane sees the mailbox namespace roster, the expected
# model-lane surface, and the rule to verify live tool availability before use.
#
# Per-pane MCP enumeration is sourced from:
#   _state/capability-inventory-2026-05-02.md (verified per-pane install state)
#   _state/incident-2026-05-03-claude-mcp-tilde.md (post-fix Claude MCP set)
#   agy mcp list for the gemini routing lane (live repoint verified 2026-09-01)
#
# Provider availability changes over time, so the status block below is rendered
# from the canonical skill/tool registry on every dispatch.
#
# Usage:  bash shared/dispatch-toolkit.sh <compatibility-namespace> <to-model> [mode]

set -euo pipefail

NAMESPACE="${1:-}"
TO_MODEL="${2:-unknown}"
# Mode-blind injection (fixed 2026-08-04): this file is appended to EVERY packet
# and took only <namespace> <to_model>, so mode-specific doctrine reached no lane
# while bounty doctrine reached tasks that were not bounties. `mode` is already
# parsed at bin/send-task.sh:764; it just was not passed.
MODE="${3:-unknown}"
# Fourth arg (added 2026-08-12): the canonical specialist name. The security-doctrine
# gate below keys on this role's SAFETY SEMANTICS, resolved from the runtime map, rather
# than on the mailbox namespace. Optional — a caller that omits it (legacy 2/3-arg callers)
# leaves the safety fields empty and the gate fails open. See the gate for the full rationale.
SPECIALIST="${4:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL_REGISTRY="${REPO_ROOT}/shared/registries/skill-tool-registry.tsv"
RUNTIME_MAP="${REPO_ROOT}/shared/specialist-runtime-map.tsv"

# Resolve a single runtime-map field for a specialist, keyed by HEADER NAME so a column
# reorder in the map can never silently read the wrong field (One fact, one home: the
# column's meaning lives in its header, not in a magic index duplicated here). Empty output
# means the specialist has no row or the map lacks that column.
map_safety_field() {
    local specialist="$1" column="$2"
    [[ -f "$RUNTIME_MAP" ]] || return 0
    awk -F '\t' -v s="$specialist" -v col="$column" '
        NR == 1 { for (i = 1; i <= NF; i++) if ($i == col) idx = i; next }
        $1 == s { print (idx ? $idx : ""); exit }
    ' "$RUNTIME_MAP"
}

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
    "**Process isolation: your filesystem is private, your PROCESS TABLE IS NOT.** Every attempt gets "
    "its own git worktree, so file state is yours alone. Processes are not isolated -- several lanes "
    "run on this host at once. Never `pkill -f` a generic tool name. On 2026-08-06 a lane cleaned up "
    "after itself with `pkill -f \"anvil --fork-url\"` and `pkill -f \"halmos\"`, and killed those "
    "processes for every sibling lane simultaneously; eight lanes lost their completion envelopes in "
    "two clusters. Kill only PIDs you captured yourself (`$!`, or a pidfile you wrote), or let the "
    "attempt teardown reap them.\n\n"
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

# ── conditional injection: offensive-security + research doctrine ─────────────
# The security toolchain (~6 KB, lane-probed), the verdict-discipline rail (~1.6 KB),
# and the research add-ons (~0.3 KB) have NO consumer on an ordinary low/medium-risk
# task, yet they shipped on EVERY dispatch -- ~8 KB (~2,100 tokens) of dead weight per
# such packet. Gate them on the ROLE's safety semantics (from the specialist passed as $4)
# and MODE. Everything above this decision ships to every packet unchanged.
#
# Why not MODE alone: a security-department AUDIT legitimately runs in `project` mode, so
# gating on mode would silently strip a real consumer's toolchain.
#
# Why not NAMESPACE (the prior selector, REJECTED by cross-family review 2026-08-11):
# `source_namespace` is a mailbox/storage location, never a risk signal (root Hard Rule 3).
# Keying on it dropped the toolchain from every high-safety or heightened-risk role that
# lives outside the `security` mailbox -- `smart-contract-engineer` (coding namespace,
# safety_level:high, heightened_risk:true, dual-use/financial) foremost, plus 15 others
# (scraping-engineer, asset-provenance-and-rights-auditor, database-engineer, devops-engineer,
# mac-ops, loop-operator, ...). Every one silently lost its offensive-security doctrine.
#
# The selector now keys on ROLE SAFETY SEMANTICS -- `safety_level` and `heightened_risk` in
# shared/specialist-runtime-map.tsv, the fields that MEAN what this gate needs -- resolved by
# the specialist name passed as $4. Every security-namespace specialist is safety_level:high,
# so the safety-keyed gate is a strict SUPERSET of the old namespace gate: it drops no prior
# consumer and adds the 16 that were wrongly stripped.
#
# The fail-open bias is UNCHANGED: a security consumer silently losing its toolchain costs a
# lead; a writer paying a few KB does not. So doctrine is stripped ONLY when we can POSITIVELY
# resolve a non-high, non-heightened role. An unnamed or unresolvable specialist (empty
# safety_level) keeps the full toolchain; `bounty` mode keeps it regardless (explicit intent).
SAFETY_LEVEL=""
HEIGHTENED_RISK=""
if [[ -n "$SPECIALIST" && "$SPECIALIST" != "none" ]]; then
    SAFETY_LEVEL="$(map_safety_field "$SPECIALIST" safety_level)"
    HEIGHTENED_RISK="$(map_safety_field "$SPECIALIST" heightened_risk)"
fi
inject_security_doctrine=false
if [[ "$MODE" == "bounty" \
    || "$SAFETY_LEVEL" == "high" \
    || "$HEIGHTENED_RISK" == "true" \
    || -z "$SAFETY_LEVEL" ]]; then
    inject_security_doctrine=true
fi

# Research add-ons (Brave/Apify/Serper) belong to the research namespace as well, plus
# anything already receiving the security doctrine (recon leans on them).
inject_research_doctrine=false
if [[ "$inject_security_doctrine" == true || "$NAMESPACE" == "research" ]]; then
    inject_research_doctrine=true
fi

cat <<EOF

## Dispatch Context

- Mailbox namespace (compatibility): \`${NAMESPACE}\`
- Executing model lane: \`${TO_MODEL}\`

- **The packet's premise is a claim, not a fact.** If the task asserts something false,
  say so and quote the evidence; do not silently repair the premise or answer it as framed.
- **A null, absent, or negative result needs a positive control.** Show the check can detect
  what you report absent; silent failure and a clean result otherwise look identical.
- **Report what you measured and what you could not measure.** Never call an unreachable or
  unmeasured surface clean or green; name the parts your environment could not reach.

EOF

if [[ "$inject_security_doctrine" == true ]]; then
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
- **Apply the universal evidence rail above to every verdict.** Its positive-control and
  measurement-boundary requirements govern negative security conclusions too.
- **You have no authority to exclude on scope, severity, impact or payability grounds.** That is the
  adjudicator's job at the end. Bank what you find with the concern attached, and continue.

A clean refutation is a valuable outcome and costs you nothing. An overclaimed one costs a lead.

EOF
fi

cat <<'EOF'
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

if [[ "$inject_research_doctrine" == true ]]; then
    emit_registry_research_guidance
fi
if [[ "$inject_security_doctrine" == true ]]; then
    emit_registry_security_toolchain
fi

case "${NAMESPACE}" in
    coding)
        cat <<'EOF'

## Mailbox Namespace Context

**Related specialist briefs in this namespace:**
- `backend-engineer` · APIs, async pipelines, server-side
- `frontend-engineer` · React/Vue/Svelte, Tailwind, perf
- `ui-engineer` · component design, design-token alignment
- `code-reviewer` · spec compliance, severity ladder, adversarial review
- `test-engineer` · unit + property + e2e tests, flake triage, mutation + fuzz harnesses
- `devops-engineer` · Docker, K8s, Terraform, CI/CD
- `performance-optimizer` · benchmark, profile, flamegraph triage
- `refactor-cleaner` · AST rewrites, dead-code elimination
- `ai-engineer` · LLM applications, RAG, agent tools
- `smart-contract-engineer` · EVM/Solana audits
- `scraping-engineer` · browser-based extraction, stealth
- `systems-engineer` · cross-arch builds, NUMA/SIMD

**Routing reminder:** for OSINT / vendor research / library exploration, ask Chrono for a research-namespace dispatch. Use only tools supported by the registry-derived status block and verified in the current runtime.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless the packet explicitly asks for cross-lane review or parallel work.
EOF
        ;;
    security)
        cat <<'EOF'

## Mailbox Namespace Context

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

## Mailbox Namespace Context

**Related specialist briefs in this namespace:**
- `writer` · prose drafting, brand-voice content
- `technical-writer` · changelogs, ADRs, post-spec handoffs
- `editor` · pass for clarity, length, voice
- `designer` · design tokens, Figma fidelity, a11y
- `brand-voice` · operator voice consistency check
- `video-editor` · video trim/edit/captions

**Research tools:** the Gemini escalation profile currently resolves to `gemini-3.1-pro-high` in `shared/registries/profiles.tsv` and carries native Google Search grounding. For other research tools, use the registry-derived status block and verify the current runtime.

**Routing reminder:** for deeper multi-source synthesis beyond a quick grounded check, hand off to research namespace.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    sysmgmt)
        cat <<'EOF'

## Mailbox Namespace Context

**Related specialist briefs in this namespace:**
- `doctor` · system health checks, CLI auth, MCP reachability
- `dreamer` · KG synthesis, pattern observation
- `archiver` · cold-storage policies, run lifecycle
- `memory-curator` · vault hygiene, contradiction detection, stale-knowledge lifecycle review
- `knowledge-librarian` · vault organization, link integrity
- `harness-optimizer` · audit the squad's own configuration
- `loop-operator` · long-running iteration with checkpoints + stall detection

**Routing reminder:** for any external research (CLI changelogs, vendor docs, frontier-tool freshness checks), hand off to research namespace — they own `chrono-research-arsenal`.

**Required:** Execute the `specialist:` named in the task packet in this model lane. Native specialist/subagent adapters are allowed when registered; creating a new Chrono/mailbox task is not allowed unless Chrono explicitly assigns a review or parallel pass.
EOF
        ;;
    research)
        cat <<'EOF'

## Mailbox Namespace Context

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

GPT/Codex lane is expected to have repo shell commands, file edits, tests, `chrono-dedup`, `chrono-recon`, `chrono-research-arsenal`, `chrono-vault`, `chrono-obsidian`, `chrono-media-studio` when relevant, and `sequential-thinking`.

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

Gemini lane is expected to have native Gemini grounding, `chrono-research-arsenal`, `chrono-media-studio`, `chrono-vault`, `chrono-obsidian`, and media/design tools when the packet allows them. `chrono-media-studio` currently exposes wrapper tools such as `generate_image`, `generate_video`, and `generate_audio`; ElevenLabs/Higgsfield child tool names are not available in this lane unless the live schema exposes them.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    grok)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Grok lane is expected to have repo shell/file capabilities permitted by the task and `chrono-vault` for durable task memory. Its CLI discovers persistent MCP configuration globally, so discovery is availability evidence only; the sealed launch context and task packet remain the authority ceiling.

This is an expected surface, not proof of live availability. Verify the tool exists in your current runtime before using it. If missing, report `capability_gap` and use the task-approved fallback.
EOF
        ;;
    kimi)
        cat <<'EOF'

## Expected Model Lane Tool Surface

Kimi lane is expected to have `chrono-recon`, `chrono-research-arsenal`, `chrono-vault`, `chrono-obsidian`, `chrono-media-studio` when relevant, and `sequential-thinking`. Use the registry-derived status block for research add-ons and verify the current runtime before invocation.

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
from: <lane>          # gpt-codex | claude | gemini | grok | kimi
to: chrono
type: RESULT
status: complete      # complete | needs_review | needs_human | blocked
return_artifact: <the return_artifact path>
---

<one-paragraph summary of the outcome.>
```

- `status` must be exactly one of `complete`, `needs_review`, `needs_human`, or `blocked` (the reconciler canonicalizes `completed`→`complete`). Nothing else settles. In escalation order:
  - `complete` — finished **and verified**. A nonblocking coordination request may still be attached separately as described below.
  - `needs_review` — finished, but the packet's trusted `mandatory_review: true` / non-empty `review_triggers` contract requires independent review before it counts. A worker-authored coordination request alone never selects this status.
  - `needs_human` — you **stopped pending an operator decision** (an approval, an operator gate, the no-delete rule below). Stronger than `needs_review`: it is a question, not a deliverable. Say exactly what decision you need.
  - `blocked` — you could not proceed and there is no usable result.
- `cancelled` is **controller-only** — never author it. Chrono/the reconciler cancels a task; a worker does not cancel itself.
- The reconciler matches on the `<id>-response.md` filename and reads `status` plus the summary body; the remaining fields are provenance.
Specialists may use their model lane's native subagents for bounded parallel sub-work when the task
warrants it; this does not authorize creating board tasks, running `send-task.sh`, or launching another
model CLI. Every subagent inherits the packet's scope, target allowlist, dry_run status, and prohibitions;
restate those rails in its instructions. Keep fan-out to single digits. Remain the sole writer: you are
the only writer of artifacts and harness files. Kimi subagents do not inherit MCP, so perform MCP work
in the lead and pass results as context. Report `subagents: N` plus each subagent's role in the response
(`subagents: 0` when solo).

### Request nonblocking coordination without changing completion

Completion and coordination are separate facts. If your scoped deliverable is finished and
verified but Chrono should schedule a follow-up, widen a later packet, run a canary, or route
another specialist, keep `status: complete` and add this body section:

```
## COORDINATION REQUESTED
- <the exact nonblocking follow-up Chrono should route>
```

Use `needs_human` only when an operator decision stopped this task from completing, and use
`blocked` when no usable result could be produced. Never use `needs_review` merely to make a
coordination request visible.

### Report any DECLARED tool you could not invoke (`needs_tool`)

Your adapter authorises a set of tools for this lane. Authorised is not the same as
callable: a tool can be declared and still fail — an auth gate, an MCP that never
connected, a name that does not exist in your live runtime. If you **attempt** a
declared tool and it does not work, you MUST report it. Chrono reconciles *declared*
against *actual* from these reports; silence reads as "everything worked."

Add a **`## needs_tool`** section to your response body, one entry per failed tool:

```
## needs_tool
- tool: <the tool name EXACTLY as your adapter declared it>
  invocation: <the literal call you attempted>
  error: <the VERBATIM error text you got back>
```

All three fields are required. "The tool didn't work" is useless — the verbatim error
is what lets Chrono tell an auth gap from an outage from a name that never existed.

**This is a FIELD, not a status. Do not invent a new envelope status.** The four
envelope statuses are unchanged; `needs_tool` here names a *report*, reusing the
capability-degradation vocabulary, and never a fifth `status:` value (which would
fail closed and strand your task). Set your envelope `status` by what happened to the
DELIVERABLE, then attach the report regardless:

- You **finished anyway** — a fallback covered the gap, or the tool was not essential —
  so keep your normal status (`complete`, or `needs_review` under `mandatory_review`)
  and attach `## needs_tool`. The work stands; the gap is still recorded.
- The tool was **essential and you could not finish** without it — set `status: blocked`
  and attach `## needs_tool` naming the tool that stopped you. `blocked` already means
  "could not proceed"; the report says *why*.

This catches only tools you actually **attempted**. A declared tool you never tried
stays unverified — that is a known limit, not something to paper over.
COMPLETION_EOF

# ── SPEC 1.5 ITEM 4: hard no-delete rule ─────────────────────────────────────
# Appended to every dispatched brief regardless of namespace.
# Prevents destructive ops by dispatched agents without operator approval.

cat <<'NODELETE'

---

<!-- spec-1.5-no-delete-rule: do not remove this block -->
## Hard constraint: no unauthorized file deletion

Delete no **tracked** file without an explicit operator-approved `authorized_delete_paths`
manifest. Ignored build residue your own run generated — `__pycache__`, `.pyc`, empty scratch
files — is not work product: clean it up silently, and never park on it.

**What counts as a destructive op (requires operator approval):**
- `rm`, `unlink`, or `os.remove` on any tracked file, or on any untracked file not covered by
  the own-run residue exception above
- Overwriting a file wholesale where diff would show net loss of lines
- Moving a file out of the repo tree (equivalent to deletion)
- Running `git clean -f` or `git checkout -- .`
- **Destroying SHARED HOST STATE outside the repo entirely** — `go clean -cache` /
  `-modcache` / `-testcache`, `cargo clean`, `rm -rf ~/.cache/*`, docker/image prunes, or any
  equivalent. This is not your scratch space: it is shared with every other lane and with the
  operator, deleting it slows every subsequent build, and it is not recoverable from the repo. A
  lane ran `go clean -cache` and destroyed ~10 GB of host cache while believing the no-delete rule
  covered only files in the target tree. It does not — it covers **anything you did not create**.
  Need disk space? Stop with `status: needs_human` and report it under
  `## OPERATOR DECISION REQUIRED`.

**If your task appears to require deletion outside that narrow exception:**
1. Do NOT delete. Pause.
2. Write to your outbox with `status: needs_human`
3. Include: which files, why deletion seems required, proposed alternative
4. Wait for operator approval before proceeding.

This constraint fires for tracked files and all untracked files outside the own-run residue
exception, even if they look like drafts, temp files, or prior-run artifacts. The operator decides
what's ephemeral outside that narrow exception.

Violation of this rule is treated as a task failure requiring immediate
operator review. This constraint applies regardless of repository state or
available recovery mechanisms.
NODELETE

# ── mode block: mode-specific doctrine reaches ONLY the matching mode ─────────
# Everything above this point ships to every packet. Everything below is gated on
# the third argument, so bounty doctrine no longer rides along on tasks that are
# not bounties.

case "$MODE" in
    bounty)
        cat "${REPO_ROOT}/shared/templates/phase-contract.md"
        ;;
    *)
        : # No mode block. A task that is not a bounty must not inherit bounty doctrine.
        ;;
esac
