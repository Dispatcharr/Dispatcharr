#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Function to clean up only running processes
cleanup() {
    echo "🔥 Cleanup triggered! Stopping services..."
    for pid in "${pids[@]}"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "⛔ Stopping process (PID: $pid)..."
            kill -TERM "$pid" 2>/dev/null
        else
            echo "✅ Process (PID: $pid) already stopped."
        fi
    done
    wait
}

# Catch termination signals (CTRL+C, Docker Stop, etc.)
trap cleanup TERM INT

# Initialize an array to store PIDs
pids=()

# Function to echo with timestamp
echo_with_timestamp() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Set PostgreSQL environment variables
export POSTGRES_DB=${POSTGRES_DB:-dispatcharr}
export POSTGRES_USER=${POSTGRES_USER:-dispatch}
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-secret}
export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export PG_VERSION=$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)
export PG_BINDIR="/usr/lib/postgresql/${PG_VERSION}/bin"
export REDIS_HOST=${REDIS_HOST:-localhost}
export REDIS_DB=${REDIS_DB:-0}
export DISPATCHARR_PORT=${DISPATCHARR_PORT:-9191}
export LIBVA_DRIVERS_PATH='/usr/local/lib/x86_64-linux-gnu/dri'
export LD_LIBRARY_PATH='/usr/local/lib'
export SECRET_FILE="/data/jwt"
# Ensure Django secret key exists or generate a new one
if [ ! -f "$SECRET_FILE" ]; then
  echo "Generating new Django secret key..."
  old_umask=$(umask)
  umask 077
  tmpfile="$(mktemp "${SECRET_FILE}.XXXXXX")" || { echo "mktemp failed"; exit 1; }
  python3 - <<'PY' >"$tmpfile" || { echo "secret generation failed"; rm -f "$tmpfile"; exit 1; }
import secrets
print(secrets.token_urlsafe(64))
PY
  mv -f "$tmpfile" "$SECRET_FILE" || { echo "move failed"; rm -f "$tmpfile"; exit 1; }
  umask $old_umask
fi
export DJANGO_SECRET_KEY="$(cat "$SECRET_FILE")"

# Process priority configuration
# UWSGI_NICE_LEVEL: Absolute nice value for uWSGI/streaming (default: 0 = normal priority)
# CELERY_NICE_LEVEL: Absolute nice value for Celery/background tasks (default: 5 = low priority)
# Note: The script will automatically calculate the relative offset for Celery since it's spawned by uWSGI
export UWSGI_NICE_LEVEL=${UWSGI_NICE_LEVEL:-0}
CELERY_NICE_ABSOLUTE=${CELERY_NICE_LEVEL:-5}

# Calculate relative nice value for Celery (since nice is relative to parent process)
# Celery is spawned by uWSGI, so we need to add the offset to reach the desired absolute value
export CELERY_NICE_LEVEL=$((CELERY_NICE_ABSOLUTE - UWSGI_NICE_LEVEL))

# Set LIBVA_DRIVER_NAME if user has specified it
if [ -v LIBVA_DRIVER_NAME ]; then
    export LIBVA_DRIVER_NAME
fi
# Extract version information from version.py
export DISPATCHARR_VERSION=$(python -c "import sys; sys.path.append('/app'); import version; print(version.__version__)")
export DISPATCHARR_TIMESTAMP=$(python -c "import sys; sys.path.append('/app'); import version; print(version.__timestamp__ or '')")

# Display version information with timestamp if available
if [ -n "$DISPATCHARR_TIMESTAMP" ]; then
    echo "📦 Dispatcharr version: ${DISPATCHARR_VERSION} (build: ${DISPATCHARR_TIMESTAMP})"
else
    echo "📦 Dispatcharr version: ${DISPATCHARR_VERSION}"
fi
export DISPATCHARR_LOG_LEVEL
# Set log level with default if not provided
DISPATCHARR_LOG_LEVEL=${DISPATCHARR_LOG_LEVEL:-INFO}
# Convert to uppercase
DISPATCHARR_LOG_LEVEL=${DISPATCHARR_LOG_LEVEL^^}


