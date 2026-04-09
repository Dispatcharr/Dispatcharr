#!/bin/bash
#
# Fix TLS client key permissions and ownership for PostgreSQL.
# libpq requires the client key to be 0600 or stricter.
#
# Triggers on:
#   - Permissions too open (Docker Desktop mounts files as 0777)
#   - Wrong ownership (Kubernetes secrets / Docker volumes mount as root;
#     the application user can't read a root-owned 0600 key)
#   - Read-only source (volume mounted :ro — can't chmod in place)
#
# Usage: source this script with FIXED_KEY_PATH set to the destination.
#   FIXED_KEY_PATH="/data/.pg-client.key"
#   . /app/docker/init/00-fix-pg-ssl-key.sh
#
# After sourcing, POSTGRES_SSL_KEY is updated to the fixed path if a copy
# was needed. The caller is responsible for propagating the new value to
# /etc/environment or profile.d if required.

: "${FIXED_KEY_PATH:?FIXED_KEY_PATH must be set before sourcing fix-pg-ssl-key.sh}"

if [ -n "${POSTGRES_SSL_KEY:-}" ] && [ -f "$POSTGRES_SSL_KEY" ]; then
    _key_perms=$(stat -c '%a' "$POSTGRES_SSL_KEY" 2>/dev/null)
    _key_owner=$(stat -c '%u' "$POSTGRES_SSL_KEY" 2>/dev/null)
    _needs_fix=false

    if [ "$_key_perms" != "600" ] && [ "$_key_perms" != "640" ]; then
        _needs_fix=true
    elif [ "$(id -u)" = "0" ] && [ -n "${PUID:-}" ] && [ "$_key_owner" != "$PUID" ]; then
        _needs_fix=true
    fi

    if [ "$_needs_fix" = true ]; then
        cp "$POSTGRES_SSL_KEY" "$FIXED_KEY_PATH"
        chmod 600 "$FIXED_KEY_PATH"
        if [ "$(id -u)" = "0" ] && [ -n "${PUID:-}" ]; then
            chown "${PUID}:${PGID:-$PUID}" "$FIXED_KEY_PATH"
        fi
        export POSTGRES_SSL_KEY="$FIXED_KEY_PATH"
        echo "Fixed PostgreSQL client key (perms: ${_key_perms}, owner: ${_key_owner} → ${PUID:-root}:600)"
    fi

    unset _key_perms _key_owner _needs_fix
fi
