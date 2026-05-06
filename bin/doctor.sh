#!/bin/bash
# Claude-Vibe-Squad doctor — health check + token-bleed detection.
# Verifies environment, reports anomalies. Surfaced in morning brief.
#
# Phases:
#   1. CLI presence + login status (Claude / Codex / Gemini / Kimi)
#   2. MCP servers reachable from each CLI
#   3. Secrets sourced
#   4. Vault accessible (Obsidian REST API)
#   5. Persistent browser session alive
#   6. Disk space (>15% free)
#   7. tmux panes (Chrono + 4 model-lane panes alive)
#   8. Token usage per CLI (where reportable)
#   9. Specialist dispatch volume last 24h
#   10. Process audit (long-running, orphaned)
#   11. Log/transcript volume audit

set -uo pipefail

# launchd's spawn shell doesn't include ~/.local/bin (where claude + kimi live).
# Prepend it so CLI presence checks work the same as in operator's interactive shell.
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
DATE="$(date -u +%Y-%m-%d)"
DOCTOR_LOG="${VAULT_ROOT}/_state/doctor-logs/${DATE}.md"
SUMMARY="${VAULT_ROOT}/_state/doctor-logs/${DATE}-summary.json"

mkdir -p "$(dirname "${DOCTOR_LOG}")"

# Initialize report
cat > "${DOCTOR_LOG}" <<EOF
# Doctor Report — ${DATE}

Run at: $(date -u +%FT%TZ)

EOF

# Track issues
ISSUES=()
WARNINGS=()
HEALTHY=()

# --- 1. CLI presence + login ---
echo "## CLI Status" >> "${DOCTOR_LOG}"
for cli in claude codex gemini kimi; do
    if command -v "$cli" >/dev/null 2>&1; then
        version=$("$cli" --version 2>/dev/null | head -1)
        echo "- ✓ $cli installed ($version)" >> "${DOCTOR_LOG}"
        HEALTHY+=("$cli installed")
    else
        echo "- ✗ $cli NOT installed" >> "${DOCTOR_LOG}"
        ISSUES+=("$cli CLI not installed")
    fi
done

# --- 2. MCP reachability — invoke bootstrap-mcps.sh in --status mode ---
echo "" >> "${DOCTOR_LOG}"
echo "## MCP Servers" >> "${DOCTOR_LOG}"
mcp_status=$(bash "${VAULT_ROOT}/scripts/bootstrap-mcps.sh" --status 2>/dev/null \
    | grep -E '^\s+[✓✗]' || echo "")
if [[ -n "${mcp_status}" ]]; then
    missing=$(echo "${mcp_status}" | grep -c '✗' | tr -d ' ')
    total=$(echo "${mcp_status}" | wc -l | tr -d ' ')
    if [[ ${missing} -eq 0 ]]; then
        echo "- ✓ All MCPs registered across CLIs (${total} total)" >> "${DOCTOR_LOG}"
        HEALTHY+=("MCPs registered")
    else
        echo "- ⚠️ ${missing}/${total} MCP registrations missing" >> "${DOCTOR_LOG}"
        WARNINGS+=("${missing} MCP registrations missing — run scripts/bootstrap-mcps.sh")
    fi
else
    echo "- ⚠️ MCP status check returned no data" >> "${DOCTOR_LOG}"
    WARNINGS+=("MCP status indeterminate")
fi

if [[ -x "${VAULT_ROOT}/bin/mcp-audit.sh" ]]; then
    if MCP_AUDIT_OUTPUT=$("${VAULT_ROOT}/bin/mcp-audit.sh" 2>/dev/null | tail -1); then
        echo "- ✓ MCP usability audit passed (${MCP_AUDIT_OUTPUT})" >> "${DOCTOR_LOG}"
        HEALTHY+=("MCP usability audit passed")
    else
        echo "- ⚠️ MCP usability audit reported issues (${MCP_AUDIT_OUTPUT:-no summary})" >> "${DOCTOR_LOG}"
        WARNINGS+=("MCP usability audit reported registered/unusable drift")
    fi
else
    echo "- ⚠️ bin/mcp-audit.sh missing or not executable" >> "${DOCTOR_LOG}"
    WARNINGS+=("mcp-audit missing")
fi

