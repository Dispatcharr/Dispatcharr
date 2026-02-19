#!/usr/bin/env bash
# Dispatcharr FUSE Linux mount runtime + guided installer.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
PROJECT_ROOT="${PROJECT_ROOT:-$SCRIPT_DIR}"

CONFIG_DIR="${CONFIG_DIR:-/etc/dispatcharr}"
CONFIG_FILE="${CONFIG_FILE:-$CONFIG_DIR/fuse-installer.env}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
INSTALL_SCRIPT_PATH="${INSTALL_SCRIPT_PATH:-$CONFIG_DIR/mount_linux.sh}"

SERVICE_MOVIES="dispatcharr-fuse-movies.service"
SERVICE_TV="dispatcharr-fuse-tv.service"

DEFAULT_BACKEND_URL="http://127.0.0.1:9191"
DEFAULT_MOVIES_MOUNTPOINT="/mnt/vod_movies"
DEFAULT_TV_MOUNTPOINT="/mnt/vod_tv"

MODE_WAS_EXPLICIT=false
if [[ -n "${MODE+x}" ]]; then
  MODE_WAS_EXPLICIT=true
fi

ACTION="${ACTION:-}"
if [[ "${1:-}" == "--mount" ]]; then
  ACTION="mount"
  shift
elif [[ "${1:-}" == "--install" ]]; then
  ACTION="install"
  shift
elif [[ "${1:-}" == "--change-mounts" ]]; then
  ACTION="change-mounts"
  shift
elif [[ "${1:-}" == "--restart" ]]; then
  ACTION="restart"
  shift
elif [[ "${1:-}" == "--uninstall" ]]; then
  ACTION="uninstall"
  shift
elif [[ "${1:-}" == "--status" ]]; then
  ACTION="status"
  shift
fi

# Runtime env knobs used by fuse_client.py (preserved compatibility)
MODE="${MODE:-movies}"
BACKEND_URL="${BACKEND_URL:-$DEFAULT_BACKEND_URL}"
MOUNTPOINT="${MOUNTPOINT:-}"
VENV_PATH="${VENV_PATH:-}"
FUSE_HOST_TOKEN="${FUSE_HOST_TOKEN:-}"
FUSE_PAIRING_TOKEN="${FUSE_PAIRING_TOKEN:-}"
FUSE_MAX_READ="${FUSE_MAX_READ:-}"
READAHEAD_BYTES="${READAHEAD_BYTES:-}"
PROBE_READ_BYTES="${PROBE_READ_BYTES:-}"
MKV_PREFETCH_BYTES="${MKV_PREFETCH_BYTES:-}"
MKV_MAX_FETCH_BYTES="${MKV_MAX_FETCH_BYTES:-}"
MKV_BUFFER_CACHE_BYTES="${MKV_BUFFER_CACHE_BYTES:-}"
PREFETCH_TRIGGER_BYTES="${PREFETCH_TRIGGER_BYTES:-}"
TRANSCODER_PREFETCH_BYTES="${TRANSCODER_PREFETCH_BYTES:-}"
TRANSCODER_MAX_FETCH_BYTES="${TRANSCODER_MAX_FETCH_BYTES:-}"
BUFFER_CACHE_BYTES="${BUFFER_CACHE_BYTES:-}"
SMOOTH_BUFFERING_ENABLED="${SMOOTH_BUFFERING_ENABLED:-}"
INITIAL_PREBUFFER_BYTES="${INITIAL_PREBUFFER_BYTES:-}"
INITIAL_PREBUFFER_TIMEOUT_SECONDS="${INITIAL_PREBUFFER_TIMEOUT_SECONDS:-}"
TARGET_BUFFER_AHEAD_BYTES="${TARGET_BUFFER_AHEAD_BYTES:-}"
LOW_WATERMARK_BYTES="${LOW_WATERMARK_BYTES:-}"
MAX_TOTAL_BUFFER_BYTES="${MAX_TOTAL_BUFFER_BYTES:-}"
PREFETCH_LOOP_SLEEP_SECONDS="${PREFETCH_LOOP_SLEEP_SECONDS:-}"
SEEK_RESET_THRESHOLD_BYTES="${SEEK_RESET_THRESHOLD_BYTES:-}"
BUFFER_RELEASE_ON_CLOSE="${BUFFER_RELEASE_ON_CLOSE:-}"
PLEX_SCANNER_PROBE_READS="${PLEX_SCANNER_PROBE_READS:-}"
PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES="${PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES:-}"
PLEX_SCANNER_PROBE_MAX_READ_BYTES="${PLEX_SCANNER_PROBE_MAX_READ_BYTES:-}"
PLEX_MEDIA_SERVER_PROBE_READS="${PLEX_MEDIA_SERVER_PROBE_READS:-}"
PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS="${PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS:-}"
PLEX_DEDICATED_SCANNER_ALWAYS_PROBE="${PLEX_DEDICATED_SCANNER_ALWAYS_PROBE:-}"
PLEX_DEDICATED_SCANNER_PROBE_READS="${PLEX_DEDICATED_SCANNER_PROBE_READS:-}"
PLEX_FAKE_EOF_PROBE_TAIL_BYTES="${PLEX_FAKE_EOF_PROBE_TAIL_BYTES:-}"
PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES="${PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES:-}"
UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES="${UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES:-}"
UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES="${UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES:-}"
FUSE_LOG_ACCESS_EVENTS="${FUSE_LOG_ACCESS_EVENTS:-}"
FUSE_LOG_PROBE_READS="${FUSE_LOG_PROBE_READS:-}"
PROBE_LOG_INITIAL_HITS="${PROBE_LOG_INITIAL_HITS:-}"
PROBE_LOG_EVERY_N_HITS="${PROBE_LOG_EVERY_N_HITS:-}"
FUSE_CLIENT_AUTO_UPDATE="${FUSE_CLIENT_AUTO_UPDATE:-true}"
USE_SUDO="${USE_SUDO:-false}"
SKIP_PIP_INSTALL="${SKIP_PIP_INSTALL:-false}"

# Local installer state (loaded/saved in CONFIG_FILE)
CFG_BACKEND_URL=""
CFG_MOVIES_MOUNTPOINT=""
CFG_TV_MOUNTPOINT=""
CFG_VENV_PATH=""
CFG_FUSE_HOST_TOKEN=""

REMOTE_MOVIES_MOUNT_PATH=""
REMOTE_TV_MOUNT_PATH=""
REMOTE_FUSE_MAX_READ=""
REMOTE_READAHEAD_BYTES=""
REMOTE_PROBE_READ_BYTES=""
REMOTE_MKV_PREFETCH_BYTES=""
REMOTE_MKV_MAX_FETCH_BYTES=""
REMOTE_MKV_BUFFER_CACHE_BYTES=""
REMOTE_PREFETCH_TRIGGER_BYTES=""
REMOTE_TRANSCODER_PREFETCH_BYTES=""
REMOTE_TRANSCODER_MAX_FETCH_BYTES=""
REMOTE_BUFFER_CACHE_BYTES=""
REMOTE_SMOOTH_BUFFERING_ENABLED=""
REMOTE_INITIAL_PREBUFFER_BYTES=""
REMOTE_INITIAL_PREBUFFER_TIMEOUT_SECONDS=""
REMOTE_TARGET_BUFFER_AHEAD_BYTES=""
REMOTE_LOW_WATERMARK_BYTES=""
REMOTE_MAX_TOTAL_BUFFER_BYTES=""
REMOTE_PREFETCH_LOOP_SLEEP_SECONDS=""
REMOTE_SEEK_RESET_THRESHOLD_BYTES=""
REMOTE_BUFFER_RELEASE_ON_CLOSE=""
REMOTE_PLEX_SCANNER_PROBE_READS=""
REMOTE_PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES=""
REMOTE_PLEX_SCANNER_PROBE_MAX_READ_BYTES=""
REMOTE_PLEX_MEDIA_SERVER_PROBE_READS=""
REMOTE_PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS=""
REMOTE_PLEX_DEDICATED_SCANNER_ALWAYS_PROBE=""
REMOTE_PLEX_DEDICATED_SCANNER_PROBE_READS=""
REMOTE_PLEX_FAKE_EOF_PROBE_TAIL_BYTES=""
REMOTE_PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES=""
REMOTE_UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES=""
REMOTE_UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES=""
REMOTE_FUSE_LOG_ACCESS_EVENTS=""
REMOTE_FUSE_LOG_PROBE_READS=""
REMOTE_PROBE_LOG_INITIAL_HITS=""
REMOTE_PROBE_LOG_EVERY_N_HITS=""

