#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Guard flag to prevent cleanup running twice (trap + explicit call)
_cleanup_done=false

# Function to clean up only running processes
cleanup() {
    if $_cleanup_done; then return; fi
    _cleanup_done=true
    set +e  # Disable exit-on-error so cleanup always runs fully
    echo "🔥 Cleanup triggered! Stopping services..."

    # Explicitly stop uwsgi workers - children of 'su' wrapper, not tracked in pids[]
    echo "⛔ Stopping uwsgi workers..."
    pkill -TERM -f uwsgi 2>/dev/null || true

    # Stop celery, daphne, redis - also not tracked in pids[]
    echo "⛔ Stopping celery, daphne, redis..."
    pkill -TERM -f "celery" 2>/dev/null || true
    pkill -TERM -f "daphne" 2>/dev/null || true
    pkill -TERM -f "redis-server" 2>/dev/null || true

    # Stop tracked processes (postgres, nginx, su/uwsgi wrapper)
    for pid in "${pids[@]}"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "⛔ Stopping process (PID: $pid)..."
            kill -TERM "$pid" 2>/dev/null
        else
            echo "✅ Process (PID: $pid) already stopped."
        fi
    done

    # Wait up to 8 s for graceful shutdown, exit early once all are gone
    # (leaves headroom within Docker's default 10 s stop_grace_period)
    _shutdown_timeout=8
    _shutdown_elapsed=0
    while [ "$_shutdown_elapsed" -lt "$_shutdown_timeout" ]; do
        pgrep -f "uwsgi|celery|daphne|redis-server|postgres" >/dev/null 2>&1 || break
        sleep 1
        _shutdown_elapsed=$((_shutdown_elapsed + 1))
    done

    # Force kill anything still lingering
    pkill -KILL -f uwsgi 2>/dev/null || true
    pkill -KILL -f "celery" 2>/dev/null || true
    pkill -KILL -f "daphne" 2>/dev/null || true
    pkill -KILL -f "redis-server" 2>/dev/null || true
    # Use pg_ctl immediate stop rather than SIGKILL. Avoids data corruption
    # while still forcing a fast exit (crash recovery runs on next startup)
    if pgrep -f "postgres" >/dev/null 2>&1; then
        su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} stop -m immediate" 2>/dev/null || true
    fi

    wait
    echo "✅ All processes stopped cleanly."
}

# Catch termination signals (CTRL+C, Docker Stop, etc.)
trap cleanup TERM INT

# Initialize an array to store PIDs and a map of PID->name
pids=()
declare -A pid_names

# Function to echo with timestamp
echo_with_timestamp() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Set PostgreSQL environment variables
export POSTGRES_DB=${POSTGRES_DB:-dispatcharr}
export POSTGRES_USER=${POSTGRES_USER:-dispatch}
# AIO mode: default to 'secret' for internal DB.
# Modular mode + TLS: no default — cert-only auth (mTLS) uses no password.
# Modular mode + no TLS: preserve 'secret' default for backward compatibility.
if [[ "${DISPATCHARR_ENV:-}" == "modular" && "${POSTGRES_SSL:-}" == "true" ]]; then
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
else
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-secret}"
fi
export DISPATCHARR_ENV=${DISPATCHARR_ENV:-aio}
if [[ "$DISPATCHARR_ENV" == "aio" ]]; then
    # Use Unix socket for loopback values (unset, localhost, 127.0.0.1)
    if [[ -z "$POSTGRES_HOST" || "$POSTGRES_HOST" == "localhost" || "$POSTGRES_HOST" == "127.0.0.1" ]]; then
        export POSTGRES_HOST=/var/run/postgresql
    fi
else
    export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
fi
export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export PG_VERSION=$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)
export PG_BINDIR="/usr/lib/postgresql/${PG_VERSION}/bin"
export REDIS_HOST=${REDIS_HOST:-localhost}
export REDIS_PORT=${REDIS_PORT:-6379}
export REDIS_DB=${REDIS_DB:-0}
export REDIS_PASSWORD=${REDIS_PASSWORD:-}
export REDIS_USER=${REDIS_USER:-}
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
export DJANGO_SECRET_KEY="$(tr -d '\r\n' < "$SECRET_FILE")"

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

# Translate Dispatcharr POSTGRES_SSL_* env vars into libpq-recognized PGSSL*
# env vars. Called once before any external PostgreSQL connection; all child
# processes (psql, pg_dump, pg_isready, createdb, dropdb) inherit these
# automatically. No-op when POSTGRES_SSL is not "true".
setup_pg_ssl_env() {
    if [ "${POSTGRES_SSL:-false}" != "true" ]; then
        return 0
    fi
    export PGSSLMODE="${POSTGRES_SSL_MODE:-verify-full}"
    if [ -n "${POSTGRES_SSL_CA_CERT:-}" ]; then export PGSSLROOTCERT="$POSTGRES_SSL_CA_CERT"; fi
    if [ -n "${POSTGRES_SSL_CERT:-}" ];    then export PGSSLCERT="$POSTGRES_SSL_CERT"; fi
    if [ -n "${POSTGRES_SSL_KEY:-}" ];     then export PGSSLKEY="$POSTGRES_SSL_KEY"; fi
}

