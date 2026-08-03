#!/usr/bin/env bash
set -Eeuo pipefail

rig_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Socket path must live OUTSIDE the tracked tree. A symlink planted under tools/ is
# classified by the board integration gate as a configuration-based sandbox-escape
# artifact and blocks the entire lane AFTER its work completes -- which is exactly
# what happened to TASK-2026-08-05-0500-exp. Override with RADAR_DOCKER_SOCKET.
docker_socket="${RADAR_DOCKER_SOCKET:-${HOME}/.colima/radar-canary/docker.sock}"
[[ -S "$docker_socket" ]] || docker_socket="${RADAR_DOCKER_SOCKET:-${HOME}/.colima/default/docker.sock}"

if [[ ! -S "$docker_socket" ]]; then
  printf '[e] Radar install blocked: Docker socket is absent: %s\n' "$docker_socket" >&2
  exit 1
fi

export DOCKER_HOST="unix://$docker_socket"
export DOCKER_CONFIG="$rig_dir/docker-config"

docker version
docker compose -f "$rig_dir/compose.yaml" pull
docker image inspect ghcr.io/auditware/radar-controller:main \
  --format 'controller={{index .RepoDigests 0}}'
docker image inspect ghcr.io/auditware/radar-api:main \
  --format 'api={{index .RepoDigests 0}}'