UI_BACKEND="text"

resolve_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    return
  fi
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
  elif command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="python3.11"
  else
    PYTHON_BIN="python3"
  fi
}

load_local_config() {
  if [[ -f "$CONFIG_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
  fi

  CFG_BACKEND_URL="${BACKEND_URL_SAVED:-${BACKEND_URL:-$DEFAULT_BACKEND_URL}}"
  CFG_MOVIES_MOUNTPOINT="${MOVIES_MOUNTPOINT_SAVED:-${MOVIES_MOUNTPOINT:-$DEFAULT_MOVIES_MOUNTPOINT}}"
  CFG_TV_MOUNTPOINT="${TV_MOUNTPOINT_SAVED:-${TV_MOUNTPOINT:-$DEFAULT_TV_MOUNTPOINT}}"

  if [[ -n "${VENV_PATH_SAVED:-}" ]]; then
    CFG_VENV_PATH="$VENV_PATH_SAVED"
  elif [[ -n "${VENV_PATH:-}" ]]; then
    CFG_VENV_PATH="$VENV_PATH"
  elif [[ -d "/root/.venv" ]]; then
    CFG_VENV_PATH="/root/.venv"
  else
    CFG_VENV_PATH="$SCRIPT_DIR/.venv"
  fi

  CFG_FUSE_HOST_TOKEN="${FUSE_HOST_TOKEN_SAVED:-${FUSE_HOST_TOKEN:-}}"
}

save_local_config() {
  mkdir -p "$CONFIG_DIR"
  cat >"$CONFIG_FILE" <<EOCFG
BACKEND_URL_SAVED=$(printf '%q' "$CFG_BACKEND_URL")
MOVIES_MOUNTPOINT_SAVED=$(printf '%q' "$CFG_MOVIES_MOUNTPOINT")
TV_MOUNTPOINT_SAVED=$(printf '%q' "$CFG_TV_MOUNTPOINT")
VENV_PATH_SAVED=$(printf '%q' "$CFG_VENV_PATH")
FUSE_HOST_TOKEN_SAVED=$(printf '%q' "$CFG_FUSE_HOST_TOKEN")
EOCFG
  chmod 600 "$CONFIG_FILE"
}

load_remote_fuse_settings() {
  local backend="$1"
  local settings_url="${backend%/}/api/fuse/settings/public/"
  local settings_json=""

  REMOTE_MOVIES_MOUNT_PATH=""
  REMOTE_TV_MOUNT_PATH=""
  REMOTE_FUSE_MAX_READ=""
  REMOTE_READAHEAD_BYTES=""
  REMOTE_PROBE_READ_BYTES=""
  REMOTE_MKV_PREFETCH_BYTES=""
  REMOTE_MKV_MAX_FETCH_BYTES=""
  REMOTE_MKV_BUFFER_CACHE_BYTES=""
  REMOTE_PREFETCH_TRIGGER_BYTES=""
  REMOTE_TRANSCODER_PREFETCH_BYTES=""
  REMOTE_TRANSCODER_MAX_FETCH_BYTES=""
  REMOTE_BUFFER_CACHE_BYTES=""
  REMOTE_SMOOTH_BUFFERING_ENABLED=""
  REMOTE_INITIAL_PREBUFFER_BYTES=""
  REMOTE_INITIAL_PREBUFFER_TIMEOUT_SECONDS=""
  REMOTE_TARGET_BUFFER_AHEAD_BYTES=""
  REMOTE_LOW_WATERMARK_BYTES=""
  REMOTE_MAX_TOTAL_BUFFER_BYTES=""
  REMOTE_PREFETCH_LOOP_SLEEP_SECONDS=""
  REMOTE_SEEK_RESET_THRESHOLD_BYTES=""
  REMOTE_BUFFER_RELEASE_ON_CLOSE=""
  REMOTE_PLEX_SCANNER_PROBE_READS=""
  REMOTE_PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES=""
  REMOTE_PLEX_SCANNER_PROBE_MAX_READ_BYTES=""
  REMOTE_PLEX_MEDIA_SERVER_PROBE_READS=""
  REMOTE_PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS=""
  REMOTE_PLEX_DEDICATED_SCANNER_ALWAYS_PROBE=""
  REMOTE_PLEX_DEDICATED_SCANNER_PROBE_READS=""
  REMOTE_PLEX_FAKE_EOF_PROBE_TAIL_BYTES=""
  REMOTE_PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES=""
  REMOTE_UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES=""
  REMOTE_UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES=""
  REMOTE_FUSE_LOG_ACCESS_EVENTS=""
  REMOTE_FUSE_LOG_PROBE_READS=""
  REMOTE_PROBE_LOG_INITIAL_HITS=""
  REMOTE_PROBE_LOG_EVERY_N_HITS=""

  if command -v curl >/dev/null 2>&1; then
    settings_json="$(curl -fsS --connect-timeout 3 --max-time 8 "$settings_url" 2>/dev/null || true)"
  elif command -v wget >/dev/null 2>&1; then
    settings_json="$(wget -qO- --timeout=8 "$settings_url" 2>/dev/null || true)"
  fi

  if [[ -z "$settings_json" ]]; then
    return 0
  fi

  local exported=""
  exported="$($PYTHON_BIN - "$settings_json" <<'PY'
import json
import shlex
import sys

try:
    data = json.loads(sys.argv[1])
except Exception:
    data = {}

if not isinstance(data, dict):
    data = {}

mapping = {
    "REMOTE_MOVIES_MOUNT_PATH": "movies_mount_path",
    "REMOTE_TV_MOUNT_PATH": "tv_mount_path",
    "REMOTE_FUSE_MAX_READ": "fuse_max_read",
    "REMOTE_READAHEAD_BYTES": "readahead_bytes",
    "REMOTE_PROBE_READ_BYTES": "probe_read_bytes",
    "REMOTE_MKV_PREFETCH_BYTES": "mkv_prefetch_bytes",
    "REMOTE_MKV_MAX_FETCH_BYTES": "mkv_max_fetch_bytes",
    "REMOTE_MKV_BUFFER_CACHE_BYTES": "mkv_buffer_cache_bytes",
    "REMOTE_PREFETCH_TRIGGER_BYTES": "prefetch_trigger_bytes",
    "REMOTE_TRANSCODER_PREFETCH_BYTES": "transcoder_prefetch_bytes",
    "REMOTE_TRANSCODER_MAX_FETCH_BYTES": "transcoder_max_fetch_bytes",
    "REMOTE_BUFFER_CACHE_BYTES": "buffer_cache_bytes",
    "REMOTE_SMOOTH_BUFFERING_ENABLED": "smooth_buffering_enabled",
    "REMOTE_INITIAL_PREBUFFER_BYTES": "initial_prebuffer_bytes",
    "REMOTE_INITIAL_PREBUFFER_TIMEOUT_SECONDS": "initial_prebuffer_timeout_seconds",
    "REMOTE_TARGET_BUFFER_AHEAD_BYTES": "target_buffer_ahead_bytes",
    "REMOTE_LOW_WATERMARK_BYTES": "low_watermark_bytes",
    "REMOTE_MAX_TOTAL_BUFFER_BYTES": "max_total_buffer_bytes",
    "REMOTE_PREFETCH_LOOP_SLEEP_SECONDS": "prefetch_loop_sleep_seconds",
    "REMOTE_SEEK_RESET_THRESHOLD_BYTES": "seek_reset_threshold_bytes",
    "REMOTE_BUFFER_RELEASE_ON_CLOSE": "buffer_release_on_close",
    "REMOTE_PLEX_SCANNER_PROBE_READS": "plex_scanner_probe_reads",
    "REMOTE_PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES": "plex_scanner_probe_max_offset_bytes",
    "REMOTE_PLEX_SCANNER_PROBE_MAX_READ_BYTES": "plex_scanner_probe_max_read_bytes",
    "REMOTE_PLEX_MEDIA_SERVER_PROBE_READS": "plex_media_server_probe_reads",
    "REMOTE_PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS": "plex_dedicated_scanner_allow_stream_reads",
    "REMOTE_PLEX_DEDICATED_SCANNER_ALWAYS_PROBE": "plex_dedicated_scanner_always_probe",
    "REMOTE_PLEX_DEDICATED_SCANNER_PROBE_READS": "plex_dedicated_scanner_probe_reads",
    "REMOTE_PLEX_FAKE_EOF_PROBE_TAIL_BYTES": "plex_fake_eof_probe_tail_bytes",
    "REMOTE_PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES": "plex_fake_eof_probe_max_read_bytes",
    "REMOTE_UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES": "unknown_process_probe_max_read_bytes",
    "REMOTE_UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES": "unknown_process_probe_max_offset_bytes",
    "REMOTE_FUSE_LOG_ACCESS_EVENTS": "fuse_log_access_events",
    "REMOTE_FUSE_LOG_PROBE_READS": "fuse_log_probe_reads",
    "REMOTE_PROBE_LOG_INITIAL_HITS": "probe_log_initial_hits",
    "REMOTE_PROBE_LOG_EVERY_N_HITS": "probe_log_every_n_hits",
}

for env_key, source_key in mapping.items():
    if source_key not in data:
        continue
    value = data.get(source_key)
    if value is None:
        continue
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    print(f"{env_key}={shlex.quote(text)}")
PY
)"

  if [[ -n "$exported" ]]; then
    eval "$exported"
  fi
}

register_fuse_host_token() {
  local backend="$1"
  local pairing_token="$2"
  local mountpoint_hint="${3:-}"
  local hostname=""
  local register_url=""
  local payload=""
  local response=""
  local host_token=""

  hostname="$(hostname 2>/dev/null || uname -n 2>/dev/null || echo "unknown")"
  register_url="${backend%/}/api/fuse/register-host/"

  payload="$($PYTHON_BIN - "$pairing_token" "$hostname" "$mountpoint_hint" <<'PY'
import json
import os
import sys

pairing_token = sys.argv[1] if len(sys.argv) > 1 else ""
hostname = sys.argv[2] if len(sys.argv) > 2 else "unknown"
mountpoint = sys.argv[3] if len(sys.argv) > 3 else ""
client_id = os.getenv("FUSE_CLIENT_ID", "")

print(
    json.dumps(
        {
            "pairing_token": pairing_token,
            "hostname": hostname,
            "client_id": client_id,
            "mountpoint": mountpoint,
        }
    )
)
PY
)"

  if command -v curl >/dev/null 2>&1; then
    response="$(curl -fsS --connect-timeout 5 --max-time 20 \
      -H "Content-Type: application/json" \
      -d "$payload" \
      "$register_url" 2>/dev/null || true)"
  elif command -v wget >/dev/null 2>&1; then
    response="$(wget -qO- --timeout=20 \
      --header="Content-Type: application/json" \
      --post-data="$payload" \
      "$register_url" 2>/dev/null || true)"
  else
    echo "Need curl or wget to register FUSE host token." >&2
    return 1
  fi

  if [[ -z "$response" ]]; then
    echo "Host registration failed (empty response)." >&2
    return 1
  fi

  host_token="$($PYTHON_BIN - "$response" <<'PY'
import json
import sys

try:
    data = json.loads(sys.argv[1])
except Exception:
    data = {}

token = data.get("host_token") if isinstance(data, dict) else ""
if token is None:
    token = ""
print(str(token))
PY
)"

  if [[ -z "$host_token" ]]; then
    echo "Host registration failed: $response" >&2
    return 1
  fi

  printf '%s' "$host_token"
}

