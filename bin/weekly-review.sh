#!/usr/bin/env bash
set -euo pipefail

# Source secrets for VIBESQUAD_DAEMON_TOKEN and GEMINI_API_KEY
source ~/.config/shell/secrets.zsh

cd "$(dirname "$0")/.."
source .venv/bin/activate
exec python3 scripts/python/weekly_review_runner.py "$@"
