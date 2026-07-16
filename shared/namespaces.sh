#!/usr/bin/env bash
# Canonical compatibility-mailbox inventory.
#
# These namespaces own departments/<namespace>/{inbox,active,outbox,archive}
# directories and therefore need lifecycle scans plus inbox/outbox watchers.
# Model execution remains packet-driven via `to_model`; this list must never be
# used to infer a model lane.

COMPATIBILITY_NAMESPACES=(
    coding
    security
    content
    sysmgmt
    research
    content-engineer
)

is_compatibility_namespace() {
    local candidate="$1" namespace
    for namespace in "${COMPATIBILITY_NAMESPACES[@]}"; do
        [[ "$candidate" == "$namespace" ]] && return 0
    done
    return 1
}
