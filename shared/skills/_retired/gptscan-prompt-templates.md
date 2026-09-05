retired: 2026-08-19 — audited "adds nothing / no identified consumer"; see departments/sysmgmt/skill-audit-batch-*.md. Moved, not deleted.
---
name: gptscan-prompt-templates
status: authored
description: Read-on-start LLM audit prompt-shape reference for EVM source review; never invoke as a tool.
category: hunting
applies_to:
  - source-review
  - static-pattern-scan
platform:
  - evm
---

# LLM Prompt Shapes for Solidity Source Review

This reference helps an auditor choose a question shape that fits the current stage of an EVM source review. Read it before using an LLM to compress a vulnerability class, test a local hypothesis, compare competing patterns, or rank a large set of functions.

The prompts below are scaffolds. Replace every bracketed field with facts from the current review. Supply the smallest complete code slice that preserves modifiers, inherited behavior, internal calls, and relevant state declarations.

## Use this reference when

Use these shapes when all of the following are true:

- Solidity source is available.
- The reviewer can define a concrete security property, weakness, or triage objective.
- The supplied context contains enough code to trace the relevant values and control flow.
- The result will guide human review, local testing, or evidence collection.

Choose a different approach in these situations:

- Use manual architecture mapping when trust boundaries, roles, upgrade paths, or asset flows are still unknown.
- Use call-graph or data-flow analysis when the decisive path crosses more code than a compact prompt can carry.
- Use compilation, unit tests, property tests, or transaction traces when the claim depends on runtime behavior.
- Use numeric modeling when the issue depends on rounding, precision, slippage, exchange rates, or solvency.
- Use specification review when the key question is intended behavior rather than implementation behavior.
- Use direct source inspection when the condition is syntactic and a deterministic search answers it.

An LLM answer is a review lead. A reportable finding requires a reachable path, violated property, attacker capability, observable impact, and evidence that survives independent checking.

## Prepare the evidence packet

Before selecting a prompt, assemble a bounded packet:

1. State the review target and contract role.
2. Name the entry point or function set.
3. Include relevant state variables, modifiers, inherited implementations, and internal callees.
4. State assumptions about callers, initialization, upgrades, and external integrations.
5. Define the security property in one sentence.
6. Mark omitted code and unresolved context explicitly.
7. Give line numbers or stable source labels.

Use this packet header with every shape:

```text
Review context
- Target: [contract and function or function set]
- Contract role: [vault, router, token, oracle adapter, governance module, other]
- Assets or privileges at risk: [specific assets or authorities]
- Authorized callers: [roles, addresses, or permissionless]
- Security property: [property that must hold]
- Assumptions: [facts established outside the excerpt]
- Missing context: [omitted definitions, inheritance, deployment facts]
- Source labels: [file and line ranges]
```

## Shape 1: Convert prose into a matchable weakness card

Use this shape before scanning code when the vulnerability class is broad, narrative, or overloaded with impact language. The goal is a compact behavioral signature. The signature should describe what must be observable in code and what would disprove the match.

```text
You are converting a vulnerability description into a Solidity review card.

Vulnerability description:
[paste the prose description]

Produce exactly these fields:

1. Security property
   One sentence describing the property that vulnerable code violates.

2. Required preconditions
   Conditions that must all hold for the weakness to be reachable.

3. Attacker control
   Values, ordering, callbacks, roles, or external state the attacker must control.

4. Sensitive operation
   The state change, transfer, authorization, accounting step, or external interaction at risk.

5. Match signals
   Concrete Solidity-level data-flow or control-flow facts that support the class.

6. Exclusion signals
   Concrete facts that rule the class out or materially weaken it.

7. Trace skeleton
   A short path in the form:
   entry point -> attacker-controlled input or state -> missing or ineffective guard -> sensitive operation -> violated property

8. Minimum code context
   Declarations, modifiers, callees, inherited code, or deployment facts needed to decide.

9. Confusable classes
   Up to three nearby weakness classes and the fact that separates each one.

Rules:
- Describe implementation evidence rather than class-name folklore.
- Keep impact separate from presence.
- Treat missing context as unresolved.
- Avoid claims about exploitability until a complete trace exists.
```

