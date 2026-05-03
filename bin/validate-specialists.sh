#!/usr/bin/env bash
# bin/validate-specialists.sh — Validate v1.1 schema across all 39 specialist files.
# - Required sections present
# - Cited MCPs are in api-catalog verified-yes entries
# - Cited skills exist in local catalog
# - Peer-specialist refs resolve

set -uo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
CATALOG="${VAULT}/shared/api-catalog.md"

REQUIRED_SECTIONS=(
    "## Tools available to me"
    "## When to fan out"
    "## When to escalate"
    "## What I do NOT do"
)

# Build verified-MCP set from api-catalog
# Look for entries in chrono MCPs squad-wide section + per-CLI sections marked verified: yes
VERIFIED_MCPS=$(awk '
    /^### / { current_entry = $0; next }
    /^- verified: yes/ { print current_entry }
    /verified per pane:/ { in_pane_matrix=1; next }
    in_pane_matrix && /yes/ { print current_entry; in_pane_matrix=0 }
    /^### / { in_pane_matrix=0 }
' "$CATALOG" | grep -oE "chrono-[a-z-]+|sequential-thinking|playwright|chrome-devtools|context7|perplexity|elevenlabs|figma|firebase|sentry|linear|search|computer-use" | sort -u)

# Build local skill set
LOCAL_SKILLS=$(find "${HOME}/.claude/plugins/cache" -path "*/skills/*" -name "SKILL.md" 2>/dev/null | sed 's|.*/skills/||; s|/SKILL.md$||' | sort -u)

# Validate each specialist
EXIT_CODE=0
TOTAL=0; PASSED=0; FAILED=0

for spec_file in "$VAULT"/departments/*/specialists/*.md; do
    TOTAL=$((TOTAL + 1))
    issues=()

    # Check required sections
    for section in "${REQUIRED_SECTIONS[@]}"; do
        if ! grep -qF "$section" "$spec_file"; then
            issues+=("missing-section: $section")
        fi
    done

    # Extract cited MCPs (within ### MCPs section, format: `name`)
    # Flag-pattern (not awk range) — range form `/^### MCPs/,/^### /` collapses
    # to 1 line because the start header itself matches `^### `.
    cited_mcps=$(awk '/^### MCPs/{flag=1; next} flag && /^### /{flag=0} flag' "$spec_file" | grep -oE '`[a-z][a-z-]*`' | tr -d '`' | grep -v "^FILL$" | sort -u)
    for mcp in $cited_mcps; do
        if ! echo "$VERIFIED_MCPS" | grep -qF "$mcp" 2>/dev/null; then
            # Allow common-known MCPs not yet in catalog (best-effort)
            issues+=("unverified-mcp: $mcp")
        fi
    done

    # Extract cited skills (within ### Skills section) — flag-pattern, not range
    cited_skills=$(awk '/^### Skills/{flag=1; next} flag && /^### /{flag=0} flag' "$spec_file" | grep -oE '`[a-z][a-z0-9_-]*`' | tr -d '`' | grep -v "^FILL$" | sort -u)
    for skill in $cited_skills; do
        if ! echo "$LOCAL_SKILLS" | grep -qFx "$skill" 2>/dev/null; then
            issues+=("missing-skill: $skill")
        fi
    done

    # Peer-specialist references in fan-out section — flag-pattern, not range
    cited_peers=$(awk '/^## When to fan out/{flag=1; next} flag && /^## /{flag=0} flag' "$spec_file" | grep -oE '`[a-z][a-z-]*`' | tr -d '`' | grep -v "^FILL$" | sort -u)
    for peer in $cited_peers; do
        if ! find "$VAULT/departments" -name "${peer}.md" -path "*/specialists/*" -print -quit | grep -q .; then
            issues+=("missing-peer-specialist: $peer")
        fi
    done

    # Output JSON line
    if [ ${#issues[@]} -eq 0 ]; then
        printf '{"file":"%s","status":"pass","issues":[]}\n' "$spec_file"
        PASSED=$((PASSED + 1))
    else
        issues_json=$(printf '"%s",' "${issues[@]}" | sed 's/,$//')
        printf '{"file":"%s","status":"fail","issues":[%s]}\n' "$spec_file" "$issues_json"
        FAILED=$((FAILED + 1))
        EXIT_CODE=1
    fi
done

# Summary to stderr
echo "" >&2
echo "Total: $TOTAL  Passed: $PASSED  Failed: $FAILED" >&2

exit $EXIT_CODE
