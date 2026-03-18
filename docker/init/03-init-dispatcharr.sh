#!/bin/bash

# Define directories that need to exist and be owned by PUID:PGID.
# DATA_DIRS may reside on external mounts (NFS, SMB/CIFS, FUSE) where
# mkdir and chown can fail. Failures are collected and reported as a
# single consolidated warning so the container still starts.
DATA_DIRS=(
    "/data/backups"
    "/data/logos"
    "/data/recordings"
    "/data/uploads/m3us"
    "/data/uploads/epgs"
    "/data/m3us"
    "/data/epgs"
    "/data/plugins"
    "/data/models"
    "/data/scripts"
)

# APP_DIRS live on the image layer and are always locally writable.
APP_DIRS=(
    "/app/logo_cache"
    "/app/media"
    "/app/static"
)

# Create app directories (image layer — always writable)
for dir in "${APP_DIRS[@]}"; do
    mkdir -p "$dir"
done

# Create data directories, tolerating failures on external mounts
_failed_mkdir=()
_failed_chown=()
for dir in "${DATA_DIRS[@]}"; do
    _mkdir_err=$(mkdir -p "$dir" 2>&1) || _failed_mkdir+=("$dir ($_mkdir_err)")
done

# Ensure /app itself is owned by PUID:PGID (needed for uwsgi socket creation)
if [ "$(id -u)" = "0" ] && [ -d "/app" ]; then
    if [ "$(stat -c '%u:%g' /app)" != "$PUID:$PGID" ]; then
        echo "Fixing ownership for /app (non-recursive)"
        chown "$PUID:$PGID" /app
    fi
fi
# Configure nginx port
if ! [[ "$DISPATCHARR_PORT" =~ ^[0-9]+$ ]]; then
    echo "⚠️  Warning: DISPATCHARR_PORT is not a valid integer, using default port 9191"
    DISPATCHARR_PORT=9191
fi
sed -i "s/NGINX_PORT/${DISPATCHARR_PORT}/g" /etc/nginx/sites-enabled/default

# Configure nginx based on IPv6 availability
if ip -6 addr show | grep -q "inet6"; then
    echo "✅ IPv6 is available, enabling IPv6 in nginx"
else
    echo "⚠️  IPv6 not available, disabling IPv6 in nginx"
    sed -i '/listen \[::\]:/d' /etc/nginx/sites-enabled/default
fi

# NOTE: mac doesn't run as root, so only manage permissions
# if this script is running as root
if [ "$(id -u)" = "0" ]; then
    # Fix data directories (non-recursive to avoid touching user files).
    # Failures are collected rather than fatal — directories may be on
    # external mounts (NFS, SMB/CIFS, FUSE) that reject chown.
    for dir in "${DATA_DIRS[@]}"; do
        if [ -d "$dir" ] && [ "$(stat -c '%u:%g' "$dir" 2>/dev/null)" != "$PUID:$PGID" ]; then
            _chown_err=$(chown "$PUID:$PGID" "$dir" 2>&1) || {
                _current_owner=$(stat -c '%u:%g' "$dir" 2>/dev/null || echo "unknown")
                _failed_chown+=("$dir (current: $_current_owner, error: $_chown_err)")
            }
        fi
    done

    # Fix app directories (recursive since they're managed by the app)
    for dir in "${APP_DIRS[@]}"; do
        if [ -d "$dir" ] && [ "$(stat -c '%u:%g' "$dir")" != "$PUID:$PGID" ]; then
            echo "Fixing ownership for $dir (recursive)"
            chown -R "$PUID:$PGID" "$dir"
        fi
    done

    # /data/db ownership is handled by 02-postgres.sh (sentinel-based reconciliation).
    # No secondary check needed here — duplicating it could chown without updating
    # the sentinel, creating inconsistent state.

    # Fix /data directory ownership (non-recursive).
    # Tolerates failure for the same external-mount reasons as DATA_DIRS.
    if [ -d "/data" ] && [ "$(stat -c '%u:%g' /data 2>/dev/null)" != "$PUID:$PGID" ]; then
        _chown_err=$(chown "$PUID:$PGID" /data 2>&1) || {
            _current_owner=$(stat -c '%u:%g' /data 2>/dev/null || echo "unknown")
            _failed_chown+=("/data (current: $_current_owner, error: $_chown_err)")
        }
    fi

    chmod +x /data 2>/dev/null || true
fi

# Consolidated warning for all mkdir/chown failures.
# Emitted outside the root guard so non-root mkdir failures are also reported.
if [ ${#_failed_mkdir[@]} -gt 0 ] || [ ${#_failed_chown[@]} -gt 0 ]; then
    echo ""
    echo "================================================================"
    echo "WARNING: Some data directories could not be created or updated."
    echo "  This typically occurs with NFS, SMB/CIFS, or other external"
    echo "  mounts that restrict ownership changes."
    echo ""
    if [ ${#_failed_mkdir[@]} -gt 0 ]; then
        echo "  Could not create:"
        for entry in "${_failed_mkdir[@]}"; do
            echo "    - $entry"
        done
        echo ""
    fi
    if [ ${#_failed_chown[@]} -gt 0 ]; then
        echo "  Could not set ownership to $PUID:$PGID:"
        for entry in "${_failed_chown[@]}"; do
            echo "    - $entry"
        done
        echo ""
    fi
    echo "  To fix, either:"
    echo "    1. Set PUID/PGID to match your mount's owner"
    echo "    2. Fix ownership on the host/NAS:"
    echo "       sudo chown $PUID:$PGID <path>"
    echo "    3. For SMB/CIFS: set uid=$PUID,gid=$PGID in mount options"
    echo "================================================================"
    echo ""
fi