### Weakness card quality check

A useful card passes these checks:

- Each required precondition can be tested against source or deployment facts.
- Each match signal names a value, branch, call, or state transition.
- Exclusion signals can produce a clear negative decision.
- The trace skeleton has a defined source and sensitive sink.
- The card distinguishes presence, reachability, and impact.

If a card says only “missing validation,” “unsafe external call,” or “bad access control,” refine it. Those phrases are too broad to match reliably.

## Shape 2: Test one weakness in one code slice

Use this shape after the weakness card exists and the relevant code has been narrowed. It asks one falsifiable question. The output supports a positive, negative, or unresolved result without rewarding agreement.

```text
Act as a skeptical Solidity reviewer. Evaluate one hypothesis against only the supplied evidence.

Hypothesis:
[one weakness card or one precise claim]

Code:
[bounded code slice with source labels]

Return one verdict:
- SUPPORTED
- REJECTED
- INDETERMINATE

Use this output:

Verdict: [one allowed value]

Evidence trace:
1. Entry point: [source label and caller conditions]
2. Attacker influence: [source label and exact value, state, or ordering]
3. Guard analysis: [source label and why the guard fails or succeeds]
4. Sensitive operation: [source label]
5. Property result: [the violated or preserved property]

Required preconditions:
- [precondition]: [established, contradicted, or unknown] with evidence

Counterevidence:
- [the strongest fact against the hypothesis]

Missing evidence:
- [facts needed for a decisive result]

Confidence:
- [high, medium, or low]
- [one sentence tied to evidence completeness]

Rules:
- Start from the code and test every required precondition.
- Search for evidence that rejects the hypothesis before selecting SUPPORTED.
- Select REJECTED when a decisive guard or impossible precondition defeats the trace.
- Select INDETERMINATE when inheritance, a callee, deployment state, or integration behavior is missing.
- Do not infer attacker control from a parameter name.
- Do not infer impact from a suspicious line alone.
- Quote only short source fragments and always include source labels.
```

### Bias controls for a single check

Change “Find the vulnerability” into “Evaluate the hypothesis.” Require a rejected verdict and an indeterminate verdict as first-class outcomes. Ask for the strongest counterevidence. Separate required preconditions from observations. These controls reduce agreement caused by the wording of the question.

Before trusting the shape in a new review context, run two controls:

- Positive control: a small synthetic or previously proven example with every required condition present.
- Negative control: a nearby safe example where one decisive guard defeats the path.

The positive control shows the question can detect the intended pattern. The negative control shows the question can resist surface similarity.

## Shape 3: Classify among competing weakness cards

Use this shape when several classes could explain the same suspicious code. The useful result is a comparison across candidates. This avoids a sequence of independent questions that each invite agreement.

```text
Classify this Solidity code against the candidate weakness cards.

Code:
[bounded code slice with source labels]

Candidate cards:
A. [card name and required conditions]
B. [card name and required conditions]
C. [card name and required conditions]
[add candidates as needed]

For each candidate, fill this table:

| Candidate | Preconditions met | Preconditions contradicted | Unknowns | Best supporting evidence | Best excluding evidence |
|---|---|---|---|---|---|

Then select one classification:
- BEST_FIT: [candidate]
- MULTIPLE_FIT: [candidates]
- NO_FIT
- INDETERMINATE

Explain the classification in at most five sentences.

Finish with:
- Decisive discriminator: [single fact that most separates the candidates]
- Next evidence to collect: [one smallest useful code or runtime fact]

Rules:
- Apply the same evidence standard to every candidate.
- Compare required conditions before comparing labels.
- Allow NO_FIT when the code supports none of the cards.
- Allow MULTIPLE_FIT only when distinct complete traces coexist.
- Treat shared surface signals as weak evidence.
- Avoid severity ranking in this step.
```

### Candidate set design

Use three to six candidates. Include the main hypothesis, its closest confusable class, and a no-match outcome. Candidate lists longer than this dilute attention. Candidate descriptions must use the same fields and level of detail.

