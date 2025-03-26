#!/bin/bash

# NOTE: mac doesn't run as root, so only manage permissions
# if this script is running as root
    touch /app/uwsgi.sock
    mkdir -p /app/media

    echo "Created and set permissions for cached_m3u directory"
