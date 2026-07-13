# Adding a Specialist

Specialists are role-based work instructions. Each gets a frontmatter contract, markdown body, and a routing entry in `shared/specialist-runtime-map.tsv`.

## Frontmatter template

Every specialist file starts with:

```yaml
---
specialist: my-specialist-name
version: 2.0
department: coding | content | content-engineer | research | security | sysmgmt | shared
lane: claude | codex | gemini | kimi
model_key: default | hard | deep | highspeed | code
required_tools:
  - mcp_server:tool_name
  - another_server:another_tool
preferred_tools:
  - optional_server:optional_tool
safety_level: low | medium | high
---
```

**Required fields:**
- `specialist`: unique identifier, kebab-case (e.g., `security-analyst`)
- `version`: always `2.0` for new specialists
- `department`: where specialist markdown lives
- `lane`: best model for this work (claude, codex, gemini, kimi)
- `model_key`: which model variant from `config/models.yaml` (see Model selection below)
- `required_tools`: MCP tools that MUST be available; task fails pre-flight if unavailable
- `safety_level`: low/medium/high; triggers review rules in `shared/lifecycle.md`

**Optional fields:**
- `preferred_tools`: nice-to-have tools specialist has discretion to use

**Safety levels:**
- `low`: mechanical work, no review needed (copywriter, editor, voice-narrator)
- `medium`: moderate risk, reviews for drift/quality (backend-engineer, research)
- `high`: security/privacy/judgment work, mandatory review (security-analyst, architect, memory-curator)

## How to pick lane and model_key

**Lane selection:**

Consult `shared/specialist-runtime-map.tsv` for existing specialists in your domain.

| Lane | Best fit |
|---|---|
| **claude** | Safety, judgment, architecture, privacy, memory, operator-sensitive work |
| **codex** | Code edits, tests, refactors, PoC mechanics, implementation review |
| **gemini** | Visual/media work, content production, brand voice, multimodal review |
| **kimi** | Source-heavy scouting, long-context reading, extraction, synthesis |

**Model_key selection:**

Look up your lane in `config/models.yaml`:

```yaml
lanes:
  claude:
    default: claude-sonnet-5
    hard: claude-opus-4-8
  codex:
    default: gpt-5
  gemini:
    default: gemini-3.5-flash
    deep: gemini-3.1-pro-preview
  kimi:
    default: kimi-k2.7-code
    highspeed: kimi-k2.7-code-highspeed
```

Use:
- `default` for routine work
- `hard` (Claude) / `deep` (Gemini) for judgment-heavy or expensive calls
- `highspeed` (Kimi) for fast turnarounds on simpler tasks
- `code` (Kimi) when code synthesis is critical

## How to declare required_tools

Check `shared/tool-catalog.md` for available tools per lane.

Format: `mcp_server:tool_name` or `github:pull_request_read`.

**Example combinations:**

Security work:
```yaml
required_tools:
  - chrono-vault:kg_query
  - github:pull_request_read
  - context7:query-docs
```

Content production:
```yaml
required_tools:
  - chrono-content-engineer:higgsfield__generate_video
  - chrono-vault:kg_query
```

Browser-based scraping:
```yaml
required_tools:
  - playwright:browser_find
  - chrome-devtools:evaluate_script
  - chrono-vault:kg_query
```

Research:
```yaml
required_tools:
  - chrono-research-arsenal:arxiv_search
  - chrono-research-arsenal:perplexity_search_web
  - chrono-vault:kg_query
```

**Pre-flight validation:**

The daemon checks that all `required_tools` are available in the destination lane. If a tool is unavailable, the task fails before dispatch.

## File location

Specialist markdown files live under:

```
departments/{department}/specialists/{specialist}.md
```

**Departments:**
- `departments/coding/specialists/` — backend-engineer, frontend-engineer, etc.
- `departments/content/specialists/` — brand-voice, editor, technical-writer
- `departments/content-engineer/specialists/` — video-director, music-composer, sound-designer
- `departments/research/specialists/` — research, scout, synthesizer
- `departments/security/specialists/` — security-analyst, exploit-developer, impact-validator
- `departments/sysmgmt/specialists/` — mac-ops, harness-optimizer, memory-curator
- `shared/specialists/` — cross-cutting specialists (planner, triage, vibecoding-check, skeptic)

