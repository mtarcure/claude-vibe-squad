# `witness_kind` + a closed predicate vocabulary for banked primitives

**Status: PROPOSAL. Nothing here is adopted.** `shared/modes/bounty.md`, the specialist briefs and
`scripts/python/` are untouched by this task. Chrono integrates after review.

Task `TASK-2026-08-04-0300-W1C-witness` · lane `claude` · specialist `harness-optimizer`.

---

## The failure

Two campaigns recorded **a bound on a harness as if it were a bound on the target**. The campaign's
own post-mortem says so in its lessons section, `_state/bounty/evmgw-2026-08-02/CAMPAIGN-CLOSED.md:82-84`:

> **A bound measured on an isolated primitive is not a property of the system.** Twelve lanes recorded
> harness limitations ("the fixture collapses the roles", "the balance is planted by me") as if they
> bounded the target.

The clean instance is recoverable in full, because the lane that removed the bound quoted the bound it
was removing. `test/P4B/P4B_GatewayCompose.t.sol:342-345`:

> L2 bounded P02 with "the fixture sets operator == admin == roleManager, so the separation cannot be
> observed" AND "P-10 shows the gateway holds no balance at rest, so the terminus precondition is
> planted". Compose: grant a FRESH address OPERATOR_ROLE only (through the system's own ROLE_MANAGER
> path), and supply the balance from X1's donation instead of a mint.

P4B did exactly that, and the separation was observable on the next line —
`assertTrue(gateway.hasRole(VAULT, puppet), "OPERATOR_ROLE minted VAULT_ROLE across the role-admin
graph")` at `:43`, terminating in a live money path at `:43`.

**This is a provenance problem, not a chaining problem.** The bound was already wrong at the moment it
was banked; composition was merely its first consumer. A better composition algorithm cannot recover
information the ledger never carried. The fix therefore belongs in the schema: *a bound with no quoted
production-code witness is not a bound.*

