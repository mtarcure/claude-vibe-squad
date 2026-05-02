---
name: library
extends: project
status: active
---

# Project Profile: Library

Public package for others to depend on. Semver discipline, docs are first-class.

## Auto-detection signals

- Operator says "library" / "package" / "publish"
- No app/service/binary in design — just code others import
- README oriented at API users, not end-users

## Phase customizations

### Phase 1 Intake
- Define public API surface explicitly
- Decide semver policy
- Pick distribution: npm / PyPI / crates.io / etc.

### Phase 2 Design
- API design is the design (this matters more for libs than apps)
- architect heavy (multi-model — interface contracts)
- Document any breaking-vs-non-breaking guidelines
- Consider: minimum supported version of host language / runtime

### Phase 4 Build
- backend-engineer
- Implementation matters but API surface matters MORE — every public symbol is a commitment
- Type definitions (TypeScript, type stubs for Python, .d.ts, etc.)

### Phase 6 Test
- Coverage on public API: 100% target
- Doctest where applicable
- Cross-version test matrix (test against multiple host runtime versions)
- Smoke test: can a fresh install + minimal usage work?

### Phase 8 Release
- Version bump per semver (no breaking changes in patch / minor)
- CHANGELOG with explicit "BREAKING:" markers
- Migration guide if breaking
- Documentation updated (API ref + examples)
- Publish to registry
- Tag + GitHub release

## Specialists most active

- architect (heavy — API design)
- backend-engineer
- test-engineer
- code-reviewer (multi-model — API change review)
- technical-writer (Content cross-Lead) for docs

## Library-specific concerns

- Every public symbol is now your commitment (deprecate-rather-than-remove)
- Breaking changes need migration paths
- Documentation is product
- Examples in README must work (run them in CI)
- Type definitions are part of the API
- License chosen and stuck to
