#!/usr/bin/env bash
# Install systemd services for Dispatcharr FUSE movie/tv mounts.

set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run this script as root (for example: sudo ./install_systemd_mounts.sh)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:9191}"
BACKEND_HEALTHCHECK_URL="${BACKEND_HEALTHCHECK_URL:-$BACKEND_URL}"
MOVIES_MOUNTPOINT="${MOVIES_MOUNTPOINT:-}"
TV_MOUNTPOINT="${TV_MOUNTPOINT:-}"
DOCKER_WAIT_CONTAINER="${DOCKER_WAIT_CONTAINER:-}"

SERVICE_USER="${SERVICE_USER:-root}"
USE_SUDO="${USE_SUDO:-false}"

MOUNT_SCRIPT="${SCRIPT_DIR}/mount_linux.sh"
if [[ ! -x "$MOUNT_SCRIPT" ]]; then
  echo "Expected executable mount script at: $MOUNT_SCRIPT" >&2
  echo "Make it executable first: chmod +x $MOUNT_SCRIPT" >&2
  exit 1
fi

load_remote_mount_paths() {
  local settings_url="${BACKEND_URL%/}/api/fuse/settings/public/"
  local settings_json=""

  if command -v curl >/dev/null 2>&1; then
    settings_json="$(curl -fsS --connect-timeout 3 --max-time 8 "$settings_url" 2>/dev/null || true)"
  elif command -v wget >/dev/null 2>&1; then
    settings_json="$(wget -qO- --timeout=8 "$settings_url" 2>/dev/null || true)"
  fi

  if [[ -z "$settings_json" ]]; then
    return 0
  fi

  local exported=""
  exported="$(python3 - "$settings_json" <<'PY'
import json
import shlex
import sys

try:
    data = json.loads(sys.argv[1])
except Exception:
    data = {}

if not isinstance(data, dict):
    data = {}

movies = str(data.get("movies_mount_path") or "")
tv = str(data.get("tv_mount_path") or "")
if movies:
    print(f"REMOTE_MOVIES_MOUNT_PATH={shlex.quote(movies)}")
if tv:
    print(f"REMOTE_TV_MOUNT_PATH={shlex.quote(tv)}")
PY
)"

  if [[ -n "$exported" ]]; then
    eval "$exported"
  fi
}

load_remote_mount_paths

MOVIES_MOUNTPOINT="${MOVIES_MOUNTPOINT:-${REMOTE_MOVIES_MOUNT_PATH:-/mnt/vod_movies}}"
TV_MOUNTPOINT="${TV_MOUNTPOINT:-${REMOTE_TV_MOUNT_PATH:-/mnt/vod_tv}}"

mkdir -p "$MOVIES_MOUNTPOINT" "$TV_MOUNTPOINT"

write_service() {
  local unit_name="$1"
  local mode="$2"
  local unit_path="${SYSTEMD_DIR}/${unit_name}.service"

  cat >"$unit_path" <<EOF
[Unit]
Description=Dispatcharr FUSE ${mode} mount
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${SCRIPT_DIR}
Environment=MODE=${mode}
Environment=BACKEND_URL=${BACKEND_URL}
Environment=USE_SUDO=${USE_SUDO}
Environment=BACKEND_HEALTHCHECK_URL=${BACKEND_HEALTHCHECK_URL}
Environment=DOCKER_WAIT_CONTAINER=${DOCKER_WAIT_CONTAINER}
ExecStartPre=/usr/bin/env bash -c 'if [[ -n "$DOCKER_WAIT_CONTAINER" ]]; then until docker inspect -f "{{.State.Running}}" "$DOCKER_WAIT_CONTAINER" 2>/dev/null | grep -q true; do echo "Waiting for Docker container $DOCKER_WAIT_CONTAINER..."; sleep 2; done; fi'
ExecStartPre=/usr/bin/env bash -c 'until curl -sS --output /dev/null --connect-timeout 2 --max-time 5 "$BACKEND_HEALTHCHECK_URL"; do echo "Waiting for backend $BACKEND_HEALTHCHECK_URL..."; sleep 2; done'
ExecStart=${MOUNT_SCRIPT}
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStartSec=0
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

  echo "Wrote ${unit_path}"
}

write_service "dispatcharr-fuse-movies" "movies"
write_service "dispatcharr-fuse-tv" "tv"

systemctl daemon-reload
systemctl enable --now dispatcharr-fuse-movies.service dispatcharr-fuse-tv.service

echo
echo "Services installed and started:"
echo "  - dispatcharr-fuse-movies.service"
echo "  - dispatcharr-fuse-tv.service"
echo "Mount paths are read from Fuse Settings at startup:"
echo "  movies -> ${MOVIES_MOUNTPOINT}"
echo "  tv     -> ${TV_MOUNTPOINT}"
echo
echo "Check status with:"
echo "  systemctl status dispatcharr-fuse-movies.service --no-pager"
echo "  systemctl status dispatcharr-fuse-tv.service --no-pager"
echo
echo "Optional: to also wait for a specific container before mounting, reinstall with:"
echo "  DOCKER_WAIT_CONTAINER=<container_name> sudo ./install_systemd_mounts.sh"
