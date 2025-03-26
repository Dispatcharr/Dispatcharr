#!/bin/bash

# Create group if it doesn't exist
if ! getent group "$PGID" >/dev/null 2>&1; then
    groupadd -g "$PGID" dispatch
fi
# Create user if it doesn't exist
if ! getent passwd $PUID > /dev/null 2>&1; then
    useradd -u $PUID -g $PGID -m $POSTGRES_USER
else
    existing_user=$(getent passwd $PUID | cut -d: -f1)
    if [ "$existing_user" != "$POSTGRES_USER" ]; then
        usermod -l $POSTGRES_USER -g $PGID "$existing_user"
    fi
fi

# Run nginx as specified user
sed -i 's/user www-data;/user dispatch;/g' /etc/nginx/nginx.conf
