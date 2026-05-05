# Capability Manifests

Status: draft coverage index

Capability manifests preserve the old `claude-chrono` plugin/subagent capability surface before Vibe Squad cleanup or script consolidation. They are not optional polish. Every old plugin-backed specialist or shared plugin must receive a manifest or an explicit disposition before any old plugin source, generated agent file, script, or related skill is deleted.

## Rule

Cleanup may not remove a capability until one of these is true:

- it is represented in a current specialist file
- it is represented in a capability manifest
- it is intentionally marked private/local-only
- it is intentionally marked deprecated with rationale
- it is tested as unavailable and documented as optional

## Manifest Template

Each manifest should include:

- status
- owner
- canonical current specialist or shared file
- old plugin source path
- role contract
- preserved current behavior
- old plugin capabilities to preserve
- required tools
- optional tools
- MCPs
- skills
- adaptive operating mode
- output contract
- KG/memory behavior
- safety boundaries
- live dispatch proof
- public/private disposition
- cleanup disposition

## Coverage Plan

### Seed Manifests

- [x] `security-analyst.md`
- [x] `frontend-engineer.md`
- [x] `memory-curator.md`
- [x] `prompt-engineer.md`

### Security And Bounty

- [x] `scout.md`
- [x] `exploit-developer.md`
- [x] `impact-validator.md`
- [x] `threat-modeler.md` current-system disposition
- [x] `privacy-steward.md` current-system disposition

### Coding And Product Build

- [x] `smart-contract-engineer.md`
- [x] `backend-engineer.md`
- [x] `code-reviewer.md`
- [x] `refactor-cleaner.md`
- [x] `devops-engineer.md`
- [x] `performance-optimizer.md`
- [x] `systems-engineer.md`
- [x] `ai-engineer.md`
- [x] `test-engineer.md`
- [x] `e2e-runner.md` merge disposition recorded in `test-engineer.md`
- [x] `ui-engineer.md`
- [x] `architect.md`
- [x] `scraping-engineer.md`

### Content And Design

- [x] `designer.md`
- [x] `technical-writer.md`
- [x] `content-creator.md` if old content-engineer plugin adds unique capability
- [x] `brand-voice.md` if old prompt/content assets add unique capability
- [x] `editor.md` if old writer/reviewer flow adds unique capability
- [x] `social-strategist.md` disposition

### Research

- [x] `research.md`
- [x] `synthesizer.md`
- [x] `large-context-analyst.md`
- [x] `data-extraction-engineer.md`

### SysMgmt And AgentOps

- [x] `harness-optimizer.md`
- [x] `loop-operator.md`
- [x] `agentops.md`
- [x] `knowledge-librarian.md`
- [x] `mac-ops.md`
- [x] `finance-analyst.md` if cost/token surfaces remain in product scope

### Cross-Cutting

- [x] `skeptic.md`
- [x] `challenger.md` merge disposition recorded in `skeptic.md`
- [x] `triage.md`
- [x] `planner.md`
- [x] `summarizer.md`
- [x] `vibecoding-check.md`

### Shared Plugin Surfaces

- [x] `chrono-kg.md`
- [x] `chrono-obsidian.md`
- [x] `chrono-catalog.md`
- [x] `chrono-observability.md`
- [x] `chrono-audit.md`
- [x] `chrono-safety.md`
- [x] `chrono-dispatch.md`
- [x] `chrono-browser-agent.md`
- [x] `chrono-research-tools.md`
- [x] `shared-common-skills.md`
- [x] `shared-common-tools.md`
- [x] `chrono-modes.md`

## Priority Order

1. Security/bounty chain: `scout`, `security-analyst`, `exploit-developer`, `impact-validator`, smart-contract handoff.
2. Project build chain: `frontend-engineer`, `ui-engineer`, `test-engineer/e2e-runner`, `code-reviewer`, `backend-engineer`.
3. SysMgmt self-maintenance: `memory-curator`, `harness-optimizer`, `loop-operator`, `agentops`, shared observability/audit.
4. Research/content chain: `research`, `synthesizer`, `large-context-analyst`, `designer`, `technical-writer`.
5. Shared foundations: KG, Obsidian, catalog, safety, common skills/tools, modes.

## Done Criteria

Manifest coverage is complete when:

- every old plugin in `~/.claude/plugins/cache/claude-chrono` has a current manifest or explicit deprecation/private disposition
- every current specialist with old plugin ancestry has a manifest
- every old tool wrapper is classified as required, optional, deprecated, private, or not shipped
- every old Skill is classified as imported, pending import, deprecated, private, or not shipped
- live dispatch tests exist for each major chain
- cleanup manifests cite these dispositions before moving or deleting files
