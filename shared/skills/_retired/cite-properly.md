---
name: cite-properly
retired: "merged into claim-verification (wired) — 'when an artifact makes factual claims' collides head-on; citation-form table (file:line / cmd+output / URL+date / note-id) preserved here."
status: authored
description: Use when an artifact, report, or memory note makes factual claims — attach a checkable source to every non-obvious claim (file:line, exact command + output, URL + date, note id) and never fabricate or launder a citation (Hard Rule 8).
---

# Cite Properly

A claim's value is bounded by how cheaply a skeptical reader can re-check it. Cite at the resolution that makes re-checking one step, label what is inference or assumption, and treat a fabricated citation as what it is: task failure.

## When to use
- Writing any artifact, review, or report that states facts: numbers, versions, behaviors, prior work, external claims.
- Quoting benchmarks, counts, or vendor statements.
- Recording durable memory notes that later sessions will trust blind.

## Inputs
- The claims the document will make.
- The evidence actually in hand: commands run, files read, pages fetched, notes recalled.

## Steps
1. Sort every claim into four bins: **verified-by-me** (I ran/read it this session), **sourced** (an external artifact says it), **inference** (follows from cited premises), **assumption** (unverified). The bin determines the citation form; a claim that fits no bin doesn't ship.
2. Cite at re-check resolution: `file:line` for code behavior; the exact command plus its decisive output lines for runtime facts; URL with retrieval date for the web; the memory note id for vault recall. "See the repo" is not a citation.
3. Quote verbatim where exact wording is load-bearing — error messages, verdict strings, API responses. Paraphrase drifts, and drifted paraphrase becomes a different claim.
4. Never cite what you have not personally read or run this session: no plausible-reconstructed URLs, no man-page-from-memory, no "commonly known" numbers. Vendor benchmark numbers are citable only labeled as vendor claims, never as verified planning inputs (Hard Rule 8).
5. Label inference as inference ("given A [cited] and B [cited], therefore C") and assumptions as unverified. "No source found" is an honest, valid citation state; an invented source is not.
6. Keep each citation adjacent to its claim. A pooled bibliography decouples claims from evidence, and the mapping decays with every edit.
7. Before shipping, spot-check your own citations as the reader would: open one file:line, re-run one command. If your own spot-check fails, assume the reader's will too.

## Outputs
- A document where every load-bearing claim carries an in-place, checkable source or an explicit unverified/inference label.

## Failure modes
- **Citation laundering** — citing a summary, README, or LLM answer that itself cites nothing; the chain must bottom out in a primary artifact.
- **Pattern-memory URLs** — links invented from what URLs usually look like; they read as evidence and resolve to 404 or, worse, to something else.
- **Wrong granularity** — citing a repo or directory for a line-level claim, pushing the verification cost back onto the reader.
- **Paraphrase drift** — a reworded quote that no longer says what the source said, now bearing the source's authority.
- **Verified-once, stale-now** — citing a past session's observation for a surface that has since changed; evidence ages with its subject.

## Worked example
An artifact claims: "the registry admits a skill for a lane only when `verified_state` is `authored` or `yes`." Wrong form: "per the validator docs." Right form: cite the membership test itself — `scripts/python/validate_capability_homes.py` in `shared_registry_capabilities()`, quoting the line `row.get("verified_state") in {"authored", "yes"}` — read this session. A companion claim, "the same rule held in July," recalled from a vault note, cites the note id and labels it as recalled context, not re-verified fact.

## Acceptance
- Spot-checking any citation reproduces the claim it supports in one step.
- Every unverified or inferred claim is labeled as such; the four bins are distinguishable in the shipped text.
- Zero references the author has not personally opened or executed this session.
- Vendor numbers appear only as labeled vendor claims.