# READ-ONLY - don't let users change these
export POSTGRES_DIR=/data/db

# Global variables, stored so other users inherit them.
# Rewritten every startup so that container restarts with changed env vars
# pick up the new values (not stale ones from a previous run).
# Define all variables to process
variables=(
    PATH VIRTUAL_ENV DJANGO_SETTINGS_MODULE PYTHONUNBUFFERED PYTHONDONTWRITEBYTECODE
    POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT
    DISPATCHARR_ENV DISPATCHARR_DEBUG DISPATCHARR_LOG_LEVEL
    REDIS_HOST REDIS_PORT REDIS_DB REDIS_PASSWORD REDIS_USER POSTGRES_DIR DISPATCHARR_PORT
    DISPATCHARR_VERSION DISPATCHARR_TIMESTAMP LIBVA_DRIVERS_PATH LIBVA_DRIVER_NAME LD_LIBRARY_PATH
    CELERY_NICE_LEVEL UWSGI_NICE_LEVEL DJANGO_SECRET_KEY
)

# TLS variables are optional — only propagate when set to avoid noisy warnings
for _tls_var in POSTGRES_SSL POSTGRES_SSL_MODE POSTGRES_SSL_CA_CERT POSTGRES_SSL_CERT POSTGRES_SSL_KEY \
                REDIS_SSL REDIS_SSL_VERIFY REDIS_SSL_CA_CERT REDIS_SSL_CERT REDIS_SSL_KEY; do
    if [ -n "${!_tls_var+x}" ]; then
        variables+=("$_tls_var")
    fi
done

# Truncate files before rewriting
> /etc/profile.d/dispatcharr.sh

# Process each variable for both profile.d and environment
for var in "${variables[@]}"; do
    # Check if the variable is set in the environment
    if [ -n "${!var+x}" ]; then
        # Add to profile.d (quoted to handle special characters in values)
        echo "export ${var}='${!var}'" >> /etc/profile.d/dispatcharr.sh
        # Add/update in /etc/environment
        sed -i "/^${var}=/d" /etc/environment
        echo "${var}='${!var}'" >> /etc/environment
    else
        echo "Warning: Environment variable $var is not set"
    fi
done

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

# Fix TLS client key permissions/ownership BEFORE any external PG connections.
# Must run after 01-user-setup.sh (user exists for chown) and before
# 02-postgres.sh / pg_isready (which make the first external PG connections).
FIXED_KEY_PATH="/data/.pg-client.key"
. /app/docker/init/00-fix-pg-ssl-key.sh
# Propagate the fixed path to login shells (su - strips env vars)
if [ "${POSTGRES_SSL_KEY:-}" = "$FIXED_KEY_PATH" ]; then
    sed -i "/^POSTGRES_SSL_KEY=/d" /etc/environment
    echo "POSTGRES_SSL_KEY='$FIXED_KEY_PATH'" >> /etc/environment
    sed -i "s|export POSTGRES_SSL_KEY=.*|export POSTGRES_SSL_KEY='$FIXED_KEY_PATH'|" /etc/profile.d/dispatcharr.sh
fi

# Export libpq TLS env vars so all subsequent psql/pg_dump/pg_isready calls
# (in 02-postgres.sh, modular-mode checks, etc.) use TLS automatically.
setup_pg_ssl_env

# Initialize PostgreSQL (script handles modular vs internal mode internally)
echo "Setting up PostgreSQL..."
. /app/docker/init/02-postgres.sh

echo "Starting init process..."
. /app/docker/init/03-init-dispatcharr.sh

# Start PostgreSQL if NOT in modular mode (using external database)
if [[ "$DISPATCHARR_ENV" != "modular" ]]; then
    echo "Starting Postgres..."
    prepare_pg_socket_dir
    su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} start -w -t 300 -o '-c port=${POSTGRES_PORT}'"
    # Wait for PostgreSQL to be ready
    until su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
        echo_with_timestamp "Waiting for PostgreSQL to be ready..."
        sleep 1
    done
    postgres_pid=$(su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} status" | sed -n 's/.*PID: \([0-9]\+\).*/\1/p')
    echo "✅ Postgres started with PID $postgres_pid"
    if [ -n "$postgres_pid" ]; then pids+=("$postgres_pid"); pid_names[$postgres_pid]="postgres"; fi

    # Unconditional startup guarantees — run on every AIO startup.
    # Each is idempotent and handles all scenarios (fresh, upgrade, restart).
    promote_app_role
    ensure_app_database
else
    echo "🔗 Modular mode: Using external PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}"
    # Wait for external PostgreSQL to be ready using pg_isready (checks actual protocol readiness)
    echo_with_timestamp "Waiting for external PostgreSQL to be ready..."
    until $PG_BINDIR/pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -q >/dev/null 2>&1; do
        echo_with_timestamp "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
        sleep 1
    done
    echo "✅ External PostgreSQL is ready"

    # Check PostgreSQL version compatibility
    check_external_postgres_version || exit 1