is_target_mounted() {
  local mountpoint="$1"
  local escaped_mountpoint
  escaped_mountpoint="$(printf '%s' "$mountpoint" | sed 's/ /\\040/g')"
  grep -qs " ${escaped_mountpoint} " /proc/mounts
}

get_fusermount_bin() {
  if command -v fusermount3 >/dev/null 2>&1; then
    printf '%s' "fusermount3"
    return 0
  fi
  if command -v fusermount >/dev/null 2>&1; then
    printf '%s' "fusermount"
    return 0
  fi
  printf '%s' ""
}

safe_unmount() {
  local mountpoint="$1"
  local fusermount_bin
  fusermount_bin="$(get_fusermount_bin)"

  if is_target_mounted "$mountpoint"; then
    if [[ -n "$fusermount_bin" ]]; then
      "$fusermount_bin" -uz "$mountpoint" >/dev/null 2>&1 || true
    fi
    if is_target_mounted "$mountpoint"; then
      umount -l "$mountpoint" >/dev/null 2>&1 || true
    fi
  fi
}

ensure_venv_dependencies() {
  local venv_path="$1"
  local skip_pip_install="$2"

  if [[ ! -d "$venv_path" ]]; then
    if [[ "$skip_pip_install" == "true" ]]; then
      echo "Virtual environment not found: $venv_path" >&2
      echo "Set SKIP_PIP_INSTALL=false to create/install automatically." >&2
      return 1
    fi
    echo "==> Creating virtual environment at $venv_path"
    "$PYTHON_BIN" -m venv "$venv_path"
  fi

  # shellcheck disable=SC1090
  source "$venv_path/bin/activate"

  if [[ "$skip_pip_install" == "true" ]]; then
    if ! "$venv_path/bin/python" -c "import requests; import fuse" >/dev/null 2>&1; then
      echo "Missing Python dependencies in $venv_path (need requests + fusepy)." >&2
      return 1
    fi
    return 0
  fi

  if ! "$venv_path/bin/python" -c "import requests; import fuse" >/dev/null 2>&1; then
    echo "==> Installing Python dependencies (fusepy, requests)"
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$venv_path/bin/pip" install --quiet --upgrade pip
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$venv_path/bin/pip" install --quiet fusepy requests
  else
    echo "==> Python dependencies already installed"
  fi
}