The second, independent cost is vocabulary. Every ledger was written in its target's private terms —
`GatewayContract.sol:220-229`, `vault_is_active`, `executed_sub_tx` — so **115 banked entries produced
nothing a later campaign could spend** (`shared/modes/bounty.md:76`; corroborated by the moat advisory
in vault note `mem-e07339c12bf6`: *"~115 entries / 41 distinct primitives -> 0 chains clearing 4
gates"*). Without shared terms `vault_is_active` and `vault_status(ACTIVE)` never unify, and **"no chain
found" is indistinguishable from "vocabulary mismatch."**

---

## Part 1 — `witness_kind` on every banked bound

Four kinds, closed:

| `witness_kind` | Means | Required alongside |
|---|---|---|
| `PRODUCTION_GUARD` | Production code or a program rule prevents the claim | `witness: <path>:<line>` **in the production tree** + verbatim `quote:` |
| `HARNESS_ARTIFACT` | The limit is in our instrumentation, not the target | `witness: <path>:<line>` **in a test/mock/fixture path** |
| `ASSUMED` | Taken on trust; nothing was measured | `assumption:` restating what is trusted |
| `EMPIRICAL` | Observed by execution | `command:` + `covered:` (a reachable-set denominator) |

**The property that makes this work is a path predicate, not a prose rule.** A lane that measured its
own harness can only cite a `test/`, `mock/`, `fixture/` or `harness/` path, or a `*.t.sol` /
`*_test.rs` / `Mock*` filename. The validator refuses `PRODUCTION_GUARD` on such a path
unconditionally. There is no wording that moves a `.t.sol` file into `src/`, so the failure becomes
**structurally unable to hide** rather than merely discouraged.

`HARNESS_ARTIFACT` is checked in the opposite direction — it must cite a harness path — so the label
cannot be used as a shrug to dodge the production-witness requirement.

`EMPIRICAL` requires `covered:` because *a tool that silently failed to run and a tool that found
nothing print the same empty output*. A green run over 1-of-3 entry points prints identically to one
over 3-of-3.

### What this does to the historical failure

The L2 bound's only available witness is `test/P4B/P4B_GatewayCompose.t.sol`. Banking it as a property
of the target now fails validation on the path alone:

```
production-guard-cites-harness-path:test/P4B/P4B_GatewayCompose.t.sol
```

It remains bankable — as `HARNESS_ARTIFACT`, which reads *"we could not see past our own fixture"* and
leaves the surface in the pool with a named cost to close it.

---

## Part 2 — the closed predicate vocabulary

`predicates.tsv` — 27 predicates in five families (authority, state, capital, timing, capability),
closed and **extensible by review**. It is a TSV rather than a constant in the validator on purpose:
extending the vocabulary should be a reviewable data diff, matching how
`shared/specialist-runtime-map.tsv` already works. The `unifies` column records the target-private
spellings each predicate absorbs, which is what makes adoption mechanical for a lane.

The payoff is cross-campaign retrieval. EVM and SVM Gateway shared no language, toolchain or asset
list, and their ledgers shared no vocabulary:

| EVM entry | SVM entry | Shared predicate |
|---|---|---|
| `isExecuted[messageId]`, set once at `GatewayContract.sol:681`, never cleared | `executed_sub_tx` gating the closable branch at `execute.rs:242` | `state.one_shot` |
| `req.token` reaching the burn path unvalidated (`GatewayContract.sol:289`) | `stored_ix_data` unvalidated on the finalize entrypoint | `state.value_unbound` |
| Vault finalize vs Gateway `isExecuted` in separate stores (L4-P04) | two entrypoints sharing one `#[derive(Accounts)]` | `state.domain_split` |

A backward chainer searching `state.one_shot` retrieves both. Under private vocabularies it would have
had to already know those were the same idea — precisely the knowledge a fresh campaign lacks.

---

## Part 3 — a record shape that compounds

Two fenced block types, flat `key: value` lines. Flat and regex-parseable because **PyYAML is not
installed on the lanes that must write these** (`ModuleNotFoundError: No module named 'yaml'` on this
host), and a format a lane cannot parse is a format a lane will not write.

````markdown
```primitive
id: P-A7
pin: <target pin>
pre.authority: auth.role_required(VAULT_ROLE)
pre.state: state.one_shot(isExecuted), state.value_unbound(messageId)
pre.capital: capital.pooled(Vault, ERC20)
pre.timing: timing.unbounded()
pre.deps: <toolchain + contract hashes>
action.command: <literal command>
action.sequence: <executable steps>
action.adapter: <how a future campaign rebinds the arguments>
post.capability: cap.deny(revert_or_rescue_for_that_messageId)
```

```bound
of: P-A7
claim: the marker is written at exactly one site and no function clears it
witness_kind: PRODUCTION_GUARD
witness: src/Example.sol:42
quote: processed[id] = true;
```
````

**`post.capability` is the correction that matters.** We have been banking verdicts and severities,
which die with the campaign that assigned them; a capability ports to every future target. The
validator rejects a postcondition containing a severity word — `critical`, `high`, `medium`, `low`,
`informational`, `severity`, `cvss`, `sev-N` — as `postcondition-is-severity`. This also keeps the
schema consistent with the mode's existing single-owner CVSS rule (`bounty.md:61`): CVSS is assigned
once, at the candidate→finding gate, by `impact-validator` — never in a Phase 3 ledger.

`action.adapter` is the chain adapter: one line saying which arguments a later campaign rebinds. It is
what turns a target-specific observation into a reusable move.

Bounds are separate blocks so a primitive can carry several with **different kinds** — which is the
normal case. X6 P-A3 carries a real `PRODUCTION_GUARD` and a real `HARNESS_ARTIFACT` simultaneously,
and the old format had one prose field for both.

---

## Part 4 — the validator

`validate_primitive_ledger.py`, stdlib only, in the style of `validate_mode_phase_refs()`: one
`Finding` per subject, JSON lines on stdout, summary on stderr, nonzero exit on any failure.

Checks: `unknown-witness-kind` · `bound-missing-field` · `bound-orphan` ·
**`production-guard-cites-harness-path`** · `production-guard-missing-witness` ·
`production-guard-missing-quote` · `production-guard-quote-mismatch` ·
`harness-artifact-missing-witness` · `harness-artifact-cites-production-path` ·
`assumed-missing-assumption` · `empirical-missing-command` · `empirical-missing-covered` ·
`unknown-predicate` · `predicate-family-mismatch` · `prose-instead-of-predicate` ·
`postcondition-is-severity` · `primitive-missing-field` · `duplicate-primitive-id`.

### Controls — both demonstrated, literal output in the response artifact

```
$ python3 validate_primitive_ledger.py fixtures/positive-control.md --target <evm-repo>
Total: 7  Passed: 7  Failed: 0        # exit 0

$ python3 validate_primitive_ledger.py fixtures/negative-control.md --target <evm-repo>
Total: 5  Passed: 0  Failed: 5        # exit 1
```

The negative control is **not synthetic**: it is the real `L2-P02` bound, quoted from the harness that
removed it, banked the way it was actually banked. It fires
`production-guard-cites-harness-path:test/P4B/P4B_GatewayCompose.t.sol`.

`--target` enables quote verification against the real tree. It is not decorative: it caught a genuine
off-by-one in a hand-written worked example here — a `PRODUCTION_GUARD` cited at
`src/Example.sol:42` whose quoted `for` loop is at `:43`. Author error, caught mechanically,
on the first run.

### Proposed wiring — the hook already exists and is half-used

`scripts/python/verification_contract.py:255-260` already requires every bounty dry-run lane to produce
a primitive ledger:

```python
"dry_run_requirements": [
    "empty_findings",
    "kill_or_negative_evidence",
    "no_submit_evidence",
    "primitive_ledger",
],
```

**Presence is contracted; shape is not.** That is the entire gap. The proposal is to keep the contract
field as-is and validate the artifact it already demands, by adding one method to
`scripts/python/validate_specialists.py` beside `validate_mode_phase_refs()` and one call in `run()`:

```diff
     def validate_mode_phase_refs(self) -> None:
         ...
 
+    def validate_primitive_ledgers(self) -> None:
+        """Reject banked bounds whose witness does not support the kind they claim.
+
+        Two campaigns recorded a bound on a HARNESS as if it bounded the TARGET; the bound was
+        already wrong when banked and composition was only its first consumer. A lane that measured
+        its own fixture can cite only a test/mock/harness path, so the path itself settles the kind.
+        """
+        from primitive_ledger import LedgerValidator, load_predicates
+
+        vocabulary = self.root / "shared/bounty/predicates.tsv"
+        if not vocabulary.is_file():
+            return
+        ledgers = sorted(self.root.glob("_state/bounty/*/lanes/*/primitive-ledger.md"))
+        if not ledgers:
+            return
+        inner = LedgerValidator(load_predicates(vocabulary))
+        for finding in inner.run(ledgers)[0]:
+            if finding.status == "fail":
+                self.add(finding.path, "fail", *finding.issues)
+
     def run(self) -> tuple[list[Finding], str, int]:
         ...
         self.validate_routes()
         self.validate_mode_phase_refs()
+        self.validate_primitive_ledgers()
```

Placement is Chrono's call. The two sane homes are `scripts/python/primitive_ledger.py` with the
vocabulary at `shared/bounty/predicates.tsv`, or leaving the rig standalone and calling it from the
bounty prevalidation path. **Note the diff is written against `validate_specialists.py` as it exists on
the `bounty-mode-rewrite` worktree, not on this branch — see Limitations.**

---

## Files

| File | What |
|---|---|
| `README.md` | this proposal |
| `predicates.tsv` | the closed vocabulary, 27 predicates across 5 families |
| `validate_primitive_ledger.py` | the working validator |
| `fixtures/positive-control.md` | well-formed ledger — must pass (7/7, exit 0) |
| `fixtures/negative-control.md` | the real L2-P02 failure — must fire (5/5, exit 1) |
| `worked-examples.md` | four real banked primitives re-expressed, both campaigns (12/12, exit 0) |

---

## Limitations, stated plainly

1. **`validate_mode_phase_refs()` is not on this branch.** The packet names it in
   `scripts/python/validate_specialists.py`; on `main` and in this worktree that file has no such
   method (its line 604 is `run()`). It exists only at
   `.claude/worktrees/bounty-mode-rewrite/scripts/python/validate_specialists.py:604`. I matched that
   style, but the integration diff above **will not apply to `main` until that worktree lands**.
2. **One `--target` per run.** Quote verification resolves witnesses under a single root, so a ledger
   spanning two target trees needs two runs. Unresolvable witnesses are *skipped*, not failed — which
   is deliberate (a missing clone must not manufacture failures) but does mean a single run cannot
   prove every quote. `worked-examples.md` was therefore run against both trees; both pass.
3. **The path predicate is a heuristic over conventions.** It catches `test/`, `mock/`, `fixture/`,
   `harness/`, `spec/`, `testdata/`, `e2e/` segments and `*.t.sol` / `*.test.ts` / `*_test.go|rs|py` /
   `Mock*` filenames. A target that puts fixtures in `src/` defeats it. It deliberately does **not**
   flag `script/` (deploy scripts are real operator paths — L4-P07 legitimately cites one) or
   `testnetV0/` (real, if out-of-scope, production source).
4. **`prose-instead-of-predicate` will be noisy on first adoption.** Every existing ledger fails it,
   because every existing ledger is prose. That is the intended signal, but it means adoption is a
   forward-only rule for new campaigns, not a retrospective gate — unless Chrono wants a
   back-conversion pass, which is a separate task.
5. **This validates form, not honesty.** It cannot tell whether a quoted production line actually
   supports the claim attached to it — only that the line exists, says what the lane says it says, and
   lives in production code. Semantic review stays a cross-family reviewer's job.
