#!/usr/bin/env bash
# bin/validate-specialists.sh — Validate specialist schema and routing references.
# - Required sections present
# - Cited MCPs are in api-catalog verified-yes entries
# - Model-lane native agent adapters exist for every runtime-map specialist
# - Cited skills exist in local catalog
# - Peer-specialist refs resolve

# The maintained schema engine is a single cached Python parse. The capability-
# home semantic gate runs immediately after it; the historical shell
# implementation below remains inert provenance.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VALIDATION_ROOT="${VAULT_ROOT:-${REPO_ROOT}}"
python3 "${REPO_ROOT}/scripts/python/validate_specialists.py" \
    --root "${VALIDATION_ROOT}" "$@"
specialist_status=$?

if [[ "${SQUAD_SKIP_CAPABILITY_HOME_GATE:-0}" == "1" ]]; then
    echo "SKIP capability-home gate: SQUAD_SKIP_CAPABILITY_HOME_GATE=1" >&2
    exit "$specialist_status"
fi

python3 "${REPO_ROOT}/scripts/python/validate_capability_homes.py" \
    --repo-root "${VALIDATION_ROOT}"
capability_status=$?

if (( specialist_status != 0 )); then
    exit "$specialist_status"
fi
exit "$capability_status"

set -uo pipefail
VAULT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
CATALOG="${VAULT}/shared/api-catalog.md"
RUNTIME_MAP="${VAULT}/shared/specialist-runtime-map.tsv"
PROFILE_REGISTRY="${VAULT}/shared/registries/profiles.tsv"
POLICY_REGISTRY="${VAULT}/shared/registries/policies.tsv"
TOOL_REGISTRY="${VAULT}/shared/registries/skill-tool-registry.tsv"
EXPECTED_RUNTIME_ROWS=69
STRICT_ADAPTERS="${STRICT_ADAPTERS:-0}"

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

profile_exists() {
    awk -F '\t' -v id="$1" 'NR > 1 && $1 == id { found=1 } END { exit(found ? 0 : 1) }' "$PROFILE_REGISTRY"
}

profile_lane() {
    awk -F '\t' -v id="$1" 'NR > 1 && $1 == id { print $2; exit }' "$PROFILE_REGISTRY"
}

policy_exists() {
    awk -F '\t' -v id="$1" 'NR > 1 && $1 == id { found=1 } END { exit(found ? 0 : 1) }' "$POLICY_REGISTRY"
}

policy_family() {
    awk -F '\t' -v id="$1" 'NR > 1 && $1 == id { print $2; exit }' "$POLICY_REGISTRY"
}

is_bracket_list() {
    [[ "$1" =~ ^\[[^]]*\]$ ]]
}

bracket_list_items() {
    local value="$1" item
    is_bracket_list "$value" || return 0
    value="${value#[}"
    value="${value%]}"
    [[ -n "$value" ]] || return 0
    IFS=',' read -ra items <<<"$value"
    for item in "${items[@]}"; do
        item="${item# }"; item="${item% }"
        [[ -n "$item" ]] && printf '%s\n' "$item"
    done
}

tool_registry_has() {
    [[ -f "$TOOL_REGISTRY" ]] || return 1
    awk -F '\t' -v name="$1" 'NR > 1 && $1 == name { found=1; exit } END { exit(found ? 0 : 1) }' "$TOOL_REGISTRY"
}

list_has_only() {
    local value="$1" allowed="$2" item
    is_bracket_list "$value" || return 1
    value="${value#[}"
    value="${value%]}"
    [[ -z "$value" ]] && return 0
    IFS=',' read -ra items <<<"$value"
    for item in "${items[@]}"; do
        item="${item# }"; item="${item% }"
        [[ " $allowed " == *" $item "* ]] || return 1
    done
}