ensure_fuse_client_script() {
  local backend="$1"
  local target_dir="${2:-$SCRIPT_DIR}"
  local client_path="$target_dir/fuse_client.py"
  local auto_update
  auto_update="$(printf '%s' "${FUSE_CLIENT_AUTO_UPDATE:-true}" | tr '[:upper:]' '[:lower:]')"
  local should_update="true"
  if [[ "$auto_update" == "0" || "$auto_update" == "false" || "$auto_update" == "no" || "$auto_update" == "off" ]]; then
    should_update="false"
  fi

  if [[ -f "$client_path" && "$should_update" != "true" ]]; then
    return 0
  fi

  mkdir -p "$target_dir"
  local tmp_path
  tmp_path="$(mktemp "${target_dir}/.fuse_client.py.XXXXXX")"
  if [[ -f "$client_path" ]]; then
    echo "==> Refreshing fuse_client.py from ${backend%/}/api/fuse/client-script/"
  else
    echo "==> fuse_client.py not found, downloading from ${backend%/}/api/fuse/client-script/"
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${backend%/}/api/fuse/client-script/" -o "$tmp_path"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp_path" "${backend%/}/api/fuse/client-script/"
  else
    echo "Need curl or wget to download fuse_client.py" >&2
    rm -f "$tmp_path"
    return 1
  fi
  mv -f "$tmp_path" "$client_path"
  chmod 644 "$client_path"
}

prepare_install_runtime() {
  local backend="$1"
  local install_dir
  install_dir="$(dirname "$INSTALL_SCRIPT_PATH")"

  mkdir -p "$install_dir"

  if [[ "$SCRIPT_PATH" != "$INSTALL_SCRIPT_PATH" ]]; then
    cp -f "$SCRIPT_PATH" "$INSTALL_SCRIPT_PATH"
  fi
  chmod 755 "$INSTALL_SCRIPT_PATH"
  chown root:root "$INSTALL_SCRIPT_PATH" >/dev/null 2>&1 || true

  ensure_fuse_client_script "$backend" "$install_dir"
}

