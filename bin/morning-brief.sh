#!/bin/bash
# Morning brief generator — synthesizes everything from earlier nightly phases.
# This is what the operator reads first thing in the morning.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
DATE="$(date +%Y-%m-%d)"
DAY_OF_WEEK="$(date +%A)"
BRIEF="${VAULT_ROOT}/_state/morning-briefs/${DATE}.md"

mkdir -p "$(dirname "${BRIEF}")"

# Pull info from earlier phase logs
DOCTOR_LOG="${VAULT_ROOT}/_state/doctor-logs/${DATE}.md"
DOCTOR_SUMMARY="${VAULT_ROOT}/_state/doctor-logs/${DATE}-summary.json"
DREAM_LOG="${VAULT_ROOT}/_state/dream-logs/${DATE}.md"

# Compute simple stats
ISSUES_COUNT=0
WARNINGS_COUNT=0
HEALTHY_COUNT=0
ISSUES_LIST=""
WARNINGS_LIST=""
if [[ -f "${DOCTOR_SUMMARY}" ]]; then
    if command -v jq >/dev/null 2>&1; then
        ISSUES_COUNT=$(jq -r '.issue_count // 0' "${DOCTOR_SUMMARY}" 2>/dev/null || echo 0)
        WARNINGS_COUNT=$(jq -r '.warning_count // 0' "${DOCTOR_SUMMARY}" 2>/dev/null || echo 0)
        HEALTHY_COUNT=$(jq -r '.healthy_count // 0' "${DOCTOR_SUMMARY}" 2>/dev/null || echo 0)
        ISSUES_LIST=$(jq -r '.issues[]? | "- 🔔 " + .' "${DOCTOR_SUMMARY}" 2>/dev/null || echo "")
        WARNINGS_LIST=$(jq -r '.warnings[]? | "- ⚠️ " + .' "${DOCTOR_SUMMARY}" 2>/dev/null || echo "")
    fi
fi

# Build the brief
cat > "${BRIEF}" <<EOF
# Daily Brief — ${DAY_OF_WEEK} ${DATE}

EOF

# Status section
echo "## Status" >> "${BRIEF}"
if [[ "${ISSUES_COUNT}" -eq 0 ]] && [[ "${WARNINGS_COUNT}" -eq 0 ]]; then
    echo "✓ All systems healthy (${HEALTHY_COUNT} checks passed)" >> "${BRIEF}"
else
    echo "${HEALTHY_COUNT} healthy / ${WARNINGS_COUNT} warnings / ${ISSUES_COUNT} issues" >> "${BRIEF}"
    echo "" >> "${BRIEF}"
    if [[ -n "${ISSUES_LIST}" ]]; then
        echo "### Issues" >> "${BRIEF}"
        echo "${ISSUES_LIST}" >> "${BRIEF}"
        echo "" >> "${BRIEF}"
    fi
    if [[ -n "${WARNINGS_LIST}" ]]; then
        echo "### Warnings" >> "${BRIEF}"
        echo "${WARNINGS_LIST}" >> "${BRIEF}"
        echo "" >> "${BRIEF}"
    fi
    echo "Full report: [doctor log](../doctor-logs/${DATE}.md)" >> "${BRIEF}"
fi
echo "" >> "${BRIEF}"

# New since yesterday — surface today's content briefs
echo "## New since yesterday" >> "${BRIEF}"
BLOG_BRIEFS=("${VAULT_ROOT}/_state/blog-summaries/${DATE}-"*.md)
PODCAST_BRIEFS=("${VAULT_ROOT}/_state/podcast-briefs/${DATE}-"*.md)

# Test if any actual files matched (bash globs leave the literal pattern if no match)
blog_count=0
for f in "${BLOG_BRIEFS[@]}"; do
    [[ -f "$f" ]] && blog_count=$((blog_count + 1))
done
podcast_count=0
for f in "${PODCAST_BRIEFS[@]}"; do
    [[ -f "$f" ]] && podcast_count=$((podcast_count + 1))
done

if [[ ${blog_count} -gt 0 ]]; then
    echo "" >> "${BRIEF}"
    echo "### Blog summaries (${blog_count})" >> "${BRIEF}"
    for f in "${BLOG_BRIEFS[@]}"; do
        [[ -f "$f" ]] || continue
        title=$(awk -F'"' '/^title: / {print $2; exit}' "$f")
        feed=$(awk -F': ' '/^feed: / {print $2; exit}' "$f" | tr -d '\r')
        rel="${f#${VAULT_ROOT}/}"
        echo "- **${feed}** — [${title}](../../${rel#_state/})" >> "${BRIEF}"
    done
fi