## Shape 4: Rank functions for deep review

Use this shape after architecture and trust boundaries are understood. It narrows attention across a large contract surface. It does not establish that a weakness exists.

```text
Rank the supplied Solidity functions for deep manual review.

Review objective:
[asset, privilege, invariant, or weakness card]

System facts:
[roles, asset flows, upgrade model, external integrations, trusted components]

Function inventory:
[function signatures plus short bodies, summaries, or source labels]

Score every function from 0 to 3 on each dimension:
- Reachability: who can call it and through which path
- Attacker influence: control over inputs, ordering, callbacks, or referenced state
- Asset or privilege effect: transfers, minting, debt, ownership, approvals, upgrades, or governance
- External interaction: calls, hooks, token behavior, oracle reads, delegate execution, or callbacks
- State coupling: dependence on shared accounting, caches, checkpoints, epochs, or cross-function invariants
- Guard uncertainty: modifiers, validation, initialization, or assumptions that need inspection
- Objective relevance: connection to the stated review objective

Return:

| Rank | Function | Total | Main reasons | Critical dependency to inspect | Deep-review question |
|---|---|---:|---|---|---|

Then provide:
- Top review set: [three to seven functions]
- Deferred set: [functions with a short reason]
- Coverage gaps: [unseen inheritance, generated interfaces, libraries, assembly, deployment, or integrations]

Rules:
- Explain every score of 3 with a source fact.
- Penalize missing bodies by marking uncertainty rather than inventing behavior.
- Keep privileged functions in scope when privilege compromise or role misuse is relevant.
- Keep view functions in scope when downstream systems consume prices, shares, collateral values, or authorization results.
- Avoid treating function length or naming as risk evidence.
- Do not call deferred functions safe.
```

### Triage review

Inspect the top-ranked functions together with their modifiers and first-order callees. Re-rank when a callee moves value, changes authorization, performs a callback, or supplies a security-critical value. Record deferred coverage so the audit conclusion remains bounded.

## Recommended audit sequence

Apply the shapes in this order:

1. Map contracts, roles, assets, trust boundaries, and important invariants.
2. Build the function inventory and identify missing source context.
3. Convert each relevant vulnerability description into a weakness card.
4. Rank functions against the current asset, invariant, or card.
5. Expand the selected functions with modifiers, inherited behavior, and callees.
6. Run the single-check shape for a precise hypothesis.
7. Use candidate classification where multiple classes remain plausible.
8. Validate supported traces with source-level reproduction, tests, or runtime evidence.
9. Record rejected, supported, and unresolved outcomes.
10. Revisit the inventory using facts learned during deep review.

Order matters because each stage supplies constraints for the next. Architecture defines meaningful properties. Weakness cards define matchable conditions. Triage allocates attention. Targeted checks test complete conditions. Classification resolves ambiguity. Validation establishes behavior. Records prevent repeated dead ends.

Avoid starting with a repository-wide request to “find all vulnerabilities.” That request combines discovery, classification, reachability, impact, and prioritization into one underspecified task.

## Failure modes and repairs

### Leading questions

Failure: “This function is reentrant, correct?” presupposes the answer.

Repair: Ask for SUPPORTED, REJECTED, or INDETERMINATE and require counterevidence.

### Class labels without operational conditions

Failure: A class name triggers generic explanations that ignore the actual code.

Repair: Use a weakness card with required preconditions, match signals, exclusion signals, and a trace skeleton.

### Truncated context

Failure: The prompt omits modifiers, inherited methods, internal calls, storage declarations, or token behavior. The answer invents the missing link.

Repair: List missing context and require INDETERMINATE whenever it controls the verdict.

### Mixing presence, reachability, and impact

Failure: A suspicious operation becomes a high-severity claim in one leap.

Repair: Decide three questions separately:

1. Does the code contain the weakness?
2. Can an authorized threat actor reach it under real system conditions?
3. What state change or asset loss can result?

### Independent yes or no checks for related classes

Failure: Several prompts each return yes because the candidates share surface features.