# --- 2b. Product hygiene + memory discipline ---
echo "" >> "${DOCTOR_LOG}"
echo "## Product Hygiene" >> "${DOCTOR_LOG}"
if [[ -x "${VAULT_ROOT}/bin/product-hygiene.sh" ]]; then
    if HYGIENE_OUTPUT=$("${VAULT_ROOT}/bin/product-hygiene.sh" --public-export 2>/dev/null | tail -2 | tr '\n' ' '); then
        echo "- ✓ Public export has no tracked runtime/private blockers (${HYGIENE_OUTPUT})" >> "${DOCTOR_LOG}"
        HEALTHY+=("public export hygiene clean")
    else
        echo "- ⚠️ Public export hygiene found tracked blockers (${HYGIENE_OUTPUT})" >> "${DOCTOR_LOG}"
        WARNINGS+=("public export hygiene blockers present — run bin/product-hygiene.sh --public-export")
    fi
else
    WARNINGS+=("product-hygiene missing")
fi

echo "" >> "${DOCTOR_LOG}"
echo "## Instruction Drift" >> "${DOCTOR_LOG}"
DRIFT_HITS=0
if command -v grep >/dev/null 2>&1; then
    DRIFT_HITS=$(grep -RInE '45 specialists|all 45 specialists|scripts/send-req\.sh|currently has FILL placeholders|<FILL:|docs/handoffs/[0-9]{4}-|docs/specs/spec-[0-9]|docs/plans/[0-9]{4}-' \
        "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
        "${VAULT_ROOT}/docs" "${VAULT_ROOT}/shared" 2>/dev/null \
        | grep -v 'bin/upgrade-specialists.py' \
        | wc -l | tr -d ' ')
fi
if [[ "${DRIFT_HITS:-0}" -eq 0 ]]; then
    echo "- ✓ No stale count/FILL/script/spec-handoff references in public instruction surfaces" >> "${DOCTOR_LOG}"
    HEALTHY+=("instruction drift clean")
else
    echo "- ⚠️ ${DRIFT_HITS} stale instruction-reference hit(s); run bin/product-hygiene.sh --public-export for details" >> "${DOCTOR_LOG}"
    WARNINGS+=("instruction drift hits: ${DRIFT_HITS}")
fi

if [[ -x "${VAULT_ROOT}/bin/validate-specialists.sh" ]]; then
    if VALIDATE_OUTPUT=$("${VAULT_ROOT}/bin/validate-specialists.sh" >/tmp/vibe-squad-validate-specialists.out 2>&1); then
        echo "- ✓ Specialist, routing, and generated-adapter validation passed" >> "${DOCTOR_LOG}"
        HEALTHY+=("specialist/routing validation passed")
    else
        echo "- ⚠️ Specialist/routing validation failed; see bin/validate-specialists.sh output" >> "${DOCTOR_LOG}"
        WARNINGS+=("specialist/routing validation failed")
    fi
else
    WARNINGS+=("validate-specialists missing")
fi

if [[ -f "${VAULT_ROOT}/docs/brain-map.md" ]]; then
    echo "- ✓ Brain map present" >> "${DOCTOR_LOG}"
    HEALTHY+=("brain map present")
else
    echo "- 🔔 docs/brain-map.md missing" >> "${DOCTOR_LOG}"
    ISSUES+=("brain map missing")
fi

MISSING_SCRIPT_REFS=0
while IFS= read -r script_ref; do
    [[ -n "$script_ref" ]] || continue
    [[ -e "${VAULT_ROOT}/${script_ref}" ]] || MISSING_SCRIPT_REFS=$((MISSING_SCRIPT_REFS + 1))
done < <(grep -RhoE '(bin|scripts|shared)/[A-Za-z0-9._/-]+\.(sh|py)' \
    "${VAULT_ROOT}/README.md" "${VAULT_ROOT}/CLAUDE.md" "${VAULT_ROOT}/chrono" \
    "${VAULT_ROOT}/docs" "${VAULT_ROOT}/shared" 2>/dev/null | sort -u)
if [[ "${MISSING_SCRIPT_REFS}" -eq 0 ]]; then
    echo "- ✓ Referenced scripts exist" >> "${DOCTOR_LOG}"
    HEALTHY+=("referenced scripts exist")
else
    echo "- ⚠️ ${MISSING_SCRIPT_REFS} referenced script path(s) are missing" >> "${DOCTOR_LOG}"
    WARNINGS+=("missing referenced scripts: ${MISSING_SCRIPT_REFS}")
fi

