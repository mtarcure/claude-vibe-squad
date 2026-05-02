#!/bin/bash
# Sweep stale active/ tasks → archive/ when their response has landed in outbox/.
#
# Why: the mailbox protocol expects a Lead to move TASK from active/ → archive/
# after writing the response to outbox/. In practice, this step sometimes fails
# (sandbox issue, Lead crashed mid-step, parallel rename race). This sweep is
# idempotent — runs harmlessly when there's nothing to do, fixes drift when there is.
#
# Runs nightly via run-nightly.sh. Can also be invoked anytime by Chrono or operator.

set -uo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"
DATE="$(date +%Y-%m-%d)"
LOG="${VAULT_ROOT}/_state/cleanup-logs/${DATE}-sweep-active.md"

mkdir -p "$(dirname "${LOG}")"

cat > "${LOG}" <<EOF
# Sweep Active — ${DATE}

Run at: $(date -u +%FT%TZ)

## Tasks moved (active/ → archive/ where response exists)

EOF

moved=0
for lead in coding security content sysmgmt research; do
    active_dir="${VAULT_ROOT}/departments/${lead}/active"
    outbox_dir="${VAULT_ROOT}/departments/${lead}/outbox"
    archive_dir="${VAULT_ROOT}/departments/${lead}/archive"
    mkdir -p "${archive_dir}"

    [[ -d "${active_dir}" ]] || continue

    for task in "${active_dir}"/TASK-*.md; do
        [[ -f "${task}" ]] || continue
        task_id=$(basename "${task}" .md)
        # Response convention: <task-id>-response.md in outbox/ OR archive/
        if [[ -f "${outbox_dir}/${task_id}-response.md" ]] \
           || [[ -f "${archive_dir}/${task_id}-response.md" ]]; then
            # Idempotent move — silent if already there, no error if source vanishes
            if mv "${task}" "${archive_dir}/" 2>/dev/null; then
                echo "- ✓ ${lead}/${task_id} → archive (response exists)" >> "${LOG}"
                moved=$((moved + 1))
            fi
        fi
    done
done

[[ ${moved} -eq 0 ]] && echo "(none — all active tasks are still in-flight or already archived)" >> "${LOG}"

cat >> "${LOG}" <<EOF

## Summary
- Tasks moved: ${moved}
EOF

echo "Sweep active complete. Moved ${moved} tasks. Log: ${LOG}"
