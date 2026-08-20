---
name: layered-analysis-loop
audience: specialist
description: "Use when analyzing a target deeply enough to require distinct structural, behavioral, edge-case, and contradiction passes rather than one undirected read—fix a question for each layer, record its evidence-backed delta, and stop only at a no-delta layer or an explicit budget cutoff."
---

# Layered Analysis Loop

Analyze in deliberate passes that each answer one question, so depth accumulates on a stable base instead of one undirected read producing a shallow summary.

## Steps
1. Write the question each layer will answer before starting it. A layer without a question becomes a re-read.
2. Run layer 1 for structure only: what exists, how it is organized, where the entry points are. Resist diagnosing anything yet.
3. Run layer 2 for behavior: follow the primary paths end to end and record what actually happens, in order.
4. Run layer 3 for edges: error paths, empty and boundary inputs, concurrency, and the states the primary path assumes but does not enforce.
5. Run layer 4 for contradiction: actively try to falsify the model built by layers 1-3. Look for the case that breaks it rather than the case that confirms it.
6. Close each layer with a written delta — what changed in the model — and carry forward only findings with evidence. An unrecorded layer did not happen.
7. Stop when a full layer produces no delta, and say so. Continuing past convergence spends budget; stopping before it ships an untested model.
8. Report the layers run, the delta from each, and the layer at which convergence occurred.

## Acceptance
- Each layer has a written question fixed before the layer ran.
- Structure, behavior, edge, and contradiction layers are separately recorded.
- Every layer closes with an explicit delta, including "no change".
- The contradiction layer names at least one specific attempt to falsify the model.
- The stopping condition is stated as convergence or as an explicit budget cutoff.
