#!/usr/bin/env bash
# bin/validate-specialists.sh — Validate specialist schema and routing references.
# - Required sections present
# - Cited MCPs are in api-catalog verified-yes entries
# - Model-lane native agent adapters exist for every runtime-map specialist
# - Cited skills exist in local catalog
# - Peer-specialist refs resolve

set -uo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
CATALOG="${VAULT}/shared/api-catalog.md"
RUNTIME_MAP="${VAULT}/shared/specialist-runtime-map.tsv"

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
' "$CATALOG" | grep -oE "chrono-[a-z-]+|sequential-?thinking|playwright|chrome-devtools|context7|perplexity|elevenlabs|figma|firebase|sentry|linear|search|computer-use" | sort -u)

# Build local skill set from both Claude plugin cache and repo-owned squad
# skills. Specialist files are validated against the repo first because this
# public repo must be self-describing even when a developer's personal plugin
# cache is empty.
LOCAL_SKILLS=$(
    {
        find "${VAULT}/shared/skills" -maxdepth 1 -type f -name "*.md" -exec basename {} .md \; 2>/dev/null
        sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "${VAULT}/shared/skills/catalog.txt" 2>/dev/null
        find "${HOME}/.claude/plugins/cache" -path "*/skills/*" -name "SKILL.md" 2>/dev/null | sed 's|.*/skills/||; s|/SKILL.md$||'
    } | sort -u
)

# Validate each specialist
EXIT_CODE=0
TOTAL=0; PASSED=0; FAILED=0; warnings=0

specialist_exists() {
    local name="$1"
    [[ -z "$name" ]] && return 1
    find "$VAULT/departments" -path "*/specialists/${name}.md" -type f -print -quit | grep -q . && return 0
    find "$VAULT/shared/specialists" -maxdepth 1 -name "${name}.md" -type f -print -quit 2>/dev/null | grep -q . && return 0
    return 1
}

map_has_specialist() {
    local name="$1"
    [[ -f "$RUNTIME_MAP" ]] || return 1
    awk -F '\t' -v s="$name" '$1 == s {found=1} END {exit(found ? 0 : 1)}' "$RUNTIME_MAP"
}

# Canonical model-lane map validation.
if [[ ! -f "$RUNTIME_MAP" ]]; then
    printf '{"file":"%s","status":"fail","issues":["missing-runtime-map"]}\n' "$RUNTIME_MAP"
    FAILED=$((FAILED + 1))
    EXIT_CODE=1
