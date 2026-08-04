#!/bin/bash
# Starts the dedicated `plugins` Celery worker only when at least one
# *enabled* plugin declares (directly or via a manifest action's
# "async": true) the "background_tasks" capability, see
# apps/plugins/management/commands/plugins_worker_needed.py.
#
# Supervised as a single long-lived process by both docker/uwsgi.ini
# (attach-daemon) and docker/entrypoint.celery.sh, so when the worker isn't
# needed this must stay resident (not exit) or the supervisor will
# respawn-loop it.
set -e

cd /app
source /dispatcharrpy/bin/activate

MODE="${CELERY_PLUGINS_WORKER:-auto}"   # auto | always | never

NICE_LEVEL="${CELERY_PLUGINS_NICE_LEVEL:-10}"
CONCURRENCY="${CELERY_PLUGINS_CONCURRENCY:-10}"
MAX_MEMORY_PER_CHILD="${CELERY_PLUGIN_WORKER_MAX_MEMORY_PER_CHILD:-262144}"

start_worker() {
    exec nice -n "$NICE_LEVEL" celery -A dispatcharr worker -Q plugins -n plugins@%h \
        --pool=threads --concurrency="$CONCURRENCY" \
        --max-memory-per-child="$MAX_MEMORY_PER_CHILD" -l info
}

case "$MODE" in
    always)
        start_worker
        ;;
    never)
        echo "Plugins worker not started (CELERY_PLUGINS_WORKER=never)."
        exec sleep infinity
        ;;
    auto|*)
        if python manage.py plugins_worker_needed; then
            start_worker
        else
            echo "Plugins worker not started: no enabled plugin declares the background_tasks capability."
            echo "Enable a plugin that needs it, then restart this container to pick it up (or set CELERY_PLUGINS_WORKER=always)."
            exec sleep infinity
        fi
        ;;
esac
