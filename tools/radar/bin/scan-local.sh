#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf 'usage: %s TARGET OUTPUT_JSON [TEMPLATE_PATH]\n' "$0" >&2
  exit 64
}

[[ $# -ge 2 && $# -le 3 ]] || usage

rig_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$(cd "$1" && pwd)"
output="$2"
template="${3:-}"
# Socket path must live OUTSIDE the tracked tree. A symlink planted under tools/ is
# classified by the board integration gate as a configuration-based sandbox-escape
# artifact and blocks the entire lane AFTER its work completes -- which is exactly
# what happened to TASK-2026-08-05-0500-exp. Override with RADAR_DOCKER_SOCKET.
docker_socket="${RADAR_DOCKER_SOCKET:-${HOME}/.colima/radar-canary/docker.sock}"
[[ -S "$docker_socket" ]] || docker_socket="${RADAR_DOCKER_SOCKET:-${HOME}/.colima/default/docker.sock}"

case "$output" in
  "$rig_dir"/*) ;;
  *) printf '[e] Output must stay beneath %s\n' "$rig_dir" >&2; exit 65 ;;
esac

if [[ -e "$output" ]]; then
  printf '[e] Refusing to overwrite existing output: %s\n' "$output" >&2
  exit 66
fi

if [[ ! -S "$docker_socket" ]]; then
  printf '[e] Radar scan blocked: Docker socket is absent: %s\n' "$docker_socket" >&2
  exit 1
fi

export DOCKER_HOST="unix://$docker_socket"
export DOCKER_CONFIG="$rig_dir/docker-config"

compose=(docker compose -f "$rig_dir/compose.yaml")
"${compose[@]}" up -d --no-recreate postgres rabbitmq api celeryworker

controller_args=(run -T -v "$target:/contract:ro")
if [[ -n "$template" ]]; then
  template="$(cd "$(dirname "$template")" && pwd)/$(basename "$template")"
  controller_args+=(-v "$template:/templates/custom.yaml:ro")
fi
controller_args+=(controller --path "$target" --container-path /contract)
if [[ -n "$template" ]]; then
  controller_args+=(--templates /templates --templates-filename custom.yaml)
fi
controller_args+=(--output "$(dirname "$output")")

"${compose[@]}" "${controller_args[@]}"
api_container="$("${compose[@]}" ps -q api)"
[[ -n "$api_container" ]] || { printf '[e] Radar API container is absent\n' >&2; exit 1; }
docker cp "$api_container:/radar_data/output.json" "$output"
printf '[i] Results written to %s\n' "$output"
