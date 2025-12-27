#!/bin/bash

# Define directories that need to exist and be owned by PUID:PGID
DATA_DIRS=(
    "/data/logos"
    "/data/recordings"
    "/data/uploads/m3us"
    "/data/uploads/epgs"
    "/data/m3us"
    "/data/epgs"
    "/data/plugins"
    "/data/models"
)

APP_DIRS=(
    "/app/logo_cache"
    "/app/media"
)

# Create all directories
for dir in "${DATA_DIRS[@]}" "${APP_DIRS[@]}"; do
    mkdir -p "$dir"
done

# Ensure /app itself is owned by PUID:PGID (needed for uwsgi socket creation)
if [ "$(id -u)" = "0" ] && [ -d "/app" ]; then
    if [ "$(stat -c '%u:%g' /app)" != "$PUID:$PGID" ]; then
        echo "Fixing ownership for /app (non-recursive)"
        chown $PUID:$PGID /app
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
    # Fix data directories (non-recursive to avoid touching user files)
    for dir in "${DATA_DIRS[@]}"; do
        if [ -d "$dir" ] && [ "$(stat -c '%u:%g' "$dir")" != "$PUID:$PGID" ]; then
            echo "Fixing ownership for $dir"
            chown $PUID:$PGID "$dir"
        fi
    done

    # Fix app directories (recursive since they're managed by the app)
    for dir in "${APP_DIRS[@]}"; do
        if [ -d "$dir" ] && [ "$(stat -c '%u:%g' "$dir")" != "$PUID:$PGID" ]; then
            echo "Fixing ownership for $dir (recursive)"
            chown -R $PUID:$PGID "$dir"
        fi
    done

    # Database permissions
    if [ -d /data/db ] && [ "$(stat -c '%u' /data/db)" != "$(id -u postgres)" ]; then
        echo "Fixing ownership for /data/db"
        chown -R postgres:postgres /data/db
    fi

    # Fix /data directory ownership (non-recursive)
    if [ -d "/data" ] && [ "$(stat -c '%u:%g' /data)" != "$PUID:$PGID" ]; then
        echo "Fixing ownership for /data (non-recursive)"
        chown $PUID:$PGID /data
    fi

    chmod +x /data
fi