echo "Environment DISPATCHARR_LOG_LEVEL set to: '${DISPATCHARR_LOG_LEVEL}'"

# Also make the log level available in /etc/environment for all login shells
#grep -q "DISPATCHARR_LOG_LEVEL" /etc/environment || echo "DISPATCHARR_LOG_LEVEL=${DISPATCHARR_LOG_LEVEL}" >> /etc/environment

# READ-ONLY - don't let users change these
export POSTGRES_DIR=/data/db

# Global variables, stored so other users inherit them
if [[ ! -f /etc/profile.d/dispatcharr.sh ]]; then
    # Define all variables to process
    variables=(
        PATH VIRTUAL_ENV DJANGO_SETTINGS_MODULE PYTHONUNBUFFERED
        POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT
        DISPATCHARR_ENV DISPATCHARR_DEBUG DISPATCHARR_LOG_LEVEL
        REDIS_HOST REDIS_DB POSTGRES_DIR DISPATCHARR_PORT
        DISPATCHARR_VERSION DISPATCHARR_TIMESTAMP LIBVA_DRIVERS_PATH LIBVA_DRIVER_NAME LD_LIBRARY_PATH
        CELERY_NICE_LEVEL UWSGI_NICE_LEVEL DJANGO_SECRET_KEY
    )

    # Process each variable for both profile.d and environment
    for var in "${variables[@]}"; do
        # Check if the variable is set in the environment
        if [ -n "${!var+x}" ]; then
            # Add to profile.d
            echo "export ${var}=${!var}" >> /etc/profile.d/dispatcharr.sh
            # Add to /etc/environment if not already there
            grep -q "^${var}=" /etc/environment || echo "${var}=${!var}" >> /etc/environment
        else
            echo "Warning: Environment variable $var is not set"
        fi
    done
fi

chmod +x /etc/profile.d/dispatcharr.sh

# Ensure root's .bashrc sources the profile.d scripts for interactive non-login shells
if ! grep -q "profile.d/dispatcharr.sh" /root/.bashrc 2>/dev/null; then
    cat >> /root/.bashrc << 'EOF'

# Source Dispatcharr environment variables
if [ -f /etc/profile.d/dispatcharr.sh ]; then
    . /etc/profile.d/dispatcharr.sh
fi
EOF
fi

# Run init scripts
echo "Starting user setup..."
. /app/docker/init/01-user-setup.sh
echo "Setting up PostgreSQL..."
. /app/docker/init/02-postgres.sh
echo "Starting init process..."
. /app/docker/init/03-init-dispatcharr.sh

# Start PostgreSQL
echo "Starting Postgres..."
su - postgres -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} start -w -t 300 -o '-c port=${POSTGRES_PORT}'"
# Wait for PostgreSQL to be ready
until su - postgres -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
    echo_with_timestamp "Waiting for PostgreSQL to be ready..."
    sleep 1
done
postgres_pid=$(su - postgres -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} status" | sed -n 's/.*PID: \([0-9]\+\).*/\1/p')
echo "✅ Postgres started with PID $postgres_pid"
pids+=("$postgres_pid")

# Ensure database encoding is UTF8
. /app/docker/init/02-postgres.sh
ensure_utf8_encoding

if [[ "$DISPATCHARR_ENV" = "dev" ]]; then
    . /app/docker/init/99-init-dev.sh
    echo "Starting frontend dev environment"
    su - $POSTGRES_USER -c "cd /app/frontend && npm run dev &"
    npm_pid=$(pgrep vite | sort | head -n1)
    echo "✅ vite started with PID $npm_pid"
    pids+=("$npm_pid")
else
    echo "🚀 Starting nginx..."
    nginx
    nginx_pid=$(pgrep nginx | sort  | head -n1)
    echo "✅ nginx started with PID $nginx_pid"
    pids+=("$nginx_pid")
