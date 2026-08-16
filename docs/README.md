# Vibe Squad documentation

New here? Start with [Getting started](getting-started.md). It covers the private
memory boundary, native model CLI authentication, the health check, and the first
launch.

- [Install](install/README.md) — the supported install path in order, with a
  **check** after every step. Required steps 1–5, optional 6–7.

## Understand the system

- [Architecture](architecture.md) — the coordinator, isolated workers, review,
  and settlement flow.
- [Model runtime map](model-runtime-map.md) — how a specialist is routed to
  Codex, Claude, Gemini, or Kimi.
- [Project](../shared/modes/project.md) — the build and delivery workflow.
- [Bounty](../shared/modes/bounty.md) — the authorized security workflow.

Project and Bounty are the only operating modes. Content and media work is a
Project capability, not another mode.

## Operate and extend

- [Private configuration](private-config.md) — what must stay off Git.
- [Production readiness](production-readiness.md) — release checks and known
  limits.
- [Git hooks](git-hooks.md) — local leak and consistency checks.
- [Add a specialist](adding-a-specialist.md) — extend the Markdown roster.
- [Security tooling](tooling/security-arsenal-guide.md) — optional, guarded
  security capabilities.

## Where the truth lives

Vibe Squad is Markdown-first. Human-readable mode, capability, specialist, and
policy files define intent and judgment. Small scripts enforce the boundaries
that should not depend on judgment: process isolation, declared write scope,
independent review, private-data separation, and atomic settlement.

This index lists maintained public documentation. Working notes, private
operator data, migration records, and release evidence are intentionally not
part of the public export.