run_mount_mode() {
  resolve_python
  load_local_config

  local mode="$MODE"
  if [[ "$mode" != "movies" && "$mode" != "tv" ]]; then
    echo "MODE must be 'movies' or 'tv'" >&2
    exit 1
  fi

  local backend_url="${BACKEND_URL:-${CFG_BACKEND_URL:-$DEFAULT_BACKEND_URL}}"
  load_remote_fuse_settings "$backend_url"

  local config_mountpoint
  local remote_mountpoint
  local default_mountpoint

  if [[ "$mode" == "movies" ]]; then
    config_mountpoint="${CFG_MOVIES_MOUNTPOINT:-$DEFAULT_MOVIES_MOUNTPOINT}"
    remote_mountpoint="${REMOTE_MOVIES_MOUNT_PATH:-}"
    default_mountpoint="$DEFAULT_MOVIES_MOUNTPOINT"
  else
    config_mountpoint="${CFG_TV_MOUNTPOINT:-$DEFAULT_TV_MOUNTPOINT}"
    remote_mountpoint="${REMOTE_TV_MOUNT_PATH:-}"
    default_mountpoint="$DEFAULT_TV_MOUNTPOINT"
  fi

  local mountpoint="${MOUNTPOINT:-${config_mountpoint:-${remote_mountpoint:-$default_mountpoint}}}"

  local venv_path="${VENV_PATH:-${CFG_VENV_PATH:-}}"
  if [[ -z "$venv_path" ]]; then
    if [[ -d "/root/.venv" ]]; then
      venv_path="/root/.venv"
    else
      venv_path="$SCRIPT_DIR/.venv"
    fi
  fi

  local fuse_host_token="${FUSE_HOST_TOKEN:-${CFG_FUSE_HOST_TOKEN:-}}"
  if [[ -z "$fuse_host_token" ]]; then
    echo "Missing FUSE host token. Re-run installer and pair this host with a one-time token." >&2
    exit 1
  fi

  local fuse_max_read="${FUSE_MAX_READ:-${REMOTE_FUSE_MAX_READ:-8388608}}"
  local readahead_bytes="${READAHEAD_BYTES:-${REMOTE_READAHEAD_BYTES:-1048576}}"
  local probe_read_bytes="${PROBE_READ_BYTES:-${REMOTE_PROBE_READ_BYTES:-524288}}"
  local mkv_prefetch_bytes="${MKV_PREFETCH_BYTES:-${REMOTE_MKV_PREFETCH_BYTES:-16777216}}"
  local mkv_max_fetch_bytes="${MKV_MAX_FETCH_BYTES:-${REMOTE_MKV_MAX_FETCH_BYTES:-33554432}}"
  local mkv_buffer_cache_bytes="${MKV_BUFFER_CACHE_BYTES:-${REMOTE_MKV_BUFFER_CACHE_BYTES:-100663296}}"
  local prefetch_trigger_bytes="${PREFETCH_TRIGGER_BYTES:-${REMOTE_PREFETCH_TRIGGER_BYTES:-2097152}}"
  local transcoder_prefetch_bytes="${TRANSCODER_PREFETCH_BYTES:-${REMOTE_TRANSCODER_PREFETCH_BYTES:-4194304}}"
  local transcoder_max_fetch_bytes="${TRANSCODER_MAX_FETCH_BYTES:-${REMOTE_TRANSCODER_MAX_FETCH_BYTES:-8388608}}"
  local buffer_cache_bytes="${BUFFER_CACHE_BYTES:-${REMOTE_BUFFER_CACHE_BYTES:-33554432}}"
  local smooth_buffering_enabled="${SMOOTH_BUFFERING_ENABLED:-${REMOTE_SMOOTH_BUFFERING_ENABLED:-true}}"
  local initial_prebuffer_bytes="${INITIAL_PREBUFFER_BYTES:-${REMOTE_INITIAL_PREBUFFER_BYTES:-33554432}}"
  local initial_prebuffer_timeout_seconds="${INITIAL_PREBUFFER_TIMEOUT_SECONDS:-${REMOTE_INITIAL_PREBUFFER_TIMEOUT_SECONDS:-20}}"
  local target_buffer_ahead_bytes="${TARGET_BUFFER_AHEAD_BYTES:-${REMOTE_TARGET_BUFFER_AHEAD_BYTES:-134217728}}"
  local low_watermark_bytes="${LOW_WATERMARK_BYTES:-${REMOTE_LOW_WATERMARK_BYTES:-16777216}}"
  local max_total_buffer_bytes="${MAX_TOTAL_BUFFER_BYTES:-${REMOTE_MAX_TOTAL_BUFFER_BYTES:-1073741824}}"
  local prefetch_loop_sleep_seconds="${PREFETCH_LOOP_SLEEP_SECONDS:-${REMOTE_PREFETCH_LOOP_SLEEP_SECONDS:-0.12}}"
  local seek_reset_threshold_bytes="${SEEK_RESET_THRESHOLD_BYTES:-${REMOTE_SEEK_RESET_THRESHOLD_BYTES:-4194304}}"
  local buffer_release_on_close="${BUFFER_RELEASE_ON_CLOSE:-${REMOTE_BUFFER_RELEASE_ON_CLOSE:-true}}"
  local plex_scanner_probe_reads="${PLEX_SCANNER_PROBE_READS:-${REMOTE_PLEX_SCANNER_PROBE_READS:-1}}"
  local plex_scanner_probe_max_offset_bytes="${PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES:-${REMOTE_PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES:-4194304}}"
  local plex_scanner_probe_max_read_bytes="${PLEX_SCANNER_PROBE_MAX_READ_BYTES:-${REMOTE_PLEX_SCANNER_PROBE_MAX_READ_BYTES:-67108864}}"
  local plex_media_server_probe_reads="${PLEX_MEDIA_SERVER_PROBE_READS:-${REMOTE_PLEX_MEDIA_SERVER_PROBE_READS:-0}}"
  local plex_dedicated_scanner_allow_stream_reads="${PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS:-${REMOTE_PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS:-false}}"
  local plex_dedicated_scanner_always_probe="${PLEX_DEDICATED_SCANNER_ALWAYS_PROBE:-${REMOTE_PLEX_DEDICATED_SCANNER_ALWAYS_PROBE:-true}}"
  local plex_dedicated_scanner_probe_reads="${PLEX_DEDICATED_SCANNER_PROBE_READS:-${REMOTE_PLEX_DEDICATED_SCANNER_PROBE_READS:-8}}"
  local plex_fake_eof_probe_tail_bytes="${PLEX_FAKE_EOF_PROBE_TAIL_BYTES:-${REMOTE_PLEX_FAKE_EOF_PROBE_TAIL_BYTES:-4194304}}"
  local plex_fake_eof_probe_max_read_bytes="${PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES:-${REMOTE_PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES:-524288}}"
  local unknown_process_probe_max_read_bytes="${UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES:-${REMOTE_UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES:-2097152}}"
  local unknown_process_probe_max_offset_bytes="${UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES:-${REMOTE_UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES:-4194304}}"
  local fuse_log_access_events="${FUSE_LOG_ACCESS_EVENTS:-${REMOTE_FUSE_LOG_ACCESS_EVENTS:-false}}"
  local fuse_log_probe_reads="${FUSE_LOG_PROBE_READS:-${REMOTE_FUSE_LOG_PROBE_READS:-false}}"
  local probe_log_initial_hits="${PROBE_LOG_INITIAL_HITS:-${REMOTE_PROBE_LOG_INITIAL_HITS:-0}}"
  local probe_log_every_n_hits="${PROBE_LOG_EVERY_N_HITS:-${REMOTE_PROBE_LOG_EVERY_N_HITS:-0}}"

  echo "==> Using Python: $PYTHON_BIN"
  echo "==> Mode: $mode"
  echo "==> Backend: $backend_url"
  echo "==> Mountpoint: $mountpoint"
  echo "==> Venv: $venv_path"
  echo "==> FUSE host auth: enabled"
  echo "==> Docker bind example: $mountpoint:/vod/$mode:ro"
  echo "==> MKV prefetch: $mkv_prefetch_bytes bytes (max fetch: $mkv_max_fetch_bytes, cache: $mkv_buffer_cache_bytes, trigger: $prefetch_trigger_bytes)"
  echo "==> Smooth buffering: $smooth_buffering_enabled (initial=$initial_prebuffer_bytes target=$target_buffer_ahead_bytes max_total=$max_total_buffer_bytes)"
  echo "==> Scanner probe: reads=$plex_scanner_probe_reads max_offset=$plex_scanner_probe_max_offset_bytes max_read=$plex_scanner_probe_max_read_bytes media_server_reads=$plex_media_server_probe_reads dedicated_allow_reads=$plex_dedicated_scanner_allow_stream_reads dedicated_always_probe=$plex_dedicated_scanner_always_probe dedicated_probe_reads=$plex_dedicated_scanner_probe_reads fake_eof_tail=$plex_fake_eof_probe_tail_bytes fake_eof_max_read=$plex_fake_eof_probe_max_read_bytes unknown_max_read=$unknown_process_probe_max_read_bytes unknown_max_offset=$unknown_process_probe_max_offset_bytes auto_update=$FUSE_CLIENT_AUTO_UPDATE"
  echo "==> FUSE logs: access_events=$fuse_log_access_events probe_reads=$fuse_log_probe_reads probe_initial_hits=$probe_log_initial_hits probe_every_n_hits=$probe_log_every_n_hits"

  command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "Python not found: $PYTHON_BIN" >&2
    exit 1
  }

  ensure_fuse_client_script "$backend_url"

  if [[ -f /etc/fuse.conf ]] && ! grep -q "^[[:space:]]*user_allow_other" /etc/fuse.conf; then
    echo "Warning: /etc/fuse.conf does not enable user_allow_other; allow_other mounts may fail." >&2
  fi

  safe_unmount "$mountpoint"
  mkdir -p "$mountpoint"

  ensure_venv_dependencies "$venv_path" "$SKIP_PIP_INSTALL"

  export MKV_PREFETCH_BYTES="$mkv_prefetch_bytes"
  export MKV_MAX_FETCH_BYTES="$mkv_max_fetch_bytes"
  export MKV_BUFFER_CACHE_BYTES="$mkv_buffer_cache_bytes"
  export PREFETCH_TRIGGER_BYTES="$prefetch_trigger_bytes"
  export TRANSCODER_PREFETCH_BYTES="$transcoder_prefetch_bytes"
  export TRANSCODER_MAX_FETCH_BYTES="$transcoder_max_fetch_bytes"
  export BUFFER_CACHE_BYTES="$buffer_cache_bytes"
  export SMOOTH_BUFFERING_ENABLED="$smooth_buffering_enabled"
  export INITIAL_PREBUFFER_BYTES="$initial_prebuffer_bytes"
  export INITIAL_PREBUFFER_TIMEOUT_SECONDS="$initial_prebuffer_timeout_seconds"
  export TARGET_BUFFER_AHEAD_BYTES="$target_buffer_ahead_bytes"
  export LOW_WATERMARK_BYTES="$low_watermark_bytes"
  export MAX_TOTAL_BUFFER_BYTES="$max_total_buffer_bytes"
  export PREFETCH_LOOP_SLEEP_SECONDS="$prefetch_loop_sleep_seconds"
  export SEEK_RESET_THRESHOLD_BYTES="$seek_reset_threshold_bytes"
  export BUFFER_RELEASE_ON_CLOSE="$buffer_release_on_close"
  export PLEX_SCANNER_PROBE_READS="$plex_scanner_probe_reads"
  export PLEX_SCANNER_PROBE_MAX_OFFSET_BYTES="$plex_scanner_probe_max_offset_bytes"
  export PLEX_SCANNER_PROBE_MAX_READ_BYTES="$plex_scanner_probe_max_read_bytes"
  export PLEX_MEDIA_SERVER_PROBE_READS="$plex_media_server_probe_reads"
  export PLEX_DEDICATED_SCANNER_ALLOW_STREAM_READS="$plex_dedicated_scanner_allow_stream_reads"
  export PLEX_DEDICATED_SCANNER_ALWAYS_PROBE="$plex_dedicated_scanner_always_probe"
  export PLEX_DEDICATED_SCANNER_PROBE_READS="$plex_dedicated_scanner_probe_reads"
  export PLEX_FAKE_EOF_PROBE_TAIL_BYTES="$plex_fake_eof_probe_tail_bytes"
  export PLEX_FAKE_EOF_PROBE_MAX_READ_BYTES="$plex_fake_eof_probe_max_read_bytes"
  export UNKNOWN_PROCESS_PROBE_MAX_READ_BYTES="$unknown_process_probe_max_read_bytes"
  export UNKNOWN_PROCESS_PROBE_MAX_OFFSET_BYTES="$unknown_process_probe_max_offset_bytes"
  export FUSE_LOG_ACCESS_EVENTS="$fuse_log_access_events"
  export FUSE_LOG_PROBE_READS="$fuse_log_probe_reads"
  export PROBE_LOG_INITIAL_HITS="$probe_log_initial_hits"
  export PROBE_LOG_EVERY_N_HITS="$probe_log_every_n_hits"
  export FUSE_HOST_TOKEN="$fuse_host_token"

  cd "$PROJECT_ROOT"
  echo "==> Mounting..."

  if [[ "$USE_SUDO" == "true" ]]; then
    exec sudo -E "$venv_path/bin/python" "$SCRIPT_DIR/fuse_client.py" \
      --mode "$mode" \
      --backend-url "$backend_url" \
      --mountpoint "$mountpoint" \
      --max-read "$fuse_max_read" \
      --readahead-bytes "$readahead_bytes" \
      --probe-read-bytes "$probe_read_bytes" \
      --foreground
  else
    exec "$venv_path/bin/python" "$SCRIPT_DIR/fuse_client.py" \
      --mode "$mode" \
      --backend-url "$backend_url" \
      --mountpoint "$mountpoint" \
      --max-read "$fuse_max_read" \
      --readahead-bytes "$readahead_bytes" \
      --probe-read-bytes "$probe_read_bytes" \
      --foreground
  fi
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Please run as root (for example: sudo \"$SCRIPT_PATH\")" >&2
    exit 1
  fi
}