fi

cd /app
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Select proper uwsgi config based on environment
if [ "$DISPATCHARR_ENV" = "dev" ] && [ "$DISPATCHARR_DEBUG" != "true" ]; then
    echo "🚀 Starting uwsgi in dev mode..."
    uwsgi_file="/app/docker/uwsgi.dev.ini"
elif [ "$DISPATCHARR_DEBUG" = "true" ]; then
    echo "🚀 Starting uwsgi in debug mode..."
    uwsgi_file="/app/docker/uwsgi.debug.ini"
else
    echo "🚀 Starting uwsgi in production mode..."
    uwsgi_file="/app/docker/uwsgi.ini"
fi

# Set base uwsgi args
uwsgi_args="--ini $uwsgi_file"

# Conditionally disable logging if not in debug mode
if [ "$DISPATCHARR_DEBUG" != "true" ]; then
    uwsgi_args+=" --disable-logging"
fi

# Launch uwsgi with configurable nice level (default: 0 for normal priority)
# Users can override via UWSGI_NICE_LEVEL environment variable in docker-compose
# Start with nice as root, then use setpriv to drop privileges to dispatch user
# This preserves both the nice value and environment variables
nice -n $UWSGI_NICE_LEVEL su - "$POSTGRES_USER" -c "cd /app && exec /dispatcharrpy/bin/uwsgi $uwsgi_args" & uwsgi_pid=$!
echo "✅ uwsgi started with PID $uwsgi_pid (nice $UWSGI_NICE_LEVEL)"
pids+=("$uwsgi_pid")

# sed -i 's/protected-mode yes/protected-mode no/g' /etc/redis/redis.conf
# su - $POSTGRES_USER -c "redis-server --protected-mode no &"
# redis_pid=$(pgrep redis)
# echo "✅ redis started with PID $redis_pid"
# pids+=("$redis_pid")

# echo "🚀 Starting gunicorn..."
# su - $POSTGRES_USER -c "cd /app && gunicorn dispatcharr.asgi:application \
#   --bind 0.0.0.0:5656 \
#   --worker-class uvicorn.workers.UvicornWorker \
#   --workers 2 \
#   --threads 1 \
#   --timeout 0 \
#   --keep-alive 30 \
#   --access-logfile - \
#   --error-logfile - &"
# gunicorn_pid=$(pgrep gunicorn | sort | head -n1)
# echo "✅ gunicorn started with PID $gunicorn_pid"
# pids+=("$gunicorn_pid")

# echo "Starting celery and beat..."
# su - $POSTGRES_USER -c "cd /app && celery -A dispatcharr worker -l info --autoscale=8,2 &"
# celery_pid=$(pgrep celery | sort | head -n1)
# echo "✅ celery started with PID $celery_pid"
# pids+=("$celery_pid")

# su - $POSTGRES_USER -c "cd /app && celery -A dispatcharr beat -l info &"
# beat_pid=$(pgrep beat | sort | head -n1)
# echo "✅ celery beat started with PID $beat_pid"
# pids+=("$beat_pid")


# Wait for services to fully initialize before checking hardware
echo "⏳ Waiting for services to fully initialize before hardware check..."
sleep 5

# Run hardware check
echo "🔍 Running hardware acceleration check..."
. /app/docker/init/04-check-hwaccel.sh

# Wait for at least one process to exit and log the process that exited first
if [ ${#pids[@]} -gt 0 ]; then
    echo "⏳ Dispatcharr is running. Monitoring processes..."
    while kill -0 "${pids[@]}" 2>/dev/null; do
        sleep 1  # Wait for a second before checking again
    done

    echo "🚨 One of the processes exited! Checking which one..."

    for pid in "${pids[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
            process_name=$(ps -p "$pid" -o comm=)
            echo "❌ Process $process_name (PID: $pid) has exited!"
        fi
    done
else
    echo "❌ No processes started. Exiting."
    exit 1
fi

# Cleanup and stop remaining processes
cleanup
