---
name: pre-audit-threat-model
status: authored
---

<!-- inspired by pashov/skills:x-ray (MIT); concept-rebuilt for Chrono -->

# pre-audit-threat-model

Audit-readiness x-ray. Build the threat model BEFORE running any tooling so every later pass
has an entry-point list, an actor map, and a stated invariant set to evaluate against.

## When to use

- First skill on any new Solidity engagement. Always.
- Operator says "x-ray", "audit readiness", "prep this protocol", "summarize this protocol",
  or "where do I start".
- Re-run when the codebase changes meaningfully (new contract, new role, new external
  integration); the cached `x-ray.md` is otherwise the source of truth.

## Pipeline (3 steps, sequential)

### Step 1 — Enumerate and measure

1. Detect source dir: read `foundry.toml` `src=` first, else `hardhat.config.*`, else try
   `src/` then `contracts/`.
2. Count: source files, nSLOC (no `~` prefix in the report), test files, test functions,
   stateful-fuzz files, foundry-invariant files, echidna/medusa/halmos/certora configs, fork
   tests. These signal *test presence* — never infer "no tests" from coverage tool failure.
3. Run coverage in background (`forge coverage`, or a project-local `hardhat coverage` only if
   the project already has Hardhat installed — never `npx`-fetch a remote tool). If the toolchain
   is missing, surface the failure reason and continue — coverage is not a gate.
4. Run a git-security scan: branch shape (linear / merged / squashed-import), fix-commit
   candidates (commits whose message matches `fix|patch|vuln|exploit|audit`), late changes
   (commits in the final 10% of history), forked deps, tech-debt markers (`TODO`/`FIXME`
   density), test co-change rate per source file.
5. Glob for spec/whitepaper docs and extract only stated invariants, actor definitions,
   trust assumptions, economic properties. Tag spec-derived claims `(per spec)` so auditors
   can tell code-verified from spec-stated.

### Step 2 — Read source and classify entry points

1. Read every in-scope `.sol`. Skip `interfaces/`, vendored copies of OZ/Uniswap libs,
   tests/mocks. For each contract record: type & inheritance, roles & access control,
   value-holding state vars, external calls, fund flows, invariant comments,
   `require`/`assert` statements.
2. Entry-point grep gate (PCRE — Bash, not the Grep tool):
   ```bash
   # single-line signatures
   grep -rnP 'function\s+\w+\s*\([^)]*\)\s+(external|public)(?!.*\b(view|pure)\b)' src/ --include='*.sol'
   # multi-line signatures (visibility on closing-paren line)
   grep -rnP '^\s*\)\s+(external|public)(?!.*\b(view|pure)\b)' src/ --include='*.sol' -B5
   ```
3. Classify EACH grep hit by reading its body: **permissionless** (no modifier AND no
   internal `msg.sender` check), **role-gated** (modifier or internal restriction —
   `acceptOwnership` style counts), or **admin-only**. `nonReentrant` alone is NOT access
   control. The grep list is the source of truth — subagent summaries lose.
4. Centralization analysis per privileged role: enumerate operational actions, distinguish
   role-transfer delays from action delays, mark which actions can extract user funds.
5. Pause-coverage analysis: which critical functions are `whenNotPaused`, which aren't.
   Integrate gaps into the relevant role's attack surface — do NOT make a standalone
   "Centralization Risks" section (that duplicates Actors / Trust Boundaries / Attack
   Surfaces).

### Step 3 — Write outputs

Write three files into `x-ray/` in a single message (parallel writes):

1. `x-ray/architecture.json` — contracts, edges, roles, value flows for SVG rendering.
2. `x-ray/x-ray.md` — under 500 lines. Sections: Overview, Threat & Trust Model, Invariants,
   Actors, Permissionless Entry Points (grep-verified list only), Trust Boundaries, Key
   Attack Surfaces, Integrations & Composability, Tests & Coverage, Git History, Verdict.
3. `x-ray/entry-points.md` — protocol flow paths first (`destination ← writer-of-precondition
   ← ... ← deployment` arrow chains), then per-access-level detail blocks.

## Verification rules

- **Permissionless list**: grep-verified only. If a subagent summary disagrees, grep wins.
- **Security claims**: before writing "check X is missing", grep for every write site of
  the variable in question and confirm against those write sites. Qualify anything you
  cannot verify with `could not confirm`.
- **Branch scoping**: state the analyzed branch in the header (`Analyzed branch: <name> at
  <commit>`). Never describe code state from other branches.
- **Test presence vs coverage**: enumeration counts test files even if coverage failed.
  Never claim "no tests" from a coverage tool failure.
- **Backwards-compatibility code**: only classify code as legacy if (a) no active callers
  exist, (b) no NatSpec documents the behavior as intentional, (c) git history shows the
  mechanism was removed. Otherwise it is current design.

## Anti-patterns

- Do NOT skip the grep gate — subagent contract summaries miss multi-line signatures.
- Do NOT make a standalone Centralization Risks subsection — distribute into Actors / Trust
  Boundaries / Attack Surfaces.
- Do NOT fabricate invariants the code does not state or imply; mark unstated ones as
  "auditor-derived" so downstream skills know which are protocol-claimed.
- Do NOT block downstream audit work on coverage tool failure.

## Recording (chrono-vault)

After the x-ray, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="attempt", fields={"title": "pre-audit x-ray of <protocol>", "body": "nsloc=<n>; entry_points=<n>; permissionless=<n>; roles=<n>; invariants=<n>; integrations=<n>; branch=<name>@<commit>; xray_path=<path>", "target": "<protocol>", "attack_class": "none", "source_task": "<task-id>"})`.
A memory error is logged in one line and never blocks the audit.
