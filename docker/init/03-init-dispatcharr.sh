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
)

APP_DIRS=(
    "/app/logo_cache"
    "/app/media"
)

# Create all directories
for dir in "${DATA_DIRS[@]}" "${APP_DIRS[@]}"; do
    mkdir -p "$dir"
done

sed -i "s/NGINX_PORT/${DISPATCHARR_PORT}/g" /etc/nginx/sites-enabled/default

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

    chmod +x /data
fi