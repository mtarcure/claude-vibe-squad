#!/bin/bash
# Email brief delivery — final nightly phase.
#
# Uses headless Claude because Gmail access is exposed through the operator's
# claude.ai MCP host, not through this repo. launchd inherits the operator's
# normal Claude config/auth path (`~/.claude.json` and `~/.claude/`), the same
# way other nightly phases inherit shell secrets.
#
# Skip conditions:
# - today's morning brief is missing or empty
# - today's brief looks trivial (no issues, no processed content, no actions)
# - `_state/email-brief-<date>.delivered` already exists
#
# Optional input:
# - `_state/newsletter-<date>.md` overrides the email body and subject when it
#   has parseable YAML frontmatter with a `subject` field. If missing or
#   malformed, this script falls back to the raw morning brief + synthesis +
#   triage summary.
#
# Disable for a day:
#   touch _state/email-brief-$(date +%F).delivered
#
# Manual test:
#   bash bin/email-brief.sh
#
# Ladder result from 2026-05-06 manual run:
# 1. Dropping `--max-budget-usd` was not enough; Claude still reported
#    "Credit balance is too low".
# 2. Dropping CLI `--allowed-tools` still returned the same credit error until
#    the environment override below was fixed; the flag is retained as the
#    narrow non-interactive grant for Gmail draft creation.
# 3. The prompt is kept minimal and the body cap is lower so this path remains
#    cheap when the operator's Claude/MCP auth path is available.
# The subprocess also unsets `ANTHROPIC_API_KEY`; when present in this shell it
# forces API-credit mode before Claude can use the local subscription/MCP auth.

set -uo pipefail

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
STATE_DIR="${STATE_DIR:-${VAULT_ROOT}/_state}"
DATE="$(date -u +%Y-%m-%d)"
WEEKDAY="$(date -u +%A)"
BRIEF="${STATE_DIR}/morning-briefs/${DATE}.md"
SYNTHESIS="${STATE_DIR}/content-synthesis-${DATE}.md"
TRIAGE="${STATE_DIR}/content-triage-${DATE}.json"
NEWSLETTER="${STATE_DIR}/newsletter-${DATE}.md"
LOG="${STATE_DIR}/cleanup-logs/${DATE}-email-brief.md"
MARKER="${STATE_DIR}/email-brief-${DATE}.delivered"
RECIPIENT="redacted@example.com"
SUBJECT="Vibe Squad morning brief — ${WEEKDAY} ${DATE}"
MAX_BODY_CHARS=6000
NEWSLETTER_BODY_CHARS=16000
NEWSLETTER_STATUS="not-present"

mkdir -p "${STATE_DIR}/cleanup-logs"

atomic_write() {
    local path="$1"
    local content="$2"
    local tmp="${path}.tmp.$$.$RANDOM"
    printf "%s" "${content}" > "${tmp}"
    python3 - "$tmp" <<'PY'
import os
import sys
with open(sys.argv[1], "rb") as fh:
    os.fsync(fh.fileno())
PY
    mv "${tmp}" "${path}"
}

append_log() {
    local text="$1"
    if [[ -f "${LOG}" ]]; then
        printf "%s\n" "${text}" >> "${LOG}"
    else
        atomic_write "${LOG}" "${text}"$'\n'
    fi
}