echo "" >> "${DOCTOR_LOG}"
echo "## Memory Discipline" >> "${DOCTOR_LOG}"
if [[ -x "${VAULT_ROOT}/bin/memory-audit.sh" ]]; then
    if MEMORY_OUTPUT=$("${VAULT_ROOT}/bin/memory-audit.sh" 2>/dev/null | tail -1); then
        echo "- ✓ Memory audit passed (${MEMORY_OUTPUT})" >> "${DOCTOR_LOG}"
        HEALTHY+=("memory audit passed")
    else
        echo "- 🔔 Memory audit found issues (${MEMORY_OUTPUT:-no summary})" >> "${DOCTOR_LOG}"
        ISSUES+=("memory audit found missing discipline cite or secret-like pattern")
    fi
else
    WARNINGS+=("memory-audit missing")
fi

# --- 3. Secrets ---
echo "" >> "${DOCTOR_LOG}"
echo "## Secrets" >> "${DOCTOR_LOG}"
if [[ -f "${HOME}/.config/shell/secrets.zsh" ]]; then
    echo "- ✓ secrets.zsh present" >> "${DOCTOR_LOG}"
    HEALTHY+=("secrets.zsh present")
else
    echo "- ✗ secrets.zsh missing" >> "${DOCTOR_LOG}"
    ISSUES+=("secrets.zsh not found at ~/.config/shell/secrets.zsh")
fi

# --- 4. Vault accessibility ---
echo "" >> "${DOCTOR_LOG}"
echo "## Vault" >> "${DOCTOR_LOG}"
if [[ -d "${VAULT_ROOT}" ]] && [[ -w "${VAULT_ROOT}" ]]; then
    echo "- ✓ Vault accessible at ${VAULT_ROOT}" >> "${DOCTOR_LOG}"
    HEALTHY+=("vault accessible")
else
    echo "- ✗ Vault not accessible" >> "${DOCTOR_LOG}"
    ISSUES+=("vault not accessible")
fi

# --- 5. Browser session — read summary written by browser-keep-alive.sh ---
echo "" >> "${DOCTOR_LOG}"
echo "## Browser Session" >> "${DOCTOR_LOG}"
BROWSER_SUMMARY="${VAULT_ROOT}/_state/cleanup-logs/${DATE}-browser-summary.json"
if [[ -f "${BROWSER_SUMMARY}" ]] && command -v jq >/dev/null 2>&1; then
    reachable=$(jq -r '.reachable // false' "${BROWSER_SUMMARY}")
    if [[ "${reachable}" == "true" ]]; then
        open=$(jq -r '.platforms_open // 0' "${BROWSER_SUMMARY}")
        expired=$(jq -r '.platforms_expired // [] | length' "${BROWSER_SUMMARY}")
        missing=$(jq -r '.platforms_missing // [] | length' "${BROWSER_SUMMARY}")
        echo "- ✓ Chrome CDP reachable: ${open}/5 bounty platforms open" >> "${DOCTOR_LOG}"
        if [[ ${expired} -gt 0 ]]; then
            expired_names=$(jq -r '.platforms_expired // [] | join(", ")' "${BROWSER_SUMMARY}")
            echo "- ⚠️ ${expired} platform(s) at sign-in (re-auth needed): ${expired_names}" >> "${DOCTOR_LOG}"
            WARNINGS+=("browser sessions expired: ${expired_names}")
        fi
        if [[ ${missing} -gt 0 ]]; then
            missing_names=$(jq -r '.platforms_missing // [] | join(", ")' "${BROWSER_SUMMARY}")
            echo "- ○ ${missing} platform(s) with no open tab: ${missing_names}" >> "${DOCTOR_LOG}"
        fi
        HEALTHY+=("browser CDP reachable")
    else
        echo "- ⚠️ Chrome not reachable on CDP debug port (run with --remote-debugging-port=9222)" >> "${DOCTOR_LOG}"
        WARNINGS+=("Chrome CDP not reachable — bounty browser tools won't work")
    fi
else
    echo "- (no browser-keep-alive run yet today)" >> "${DOCTOR_LOG}"
fi

# --- 6. Disk space ---
echo "" >> "${DOCTOR_LOG}"
echo "## Disk Space" >> "${DOCTOR_LOG}"
disk_free_pct=$(df -h ~ | awk 'NR==2 {gsub("%",""); print 100-$5}')
if [[ "${disk_free_pct}" -gt 15 ]]; then
    echo "- ✓ Disk: ${disk_free_pct}% free" >> "${DOCTOR_LOG}"
    HEALTHY+=("disk OK")
