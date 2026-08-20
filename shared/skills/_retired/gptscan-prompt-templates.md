retired: 2026-08-19 — audited "adds nothing / no identified consumer"; see departments/sysmgmt/skill-audit-batch-*.md. Moved, not deleted.
---
name: gptscan-prompt-templates
status: authored
---

<!-- inspired by GPTScan/GPTScan:src/query_template.py (AGPL); concept-rebuilt for Chrono -->

# gptscan-prompt-templates

Prompt shapes for LLM-driven smart-contract review. Each shape has a specific job; using the
wrong shape is the most common cause of noisy LLM audit output. These are concept-rebuilt
templates — adapt the wording per call, but keep the structure.

## When to use

- Authoring a new audit prompt for a Chrono skill that calls a model (Claude/Gemini/GPT) on
  source code.
- Existing audit prompt produces "yes" verdicts that are unrelated to the asked vuln class.
- Sifting hundreds of functions down to a short list worth reading carefully.
- Distilling a long vulnerability description into one searchable sentence + scenario tag.

## Template 1 — Distill vuln description into KeySentence + Scenario

Use when you have a verbose vulnerability writeup and need a one-line summary the model can
match against new code, plus a single-word scenario tag derived from function names.

```
Code:
```solidity
<vulnerable code>
```
VulnerabilityImpact:
- (S1) <Title>: <one-paragraph description>
- (S2) <Title>: <one-paragraph description>

Tasks:
- Describe the vulnerability in a paragraph called "Description:".
- Summarize it in ONE sentence (no mitigation) starting "KeySentence:". Use only natural
  English words and numbers — no parentheses or backticks.
- Pick ONE word that summarizes the trigger scenario (derived from function names) starting
  "Scenario:".
```

Output keys: `Description:`, `KeySentence:`, `Scenario:`. Persist `KeySentence` + `Scenario`
to chrono-vault (via `record`) as the searchable handle for that vuln class, so future
`recall` queries can match it against new code.

## Template 2 — Yes/no targeted vuln check

Use when you already know the vuln class you are looking for and want a single contract
checked for it. This is the lowest-noise prompt shape.

```
Code:
```solidity
<contract code>
```

Does this code have a vulnerability called "<KeySentence from Template 1>"?

- "Answer:" yes or no, ONE word.
- If yes: "Location:" function name + line, "Description:" root cause, "PatchCode:" minimal
  fix, "ProofOfConcept:" PoC.
- If no: "NoVulnerability:" (empty paragraph).
- Strict format. No prose outside these keys.
```

Run this against EACH suspected function from Template 4 separately — never batch unrelated
functions into one yes/no call (the model collapses verdicts).

## Template 3 — Multi-pattern multiple-choice classification

Use when you have a known list of vuln patterns and want to know which (if any) applies. The
last option is always "no logical vulnerability matches" so the model has a graceful exit.

```
Code:
```solidity
<contract code>
```

Patterns:
1. <pattern KeySentence 1>
2. <pattern KeySentence 2>
...
N. <pattern KeySentence N>
N+1. The given code has no logical vulnerability matching the patterns above.

- "Answer:" the integer ID of the chosen pattern.
- If not the last option: "Location:" function name, "Description:" root cause,
  "PatchCode:" minimal fix.
- Strict format.
```

Cap the pattern list at ~12 — model attention drops sharply past that. For larger pattern
libraries, batch into multiple multi-choice calls.

## Template 4 — Function-list relevance filter

Use to triage a large codebase. Given a list of function names from one file and a set of
vuln-pattern statements (KeySentence + Scenario + FunctionNames), return only the functions
that COULD be affected. This is the upstream filter for Templates 2 and 3.

```
Functions: <comma-separated function name list>

Statements:
1.
KeySentence: <one-line vuln summary>
Scenario: <one-word trigger>
FunctionNames: <comma-separated typical function names from the vuln class>

2. ...

- "Result:" comma-separated function names from Functions that match any statement.
- If none match: "Result: None".
```

Output is a SHORT list — feed each surviving function into Template 2 or 3 for the actual
verdict. Do NOT skip this filter on codebases with >50 functions; deep-reading every function
is wasteful and noisy.

## Order of operations (typical pipeline)

1. Distill known historical vulns into `(KeySentence, Scenario, FunctionNames)` triples
   using Template 1. Persist each triple to chrono-vault once (`record`).
2. For a new target codebase: list every function name, then run Template 4 against the
   stored triple set to get a candidate function list.
3. For each candidate: run Template 3 (multi-choice over the matched patterns) OR Template 2
   (single-pattern yes/no) depending on whether one or many patterns apply.
4. Hand off `Answer != "no"` results to the **multi-model-fanout** false-positive filter
   (Chrono dispatches a second model / skeptic stance) and then to `impact-validator` for the
   G1–G4 impact gate — these prompt shapes maximize signal but do not eliminate FPs on their
   own, and reachability/disclosure alone does not pay.

## Anti-patterns

- Do NOT skip the function-list filter (Template 4) on large codebases — deep-reading every
  function with Template 2 wastes tokens and dilutes findings.
- Do NOT batch unrelated functions into a single yes/no call (Template 2). One function per
  call. The model collapses verdicts otherwise.
- Do NOT use Template 3 with > ~12 patterns — model attention drops; split into batches.
- Do NOT keep brackets, backticks, or quoted code in the KeySentence — the templates
  explicitly require natural English so the sentence is searchable across recall indexes.

## Recording (chrono-vault)

After a prompt batch, record best-effort telemetry via chrono-vault `record` (never a gate):
`record(note_type="attempt", fields={"title": "gptscan prompt batch (template <1-4>)", "body": "template_id=<1-4>; function_count=<n>; pattern_count=<n>; confirmed_count=<n>; model_used=<model>", "target": "<codebase>", "attack_class": "none", "source_task": "<task-id>"})`.
Record an `Answer != "no"` result as a `note_type="finding"` only AFTER multi-model FP-filter
and the impact gate. A memory error is logged in one line and never blocks the audit.
