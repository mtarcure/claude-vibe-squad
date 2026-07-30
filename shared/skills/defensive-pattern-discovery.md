---
name: defensive-pattern-discovery
status: authored
---

<!-- inspired by OpenZeppelin/openzeppelin-skills:develop-secure-contracts (AGPL); concept-rebuilt for Chrono -->

# defensive-pattern-discovery

Defensive/remediation partner to the offensive audit skills. This is an **implementer**
skill (smart-contract-engineer / coding namespace) — it uses `Edit` to modify user contracts
and steers fixes toward audited library components instead of new custom code that needs its
own audit. It is NOT a read-only security-analyst skill; the analyst finds bugs, the
implementer applies the library-backed fix.

## Core rule

Before writing ANY logic, search the relevant library (OpenZeppelin, Solady, Solmate) for an
existing component:

1. **Exact match exists?** Import and use directly.
2. **Close match exists?** Import and extend only via marked extension points (`virtual`
   functions, hooks, configurable constructor params).
3. **No match exists?** Only then write custom logic, and confirm "no match" by browsing the
   library's installed directory listing — never assume from training-data knowledge.

NEVER copy or embed library source into the user's contract — always import. Hand-written
duplicates lose security updates.

## When to use

- Reviewing or fixing a contract with hand-rolled access control, pausability, reentrancy
  guards, ERC-20/721/1155 logic, ECDSA recovery, EIP-712 signing, proxies, timelocks, or
  governance.
- Operator asks "make this safer" / "use OZ here" / "is there a library for this".
- Proposing a remediation patch that introduces a new modifier or primitive — pause and
  check whether the library already provides it.

## Always read the project first

1. `Glob **/*.sol` to enumerate user contracts. Read the contract under change before
   suggesting anything. If a path read fails, surface the path attempted and the reason; do
   NOT silently fall back to a generic answer.
2. Read the existing `import` statements to learn which library components are already in
   use — extend that surface instead of introducing a parallel one.
3. Default to **integration**, not replacement. "Add pausability" means edit the existing
   contract; do not regenerate.

## Pattern discovery procedure

### Step 1 — Locate the installed dependency source

Solidity ecosystems install OZ to one of:

- `node_modules/@openzeppelin/contracts/` (Hardhat / npm)
- `lib/openzeppelin-contracts/` (Foundry / forge)

If neither exists, surface the gap before guessing — "OZ is not installed at `lib/` or
`node_modules/`; it must be added as a project dependency by the operator/host before
remediation" — do NOT fetch or install it yourself. Surfacing the missing dependency beats
inventing imports against it. Same pattern for Solady (`solady/src/`) and Solmate.

### Step 2 — Browse the directory listing, then read the component

Use `Glob` against the installed path (e.g.
`node_modules/@openzeppelin/contracts/access/**/*.sol`). Do not assume what files exist;
list them. Read NatSpec for override points, hooks, and integration requirements. Note any
`NOTE: This function is not virtual, {X} should be overridden instead` directives — those
change between major versions.

### Step 3 — Extract the minimal integration pattern

From the read, list the minimum changes:

- Imports / inheritance to add (always via import, never via copy)
- Storage to declare (mind upgradeable storage layout if proxy)
- Constructor / initializer changes
- Functions to ADD (required overrides, hooks)
- Functions to MODIFY (add modifiers, call hooks, emit events)

This is the minimal diff between "contract without feature" and "contract with feature".
Stop at that diff — do not gold-plate.

### Step 4 — Apply via Edit, not full rewrite

Use the `Edit` tool against the user's contract. Do NOT replace the entire file. Resolve
conflicts (duplicate access systems, conflicting overrides, incompatible inheritance) before
finishing. Never ask the user to apply the patch themselves.

## Generate-compare-apply shortcut (installed OZ as ground truth)

When OZ is installed (located above), use its **installed source** as the canonical reference —
never fetch a remote generator:

```bash
# canonical OZ base lives in the already-installed dependency (Foundry or npm layout):
OZ=$(ls -d lib/openzeppelin-contracts/contracts 2>/dev/null || ls -d node_modules/@openzeppelin/contracts 2>/dev/null)
# diff the user's contract against OZ's implementation of the same primitive
diff "$OZ/token/ERC20/ERC20.sol" <user-erc20>
# for a feature (e.g. Pausable) compare against OZ's extension source
diff "$OZ/token/ERC20/extensions/ERC20Pausable.sol" <user-erc20>
```

Apply the delta to the user's contract. The installed OZ source is the canonical correct
integration — treat it as ground truth for what imports / inheritance / overrides the feature
requires. Do NOT `npx`-fetch a remote contracts-cli; use the dependency already in the project.

If no CLI command exists for the contract type, fall back to the manual pattern-discovery
procedure (steps 1-4 above). Absence of a CLI command does NOT mean the library lacks the
component.

## Anti-patterns

- Do NOT write a custom `paused` modifier when `Pausable`/`ERC20Pausable` exists.
- Do NOT write `require(msg.sender == owner)` when `Ownable` or `Ownable2Step` exists.
- Do NOT copy library source into the user's contract — import it.
- Do NOT assume override points from prior knowledge — read the installed source. Override
  points change between OZ v4 and v5 (e.g., the ERC-20 transfer hook).
- Do NOT replace the user's full contract when "add X" was requested. Edit, do not rewrite.
- Do NOT skip the project read — generic answers without reading the user's existing imports
  are the failure mode this skill exists to prevent.

## Recording (chrono-vault)

After a defensive pass, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="learning", fields={"title": "defensive-pattern-discovery on <file>", "body": "library=<oz|solady|solmate|custom>; component_used=<name>; cli_used=<bool>; new_imports=<...>; lines_added=<n>; lines_removed=<n>", "target": "<target_file>", "attack_class": "none", "source_task": "<task-id>"})`.
Surface the chosen library component in the patch description so the operator sees what was
reused vs newly written. A memory error is logged in one line and never blocks the fix.