elif [[ "${disk_free_pct}" -gt 5 ]]; then
    echo "- ⚠️ Disk: ${disk_free_pct}% free (getting tight)" >> "${DOCTOR_LOG}"
    WARNINGS+=("disk at ${disk_free_pct}%")
else
    echo "- 🔔 Disk: ${disk_free_pct}% free (CRITICAL)" >> "${DOCTOR_LOG}"
    ISSUES+=("disk critical at ${disk_free_pct}%")
fi

# --- 7. tmux panes ---
echo "" >> "${DOCTOR_LOG}"
echo "## tmux Sessions" >> "${DOCTOR_LOG}"
if command -v tmux >/dev/null 2>&1; then
    if tmux ls >/dev/null 2>&1; then
        pane_count=$(tmux list-sessions 2>/dev/null | wc -l | tr -d ' ')
        echo "- ✓ tmux running: ${pane_count} session(s)" >> "${DOCTOR_LOG}"
        HEALTHY+=("tmux running")
    else
        echo "- ⚠️ tmux installed but no sessions running" >> "${DOCTOR_LOG}"
        WARNINGS+=("tmux no sessions")
    fi
else
    echo "- ⚠️ tmux not installed" >> "${DOCTOR_LOG}"
    WARNINGS+=("tmux not installed")
fi

# --- 8. Token usage proxy (squad-driven LLM artifact volume) ---
# We don't have direct token counters per CLI, but we know the squad's own
# scripts produce one artifact per LLM call. Counting today's vs the trailing
# 7-day average gives an anomaly signal.
echo "" >> "${DOCTOR_LOG}"
echo "## Token Usage (proxy via artifact count)" >> "${DOCTOR_LOG}"
TODAY_ARTIFACTS=0
for sub in blog-summaries podcast-briefs dream-logs; do
    cnt=$(find "${VAULT_ROOT}/_state/${sub}" -name "${DATE}-*" -type f 2>/dev/null | wc -l | tr -d ' ')
    TODAY_ARTIFACTS=$((TODAY_ARTIFACTS + cnt))
done
WEEKLY_ARTIFACTS=$(find "${VAULT_ROOT}/_state"/{blog-summaries,podcast-briefs,dream-logs} \
    -name '*.md' -mtime -7 -type f 2>/dev/null | wc -l | tr -d ' ')
WEEKLY_AVG=$(( WEEKLY_ARTIFACTS / 7 ))
echo "- Today: ${TODAY_ARTIFACTS} artifacts" >> "${DOCTOR_LOG}"
echo "- 7d total: ${WEEKLY_ARTIFACTS} (avg/day: ${WEEKLY_AVG})" >> "${DOCTOR_LOG}"
# Flag if today is 3x the weekly average AND average isn't trivial
if [[ ${WEEKLY_AVG} -ge 3 ]] && [[ ${TODAY_ARTIFACTS} -gt $((WEEKLY_AVG * 3)) ]]; then
    echo "- ⚠️ Anomaly: today's volume is >3x weekly average — possible token-bleed" >> "${DOCTOR_LOG}"
    WARNINGS+=("token-bleed suspect: today=${TODAY_ARTIFACTS} vs weekly_avg=${WEEKLY_AVG}")
fi

# Primary token-spend signal: dispatch count from dispatch-log.jsonl (last 24h).
# Catches retry loops with single-artifact output (which the artifact-count
# proxy above misses). finance-daily.sh provides per-pane breakdown + baseline
# comparison; this is just a high-water-mark check.
if [[ -f "${VAULT_ROOT}/_state/dispatch-log.jsonl" ]] && command -v jq >/dev/null 2>&1; then
    yesterday_iso=$(date -u -v-1d +%FT%TZ 2>/dev/null || date -u -d '1 day ago' +%FT%TZ 2>/dev/null)
    DISPATCHES_LAST_24H=$(jq -r --arg t "$yesterday_iso" 'select(.ts > $t) | (.model_lane // .to_model // "?")' \
        "${VAULT_ROOT}/_state/dispatch-log.jsonl" 2>/dev/null | wc -l | tr -d ' ')
    echo "- Total dispatches last 24h: ${DISPATCHES_LAST_24H} (see _state/finance-daily/ for per-pane breakdown)" >> "${DOCTOR_LOG}"
    if [[ ${DISPATCHES_LAST_24H} -gt 200 ]]; then
        echo "- ⚠️ High dispatch volume (>200/day) — possible runaway loop. Cross-check finance-daily." >> "${DOCTOR_LOG}"
        WARNINGS+=("dispatch volume ${DISPATCHES_LAST_24H} exceeds 200/24h baseline")
    fi
