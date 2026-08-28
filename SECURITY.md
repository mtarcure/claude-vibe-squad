# Security Policy

## Supported versions

Vibe Squad develops on a single `main` branch — there are no release or
maintenance branches, so security fixes land on `main` and are not backported to
tagged releases. `CHANGELOG.md` records `v1.0.0`; the repository's tags are
`v1.0-pre-1.1`, `v1.1.0`, `v1.1.1`, `v1.1.2`, and `v1.1.3`. Work since the latest tag is
tracked in the changelog's `Unreleased` section.

If you are running a tagged release, update to `main` to pick up a fix.

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting**: go to the repository's
**Security** tab and choose **Report a vulnerability**. This opens a private
advisory visible only to the maintainers.

Please do not open a public issue for a security report — a public issue
discloses the problem to everyone before there is a fix.

Include what you can: the affected file or component, reproduction steps, the
impact you believe it has, and your environment (OS, model-CLI versions). A
minimal proof of concept helps; a weaponized exploit is not required.

## What to expect

This is a small project, so treat response times as best-effort rather than a
commitment. We will reproduce the issue, judge its severity, and tell you what we
conclude — including if we decide it is not a vulnerability. We ask that you hold
public disclosure until a fix has landed. Credit in the changelog or advisory is
yours if you want it, and anonymity if you prefer.

There is no paid bug bounty program for this repository.

## Scope

**In scope:** the code in this repository — the dispatch rail, the export and
leak gates, the approval-gate logic, the memory plugins, and the launcher.

**Out of scope:** vulnerabilities in the upstream model CLIs (Claude Code, Codex,
Gemini, Kimi) or their providers — report those to the vendors directly. Also out
of scope: issues that require an attacker to already have local access to the
machine running Vibe Squad, since the system runs with the operator's own
privileges by design.

## The offensive tooling in this repository

Vibe Squad ships an authorized-scope bounty mode, reconnaissance plugins, and an
exploit-development specialist role. These exist for security work you are
**authorized to perform** — your own systems, or targets covered by a written
scope such as a bug-bounty program.

Pointing them at systems you do not own and have no permission to test is
unauthorized access. That is illegal in most jurisdictions and is not a use this
project supports. The tooling includes scope gates and approval holds precisely
because "I was just testing" is not a defence.

Using this project to attack third parties is not a vulnerability in this project.
