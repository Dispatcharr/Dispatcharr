#!/bin/bash

mkdir -p /data/logos
mkdir -p /data/recordings
mkdir -p /data/uploads/m3us
mkdir -p /data/uploads/epgs
mkdir -p /data/m3us
mkdir -p /data/epgs
mkdir -p /data/plugins
mkdir -p /app/logo_cache
mkdir -p /app/media

sed -i "s/NGINX_PORT/${DISPATCHARR_PORT}/g" /etc/nginx/sites-enabled/default

# NOTE: mac doesn't run as root, so only manage permissions
# if this script is running as root
if [ "$(id -u)" = "0" ]; then
    # Needs to own ALL of /data except db, we handle that below
    chown -R $PUID:$PGID /data
    chown -R $PUID:$PGID /app

    # Permissions
    chown -R postgres:postgres /data/db
    chmod +x /data
fi