fi

# --- 9. Specialist dispatch volume ---
echo "" >> "${DOCTOR_LOG}"
echo "## Dispatch Activity (last 24h)" >> "${DOCTOR_LOG}"
DISPATCHES_24H=$(find "${VAULT_ROOT}/departments"/*/archive -name 'TASK-*-response.md' -mtime -1 2>/dev/null | wc -l | tr -d ' ')
INBOX_BACKLOG=$(find "${VAULT_ROOT}/departments"/*/inbox -name 'TASK-*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
echo "- Tasks completed (last 24h): ${DISPATCHES_24H}" >> "${DOCTOR_LOG}"
echo "- Inbox backlog: ${INBOX_BACKLOG}" >> "${DOCTOR_LOG}"
if [[ ${INBOX_BACKLOG} -gt 10 ]]; then
    echo "- ⚠️ Inbox backlog exceeds 10 — model leads may be stuck" >> "${DOCTOR_LOG}"
    WARNINGS+=("inbox backlog: ${INBOX_BACKLOG} unacknowledged tasks")
fi

# --- 10. Process audit (with pathology detection) ---
echo "" >> "${DOCTOR_LOG}"
echo "## Process Audit" >> "${DOCTOR_LOG}"
SQUAD_PIDS=""
if command -v tmux >/dev/null 2>&1 && tmux has-session -t squad 2>/dev/null; then
    SQUAD_PIDS=$(tmux list-panes -a -F '#{pane_pid}' 2>/dev/null | tr '\n' ' ')
    echo "- ✓ squad tmux session is running with pane roots: ${SQUAD_PIDS}" >> "${DOCTOR_LOG}"
    HEALTHY+=("squad tmux session present")
else
    echo "- ⚠️ squad tmux session is not running" >> "${DOCTOR_LOG}"
    WARNINGS+=("squad tmux session not running")
fi

# Long-running claude/codex/gemini/kimi processes are expected for the daily
# driver, but extra interactive CLIs outside the squad pane roots can leave MCP
# children around. Report them separately; do not kill them automatically.
long_procs=$(ps -eo pid,ppid,etime,pcpu,comm | awk '$5 ~ /(claude|codex|gemini|kimi)/ && $3 ~ /^[0-9]+-[0-9]+/ {print}' | head -10)
if [[ -n "${long_procs}" ]]; then
    echo "- ℹ️ Long-running CLI processes (>1 day; may be active non-squad sessions):" >> "${DOCTOR_LOG}"
    echo "${long_procs}" | sed 's/^/  /' >> "${DOCTOR_LOG}"
    HEALTHY+=("persistent CLI processes present")
else
    echo "- ✓ No long-running CLI processes detected" >> "${DOCTOR_LOG}"
fi

extra_cli=$(ps -eo pid,ppid,etime,pcpu,command | awk -v squad_pids="${SQUAD_PIDS}" '
    function is_squad(pid) {
        return index(" " squad_pids " ", " " pid " ") > 0
    }
    $0 ~ /(claude|codex|gemini|kimi)( |$)/ && $0 !~ /bin\/(launch-squad|squad-stop|doctor)\.sh/ {
        if (!is_squad($1) && !is_squad($2)) print
    }
' | head -20)
if [[ -n "${extra_cli}" ]]; then
    echo "- 🟡 Extra non-squad CLI roots detected (informational; may be active terminals):" >> "${DOCTOR_LOG}"
    echo "${extra_cli}" | sed 's/^/  /' >> "${DOCTOR_LOG}"
    WARNINGS+=("extra non-squad CLI sessions detected; use normal terminal cleanup if stale")
fi

# Pathology: high-CPU CLI processes (likely retry storm or runaway loop)
runaway=$(ps -eo pid,etime,pcpu,comm | awk '$4 ~ /(claude|codex|gemini|kimi)/ && $3+0 > 80 {print}' | head -3)
if [[ -n "${runaway}" ]]; then
    echo "- 🔔 High-CPU CLI processes (>80% CPU — possible runaway):" >> "${DOCTOR_LOG}"
    echo "${runaway}" | sed 's/^/  /' >> "${DOCTOR_LOG}"
    ISSUES+=("CLI process consuming >80% CPU — kill if stuck in retry loop")
fi

# Pathology: MCP retry storms — search recent CLI stdout for connection-failure patterns.
# tmux-logs are pane stdout (where CLIs actually log connection issues), not
# cleanup-logs (which are short structured docs that don't reflect real retry
# spam). Time-windowed to last hour; pattern targets MCP-specific failures.
RETRY_STORM_LOG=$(find "${VAULT_ROOT}/_state/tmux-logs" -name '*.log' -mmin -60 2>/dev/null \
    | xargs grep -hcE 'Failed to connect|connection refused|retrying.*MCP|MCP.*timeout|reconnect attempt' 2>/dev/null \
    | awk -F: '{sum+=$1} END {print sum+0}')
if [[ ${RETRY_STORM_LOG} -gt 100 ]]; then
    echo "- ⚠️ Possible MCP retry storm: ${RETRY_STORM_LOG} connection-failure lines in last hour of tmux-logs" >> "${DOCTOR_LOG}"
    WARNINGS+=("MCP retry storm suspect — ${RETRY_STORM_LOG} connection failures in last hour")
elif [[ ${RETRY_STORM_LOG} -gt 30 ]]; then
    echo "- 🟡 Elevated MCP retry activity: ${RETRY_STORM_LOG} connection-failure lines in last hour" >> "${DOCTOR_LOG}"
else
    echo "- ✓ No retry-storm pattern detected (${RETRY_STORM_LOG} connection-failure lines in last hour)" >> "${DOCTOR_LOG}"
fi

# Pathology: stale tmp files in _state (signal of crashed atomic writes)
STALE_TMPS=$(find "${VAULT_ROOT}/_state" -name '*.tmp.*' -type f -mmin +30 2>/dev/null | wc -l | tr -d ' ')
if [[ ${STALE_TMPS} -gt 0 ]]; then
    echo "- ⚠️ ${STALE_TMPS} stale .tmp.* files in _state (atomic-write fragments — crash residue?)" >> "${DOCTOR_LOG}"
    WARNINGS+=("${STALE_TMPS} stale temp-file fragments in _state")
fi

# --- 11. Log volume ---
echo "" >> "${DOCTOR_LOG}"
echo "## Log Volume" >> "${DOCTOR_LOG}"
state_size=$(du -sh "${VAULT_ROOT}/_state" 2>/dev/null | cut -f1)
echo "- _state/ size: ${state_size}" >> "${DOCTOR_LOG}"

# --- Summary ---
echo "" >> "${DOCTOR_LOG}"
echo "## Summary" >> "${DOCTOR_LOG}"
echo "- Healthy: ${#HEALTHY[@]}" >> "${DOCTOR_LOG}"
echo "- Warnings: ${#WARNINGS[@]}" >> "${DOCTOR_LOG}"
echo "- Issues: ${#ISSUES[@]}" >> "${DOCTOR_LOG}"

# Write JSON summary for morning-brief.sh to consume
# Build arrays as proper JSON
json_array() {
    local arr=("$@")
    if [[ "${#arr[@]}" -eq 0 ]]; then
        echo "[]"
    else
        local out="["
        local first=1
        for item in "${arr[@]}"; do
            # Escape backslashes and double-quotes for JSON
            local esc="${item//\\/\\\\}"
            esc="${esc//\"/\\\"}"
            if [[ ${first} -eq 1 ]]; then
                out+="\"${esc}\""
                first=0
            else
                out+=",\"${esc}\""
            fi
        done
        out+="]"
        echo "${out}"
    fi
}

# Bash empty-array under set -u needs the +expansion guard
WARNINGS_JSON=$(json_array ${WARNINGS[@]+"${WARNINGS[@]}"})
ISSUES_JSON=$(json_array ${ISSUES[@]+"${ISSUES[@]}"})

cat > "${SUMMARY}" <<EOF
{
  "date": "${DATE}",
  "healthy_count": ${#HEALTHY[@]},
  "warning_count": ${#WARNINGS[@]},
  "issue_count": ${#ISSUES[@]},
  "warnings": ${WARNINGS_JSON},
  "issues": ${ISSUES_JSON}
}
EOF

# Exit code = 0 if no critical issues, 1 otherwise
if [[ "${#ISSUES[@]}" -gt 0 ]]; then
    exit 1
fi
exit 0
