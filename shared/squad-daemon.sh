#!/usr/bin/env bash
# Process-mode daemon helpers (Linux / container / SQUAD_DAEMON_MODE=process).
#
# launchd remains the Darwin implementation in bin/launch-squad.sh and
# bin/squad. This file is the PID-file / compose-signal path so `squad stop`
# never requires launchctl.
#
# Sourced, never executed. No `set -e` / `set -u` of its own.

SQUAD_DAEMON_PIDFILE="${SQUAD_DAEMON_PIDFILE:-${VAULT_ROOT}/_state/runtime/daemon/${SQUAD_SESSION:-squad}.pid}"
SQUAD_DAEMON_HOST="${SQUAD_DAEMON_HOST:-127.0.0.1}"
SQUAD_DAEMON_PORT="${SQUAD_DAEMON_PORT:-9876}"

squad_daemon_pidfile_pid() {
    local pid
    [[ -f "${SQUAD_DAEMON_PIDFILE}" ]] || return 1
    pid="$(tr -d ' \t\r\n' < "${SQUAD_DAEMON_PIDFILE}" 2>/dev/null || true)"
    [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || return 1
    printf '%s\n' "${pid}"
}

squad_process_daemon_alive() {
    local pid
    pid="$(squad_daemon_pidfile_pid)" || return 1
    kill -0 "${pid}" 2>/dev/null || return 1
    return 0
}

squad_ensure_process_daemon() {
    local pid log_dir log uvicorn_bin
    if squad_process_daemon_alive; then
        echo "✓ Process-mode daemon already running (pid $(squad_daemon_pidfile_pid))"
        return 0
    fi
    mkdir -p "$(dirname -- "${SQUAD_DAEMON_PIDFILE}")"
    log_dir="${VAULT_ROOT}/_state/runtime/daemon"
    mkdir -p "${log_dir}"
    log="${log_dir}/${SQUAD_SESSION:-squad}.log"

    uvicorn_bin=""
    if [[ -x "${VAULT_ROOT}/.venv/bin/uvicorn" ]]; then
        uvicorn_bin="${VAULT_ROOT}/.venv/bin/uvicorn"
    elif command -v uvicorn >/dev/null 2>&1; then
        uvicorn_bin="$(command -v uvicorn)"
    fi
    if [[ -z "${uvicorn_bin}" ]]; then
        echo "ERROR: SQUAD_DAEMON_MODE=process but uvicorn is not on PATH or in .venv." >&2
        return 1
    fi

    echo "Starting process-mode daemon on ${SQUAD_DAEMON_HOST}:${SQUAD_DAEMON_PORT}..."
    (
        cd -- "${VAULT_ROOT}" || exit 1
        nohup "${uvicorn_bin}" daemon.main:app \
            --host "${SQUAD_DAEMON_HOST}" \
            --port "${SQUAD_DAEMON_PORT}" \
            >>"${log}" 2>&1 &
        printf '%s\n' "$!" > "${SQUAD_DAEMON_PIDFILE}"
    )
    if squad_process_daemon_alive; then
        echo "✓ Process-mode daemon started (pid $(squad_daemon_pidfile_pid))"
        return 0
    fi
    echo "ERROR: process-mode daemon failed to stay running; see ${log}" >&2
    return 1
}

squad_stop_process_daemon() {
    local pid attempt
    local verify_attempts="${SQUAD_DAEMON_VERIFY_ATTEMPTS:-20}"
    local verify_delay="${SQUAD_DAEMON_VERIFY_DELAY:-0.1}"

    if [[ -n "${SQUAD_DAEMON_COMPOSE_SERVICE:-}" ]] && command -v docker >/dev/null 2>&1; then
        echo "Stopping compose daemon service '${SQUAD_DAEMON_COMPOSE_SERVICE}'..."
        docker compose stop "${SQUAD_DAEMON_COMPOSE_SERVICE}" || return $?
        echo "✓ Compose daemon service '${SQUAD_DAEMON_COMPOSE_SERVICE}' stopped."
        return 0
    fi

    if ! pid="$(squad_daemon_pidfile_pid)"; then
        echo "✓ No process-mode daemon pidfile at ${SQUAD_DAEMON_PIDFILE}."
        return 0
    fi
    if ! kill -0 "${pid}" 2>/dev/null; then
        rm -f "${SQUAD_DAEMON_PIDFILE}"
        echo "✓ Process-mode daemon already stopped (stale pidfile removed)."
        return 0
    fi

    echo "Stopping process-mode daemon (pid ${pid})..."
    kill -TERM "${pid}" 2>/dev/null || true
    attempt=1
    while [[ "${attempt}" -le "${verify_attempts}" ]]; do
        if ! kill -0 "${pid}" 2>/dev/null; then
            rm -f "${SQUAD_DAEMON_PIDFILE}"
            echo "✓ Process-mode daemon stopped and verified absent (pid ${pid})."
            return 0
        fi
        if [[ "${attempt}" -lt "${verify_attempts}" ]]; then
            sleep "${verify_delay}"
        fi
        attempt=$((attempt + 1))
    done
    kill -KILL "${pid}" 2>/dev/null || true
    rm -f "${SQUAD_DAEMON_PIDFILE}"
    echo "✓ Process-mode daemon killed (pid ${pid})."
    return 0
}