ui_init() {
  if command -v whiptail >/dev/null 2>&1 && [[ -t 0 ]]; then
    UI_BACKEND="whiptail"
  else
    UI_BACKEND="text"
  fi
}

ui_msg() {
  local title="$1"
  local message="$2"
  if [[ "$UI_BACKEND" == "whiptail" ]]; then
    whiptail --title "$title" --msgbox "$message" 14 78
  else
    echo
    echo "[$title]"
    echo "$message"
    echo
  fi
}

ui_error() {
  ui_msg "Error" "$1"
}

ui_yesno() {
  local title="$1"
  local message="$2"
  if [[ "$UI_BACKEND" == "whiptail" ]]; then
    whiptail --title "$title" --yesno "$message" 14 78
    return $?
  fi

  while true; do
    read -r -p "$message [y/N]: " ans
    ans="${ans:-N}"
    case "$ans" in
      [Yy]|[Yy][Ee][Ss]) return 0 ;;
      [Nn]|[Nn][Oo]) return 1 ;;
      *) echo "Please enter y or n." ;;
    esac
  done
}

ui_input() {
  local title="$1"
  local prompt="$2"
  local default_value="$3"
  local result=""

  if [[ "$UI_BACKEND" == "whiptail" ]]; then
    result=$(whiptail --title "$title" --inputbox "$prompt" 12 78 "$default_value" 3>&1 1>&2 2>&3) || return 1
    printf '%s' "$result"
    return 0
  fi

  read -r -p "$prompt [$default_value]: " result
  if [[ -z "$result" ]]; then
    result="$default_value"
  fi
  printf '%s' "$result"
}

ui_menu() {
  local title="$1"
  local prompt="$2"
  shift 2

  if [[ "$UI_BACKEND" == "whiptail" ]]; then
    local choice=""
    choice=$(whiptail --title "$title" --menu "$prompt" 20 84 10 "$@" 3>&1 1>&2 2>&3) || return 1
    printf '%s' "$choice"
    return 0
  fi

  local idx=1
  local tags=()
  local descriptions=()
  while (( "$#" )); do
    tags+=("$1")
    descriptions+=("$2")
    shift 2
  done

  echo
  echo "$title"
  echo "$prompt"
  for i in "${!tags[@]}"; do
    printf "  %d) %s\n" "$((i + 1))" "${descriptions[$i]}"
  done

  local pick=""
  while true; do
    read -r -p "Select an option [1-${#tags[@]}]: " pick
    if [[ "$pick" =~ ^[0-9]+$ ]] && (( pick >= 1 && pick <= ${#tags[@]} )); then
      printf '%s' "${tags[$((pick - 1))]}"
      return 0
    fi
    echo "Invalid selection."
  done
}

ensure_system_dependencies() {
  local package_manager=""
  if command -v apt-get >/dev/null 2>&1; then
    package_manager="apt-get"
  elif command -v dnf >/dev/null 2>&1; then
    package_manager="dnf"
  elif command -v yum >/dev/null 2>&1; then
    package_manager="yum"
  elif command -v pacman >/dev/null 2>&1; then
    package_manager="pacman"
  elif command -v zypper >/dev/null 2>&1; then
    package_manager="zypper"
  elif command -v apk >/dev/null 2>&1; then
    package_manager="apk"
  else
    package_manager="unknown"
  fi

  echo "==> Ensuring system dependencies for package manager: ${package_manager}"

  case "$package_manager" in
    apt-get)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -y
      if ! apt-get install -y --no-install-recommends \
        fuse3 libfuse2 python3 python3-venv python3-pip curl psmisc; then
        echo "==> Retrying apt install without libfuse2 compatibility package"
        apt-get install -y --no-install-recommends \
          fuse3 python3 python3-venv python3-pip curl psmisc || {
            echo "==> Automatic apt dependency install failed. Install dependencies manually."
            return 0
          }
      fi
      ;;
    dnf)
      if ! dnf install -y \
        fuse3 python3 python3-pip python3-virtualenv curl psmisc; then
        dnf install -y fuse3 python3 python3-pip curl psmisc || {
          echo "==> Automatic dnf dependency install failed. Install dependencies manually."
          return 0
        }
      fi
      ;;
    yum)
      if ! yum install -y \
        fuse3 python3 python3-pip python3-virtualenv curl psmisc; then
        yum install -y fuse3 python3 python3-pip curl psmisc || {
          echo "==> Automatic yum dependency install failed. Install dependencies manually."
          return 0
        }
      fi
      ;;
    pacman)
      if ! pacman -Sy --noconfirm --needed \
        fuse3 fuse2 python python-pip curl psmisc; then
        pacman -Sy --noconfirm --needed fuse3 python python-pip curl psmisc || {
          echo "==> Automatic pacman dependency install failed. Install dependencies manually."
          return 0
        }
      fi
      ;;
    zypper)
      zypper --non-interactive refresh || true
      if ! zypper --non-interactive install --no-recommends \
        fuse3 python3 python3-pip curl psmisc; then
        echo "==> Automatic zypper dependency install failed. Install dependencies manually."
        return 0
      fi
      ;;
    apk)
      if ! apk add --no-cache \
        fuse3 python3 py3-pip curl psmisc; then
        apk add --no-cache fuse3 python3 py3-pip curl || {
          echo "==> Automatic apk dependency install failed. Install dependencies manually."
          return 0
        }
      fi
      ;;
    *)
      echo "==> No supported package manager detected."
      echo "==> Install dependencies manually: fuse3, python3, python3-venv/virtualenv, pip, curl."
      ;;
  esac
}

ensure_fuse_conf() {
  if [[ -f /etc/fuse.conf ]]; then
    if ! grep -q "^[[:space:]]*user_allow_other" /etc/fuse.conf; then
      echo "==> Enabling user_allow_other in /etc/fuse.conf"
      echo "user_allow_other" >> /etc/fuse.conf
    fi
  fi
}

has_systemd() {
  command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

show_systemd_required_message() {
  local backend_hint="$1"
  local movies_hint="$2"
  local tv_hint="$3"
  local venv_hint="$4"
  local message=""

  message="$(cat <<EOFMSG
This installer can prepare dependencies and config on any Linux distro, but service management in this script uses systemd.

No active systemd environment was detected on this host.

You can still run mounts manually:

FUSE_HOST_TOKEN=<host-token> ACTION=mount MODE=movies BACKEND_URL=$backend_hint MOUNTPOINT=$movies_hint VENV_PATH=$venv_hint $SCRIPT_PATH
FUSE_HOST_TOKEN=<host-token> ACTION=mount MODE=tv BACKEND_URL=$backend_hint MOUNTPOINT=$tv_hint VENV_PATH=$venv_hint $SCRIPT_PATH
EOFMSG
)"

  ui_msg "Systemd Not Detected" "$message"
}