Create the file:

```bash
touch departments/coding/specialists/my-specialist.md
```

## Specialist markdown body

After frontmatter, write your specialist instructions in markdown. Example:

```markdown
---
specialist: security-analyzer
...
---

## Role

You are a security analyzer. Your job is to review code for vulnerabilities and produce clear findings.

## Approach

1. Read the target code carefully
2. Check for common vulnerability classes (injection, auth bypass, data leakage, etc.)
3. Rate severity using CVSS if applicable
4. Produce structured findings with remediation

## Acceptance criteria

- Findings are specific to lines/functions
- Each finding includes severity, impact, and remediation
- No false positives
- Results are concise (one-pager max)
```

## Routing entry

Add a row to `shared/specialist-runtime-map.tsv`:

```
my-specialist	lane	review_model	department	required_tools_mcp_api	safety_level	preferred_tools	notes
```

**Example:**

```
security-analyzer	claude	gpt-codex	security	chrono-vault,github:pull_request_read,context7:query-docs	high	chrono-research-arsenal	Code review for vulnerabilities; Codex helps trace execution paths.
```

## Testing

### Manual dispatch

Start the daemon:

```bash
cd daemon
python main.py
```

In another terminal, send a test task:

```bash
curl -X POST http://127.0.0.1:9876/task \
  -H "Content-Type: application/json" \
  -d '{
    "specialist": "my-specialist",
    "lane": "claude",
    "model_key": "default",
    "required_tools": ["chrono-vault:kg_query"],
    "prompt": "Test: analyze this code for vulnerabilities..."
  }'
```

Expected response:

```json
{
  "task_id": "t-abc-123-4567",
  "status": "queued",
  "lane": "claude",
  "specialist": "my-specialist"
}
```

### Check outbox

Once the specialist completes, check:

```bash
cat daemon/state/outbox/claude/t-abc-123-4567.md
```

Should contain:
- Task result
- Tools used with call counts
- Token usage (if available)
- Duration

### Validation

Run the validation script:

```bash
bash bin/validate-specialists.sh
```

Checks:
- All specialists in specialist-runtime-map.tsv have corresponding .md files
- All .md files have valid frontmatter (specialist, version, lane, department, etc.)
- All required_tools exist in `shared/tool-catalog.md`
- No duplicates or orphan entries

## Updating specialist-runtime-map.tsv

After creating your specialist, update the routing map:

```bash
# View current entries
head -20 shared/specialist-runtime-map.tsv

# Add your row (preserve tab-separated format)
echo "my-specialist	claude	gpt-codex	security	chrono-vault,github:pull_request_read	high	chrono-research-arsenal	One-line description" >> shared/specialist-runtime-map.tsv
```

## Review gates

If `safety_level: high`, tasks using this specialist will trigger mandatory review.

See `shared/lifecycle.md` for review rules:
- Security findings, bounty reports, privacy/PII work require review
- Deletes, credential changes, public release changes require review
- Reviewers are read-only by default
- If reviewer finds required fix, Chrono creates a later serialized write pass

## Lifecycle & refresh

Specialists are versioned via `version: 2.0` in frontmatter.

- Upgrades require operator approval (no auto-promotion)
- Drift detection runs weekly (harness-optimizer specialist)
- Changes to safety_level or required_tools require `shared/specialist-runtime-map.tsv` update + git commit

## See also

- Architecture: `docs/architecture.md` § Specialists
- Protocol: `shared/protocol.md` (task packet schema)
- Routing map: `shared/specialist-runtime-map.tsv` (canonical source-of-truth)
- Tool catalog: `shared/tool-catalog.md` (all MCP tools per lane)
- Lifecycle: `shared/lifecycle.md` (review gates, safety levels, session management)
- Design spec: `docs/superpowers/specs/2026-07-11-vibe-squad-redesign-design.md` § 5 (Specialists)
