#!/usr/bin/env bash
# Run the private/local outreach pipeline in fixture mode only.
# This bridge proves the restored Outreach Mode without sending email or
# copying private lead data into the public Vibe Squad repo.

set -euo pipefail

LEGACY_OUTREACH="${LEGACY_OUTREACH_ROOT:-${HOME}/916mechaniks}"
OUTREACH_PACKAGE="${LEGACY_OUTREACH}/outreach"

if [[ ! -d "${OUTREACH_PACKAGE}" ]]; then
    echo "ERROR: legacy outreach package not found at ${OUTREACH_PACKAGE}" >&2
    echo "Set LEGACY_OUTREACH_ROOT to the parent directory that contains outreach/." >&2
    exit 1
fi

if [[ ! -f "${OUTREACH_PACKAGE}/runner.py" ]]; then
    echo "ERROR: outreach runner missing: ${OUTREACH_PACKAGE}/runner.py" >&2
    exit 1
fi

echo "Running outreach dry-run from ${LEGACY_OUTREACH}"
echo "No live monitors, SMTP sends, or external contact actions are allowed in this mode."

(
    cd "${LEGACY_OUTREACH}"
    if command -v uv >/dev/null 2>&1; then
        uv run --project "${OUTREACH_PACKAGE}" python -m outreach.runner --dry-run
    else
        PYTHON_BIN="${PYTHON_BIN:-}"
        if [[ -z "${PYTHON_BIN}" ]]; then
            if command -v python3 >/dev/null 2>&1; then
                PYTHON_BIN="$(command -v python3)"
            elif command -v python >/dev/null 2>&1; then
                PYTHON_BIN="$(command -v python)"
            else
                echo "ERROR: no uv, python3, or python executable found on PATH" >&2
                exit 1
            fi
        fi
        "${PYTHON_BIN}" -m outreach.runner --dry-run
    fi
)