ensure_systemd_for_service_actions() {
  local backend_hint="$1"
  local movies_hint="$2"
  local tv_hint="$3"
  local venv_hint="$4"

  if has_systemd; then
    return 0
  fi

  show_systemd_required_message "$backend_hint" "$movies_hint" "$tv_hint" "$venv_hint"
  return 1
}

escape_systemd_env_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value"
}

write_systemd_service() {
  local unit_name="$1"
  local mode="$2"
  local mountpoint="$3"
  local backend="$4"
  local venv_path="$5"
  local script_path="${6:-$INSTALL_SCRIPT_PATH}"
  local fuse_host_token="${7:-}"

  local unit_path="$SYSTEMD_DIR/$unit_name"
  local backend_check="${backend%/}/api/fuse/settings/public/"
  local script_working_dir
  script_working_dir="$(dirname "$script_path")"

  local esc_backend esc_mountpoint esc_venv esc_backend_check esc_working_dir esc_script_path esc_host_token
  esc_backend="$(escape_systemd_env_value "$backend")"
  esc_mountpoint="$(escape_systemd_env_value "$mountpoint")"
  esc_venv="$(escape_systemd_env_value "$venv_path")"
  esc_backend_check="$(escape_systemd_env_value "$backend_check")"
  esc_working_dir="$(escape_systemd_env_value "$script_working_dir")"
  esc_script_path="$(escape_systemd_env_value "$script_path")"
  esc_host_token="$(escape_systemd_env_value "$fuse_host_token")"

  cat >"$unit_path" <<EOFUNIT
[Unit]
Description=Dispatcharr FUSE ${mode} mount
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${esc_working_dir}
Environment="ACTION=mount"
Environment="MODE=${mode}"
Environment="BACKEND_URL=${esc_backend}"
Environment="MOUNTPOINT=${esc_mountpoint}"
Environment="VENV_PATH=${esc_venv}"
Environment="FUSE_HOST_TOKEN=${esc_host_token}"
Environment="BACKEND_CHECK_URL=${esc_backend_check}"
Environment="SKIP_PIP_INSTALL=true"
Environment="USE_SUDO=false"
ExecStartPre=/usr/bin/env bash -c 'if command -v curl >/dev/null 2>&1; then curl -fsS --output /dev/null --connect-timeout 2 --max-time 5 "\$BACKEND_CHECK_URL"; elif command -v wget >/dev/null 2>&1; then wget -qO- --timeout=5 "\$BACKEND_CHECK_URL" >/dev/null; else echo "curl or wget is required for backend health checks."; exit 1; fi'
ExecStart=${esc_script_path}
Restart=always
RestartSec=3
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOFUNIT
}

install_or_update_services() {
  require_root
  resolve_python
  load_local_config

  local backend_default="${BACKEND_URL:-${CFG_BACKEND_URL:-$DEFAULT_BACKEND_URL}}"
  local backend_choice
  backend_choice="$(ui_input "Dispatcharr FUSE" "Backend URL:" "$backend_default")" || return 0
  backend_choice="${backend_choice:-$backend_default}"

  load_remote_fuse_settings "$backend_choice"

  local movies_default="${CFG_MOVIES_MOUNTPOINT:-${REMOTE_MOVIES_MOUNT_PATH:-$DEFAULT_MOVIES_MOUNTPOINT}}"
  local tv_default="${CFG_TV_MOUNTPOINT:-${REMOTE_TV_MOUNT_PATH:-$DEFAULT_TV_MOUNTPOINT}}"
  local venv_default="${CFG_VENV_PATH:-$( [[ -d /root/.venv ]] && echo /root/.venv || echo "$SCRIPT_DIR/.venv" )}"
  local existing_host_token="${CFG_FUSE_HOST_TOKEN:-${FUSE_HOST_TOKEN:-}}"

  local movies_choice tv_choice venv_choice
  movies_choice="$(ui_input "Dispatcharr FUSE" "Movies mount path on this host:" "$movies_default")" || return 0
  tv_choice="$(ui_input "Dispatcharr FUSE" "TV mount path on this host:" "$tv_default")" || return 0
  venv_choice="$(ui_input "Dispatcharr FUSE" "Python virtualenv path:" "$venv_default")" || return 0

  movies_choice="${movies_choice:-$movies_default}"
  tv_choice="${tv_choice:-$tv_default}"
  venv_choice="${venv_choice:-$venv_default}"

  local pairing_default="${FUSE_PAIRING_TOKEN:-}"
  local pairing_choice=""
  local host_token_choice="$existing_host_token"
  local token_summary="saved-token"

  if [[ -z "$host_token_choice" ]]; then
    pairing_choice="$(ui_input "Dispatcharr FUSE Auth" "One-time pairing token from Settings > FUSE:" "$pairing_default")" || return 0
    pairing_choice="${pairing_choice:-$pairing_default}"
    if [[ -z "$pairing_choice" ]]; then
      ui_error "A pairing token is required for first-time Linux install."
      return 1
    fi
    token_summary="new-pairing-token"
  else
    if ui_yesno "Dispatcharr FUSE Auth" "Use the saved host token on this machine?\n\nChoose 'No' to pair with a new one-time token."; then
      token_summary="saved-token"
    else
      pairing_choice="$(ui_input "Dispatcharr FUSE Auth" "New one-time pairing token from Settings > FUSE:" "$pairing_default")" || return 0
      pairing_choice="${pairing_choice:-$pairing_default}"
      if [[ -z "$pairing_choice" ]]; then
        ui_error "Pairing token cannot be empty."
        return 1
      fi
      token_summary="new-pairing-token"
    fi
  fi

  if ! ui_yesno "Confirm" "Install/update services with:\n\nBackend: $backend_choice\nMovies: $movies_choice\nTV: $tv_choice\nVenv: $venv_choice\nAuth: $token_summary\n\nProceed?"; then
    return 0
  fi

  if [[ -n "$pairing_choice" ]]; then
    echo "==> Registering host token with one-time pairing token"
    host_token_choice="$(register_fuse_host_token "$backend_choice" "$pairing_choice" "$movies_choice")"
    if [[ -z "$host_token_choice" ]]; then
      ui_error "Unable to register host token. Verify pairing token and backend URL."
      return 1
    fi
  fi

  if [[ -z "$host_token_choice" ]]; then
    ui_error "Host token is missing. Re-run install and provide a pairing token."
    return 1
  fi

  ensure_system_dependencies
  ensure_fuse_conf
  prepare_install_runtime "$backend_choice"
  chmod +x "$INSTALL_SCRIPT_PATH"

  VENV_PATH="$venv_choice"
  ensure_venv_dependencies "$venv_choice" "false"

  mkdir -p "$movies_choice" "$tv_choice"
  safe_unmount "$movies_choice"
  safe_unmount "$tv_choice"

  CFG_BACKEND_URL="$backend_choice"
  CFG_MOVIES_MOUNTPOINT="$movies_choice"
  CFG_TV_MOUNTPOINT="$tv_choice"
  CFG_VENV_PATH="$venv_choice"
  CFG_FUSE_HOST_TOKEN="$host_token_choice"
  save_local_config

  if ! ensure_systemd_for_service_actions "$backend_choice" "$movies_choice" "$tv_choice" "$venv_choice"; then
    ui_msg "Configured" "Saved settings and dependencies for manual FUSE mounts.\n\nRun mount commands manually using ACTION=mount MODE=movies|tv."
    return 0
  fi

  write_systemd_service "$SERVICE_MOVIES" "movies" "$movies_choice" "$backend_choice" "$venv_choice" "$INSTALL_SCRIPT_PATH" "$host_token_choice"
  write_systemd_service "$SERVICE_TV" "tv" "$tv_choice" "$backend_choice" "$venv_choice" "$INSTALL_SCRIPT_PATH" "$host_token_choice"

  systemctl daemon-reload
  systemctl enable --now "$SERVICE_MOVIES" "$SERVICE_TV"

  ui_msg "Success" "Dispatcharr FUSE services are installed and running.\n\nMovies: $movies_choice\nTV: $tv_choice\n\nUse this script again to change mount points, restart, or uninstall."
}

