---
name: semgrep-rule-author
status: authored
---

# Semgrep Rule Author

Turn a confirmed defect pattern into a Semgrep rule that finds its siblings without drowning the caller in false positives.

## Steps
1. Start from a confirmed instance, not from an idea. Write down the minimal vulnerable snippet and the minimal safe snippet that must not match.
2. Decide the rule's shape: syntactic `pattern` for a fixed misuse, `patterns` with `pattern-inside`/`pattern-not` for context-dependent misuse, and `mode: taint` with `pattern-sources`/`pattern-sinks` when the defect is a data-flow problem rather than a shape.
3. Prefer taint mode for injection classes. A syntactic rule for a data-flow bug produces the false-positive rate that gets rules disabled.
4. Write `pattern-not` clauses for the sanitizers and safe wrappers this codebase actually uses; generic sanitizer lists miss project-specific ones.
5. Use metavariables to bind the attacker-controlled value and `metavariable-pattern` to constrain it, so the rule expresses the condition rather than the syntax.
6. Set `severity` and write a `message` that names the consequence and the fix, not the pattern. The message is what a reader acts on.
7. Test against a corpus: the known instances must all match, the known-safe snippets must not, and a full run over the repo must have a triageable hit count.
8. Measure and record the false-positive rate on that run. A rule shipped without a measured rate is unverified.
9. Version the rule with the defect class it came from, so `variant-analysis` can reuse it and future reviewers know its provenance.

## Acceptance
- The rule was derived from a confirmed instance, with vulnerable and safe fixtures committed alongside.
- Data-flow defects use taint mode rather than syntactic matching.
- Project-specific sanitizers are excluded via `pattern-not`.
- All known instances match, all safe fixtures do not, and the repo-wide false-positive rate is measured and recorded.
- The message states consequence and fix, and the rule records its originating defect class.