else
    while IFS= read -r line; do
        [[ "$line" == \#* || -z "$line" ]] && continue
        # Schema is exactly 8 tab-separated columns (see docs/model-runtime-map.md).
        nfields=$(awk -F'\t' '{print NF}' <<<"$line")
        IFS=$'\t' read -r specialist best_model review_model source_namespace required_tools safety_level preferred_tools notes <<<"$line"
        [[ "$specialist" == \#* || -z "$specialist" ]] && continue
        map_issues=()
        [[ "$nfields" -ne 8 ]] && map_issues+=("wrong-column-count:${nfields}-expected-8")
        [[ -z "$notes" ]] && map_issues+=("malformed-runtime-map-row")
        case "$best_model" in gpt-codex|claude|gemini|kimi) ;; *) map_issues+=("invalid-best-model:${best_model}") ;; esac
        case "$review_model" in gpt-codex|claude|gemini|kimi|none) ;; *) map_issues+=("invalid-review-model:${review_model}") ;; esac
        case "$source_namespace" in coding|security|content|content-engineer|sysmgmt|research|shared) ;; *) map_issues+=("invalid-source-namespace:${source_namespace}") ;; esac
        case "$safety_level" in low|medium|high) ;; *) map_issues+=("invalid-safety-level:${safety_level}") ;; esac
        specialist_exists "$specialist" || map_issues+=("map-specialist-file-missing:${specialist}")
        if [[ "$safety_level" == "high" && "$review_model" == "none" ]]; then
            map_issues+=("high-safety-missing-review-model:${specialist}")
        fi
        # Non-fatal flag: reviewer lane == best lane means the review is NOT cross-family.
        if [[ -n "$review_model" && "$review_model" != "none" && "$review_model" == "$best_model" ]]; then
            printf '{"file":"%s","status":"warn","issues":["same-family-review:%s(%s-reviews-%s)"]}\n' "$RUNTIME_MAP:$specialist" "$specialist" "$review_model" "$best_model"
            warnings=$((warnings + 1))
        fi
        if [ ${#map_issues[@]} -gt 0 ]; then
            issues_json=$(printf '"%s",' "${map_issues[@]}" | sed 's/,$//')
            printf '{"file":"%s","status":"fail","issues":[%s]}\n' "$RUNTIME_MAP:$specialist" "$issues_json"
            FAILED=$((FAILED + 1))
            EXIT_CODE=1
        fi
    done < "$RUNTIME_MAP"
fi

for spec_file in "$VAULT"/departments/*/specialists/*.md "$VAULT"/shared/specialists/*.md; do
    [[ -f "$spec_file" ]] || continue
    TOTAL=$((TOTAL + 1))
    issues=()

    # Check required sections
    for section in "${REQUIRED_SECTIONS[@]}"; do
        if ! grep -qF "$section" "$spec_file"; then
            issues+=("missing-section: $section")
        fi
    done

    if grep -q '<FILL:' "$spec_file"; then
        issues+=("fill-placeholder-present")
    fi

    spec_name="$(basename "$spec_file" .md)"
    if ! map_has_specialist "$spec_name"; then
        issues+=("missing-runtime-map-entry:${spec_name}")
    fi

    # Extract cited MCPs (within MCP section, format: `name`)
    # Flag-pattern (not awk range) — range form `/^### MCPs/,/^### /` collapses
    # to 1 line because the start header itself matches `^### `.
    cited_mcps=$(awk '/^### (Expected )?MCPs/{flag=1; next} flag && /^### /{flag=0} flag' "$spec_file" | grep -oE '`[a-z][a-z-]*`' | tr -d '`' | grep -v "^FILL$" | sort -u)
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
        if ! {
            find "$VAULT/departments" -name "${peer}.md" -path "*/specialists/*" -print -quit
            find "$VAULT/shared/specialists" -maxdepth 1 -name "${peer}.md" -print -quit 2>/dev/null
        } | grep -q .; then
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

# shared/specialists/*.md are validated in the main loop above (which now includes
# them and runs the full section/MCP/skill/peer + runtime-map-entry checks), so no
# separate shared-only pass is needed.

# Validate model-lane native adapter registration. These adapters are thin
# wrappers around canonical markdown; they make native subagent dispatch honest
# while keeping markdown files as the source of truth.
if [[ -f "$RUNTIME_MAP" ]]; then
    while IFS=$'\t' read -r specialist best_model _review_model _source_namespace _required_tools _safety_level _notes; do
        [[ "$specialist" == \#* || -z "$specialist" ]] && continue
        adapter_issue=""
        case "$best_model" in
            gpt-codex)
                agent_name="${specialist//-/_}"
                adapter="$VAULT/model-lanes/gpt-codex/.codex/agents/${specialist}.toml"
                if [[ ! -f "$adapter" ]]; then
                    adapter_issue="missing-codex-agent-adapter:${specialist}"
                elif ! grep -q "name = \"${agent_name}\"" "$adapter"; then
                    adapter_issue="codex-agent-name-mismatch:${specialist}"
                fi
                ;;
            claude)
                adapter="$VAULT/model-lanes/claude/.claude/agents/${specialist}.md"
                [[ -f "$adapter" ]] || adapter_issue="missing-claude-agent-adapter:${specialist}"
                ;;
            gemini)
                adapter="$VAULT/model-lanes/gemini/.gemini/agents/${specialist}.md"
                if [[ ! -f "$adapter" ]]; then
                    adapter_issue="missing-gemini-agent-adapter:${specialist}"
                elif [[ "$(head -n 1 "$adapter")" != "---" ]]; then
                    adapter_issue="gemini-agent-missing-frontmatter:${specialist}"
                elif ! grep -q "^name: ${specialist}$" "$adapter"; then
                    adapter_issue="gemini-agent-name-mismatch:${specialist}"
                fi
                ;;
            kimi)
                adapter="$VAULT/model-lanes/kimi/subagents/${specialist}.yaml"
                if [[ ! -f "$adapter" ]]; then
                    adapter_issue="missing-kimi-agent-adapter:${specialist}"
                elif ! grep -q "^[[:space:]]*${specialist}:" "$VAULT/model-lanes/kimi/main.yaml"; then
                    adapter_issue="kimi-main-missing-subagent:${specialist}"
                fi
                ;;
        esac
        if [[ -n "$adapter_issue" ]]; then
            printf '{"file":"%s","status":"fail","issues":["%s"]}\n' "$RUNTIME_MAP:$specialist" "$adapter_issue"
            FAILED=$((FAILED + 1))
            EXIT_CODE=1
        fi
    done < "$RUNTIME_MAP"
fi

for gemini_md in "$VAULT"/model-lanes/gemini/.gemini/agents/*.md; do
    [[ -f "$gemini_md" ]] || continue
    gemini_file="$(basename "$gemini_md")"
    if [[ "$(head -n 1 "$gemini_md")" != "---" ]]; then
        printf '{"file":"%s","status":"fail","issues":["gemini-agent-file-missing-frontmatter:%s"]}\n' "$gemini_md" "$gemini_file"
        FAILED=$((FAILED + 1))
        EXIT_CODE=1
    fi
done

# Validate route/invocation references in canonical instruction surfaces.
# This catches mode docs dispatching fake subagents even when every specialist
# file individually validates.
ROUTE_FILES=(
    "$VAULT"/shared/modes/*.md
    "$VAULT"/chrono/CLAUDE.md
    "$VAULT"/chrono/operator-setup.md
    "$VAULT"/chrono/SPECIALIST-INDEX.md
    "$VAULT"/departments/*/NAMESPACE.md
)

STALE_ROUTE_NAMES=(
    quick-lookup
    scope-checker
    legal-guard
    code-auditor
    variant-analyst
    chain-constructor
    cvss-scorer
    product-analyst
    repo-scout
)

for route_file in "${ROUTE_FILES[@]}"; do
    [[ -f "$route_file" ]] || continue
    route_issues=()

    for stale in "${STALE_ROUTE_NAMES[@]}"; do
        if grep -qE "(subagent_type=${stale}|@${stale}\\b|\\b${stale}\\b)" "$route_file"; then
            route_issues+=("stale-route-reference:${stale}")
        fi
    done

    if [[ "$route_file" == "$VAULT"/shared/modes/*.md ]]; then
        if ! grep -q "vibecoding-check" "$route_file"; then
            route_issues+=("mode-missing-vibecoding-check")
        fi
    fi

    while IFS= read -r ref; do
        [[ -n "$ref" ]] || continue
        canonical="${ref//_/-}"
        specialist_exists "$canonical" || route_issues+=("missing-subagent-reference:${ref}")
    done < <(grep -oE 'subagent_type=[A-Za-z0-9_-]+' "$route_file" 2>/dev/null | sed 's/subagent_type=//' | sort -u)

    while IFS= read -r ref; do
        [[ -n "$ref" ]] || continue
        canonical="${ref//_/-}"
        specialist_exists "$canonical" || route_issues+=("missing-at-reference:${ref}")
    done < <(grep -oE '@[a-z][a-z0-9-]+' "$route_file" 2>/dev/null | tr -d '@' | sort -u)

    if [ ${#route_issues[@]} -gt 0 ]; then
        issues_json=$(printf '"%s",' "${route_issues[@]}" | sed 's/,$//')
        printf '{"file":"%s","status":"fail","issues":[%s]}\n' "$route_file" "$issues_json"
        FAILED=$((FAILED + 1))
        EXIT_CODE=1
    fi
done

# Summary to stderr
echo "" >&2
echo "Total: $TOTAL  Passed: $PASSED  Failed: $FAILED  Warnings(non-fatal): $warnings" >&2

exit $EXIT_CODE
