---
name: dependency-cycle-audit
audience: specialist
description: "Use when module, package, or build dependencies may contain cycles, especially load-order failures, broad rebuilds, or a planned extraction: derive the real graph, compute strongly connected components, rank cycle clusters, choose the minimal feedback-edge cut, and add an acyclicity guard."
---

# Dependency Cycle Audit

Find every dependency cycle at the granularity the build or loader actually enforces, rank the cycle clusters by blast radius, and break each with the cheapest cut that removes the coupling instead of hiding it.

## When to use
- Before approving an architecture change, module split, or extraction of a shared library.
- When builds rebuild "everything" on small changes, tests cannot run in isolation, or imports fail depending on load order.
- After a refactor that moved code between modules — cycles regrow silently.

## Inputs
- The codebase at a fixed revision, and its dependency ground truth: import statements, build-file dependency declarations, package manifests, linker inputs — never a diagram or a doc.
- The enforcement level to audit at: package, module, file, or build target.

## Steps
1. Fix the granularity first. A cycle visible at file level may be legal inside one package, while a package-level cycle breaks the build; audit at the level the toolchain enforces, and say which level you chose.
2. Extract the edge list from ground truth. Use an import-graph or build-graph extractor for the ecosystem (a dependency-graph tool category exists for every major toolchain: import-graph analyzers, build-graph query commands, module-dependency linters); where none is at hand, grep the import forms directly. Record the extraction command so the audit is repeatable.
3. Compute strongly-connected components (Tarjan or Kosaraju; any graph library, or a short script over the edge list). Every SCC with more than one node is a cycle cluster. Enumerate all of them — do not stop at the first cycle found; cycles cluster, and the count is the honest baseline.
4. Characterize each cluster: which edges close the cycle, each edge's weight (distinct symbols imported across it), and whether the edge is load-bearing (core call path) or incidental (one type reference, a convenience re-export, a leftover import).
5. Rank clusters by blast radius: fan-in of the cluster's members times the churn of its files (git log frequency). High fan-in, high-churn cycles invalidate the most builds and tests — break those first; a stable low-fan-in cycle may be acceptable, documented, for now.
6. Choose the break per edge, preferring the cut that removes the fewest, lightest edges (an approximation of the minimum feedback edge set):
   - **Delete** incidental edges — unused imports and convenience re-exports just go.
   - **Re-home** a misplaced piece — often one function or type sits in the wrong module and carries the whole back-edge.
   - **Extract a shared kernel** — move the types both sides need into a new leaf module both depend on.
   - **Invert** a genuine mutual dependency — the lower module defines an interface/protocol/callback; the higher module implements and injects it.
7. Re-extract the graph and recompute SCCs after each break. The cluster must dissolve, and no new cycle may appear — inversion done carelessly can relocate a cycle rather than remove it.
8. Guard the result: add a CI assertion at the audited granularity (an import-contract linter rule, a build-graph acyclicity check) so the cycle cannot regrow unnoticed.

## Outputs
- The audit record: granularity, extraction command, revision, SCC count and membership.
- Per broken cycle: the closing edges, the cut chosen and why it was the cheapest, and the re-check proving dissolution.
- The CI guard that keeps the graph acyclic at that level.

## Failure modes
- **Wrong granularity** — a clean package graph hiding file-level tangles that block a planned module split, or vice versa; always state the level.
- **Merging the modules** — the cycle "disappears" because the two nodes became one; the coupling is now invisible and worse.
- **Cutting the semantically central edge** — forcing a huge refactor when a one-line incidental edge closed the same cycle; weigh edges before cutting.
- **Trusting stale maps** — diagrams and docs describe the intended graph; only extracted edges describe the real one.
- **Masked runtime cycles** — type-only imports, lazy/deferred imports, and service locators keep the static graph clean while initialization order still deadlocks at runtime; audit deferred-import sites separately.

## Worked example
A Python service shows `orders → billing → notifications → orders`. Extraction (import-graph tool over `src/`) yields the edge list; SCC detection reports one 3-node cluster. Edge weights: `orders→billing` 14 symbols (load-bearing), `billing→notifications` 6 (load-bearing), `notifications→orders` 1 — a single `Order` type import used for a type hint. The cheapest cut is the 1-symbol back-edge: move `Order` into a new leaf `models` module (shared kernel); all three import `models`, the back-edge disappears. Re-run: zero multi-node SCCs. An import-linter contract (`models` may import nothing; no package may import `orders` except the API layer) goes into CI so the back-edge cannot return.

## Acceptance
- The audit names its granularity, revision, and extraction command; the edge list comes from code or build files, not documentation.
- All multi-node SCCs are enumerated, not just the first found.
- Each broken cycle records the closing edges, the chosen cut, and why cheaper cuts were not available.
- A post-break re-extraction shows the cluster dissolved with no new cycles introduced.
- A CI guard now enforces acyclicity at the audited level, or the residual cycle is documented as accepted with its blast radius.