change_mountpoints() {
  require_root
  resolve_python
  load_local_config

  local backend="${CFG_BACKEND_URL:-$DEFAULT_BACKEND_URL}"
  load_remote_fuse_settings "$backend"

  local movies_default="${CFG_MOVIES_MOUNTPOINT:-${REMOTE_MOVIES_MOUNT_PATH:-$DEFAULT_MOVIES_MOUNTPOINT}}"
  local tv_default="${CFG_TV_MOUNTPOINT:-${REMOTE_TV_MOUNT_PATH:-$DEFAULT_TV_MOUNTPOINT}}"

  local movies_choice tv_choice
  movies_choice="$(ui_input "Dispatcharr FUSE" "New movies mount path:" "$movies_default")" || return 0
  tv_choice="$(ui_input "Dispatcharr FUSE" "New TV mount path:" "$tv_default")" || return 0

  movies_choice="${movies_choice:-$movies_default}"
  tv_choice="${tv_choice:-$tv_default}"

  if ! ui_yesno "Confirm" "Apply mountpoint changes?\n\nMovies: $movies_choice\nTV: $tv_choice"; then
    return 0
  fi

  mkdir -p "$movies_choice" "$tv_choice"

  CFG_MOVIES_MOUNTPOINT="$movies_choice"
  CFG_TV_MOUNTPOINT="$tv_choice"
  save_local_config

  if [[ -z "${CFG_FUSE_HOST_TOKEN:-}" ]]; then
    ui_error "No saved FUSE host token found. Run Install / Update and pair this host first."
    return 1
  fi

  if ! ensure_systemd_for_service_actions "$backend" "$movies_choice" "$tv_choice" "$CFG_VENV_PATH"; then
    ui_msg "Updated" "Mountpoints were updated in config for manual mount mode."
    return 0
  fi

  local service_script="$INSTALL_SCRIPT_PATH"
  if [[ ! -f "$service_script" ]]; then
    service_script="$SCRIPT_PATH"
  fi

  write_systemd_service "$SERVICE_MOVIES" "movies" "$movies_choice" "$backend" "$CFG_VENV_PATH" "$service_script" "$CFG_FUSE_HOST_TOKEN"
  write_systemd_service "$SERVICE_TV" "tv" "$tv_choice" "$backend" "$CFG_VENV_PATH" "$service_script" "$CFG_FUSE_HOST_TOKEN"

  systemctl daemon-reload
  systemctl restart "$SERVICE_MOVIES" "$SERVICE_TV"

  ui_msg "Updated" "Mountpoints were updated and services restarted."
}

restart_services() {
  require_root
  load_local_config

  local backend="${CFG_BACKEND_URL:-$DEFAULT_BACKEND_URL}"
  local movies_mount="${CFG_MOVIES_MOUNTPOINT:-$DEFAULT_MOVIES_MOUNTPOINT}"
  local tv_mount="${CFG_TV_MOUNTPOINT:-$DEFAULT_TV_MOUNTPOINT}"
  local venv_path="${CFG_VENV_PATH:-$SCRIPT_DIR/.venv}"

  if ! ensure_systemd_for_service_actions "$backend" "$movies_mount" "$tv_mount" "$venv_path"; then
    return 0
  fi

  systemctl restart "$SERVICE_MOVIES" "$SERVICE_TV"
  ui_msg "Restarted" "Restarted:\n- $SERVICE_MOVIES\n- $SERVICE_TV"
}

show_status() {
  load_local_config

  local backend="${CFG_BACKEND_URL:-$DEFAULT_BACKEND_URL}"
  local movies_mount="${CFG_MOVIES_MOUNTPOINT:-$DEFAULT_MOVIES_MOUNTPOINT}"
  local tv_mount="${CFG_TV_MOUNTPOINT:-$DEFAULT_TV_MOUNTPOINT}"
  local venv_path="${CFG_VENV_PATH:-$SCRIPT_DIR/.venv}"

  if ! ensure_systemd_for_service_actions "$backend" "$movies_mount" "$tv_mount" "$venv_path"; then
    return 0
  fi

  local out=""
  out+="$(systemctl is-active "$SERVICE_MOVIES" 2>/dev/null || true)  $SERVICE_MOVIES"$'\n'
  out+="$(systemctl is-active "$SERVICE_TV" 2>/dev/null || true)  $SERVICE_TV"$'\n\n'
  out+="Hint: systemctl status $SERVICE_MOVIES --no-pager\n"
  out+="Hint: systemctl status $SERVICE_TV --no-pager"
  ui_msg "Service Status" "$out"
}

uninstall_services() {
  require_root
  load_local_config

  local backend="${CFG_BACKEND_URL:-$DEFAULT_BACKEND_URL}"
  local movies_mount="${CFG_MOVIES_MOUNTPOINT:-$DEFAULT_MOVIES_MOUNTPOINT}"
  local tv_mount="${CFG_TV_MOUNTPOINT:-$DEFAULT_TV_MOUNTPOINT}"
  local venv_path="${CFG_VENV_PATH:-$SCRIPT_DIR/.venv}"

  if ! ensure_systemd_for_service_actions "$backend" "$movies_mount" "$tv_mount" "$venv_path"; then
    return 0
  fi

  if ! ui_yesno "Confirm" "Uninstall Dispatcharr FUSE services?"; then
    return 0
  fi

  systemctl disable --now "$SERVICE_MOVIES" "$SERVICE_TV" >/dev/null 2>&1 || true
  rm -f "$SYSTEMD_DIR/$SERVICE_MOVIES" "$SYSTEMD_DIR/$SERVICE_TV"
  systemctl daemon-reload

  if ui_yesno "Remove Config" "Remove saved installer config at $CONFIG_FILE?"; then
    rm -f "$CONFIG_FILE"
  fi

  ui_msg "Uninstalled" "Removed Dispatcharr FUSE systemd services."
}

guided_menu() {
  ui_init
  while true; do
    local choice=""
    choice="$(ui_menu \
      "Dispatcharr FUSE Installer" \
      "Choose an action:" \
      "install" "Install / Update (guided)" \
      "change" "Change mount points" \
      "restart" "Restart services" \
      "status" "Show service status" \
      "uninstall" "Uninstall services" \
      "exit" "Exit")" || return 0

    case "$choice" in
      install) install_or_update_services ;;
      change) change_mountpoints ;;
      restart) restart_services ;;
      status) show_status ;;
      uninstall) uninstall_services ;;
      exit) return 0 ;;
    esac
  done
}

main() {
  resolve_python

  # Backward compatibility:
  # - ACTION=mount (new systemd path)
  # - explicit MODE from caller (old service/manual usage)
  # - non-interactive shell (systemd/no tty)
  if [[ "$ACTION" == "mount" || "$MODE_WAS_EXPLICIT" == "true" || ! -t 0 ]]; then
    run_mount_mode
    return 0
  fi

  case "$ACTION" in
    install) install_or_update_services ;;
    change-mounts) change_mountpoints ;;
    restart) restart_services ;;
    uninstall) uninstall_services ;;
    status) show_status ;;
    "") guided_menu ;;
    *) echo "Unknown action: $ACTION" >&2; exit 1 ;;
  esac
}

main "$@"