if [[ ${podcast_count} -gt 0 ]]; then
    echo "" >> "${BRIEF}"
    echo "### Podcast headlines (${podcast_count})" >> "${BRIEF}"
    for f in "${PODCAST_BRIEFS[@]}"; do
        [[ -f "$f" ]] || continue
        title=$(awk -F'"' '/^title: / {print $2; exit}' "$f")
        feed=$(awk -F': ' '/^feed: / {print $2; exit}' "$f" | tr -d '\r')
        rel="${f#${VAULT_ROOT}/}"
        echo "- **${feed}** — [${title}](../../${rel#_state/})" >> "${BRIEF}"
    done
fi

if [[ ${blog_count} -eq 0 && ${podcast_count} -eq 0 ]]; then
    echo "*(no new content processed today)*" >> "${BRIEF}"
fi
echo "" >> "${BRIEF}"

# Dream insights — surface gemini's notable patterns + reviewer verdict
echo "## 💭 Dream insights" >> "${BRIEF}"
if [[ -f "${DREAM_LOG}" ]]; then
    # Pull the journaler's "Notable Patterns" section (3-5 bullets)
    awk '
        /^## Notable Patterns/ { in_section=1; next }
        in_section && /^## / { exit }
        in_section { print }
    ' "${DREAM_LOG}" | head -10 >> "${BRIEF}"
    # Pull reviewer verdict
    verdict=$(awk '/^## Verdict/ {getline; print; exit}' "${DREAM_LOG}" | head -1)
    if [[ -n "${verdict}" ]]; then
        echo "" >> "${BRIEF}"
        echo "*Reviewer verdict: ${verdict} — see [full dream log](../dream-logs/${DATE}.md)*" >> "${BRIEF}"
    fi
else
    echo "*(no dream pass yet)*" >> "${BRIEF}"
fi
echo "" >> "${BRIEF}"

# Pending dream proposals (only fire if any)
PROPOSALS_DIR="${VAULT_ROOT}/_state/dream-proposals"
PENDING_PROPOSALS=()
if [[ -d "${PROPOSALS_DIR}" ]]; then
    while IFS= read -r p; do
        [[ -z "$p" ]] && continue
        if grep -q '^status: pending' "$p" 2>/dev/null; then
            PENDING_PROPOSALS+=("$p")
        fi
    done < <(find "${PROPOSALS_DIR}" -name '*.md' -type f 2>/dev/null)
fi
if [[ ${#PENDING_PROPOSALS[@]} -gt 0 ]]; then
    echo "## ✋ Pending dream proposals (${#PENDING_PROPOSALS[@]})" >> "${BRIEF}"
    echo "" >> "${BRIEF}"
    for p in "${PENDING_PROPOSALS[@]}"; do
        title=$(awk '/^# / {sub(/^# /, ""); print; exit}' "$p" 2>/dev/null)
        kind=$(awk -F': ' '/^kind:/ {print $2; exit}' "$p" 2>/dev/null)
        risk=$(awk -F': ' '/^risk:/ {print $2; exit}' "$p" 2>/dev/null)
        rel="${p#${VAULT_ROOT}/}"
        echo "- *${kind}* (risk: ${risk}) — **${title}**" >> "${BRIEF}"
        echo "    - [\`${rel}\`](../../${rel#_state/})" >> "${BRIEF}"
    done
    echo "" >> "${BRIEF}"
    echo "*To act: edit each file and change \`status: pending\` to \`APPROVE\` or \`REJECT\`.*" >> "${BRIEF}"
    echo "" >> "${BRIEF}"
fi

# Active modes section (read from chrono/current.md or each Lead's current.md)
echo "## 🔵 Active modes" >> "${BRIEF}"
active_count=0
for current_file in "${VAULT_ROOT}/chrono/current.md" "${VAULT_ROOT}/departments/"*/current.md; do
    [[ -f "${current_file}" ]] || continue
    # Look for Active Tasks section with non-"None" content (skip the header itself)
    if awk '/^## Active Tasks/{flag=1; next} /^## /{flag=0} flag' "${current_file}" 2>/dev/null \
        | grep -vqiE '^(none|$|---|none yet)' ; then
        rel="${current_file#${VAULT_ROOT}/}"
        owner=$(dirname "${rel}" | xargs basename)
        active_count=$((active_count + 1))
        echo "- **${owner}**: see [\`${rel}\`](../../${rel})" >> "${BRIEF}"
    fi
done
if [[ ${active_count} -eq 0 ]]; then
    echo "*(none — all Leads idle)*" >> "${BRIEF}"
fi
echo "" >> "${BRIEF}"

# Suggestions
echo "## Suggestions" >> "${BRIEF}"
echo "- Review status above" >> "${BRIEF}"
echo "- Type 'where are we' for full state summary" >> "${BRIEF}"
echo "" >> "${BRIEF}"

# Footer
cat >> "${BRIEF}" <<EOF
---
*Generated by morning-brief.sh at $(date -u +%FT%TZ)*
EOF

echo "Morning brief: ${BRIEF}"
exit 0
