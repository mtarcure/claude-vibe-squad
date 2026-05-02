---
name: cli-tool
extends: project
status: active
---

# Project Profile: CLI Tool

Argparse / clap / cobra / oclif command-line tools. Distributed via npm / pip / cargo / brew / homebrew.

## Auto-detection signals

- Single-binary intent (no UI, no service)
- `argparse` / `clap` / `cobra` / `commander` deps
- `bin/` directory with executable scripts
- Operator says "CLI" / "command-line tool"

## Phase customizations

### Phase 1 Intake
- Test command: `pytest` / `cargo test` / `go test` etc.
- Build: produces single binary or installable package
- Distribution: npm publish / pip publish / cargo publish / Homebrew formula / direct binary

### Phase 2 Design
- Command structure (subcommands? flat? per-noun-verb?)
- Output format (human vs machine-readable; --json flag?)
- Config file location (XDG_CONFIG, ~/.toolname, etc.)
- Help text quality

### Phase 4 Build
- backend-engineer (CLI logic)
- devops-engineer (release pipeline)
- Test stdout/stderr behavior precisely

### Phase 6 Test
- Unit tests for pure logic
- Integration: invoke the CLI binary with real args, check stdout/stderr/exit codes
- Cross-platform if applicable (macOS / Linux / Windows)

### Phase 8 Release
- Version bump (semver)
- CHANGELOG.md updated
- Tag + push
- Publish to registry (npm/pypi/crates.io)
- Homebrew formula update if applicable

## Specialists most active

- backend-engineer
- test-engineer (CLI integration tests)
- devops-engineer (release pipeline)
- technical-writer (Content cross-Lead) for README + docs

## CLI-specific concerns

- Help output is documentation — write it well
- Exit codes are part of API
- Stdout for output, stderr for diagnostics (don't mix)
- Streaming output for long-running ops
- TTY-aware behavior (color, spinners only when interactive)
- Config precedence: flag > env var > config file > default
