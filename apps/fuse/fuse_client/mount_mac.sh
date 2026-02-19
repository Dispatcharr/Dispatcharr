#!/usr/bin/env bash
# Helper to mount Dispatcharr VOD via FUSE on macOS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Prefer a stable Python for fusepy (3.11/3.12); fall back to python3
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
  elif command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="python3.11"
  else
    PYTHON_BIN="python3"
  fi
fi
MODE="${MODE:-movies}"          # movies | tv
BACKEND_URL="${BACKEND_URL:-http://10.0.0.192:5656}"
MOUNTPOINT="${MOUNTPOINT:-/Volumes/vod_${MODE}}"
VENV_PATH="${VENV_PATH:-$PROJECT_ROOT/.venv}"
FUSE_MAX_READ="${FUSE_MAX_READ:-8388608}"       # 8 MiB
READAHEAD_BYTES="${READAHEAD_BYTES:-8388608}"   # 8 MiB

if [[ "$MODE" != "movies" && "$MODE" != "tv" ]]; then
  echo "MODE must be 'movies' or 'tv'" >&2
  exit 1
fi

echo "==> Using Python: $PYTHON_BIN"
echo "==> Mode: $MODE"
echo "==> Backend: $BACKEND_URL"
echo "==> Mountpoint: $MOUNTPOINT"
echo "==> Venv: $VENV_PATH"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "Python not found: $PYTHON_BIN" >&2; exit 1; }

# macFUSE detection: warn but don’t hard-exit so we can proceed if you know it’s installed
if ! kextstat 2>/dev/null | grep -q "com.github.osxfuse.filesystems.osxfuse" && ! systemextensionsctl list 2>/dev/null | grep -qi "macfuse"; then
  echo "Warning: macFUSE not detected via kext/systemextension. Trying anyway." >&2
fi

# Prepare venv and deps
if [[ ! -d "$VENV_PATH" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_PATH"
fi
source "$VENV_PATH/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet fusepy requests

# Patch fusepy _wrapper to be an instance method (avoids NameError: self is not defined)
FUSE_PY=$(find "$VENV_PATH/lib" -path "*/site-packages/fuse.py" -maxdepth 4 -print -quit 2>/dev/null || true)
if [[ -n "$FUSE_PY" ]]; then
  python - "$FUSE_PY" <<'PY'
import pathlib, sys, re
path = pathlib.Path(sys.argv[1])
text = path.read_text()
patched = re.sub(r'@staticmethod\s*\n\s*def _wrapper\(func', '    def _wrapper(self, func', text, count=1)
if text != patched:
    path.write_text(patched)
PY
fi

# Prepare mountpoint (unmount if stale)
diskutil umount force "$MOUNTPOINT" >/dev/null 2>&1 || true

# Disable Spotlight indexing on the mount to prevent background scans/thumbnails
if command -v mdutil >/dev/null 2>&1; then
  mdutil -i off "$MOUNTPOINT" >/dev/null 2>&1 || true
fi

cleanup() {
  local exit_code=$?
  if [[ -n "${CHILD_PID:-}" ]] && ps -p "$CHILD_PID" >/dev/null 2>&1; then
    # Politely ask the FUSE client to exit
    kill "$CHILD_PID" >/dev/null 2>&1 || true
    # Give it a moment, then force if needed
    sleep 1
    kill -9 "$CHILD_PID" >/dev/null 2>&1 || true
  fi
  diskutil umount force "$MOUNTPOINT" >/dev/null 2>&1 || true
  rmdir "$MOUNTPOINT" >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup INT TERM EXIT

cd "$PROJECT_ROOT"
echo "==> Mounting (requires sudo for allow_other)..."
sudo "$VENV_PATH/bin/python" "$SCRIPT_DIR/fuse_client.py" \
  --mode "$MODE" \
  --backend-url "$BACKEND_URL" \
  --mountpoint "$MOUNTPOINT" \
  --max-read "$FUSE_MAX_READ" \
  --readahead-bytes "$READAHEAD_BYTES" \
  --foreground &

CHILD_PID=$!
wait "$CHILD_PID"