json_escape() {
    python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

skip_with_log() {
    local reason="$1"
    atomic_write "${LOG}" "# Email Brief — ${DATE}

Run at: $(date -u +%FT%TZ)
Status: skipped — ${reason}
"
    echo "email-brief skipped — ${reason}"
    exit 0
}

if [[ -f "${MARKER}" ]]; then
    skip_with_log "already delivered"
fi

if [[ ! -f "${BRIEF}" ]]; then
    skip_with_log "no brief to deliver"
fi

if [[ ! -s "${BRIEF}" ]]; then
    skip_with_log "brief is empty"
fi

BRIEF_TEXT="$(cat "${BRIEF}")"

is_trivial_brief() {
    local text="$1"
    if grep -qE 'warnings / [1-9][0-9]* issues|[1-9][0-9]* warnings /|### Issues|### Warnings|Top N worth reading|Processed blog artifacts|Podcast headline artifacts|Pending dream proposals|Cards for your decision|Active modes' <<< "${text}"; then
        # `Cards for your decision` and `Active modes` sections can be present
        # with `(none)`, so require non-empty content for those two.
        if grep -q 'Cards for your decision' <<< "${text}" && grep -q '\*(none pending)\*' <<< "${text}"; then
            :
        else
            return 1
        fi
        if grep -q 'Active modes' <<< "${text}" && grep -q '\*(none - all model lanes idle)\*' <<< "${text}"; then
            :
        else
            return 1
        fi
        if grep -qE 'warnings / [1-9][0-9]* issues|[1-9][0-9]* warnings /|### Issues|### Warnings|Top N worth reading|Processed blog artifacts|Podcast headline artifacts|Pending dream proposals' <<< "${text}"; then
            return 1
        fi
    fi
    if grep -q 'All systems healthy' <<< "${text}" \
       && grep -q '(no new content processed today)' <<< "${text}" \
       && grep -q '(none - all model lanes idle)' <<< "${text}"; then
        return 0
    fi
    return 1
}

if is_trivial_brief "${BRIEF_TEXT}"; then
    skip_with_log "nothing to deliver"
fi

BODY=""
if [[ -f "${NEWSLETTER}" ]]; then
    NEWSLETTER_RESULT="$(python3 - "${NEWSLETTER}" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    text = path.read_text(encoding="utf-8")
except OSError as exc:
    print(json.dumps({"ok": False, "reason": str(exc)}))
    raise SystemExit(0)

match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)(.*)$", text, re.S)
if not match:
    print(json.dumps({"ok": False, "reason": "missing frontmatter"}))
    raise SystemExit(0)

subject = ""
for line in match.group(1).splitlines():
    if not line.strip().startswith("subject:"):
        continue
    raw = line.split(":", 1)[1].strip()
    try:
        subject = json.loads(raw)
    except json.JSONDecodeError:
        subject = raw.strip("\"'")
    break

body = match.group(2).strip()
if not subject:
    print(json.dumps({"ok": False, "reason": "missing subject"}))
elif not body:
    print(json.dumps({"ok": False, "reason": "empty body"}))
else:
    print(json.dumps({"ok": True, "subject": " ".join(str(subject).split())[:120], "body": body}))
PY
)"
    NEWSLETTER_OK="$(printf "%s" "${NEWSLETTER_RESULT}" | python3 -c 'import json,sys; print(str(json.load(sys.stdin).get("ok", False)).lower())')"
    if [[ "${NEWSLETTER_OK}" == "true" ]]; then
        SUBJECT="$(printf "%s" "${NEWSLETTER_RESULT}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["subject"], end="")')"
        BODY="$(printf "%s" "${NEWSLETTER_RESULT}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["body"], end="")')"
        NEWSLETTER_STATUS="used"
    else
        NEWSLETTER_REASON="$(printf "%s" "${NEWSLETTER_RESULT}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("reason", "malformed"), end="")')"
        NEWSLETTER_STATUS="fallback: ${NEWSLETTER_REASON}"
    fi
fi

if [[ -z "${BODY}" ]]; then
    TRIAGE_SUMMARY=""
    if [[ -f "${TRIAGE}" ]]; then
        if command -v jq >/dev/null 2>&1; then
            TRIAGE_SUMMARY="$( {
                echo "## Content triage summary"
                jq -r '"- total: \(.summary.total_items // 0), depth: \(.summary.depth_count // 0), skim: \(.summary.skim_count // 0), drop: \(.summary.drop_count // 0)"' "${TRIAGE}" 2>/dev/null || true
                jq -r '.items[]? | select(.tier=="depth") | "- [" + .source_lane + "] " + .source_name + " — " + .feed_metadata.title + " (" + (.relevance_score|tostring) + "): " + .reason' "${TRIAGE}" 2>/dev/null | head -10 || true
            } )"
        else
            TRIAGE_SUMMARY="## Content triage summary
- content-triage-${DATE}.json present; install jq for inline counts."
        fi
    fi

    BODY="${BRIEF_TEXT}"
    if [[ -f "${SYNTHESIS}" ]]; then
        BODY="${BODY}

---

$(cat "${SYNTHESIS}")"
    fi
    if [[ -n "${TRIAGE_SUMMARY}" ]]; then
        BODY="${BODY}

---

${TRIAGE_SUMMARY}"
    fi
