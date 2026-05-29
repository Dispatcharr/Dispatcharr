#!/bin/bash
# Conditionally start Redis.
#
# When Dispatcharr shares a network namespace with another container that
# already runs Redis (network_mode: service:<svc>), redis-server cannot
# bind port 6379 and exits immediately. uWSGI's attach-daemon then
# respawns it in a tight loop, flooding the logs with:
#   Address already in use / Failed listening on port 6379
#
# This wrapper checks whether Redis is already accepting connections on
# the configured host/port before starting redis-server. If Redis is
# already available, the script runs `sleep infinity` so the attach-daemon
# process stays alive without generating log spam or consuming resources.

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"

if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null         | grep -qiE "^(PONG|NOAUTH)"; then
    echo "Redis already listening at ${REDIS_HOST}:${REDIS_PORT} — skipping redis-server."
    exec sleep infinity
fi

exec redis-server
