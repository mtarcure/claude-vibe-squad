---
name: cross-file-relationship-synthesis
status: authored
---

# Cross-File Relationship Synthesis

Turn a set of independently-read files into an explicit relationship map, so conclusions rest on traced edges rather than on the impression that the files are related.

## Steps
1. List the files in scope and give each a one-line role. A file whose role you cannot state in one line has not been understood well enough to relate to others.
2. Name the edge kinds you will trace before tracing them — calls, imports, writes-then-reads, schema producer/consumer, config-to-consumer, generator-to-generated. Untyped "related to" edges hide the actual dependency.
3. Trace each edge in the direction data or control actually flows, and record the file and line at both ends. An edge without two anchors is a hypothesis.
4. Distinguish edges you observed from edges you inferred from naming. Matching names are a lead to verify, never an edge.
5. Look specifically for the edges that contradict the obvious structure: the secondary writer, the path that bypasses the abstraction, the consumer nobody registered. These decide correctness more often than the primary path does.
6. Identify the cut points — files whose change propagates furthest — and state the blast radius of each as a concrete list of affected files.
7. Check the map for orphans and dead ends, and resolve each: either an edge is missing from the map, or the file genuinely is unreachable. Never leave the ambiguity unexplained.
8. State the conclusion as a traversal over the map, so a reader can follow the same path and reach the same result.

## Acceptance
- Every file in scope has a stated one-line role.
- Every edge is typed, directed, and anchored at both ends with file and line.
- Observed edges and name-inferred edges are visibly separated.
- Cut points are named with an explicit blast-radius file list.
- Orphans and dead ends are each resolved as missing-edge or genuinely-unreachable.
- The final claim is expressed as a walk over recorded edges, not as a summary impression.
