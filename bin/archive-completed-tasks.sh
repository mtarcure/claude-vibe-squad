#!/bin/bash
# Move completed task packets out of inbox/active into archive/ when the
# matching outbox response exists.

set -euo pipefail

VAULT_ROOT="${VAULT_ROOT:-${HOME}/Obsidian-Claude-Vibe-Squad}"

archived=0
for ns_dir in "${VAULT_ROOT}/departments"/*; do
    [[ -d "$ns_dir" ]] || continue
    for state in inbox active; do
        for task_file in "${ns_dir}/${state}"/TASK-*.md; do
            [[ -f "$task_file" ]] || continue
            task_id="$(basename "$task_file" .md)"
            response="${ns_dir}/outbox/${task_id}-response.md"
            [[ -f "$response" ]] || continue
            mkdir -p "${ns_dir}/archive"
            mv "$task_file" "${ns_dir}/archive/${task_id}.md"
            archived=$((archived + 1))
            echo "archived ${state}/$(basename "$task_file") -> archive/${task_id}.md"
        done
    done
done

echo "archived_count=${archived}"