fi

BODY_LIMIT="${MAX_BODY_CHARS}"
if [[ "${NEWSLETTER_STATUS}" == "used" ]]; then
    BODY_LIMIT="${NEWSLETTER_BODY_CHARS}"
fi
BODY="$(printf "%s" "${BODY}" | python3 -c 'import sys; data=sys.stdin.read(); limit=int(sys.argv[1]); print(data[:limit] + ("\n\n[truncated for email prompt]" if len(data) > limit else ""), end="")' "${BODY_LIMIT}")"

ESCAPED_SUBJECT="$(printf "%s" "${SUBJECT}" | json_escape)"

PROMPT="Create one Gmail draft with these exact fields using mcp__claude_ai_Gmail__create_draft. Return only the draft ID.

to: [\"${RECIPIENT}\"]
subject: \"${ESCAPED_SUBJECT}\"
body: |
$(printf "%s\n" "${BODY}" | sed 's/^/    /')
"

if ! command -v claude >/dev/null 2>&1; then
    atomic_write "${LOG}" "# Email Brief — ${DATE}

Run at: $(date -u +%FT%TZ)
Status: failed
Reason: claude binary not found in PATH
"
    echo "email-brief failed — claude binary not found" >&2
    exit 1
fi

set +e
CLAUDE_RESULT="$(printf "%s" "${PROMPT}" | python3 -c '
import json
import os
import subprocess
import sys

prompt = sys.stdin.read()
cmd = [
    "claude", "-p",
    "--output-format", "text",
    "--no-session-persistence",
    "--allowed-tools", "mcp__claude_ai_Gmail__create_draft",
]
env = os.environ.copy()
env.pop("ANTHROPIC_API_KEY", None)
try:
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=300, env=env)
    payload = {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
except subprocess.TimeoutExpired as exc:
    payload = {
        "returncode": 124,
        "stdout": exc.stdout or "",
        "stderr": (exc.stderr or "") + "\nclaude command timed out after 300s",
    }
print(json.dumps(payload))
')"
RC=$?
set -e

if [[ "${RC}" -ne 0 ]]; then
    STDOUT_CONTENT=""
    STDERR_CONTENT="python subprocess wrapper failed"
    CLAUDE_RC="${RC}"
else
    CLAUDE_RC="$(printf "%s" "${CLAUDE_RESULT}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["returncode"])')"
    STDOUT_CONTENT="$(printf "%s" "${CLAUDE_RESULT}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["stdout"], end="")')"
    STDERR_CONTENT="$(printf "%s" "${CLAUDE_RESULT}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["stderr"], end="")')"
fi
if [[ "${CLAUDE_RC}" -eq 0 ]]; then
    DRAFT_ID="$(printf "%s" "${STDOUT_CONTENT}" | awk '/^r[[:alnum:]_-]+$/ {print $1; exit}')"
else
    DRAFT_ID=""
fi

LOG_BODY="# Email Brief — ${DATE}

Run at: $(date -u +%FT%TZ)
Recipient: ${RECIPIENT}
Subject: ${SUBJECT}
Newsletter: ${NEWSLETTER_STATUS}
Command: claude -p --output-format text --no-session-persistence --allowed-tools mcp__claude_ai_Gmail__create_draft
Return code: ${CLAUDE_RC}
Stdout length: ${#STDOUT_CONTENT}
Stderr length: ${#STDERR_CONTENT}
Draft ID: ${DRAFT_ID}

## Stdout

\`\`\`
${STDOUT_CONTENT}
\`\`\`

## Stderr

\`\`\`
${STDERR_CONTENT}
\`\`\`
"
atomic_write "${LOG}" "${LOG_BODY}"

if [[ "${CLAUDE_RC}" -ne 0 ]]; then
    echo "email-brief failed — claude exited ${CLAUDE_RC}" >&2
    exit "${CLAUDE_RC}"
fi

if [[ -z "${DRAFT_ID}" ]]; then
    echo "email-brief failed — no draft ID returned" >&2
    exit 1
fi

atomic_write "${MARKER}" "delivered_at: $(date -u +%FT%TZ)
draft_id: ${DRAFT_ID}
log: ${LOG#${VAULT_ROOT}/}
"

echo "email-brief delivered draft ${DRAFT_ID}"
exit 0
