---
name: variant-analysis
audience: specialist
description: "Use immediately after one defect is confirmed to sweep for structurally related siblings across current code, history, copies, vendored forks, services, or languages; encode a repeatable Semgrep or AST query, gate each hit independently, and propose one root-cause fix."
---

# Variant Analysis

After one defect is confirmed, find every sibling of it in the codebase before closing the issue — the first instance is rarely the only one.

## Steps
1. Characterize the root cause precisely: the unsafe primitive, the missing check, and the condition that makes it exploitable. A vague characterization finds nothing.
2. Decide the variant axes to sweep: same primitive elsewhere, same call site with a different input source, same missing check in sibling handlers, and the same idiom in other languages or services in the repo.
3. Search structurally, not textually. Encode the pattern as a Semgrep rule via `semgrep-rule-author` or an AST query; grep misses reformatted and refactored instances, which are the ones that survive.
4. Sweep history as well as the working tree: the same defect frequently exists in a copied file, a vendored fork, or a branch that was never merged back.
5. For each candidate hit, run the reachability and impact gates from `findings-filter` — a variant is only a finding if it is independently reachable.
6. Group confirmed variants under the single root cause and propose one structural fix, such as a safe wrapper or a type that makes the unsafe state unrepresentable, rather than N local patches.
7. Where a local patch is unavoidable, add the rule to the repo's static-analysis config so future instances are caught at review time.
8. Record the sweep's coverage explicitly: which axes were swept, which paths were excluded, and what would still be missed. An unbounded "we looked" claim is not coverage.

## Acceptance
- The root cause is stated as primitive + missing check + exploitability condition.
- The sweep is structural (rule or AST query), with the query recorded and re-runnable.
- Vendored, copied, and historical instances were searched, not just the working tree.
- Each variant passed reachability and impact gates independently.
- A single structural fix is proposed where possible, and a detection rule is added to prevent regression.
- Sweep coverage and known gaps are stated explicitly.
