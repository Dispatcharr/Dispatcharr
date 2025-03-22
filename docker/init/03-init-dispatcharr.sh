#!/bin/bash

# Required so both uwsgi and nginx (www-data) can use it
# @TODO: change nginx to run as the same use as uwsgi

# NOTE: mac doesn't run as root, so only manage permissions
# if this script is running as root
if [ "$(id -u)" = "0" ]; then
    touch /app/uwsgi.sock
    chown -R $PUID:$PGID /app
    chown $PUID:www-data /app/uwsgi.sock
    chmod 777 /app/uwsgi.sock

    # Create and set permissions for the cached_m3u directory
    mkdir -p /app/media/cached_m3u
    chown -R $PUID:$PGID /app/media/cached_m3u
    chmod 777 /app/media/cached_m3u
    echo "Created and set permissions for cached_m3u directory"
fi