Repair: Use one candidate table with common evidence standards and a decisive discriminator.

### Pattern matching on names

Failure: Terms such as “admin,” “oracle,” “callback,” or “unchecked” are treated as proof.

Repair: Trace actual caller authority, value origin, guards, state transitions, and external behavior.

### Ignoring negative evidence

Failure: The answer collects supporting facts and skips a decisive access check, state update, revert condition, or pull-based settlement.

Repair: Require the strongest excluding fact before the verdict.

### Hallucinated cross-file behavior

Failure: The model fills an unseen callee or inherited implementation with a plausible body.

Repair: Use stable source labels, list unseen definitions, and block decisive verdicts on missing code.

### Treating comments as execution

Failure: NatSpec, inline comments, or variable names substitute for control-flow evidence.

Repair: Treat comments as intended behavior. Verify executable branches and state changes independently.

### Unsafe assumptions about external contracts

Failure: Tokens, hooks, oracles, routers, and proxies are assumed to follow familiar behavior.

Repair: State each integration assumption and collect interface, implementation, deployment, or trace evidence.

### Context overload

Failure: A large undifferentiated source dump lowers attention and obscures dependencies.

Repair: Supply a function-centered slice plus the exact declarations and callees that determine the property.

### Severity anchoring

Failure: A severity label biases the model toward proving a dramatic outcome.

Repair: Establish the trace and observable state change first. Assign severity in a separate step under the governing rubric.

### Uncalibrated confidence

Failure: Fluent prose receives high confidence despite unresolved prerequisites.

Repair: Tie confidence to the count and importance of established, contradicted, and unknown preconditions.

### Missing controls

Failure: A negative result may reflect a weak question or missing context.

Repair: Run a positive control that should match and a negative control with a decisive exclusion signal. Record both observed results.

### Repeating an attractive dead end

Failure: Later reviewers rescan a rejected hypothesis without learning why it failed.

Repair: Store the decisive counterevidence, scope, source revision, and conditions that would justify reopening it.

## Record outcomes for later audits

Record every deep check, including rejected and indeterminate results. Use stable identifiers and source revisions so later reviewers can determine whether the evidence still applies.

```text
Audit prompt outcome

- Outcome ID: [stable identifier]
- Date: [ISO date]
- Reviewer or model configuration: [identifier and relevant settings]
- Repository revision: [commit or source snapshot]
- Target: [contract, function, and source labels]
- Prompt shape: [weakness-card, single-check, classification, or triage]
- Security property: [one sentence]
- Candidate class or objective: [identifier]
- Verdict: [SUPPORTED, REJECTED, INDETERMINATE, or TRIAGE_ONLY]
- Preconditions established: [list with evidence labels]
- Preconditions contradicted: [list with evidence labels]
- Unknowns: [list]
- Decisive evidence: [short description and source label]
- Counterevidence: [short description and source label]
- Validation performed: [manual trace, compile, test, property test, transaction trace, other]
- Observed result: [what occurred]
- Coverage boundary: [what was not reviewed]
- Follow-up: [next action or none]
- Reopen conditions: [code or deployment changes that invalidate this outcome]
```

For reusable weakness cards, store:

- A stable card identifier and revision.
- The security property and trace skeleton.
- Required preconditions and exclusion signals.
- One observed positive control.
- One observed negative control.
- Confusable classes and their discriminators.
- Known false-positive triggers.
- The Solidity or EVM assumptions under which the card applies.

Do not promote a candidate to a finding based only on an LLM verdict. Link the recorded prompt outcome to the independent evidence that establishes reachability and impact.

## Quick selector

Use this decision path:

- Broad prose class needs operational meaning: build a weakness card.
- One class and one bounded code slice: run a single check.
- Several plausible classes on the same slice: run candidate classification.
- Many functions and limited review attention: run function triage.
- Missing architecture or trust boundaries: map the system first.
- Runtime-dependent claim: validate with execution evidence.
- Decisive context absent: record INDETERMINATE and collect the smallest missing fact.

The best prompt is the smallest question that preserves the evidence needed for a falsifiable answer.