fi

# Wait for Redis to be ready and flush stale state.
# In modular mode Redis is external — call wait_for_redis.py here
# because uWSGI's exec-pre runs under 'su -' which strips env vars
# (DISPATCHARR_ENV, REDIS_HOST, etc.).
# In AIO mode Redis is started by uWSGI (attach-daemon), so the
# exec-pre in uwsgi.ini handles the wait + flush there instead.
if [[ "$DISPATCHARR_ENV" == "modular" ]]; then
    echo "🔗 Modular mode: Using external Redis at ${REDIS_HOST}:${REDIS_PORT}"
    echo_with_timestamp "Waiting for Redis to be ready..."
    python3 /app/scripts/wait_for_redis.py
    echo "✅ Redis is ready"
fi

# Ensure database encoding is UTF8 (handles both internal and external databases)
ensure_utf8_encoding

if [[ "$DISPATCHARR_ENV" = "dev" ]]; then
    . /app/docker/init/99-init-dev.sh
    echo "Starting frontend dev environment"
    su - "$POSTGRES_USER" -c "cd /app/frontend && npm run dev &"
    npm_pid=$(pgrep vite | sort | head -n1)
    echo "✅ vite started with PID $npm_pid"
    if [ -n "$npm_pid" ]; then pids+=("$npm_pid"); pid_names[$npm_pid]="vite"; fi
else
    echo "🚀 Starting nginx..."
    nginx
    nginx_pid=$(pgrep nginx | sort | head -n1)
    echo "✅ nginx started with PID $nginx_pid"
    if [ -n "$nginx_pid" ]; then pids+=("$nginx_pid"); pid_names[$nginx_pid]="nginx"; fi
fi


# --- NumPy version switching for legacy hardware ---
if [ "$USE_LEGACY_NUMPY" = "true" ]; then
    # Check if NumPy was compiled with baseline support
    if "$VIRTUAL_ENV/bin/python" -c "import numpy; numpy.show_config()" 2>&1 | grep -qi "baseline" || [ $? -ne 0 ]; then
        echo_with_timestamp "🔧 Switching to legacy NumPy (no CPU baseline)..."
        uv pip install --python "$VIRTUAL_ENV/bin/python" --no-cache --force-reinstall --no-deps /opt/numpy-*.whl
        echo_with_timestamp "✅ Legacy NumPy installed"
    else
        echo_with_timestamp "✅ Legacy NumPy (no baseline) already installed, skipping reinstallation"
    fi
fi

# Run Django commands as non-root user to prevent permission issues
su - "$POSTGRES_USER" -c "cd /app && python manage.py migrate --noinput"
su - "$POSTGRES_USER" -c "cd /app && python manage.py collectstatic --noinput"

# Select proper uwsgi config based on environment
if [ "$DISPATCHARR_ENV" = "dev" ] && [ "$DISPATCHARR_DEBUG" != "true" ]; then
    echo "🚀 Starting uwsgi in dev mode..."
    uwsgi_file="/app/docker/uwsgi.dev.ini"
elif [ "$DISPATCHARR_DEBUG" = "true" ]; then
    echo "🚀 Starting uwsgi in debug mode..."
    uwsgi_file="/app/docker/uwsgi.debug.ini"
elif [ "$DISPATCHARR_ENV" = "modular" ]; then
    echo "🚀 Starting uwsgi in modular mode..."
    uwsgi_file="/app/docker/uwsgi.modular.ini"
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
nice -n "$UWSGI_NICE_LEVEL" su - "$POSTGRES_USER" -c "cd /app && exec $VIRTUAL_ENV/bin/uwsgi $uwsgi_args" & uwsgi_pid=$!
echo "✅ uwsgi started with PID $uwsgi_pid (nice $UWSGI_NICE_LEVEL)"
pids+=("$uwsgi_pid"); pid_names[$uwsgi_pid]="uwsgi"

# Wait for services to fully initialize before checking hardware
echo "⏳ Waiting for services to fully initialize before hardware check..."
sleep 5

# Run hardware check
echo "🔍 Running hardware acceleration check..."
. /app/docker/init/04-check-hwaccel.sh

# Wait for at least one process to exit and log the process that exited first
if [ ${#pids[@]} -gt 0 ]; then
    echo "⏳ Dispatcharr is running. Monitoring processes..."
    set +e
    while kill -0 "${pids[@]}" 2>/dev/null; do
        sleep 1  # Wait for a second before checking again
    done

    # Only report unexpected exits — skip if cleanup was already triggered by
    # the trap (i.e. docker stop sent SIGTERM and we shut down intentionally)
    if ! $_cleanup_done; then
        echo "🚨 One of the processes exited unexpectedly! Checking which one..."

        for pid in "${pids[@]}"; do
            if ! kill -0 "$pid" 2>/dev/null; then
                process_name=${pid_names[$pid]:-unknown}
                echo "❌ Process $process_name (PID: $pid) has exited!"
            fi
        done
    fi
else
    echo "❌ No processes started. Exiting."
    exit 1
fi

# Cleanup and stop remaining processes
cleanup