# Canonical routing configuration validation. The final schema is deliberately
# strict: every routing decision is explicit and all profile/policy references
# are foreign keys into the two registries.
EXPECTED_HEADER=$'specialist\tsource_namespace\tcapability_class\tsafety_level\tsafety_tags\ttool_profile\tprimary_lane\tprimary_profile\tbackup_lane\tbackup_profile\tescalate_lane\tescalate_profile\tescalation_policy\treview_lane\treview_profile\tanti_affinity\tthroughput_lane\tthroughput_profile\tthroughput_policy\tfailover_policy\toperator_gate\theightened_risk\trequires_approval\trequired_tools\tpreferred_tools\tnotes\ttags\tversion'

for registry in "$PROFILE_REGISTRY" "$POLICY_REGISTRY"; do
    registry_issues=()
    if [[ ! -f "$registry" ]]; then
        registry_issues+=("missing-registry")
    else
        if [[ "$registry" == "$PROFILE_REGISTRY" ]]; then
            expected_registry_header=$'profile_id\tlane\tmodel_id\teffort\tflags\tusage'
            expected_registry_fields=6
        else
            expected_registry_header=$'policy_id\tfamily\tdescription'
            expected_registry_fields=3
        fi
        [[ "$(head -n 1 "$registry")" == "$expected_registry_header" ]] || registry_issues+=("wrong-registry-header")
        bad_registry_fields=$(awk -F '\t' -v n="$expected_registry_fields" 'NF != n { printf "%s:%s,", NR, NF }' "$registry")
        [[ -z "$bad_registry_fields" ]] || registry_issues+=("wrong-registry-column-count:${bad_registry_fields%,}")
        duplicate_ids=$(tail -n +2 "$registry" | cut -f1 | sort | uniq -d | paste -sd, -)
        [[ -z "$duplicate_ids" ]] || registry_issues+=("duplicate-registry-ids:${duplicate_ids}")
        if ! diff -q <(tail -n +2 "$registry" | cut -f1) <(tail -n +2 "$registry" | cut -f1 | sort) >/dev/null; then
            registry_issues+=("registry-not-sorted")
        fi
        if [[ "$registry" == "$PROFILE_REGISTRY" ]]; then
            invalid_registry_value=$(awk -F '\t' 'NR > 1 && $2 !~ /^(codex|claude|gemini|kimi)$/ { print $1 ":" $2; exit }' "$registry")
        else
            invalid_registry_value=$(awk -F '\t' 'NR > 1 && $2 !~ /^(escalation|failover|throughput)$/ { print $1 ":" $2; exit }' "$registry")
        fi
        [[ -z "$invalid_registry_value" ]] || registry_issues+=("invalid-registry-value:${invalid_registry_value}")
    fi
    if [ ${#registry_issues[@]} -gt 0 ]; then
        issues_json=$(printf '"%s",' "${registry_issues[@]}" | sed 's/,$//')
        printf '{"file":"%s","status":"fail","issues":[%s]}\n' "$registry" "$issues_json"
        FAILED=$((FAILED + 1)); EXIT_CODE=1
    fi
done

if [[ ! -f "$RUNTIME_MAP" ]]; then
    printf '{"file":"%s","status":"fail","issues":["missing-runtime-map"]}\n' "$RUNTIME_MAP"
    FAILED=$((FAILED + 1)); EXIT_CODE=1
elif [[ ! -f "$PROFILE_REGISTRY" || ! -f "$POLICY_REGISTRY" ]]; then
    printf '{"file":"%s","status":"fail","issues":["cannot-validate-map-without-registries"]}\n' "$RUNTIME_MAP"
    FAILED=$((FAILED + 1)); EXIT_CODE=1
else
    map_global_issues=()
    [[ "$(head -n 1 "$RUNTIME_MAP")" == "$EXPECTED_HEADER" ]] || map_global_issues+=("wrong-runtime-map-header")
    map_row_count=$(( $(wc -l < "$RUNTIME_MAP") - 1 ))
    [[ "$map_row_count" -eq "$EXPECTED_RUNTIME_ROWS" ]] || map_global_issues+=("wrong-row-count:${map_row_count}-expected-${EXPECTED_RUNTIME_ROWS}")
    bad_map_fields=$(awk -F '\t' 'NF != 28 { printf "%s:%s,", NR, NF }' "$RUNTIME_MAP")
    [[ -z "$bad_map_fields" ]] || map_global_issues+=("wrong-column-count:${bad_map_fields%,}")
    duplicate_specialists=$(tail -n +2 "$RUNTIME_MAP" | cut -f1 | sort | uniq -d | paste -sd, -)
    [[ -z "$duplicate_specialists" ]] || map_global_issues+=("duplicate-specialists:${duplicate_specialists}")
    if ! diff -q <(tail -n +2 "$RUNTIME_MAP" | cut -f1) <(tail -n +2 "$RUNTIME_MAP" | cut -f1 | sort) >/dev/null; then
        map_global_issues+=("runtime-map-not-sorted")
    fi
    kimi_primary_count=$(awk -F '\t' 'NR > 1 && $7 == "kimi" { n++ } END { print n+0 }' "$RUNTIME_MAP")
    [[ "$kimi_primary_count" -eq 0 ]] || map_global_issues+=("kimi-primary-forbidden:${kimi_primary_count}")
    if [ ${#map_global_issues[@]} -gt 0 ]; then
        issues_json=$(printf '"%s",' "${map_global_issues[@]}" | sed 's/,$//')
        printf '{"file":"%s","status":"fail","issues":[%s]}\n' "$RUNTIME_MAP" "$issues_json"
        FAILED=$((FAILED + 1)); EXIT_CODE=1
    fi

    while IFS=$'\t' read -r specialist source_namespace capability_class safety_level safety_tags tool_profile primary_lane primary_profile backup_lane backup_profile escalate_lane escalate_profile escalation_policy review_lane review_profile anti_affinity throughput_lane throughput_profile throughput_policy failover_policy operator_gate heightened_risk requires_approval required_tools preferred_tools notes tags version; do
        [[ "$specialist" == "specialist" || -z "$specialist" ]] && continue
        map_issues=()
        case "$source_namespace" in coding|security|content|content-engineer|sysmgmt|research|shared) ;; *) map_issues+=("invalid-source-namespace:${source_namespace}") ;; esac
        case "$capability_class" in implementation|judgment|code_review|content_text|extraction|game_design|media_production|research_synthesis|security_defense|security_reasoning) ;; *) map_issues+=("invalid-capability-class:${capability_class}") ;; esac
        case "$safety_level" in low|medium|high) ;; *) map_issues+=("invalid-safety-level:${safety_level}") ;; esac
        list_has_only "$safety_tags" "dual_use privacy financial live_target" || map_issues+=("invalid-safety-tags:${safety_tags}")
        case "$tool_profile" in none|media.elevenlabs|media.elevenlabs-agent|media.higgsfield) ;; *) map_issues+=("invalid-tool-profile:${tool_profile}") ;; esac
        # source_namespace is provenance metadata only. Routing is validated
        # exclusively from the explicit lane/profile fields below; namespace
        # membership is never translated into a model-lane decision.
        for lane_field in "$primary_lane" "$backup_lane" "$escalate_lane" "$review_lane"; do
            [[ "$lane_field" =~ ^(codex|claude|gemini|kimi)$ ]] || map_issues+=("invalid-routing-lane:${lane_field}")
        done
        [[ "$throughput_lane" =~ ^(none|kimi)$ ]] || map_issues+=("invalid-throughput-lane:${throughput_lane}")
        [[ "$primary_lane" != "kimi" ]] || map_issues+=("kimi-primary-forbidden")
        [[ "$primary_lane" != "$backup_lane" ]] || map_issues+=("primary-backup-same-lane:${primary_lane}")
        for lane_profile in "$primary_lane:$primary_profile" "$backup_lane:$backup_profile" "$escalate_lane:$escalate_profile" "$review_lane:$review_profile"; do
            route_lane="${lane_profile%%:*}"; route_profile="${lane_profile#*:}"
            if ! profile_exists "$route_profile"; then
                map_issues+=("unknown-profile:${route_profile}")
            elif [[ "$(profile_lane "$route_profile")" != "$route_lane" ]]; then
                map_issues+=("profile-lane-mismatch:${route_lane}:${route_profile}")
            fi
        done
        case "$anti_affinity" in none|author_family) ;; *) map_issues+=("invalid-anti-affinity:${anti_affinity}") ;; esac
        [[ "$heightened_risk" =~ ^(true|false)$ ]] || map_issues+=("invalid-heightened-risk:${heightened_risk}")
        expected_heightened=false
        case "$specialist" in security-analyst|exploit-developer|privacy-steward|threat-modeler|scout|impact-validator|smart-contract-engineer|scraping-engineer|incident-responder|detection-engineer|software-supply-chain-engineer|asset-provenance-and-rights-auditor|red-team-operator|reverse-engineer) expected_heightened=true ;; esac
        [[ "$heightened_risk" == "$expected_heightened" ]] || map_issues+=("heightened-risk-mismatch:${heightened_risk}-expected-${expected_heightened}")
        for policy_pair in "escalation:$escalation_policy" "throughput:$throughput_policy" "failover:$failover_policy"; do
            expected_family="${policy_pair%%:*}"; policy_id="${policy_pair#*:}"
            if ! policy_exists "$policy_id"; then
                map_issues+=("unknown-policy:${policy_id}")
            elif [[ "$(policy_family "$policy_id")" != "$expected_family" ]]; then
                map_issues+=("policy-family-mismatch:${expected_family}:${policy_id}")
            fi
        done
        [[ "$failover_policy" == "failover.conservative.v1" ]] || map_issues+=("invalid-failover-policy:${failover_policy}")
        if [[ "$safety_level" == "high" || "$heightened_risk" == "true" ]]; then
            [[ "$escalation_policy" == "escalation.safety_floor.v1" ]] || map_issues+=("risk-requires-safety-floor")
            [[ "$throughput_policy" == "throughput.never.v1" && "$throughput_lane" == "none" && "$throughput_profile" == "none" ]] || map_issues+=("risk-forbids-throughput")
        else
            [[ "$escalation_policy" == "escalation.signal.v1" ]] || map_issues+=("non-heightened-requires-signal-escalation")
            if [[ "$safety_level" == "medium" ]]; then
                [[ "$throughput_policy" == "throughput.never.v1" && "$throughput_lane" == "none" && "$throughput_profile" == "none" ]] || map_issues+=("medium-safety-forbids-throughput")
            elif [[ "$throughput_policy" == "throughput.downshift_gated.v1" ]]; then
                [[ "$throughput_lane" == "kimi" && "$throughput_profile" == "kimi.k2.7.bulk" ]] || map_issues+=("gated-throughput-requires-kimi-profile")
                [[ "$safety_tags" == "[]" ]] || map_issues+=("sensitive-tag-forbids-throughput")
            elif [[ "$throughput_policy" == "throughput.never.v1" ]]; then
                [[ "$throughput_lane" == "none" && "$throughput_profile" == "none" ]] || map_issues+=("never-throughput-requires-none")
            else
                map_issues+=("invalid-low-safety-throughput-policy:${throughput_policy}")
            fi
        fi
        list_has_only "$operator_gate" "delete cleanup credential_change public_release paid_media live_outreach production_mutation offensive_execution malware_detonation" || map_issues+=("invalid-operator-gate:${operator_gate}")
        is_bracket_list "$requires_approval" || map_issues+=("invalid-requires-approval:${requires_approval}")
        is_bracket_list "$required_tools" || map_issues+=("invalid-required-tools:${required_tools}")
        is_bracket_list "$preferred_tools" || map_issues+=("invalid-preferred-tools:${preferred_tools}")
        for tool_pair in "required:${required_tools}" "preferred:${preferred_tools}"; do
            tool_kind="${tool_pair%%:*}"; tool_list="${tool_pair#*:}"
            while IFS= read -r tool_ref; do
                [[ -n "$tool_ref" ]] || continue
                if [[ "$tool_ref" == "grok_reason" || "$tool_ref" == *":grok_reason" ]]; then
                    map_issues+=("stale-tool-token:${tool_kind}:${tool_ref}")
                elif ! tool_registry_has "$tool_ref"; then
                    printf '{"file":"%s","status":"warn","issues":["unresolved-tool-reference:%s:%s:%s"]}\n' "$RUNTIME_MAP:$specialist" "$tool_kind" "$tool_ref" "warning-mode"
                    warnings=$((warnings + 1))
                fi
            done < <(bracket_list_items "$tool_list")
        done
        is_bracket_list "$tags" || map_issues+=("invalid-tags:${tags}")
        [[ -n "$notes" ]] || map_issues+=("missing-notes")
        [[ "$version" =~ ^[0-9]+\.[0-9]+$ ]] || map_issues+=("invalid-version:${version}")
        specialist_exists "$specialist" || map_issues+=("map-specialist-file-missing:${specialist}")
        if [ ${#map_issues[@]} -gt 0 ]; then
            issues_json=$(printf '"%s",' "${map_issues[@]}" | sed 's/,$//')
            printf '{"file":"%s","status":"fail","issues":[%s]}\n' "$RUNTIME_MAP:$specialist" "$issues_json"
            FAILED=$((FAILED + 1)); EXIT_CODE=1
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
    cited_mcps=$(awk '/^### (Expected )?MCPs/{flag=1; next} flag && /^### /{flag=0} flag' "$spec_file" | sed -nE 's/^[[:space:]]*-[[:space:]]*`([a-z][a-z-]*)`.*/\1/p' | grep -v "^FILL$" | sort -u)
    for mcp in $cited_mcps; do
        if ! echo "$VERIFIED_MCPS" | grep -qF "$mcp" 2>/dev/null; then
            # Allow common-known MCPs not yet in catalog (best-effort)
            issues+=("unverified-mcp: $mcp")
        fi
    done

    # Extract cited skills (within ### Skills section) — flag-pattern, not range
    skill_block=$(awk '/^### Skills/{flag=1; next} flag && /^### /{flag=0} flag' "$spec_file")
    cited_skills=$(printf '%s\n' "$skill_block" | grep -oE '`[a-z][a-z0-9_-]*`' | tr -d '`' | grep -vE '^(FILL|capability_gap|needs_tool)$' | sort -u)
    for skill in $cited_skills; do
        if ! echo "$LOCAL_SKILLS" | grep -qFx "$skill" 2>/dev/null; then
            if printf '%s\n' "$skill_block" | grep -F "\`$skill\` (proposed" >/dev/null; then
                printf '{"file":"%s","status":"warn","issues":["proposed-skill-not-registered:%s"]}\n' "$spec_file" "$skill"
                warnings=$((warnings + 1))
            else
                issues+=("missing-skill: $skill")
            fi
        fi
    done

    # Peer-specialist references in fan-out section — flag-pattern, not range
    cited_peers=$(awk '/^## When to fan out/{flag=1; next} flag && /^## /{flag=0} flag' "$spec_file" | grep -oE '`[a-z][a-z-]*`' | tr -d '`' | grep -v "^FILL$" | sort -u)
    for peer in $cited_peers; do
        if ! {
            find "$VAULT/departments" -name "${peer}.md" -path "*/specialists/*" -print -quit
            find "$VAULT/shared/specialists" -maxdepth 1 -name "${peer}.md" -print -quit 2>/dev/null
        } | grep -q .; then
            printf '{"file":"%s","status":"warn","issues":["unresolved-peer-reference:%s"]}\n' "$spec_file" "$peer"
            warnings=$((warnings + 1))
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
    while IFS=$'\t' read -r specialist _source_namespace _capability_class _safety_level _safety_tags _tool_profile primary_lane _rest; do
        [[ "$specialist" == "specialist" || -z "$specialist" ]] && continue
        adapter_issue=""
        case "$primary_lane" in
            codex)
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
            if [[ "$STRICT_ADAPTERS" == "1" ]]; then
                printf '{"file":"%s","status":"fail","issues":["%s"]}\n' "$RUNTIME_MAP:$specialist" "$adapter_issue"
                FAILED=$((FAILED + 1)); EXIT_CODE=1
            else
                printf '{"file":"%s","status":"warn","issues":["%s"]}\n' "$RUNTIME_MAP:$specialist" "$adapter_issue"
                warnings=$((warnings + 1))
            fi
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
