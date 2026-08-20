---
name: claim-validation-gate
retired: "merged into claim-verification (wired) — observed/derived/asserted gate is claim-verification's decompose-classify-cite method."
status: authored
---

# Claim Validation Gate

Refuse to let an unverified assertion leave a review, report, or completion envelope; every claim carries its evidence or is downgraded.

## Steps
1. Extract every factual claim from the draft: what was changed, what was tested, what passes, what a tool reported, what a third party said.
2. Classify each claim as `observed` (a command was run and its output read), `derived` (follows from something observed), or `asserted` (neither).
3. For each `observed` claim, cite the exact command and the decisive line of its output; a claim whose evidence you cannot re-quote is not observed.
4. For each `derived` claim, name the observation it rests on and state the inference in one sentence, so a reader can attack the inference rather than the conclusion.
5. Downgrade or delete every `asserted` claim. Prefer an explicit "not verified" over an unqualified statement; never promote an assertion by rewording it.
6. Re-check quantities, versions, file paths, and identifiers against the source rather than against memory of the source — these drift silently between drafts.
7. Gate the deliverable: if any load-bearing claim is still `asserted`, the work is not complete, regardless of how much of it is done.

## Acceptance
- Every claim in the deliverable is `observed`, `derived` with a named basis, or explicitly labelled unverified.
- Each `observed` claim quotes runnable evidence, not a summary of evidence.
- No file path, version string, count, or identifier appears without having been read from its source.
- "Not verified" appears where verification did not happen, instead of hedged phrasing that implies it did.
- A reader can reproduce every `observed` claim from the citations alone.
