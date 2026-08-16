#!/usr/bin/env bash
# Canonical durable home for doctor reports and summaries.
#
# Source this file; it exports CHRONO_DOCTOR_LOG_DIR. The default deliberately
# mirrors CHRONO_VAULT_AUDIT_DIR's stable local-state home and never follows
# VAULT_ROOT/CHRONO_VAULT_ROOT or an attempt worktree.

if [[ -z "${CHRONO_DOCTOR_LOG_DIR:-}" ]]; then
    CHRONO_DOCTOR_LOG_DIR="${HOME:-/var/tmp/chrono-vault-${EUID}}/.local/state/chrono-vault/doctor-logs"
fi

case "${CHRONO_DOCTOR_LOG_DIR}" in
    /*) ;;
    *)
        printf 'doctor-log-home.sh: CHRONO_DOCTOR_LOG_DIR must be absolute: %s\n' \
            "${CHRONO_DOCTOR_LOG_DIR}" >&2
        return 64
        ;;
esac

export CHRONO_DOCTOR_LOG_DIR
