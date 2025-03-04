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

# Global variables
if [[ ! -f /etc/profile.d/dispatcharr.sh ]]; then
    echo "export PATH=$PATH" >> /etc/profile.d/dispatcharr.sh
    echo "export VIRTUAL_ENV=$VIRTUAL_ENV" >> /etc/profile.d/dispatcharr.sh
    echo "export DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE" >> /etc/profile.d/dispatcharr.sh
    echo "export PYTHONUNBUFFERED=$PYTHONUNBUFFERED" >> /etc/profile.d/dispatcharr.sh
fi

chmod +x /etc/profile.d/dispatcharr.sh

# Dispatcharr variables
export ADMIN_PORT=5656

# Set PostgreSQL environment variables
export POSTGRES_DB=${POSTGRES_DB:-dispatcharr}
export POSTGRES_USER=${POSTGRES_USER:-dispatch}
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-secret}
export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export PGDATA=${PGDATA:-/app/data/db}
export PG_BINDIR="/usr/lib/postgresql/14/bin"

# Set up user details
export PUID=${PUID:-1000}
export PGID=${PGID:-1000}

# Set up initial django admin
export DJANGO_SUPERUSER_USERNAME=${DEFAULT_USERNAME:-admin}
export DJANGO_SUPERUSER_PASSWORD=${DEFAULT_PASSWORD:-admin}
export DJANGO_SUPERUSER_EMAIL=${DEFAULT_EMAIL:-admin@dispatcharr.local}


# Echo environment variables for debugging
echo_with_timestamp "POSTGRES_DB: $POSTGRES_DB"
echo_with_timestamp "POSTGRES_USER: $POSTGRES_USER"
echo_with_timestamp "POSTGRES_PASSWORD: $POSTGRES_PASSWORD"
echo_with_timestamp "POSTGRES_HOST: $POSTGRES_HOST"
echo_with_timestamp "POSTGRES_PORT: $POSTGRES_PORT"

# Create group if it doesn't exist
if ! getent group "$PGID" >/dev/null 2>&1; then
    groupadd -g "$PGID" mygroup
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

# If running in development mode, install and start frontend
if [ "$DISPATCHARR_ENV" = "dev" ]; then
    echo "🚀 Development Mode - Setting up Frontend..."

    # Install Node.js
    apt-get update && apt-get install -y nodejs

    # Install frontend dependencies
    cd /app/frontend && npm install
    cd /app

    # Start React development server
    echo "🚀 Starting React Dev Server..."
    cd /app/frontend
    su - $POSTGRES_USER -c "PORT=9191 /app/frontend/node_modules/pm2/bin/pm2 --name dev-server start npm -- start"
    ./node_modules/pm2/bin/pm2 logs &
    react_pid=$(cat /home/dispatch/.pm2/pids/dev-server*)
    echo "✅ React started with PID $react_pid"
    pids+=("$react_pid")
    cd /app
fi

# If running in `dev` or `aio`, start Postgres, Redis, and Celery
if [ "$DISPATCHARR_ENV" = "dev" ] || [ "$DISPATCHARR_ENV" = "aio" ]; then
    echo "🚀 Running Postgres, Redis, and Celery for '$DISPATCHARR_ENV'..."

    # Initialize PostgreSQL database
    if [ -z "$(ls -A "$PGDATA")" ]; then
        echo_with_timestamp "Initializing PostgreSQL database..."
        mkdir -p "$PGDATA"
        chown -R postgres:postgres "$PGDATA"
        chmod 700 "$PGDATA"

        # Initialize PostgreSQL
        su - postgres -c "$PG_BINDIR/initdb -D $PGDATA"
        # Configure PostgreSQL
        echo "host all all 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"
        echo "listen_addresses='*'" >> "$PGDATA/postgresql.conf"
    fi

    # Start Redis
    echo "🚀 Starting Redis..."
    su - $POSTGRES_USER -c "redis-server --daemonize no &"
    sleep 1  # Give Redis time to start
    redis_pid=$(pgrep -x redis-server)
    if [ -n "$redis_pid" ]; then
        echo "✅ Redis started with PID $redis_pid"
        pids+=("$redis_pid")
    else
        echo "❌ Redis failed to start!"
    fi

    # Start Celery
    echo "🚀 Starting Celery..."
    su - $POSTGRES_USER -c "cd /app && celery -A dispatcharr worker -l info &"
    celery_pid=$(pgrep -x celery)
    echo "✅ Celery started with PID $celery_pid"
    pids+=("$celery_pid")

    # Start PostgreSQL
    echo "Starting Postgres..."
    su - postgres -c "$PG_BINDIR/pg_ctl -D $PGDATA start -w -t 300 -o '-c port=${POSTGRES_PORT}'"
    # Wait for PostgreSQL to be ready
    until su - postgres -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
        echo_with_timestamp "Waiting for PostgreSQL to be ready..."
        sleep 1
    done
    postgres_pid=$(su - postgres -c "$PG_BINDIR/pg_ctl -D $PGDATA status" | sed -n 's/.*PID: \([0-9]\+\).*/\1/p')
    echo "✅ Postgres started with PID $postgres_pid"
    pids+=("$postgres_pid")

    # Setup database if needed
    if ! su - postgres -c "psql -p ${POSTGRES_PORT} -tAc \"SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB';\"" | grep -q 1; then
        # Create PostgreSQL database
        echo_with_timestamp "Creating PostgreSQL database..."
        su - postgres -c "createdb -p ${POSTGRES_PORT} ${POSTGRES_DB}"

        # Create user, set ownership, and grant privileges
        echo_with_timestamp "Creating PostgreSQL user..."
        su - postgres -c "psql -p ${POSTGRES_PORT} -d ${POSTGRES_DB}" <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$POSTGRES_USER') THEN
        CREATE ROLE $POSTGRES_USER WITH LOGIN PASSWORD '$POSTGRES_PASSWORD';
    END IF;
END
\$\$;
EOF
        echo_with_timestamp "Setting PostgreSQL user privileges..."
        su postgres -c "$PG_BINDIR/psql -p ${POSTGRES_PORT} -c \"ALTER DATABASE ${POSTGRES_DB} OWNER TO $POSTGRES_USER;\""
        su postgres -c "$PG_BINDIR/psql -p ${POSTGRES_PORT} -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO $POSTGRES_USER;\""
        # Finished setting up PosgresSQL database
        echo_with_timestamp "PostgreSQL database setup complete."
    fi

    # Test PostgreSQL connection and exit if unavailable
    echo_with_timestamp "Testing database connection..."
    if ! pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB; then
        echo_with_timestamp "ERROR: PostgreSQL is not ready. Exiting..."
        exit 1
    else
        echo_with_timestamp "PostgreSQL is ready to accept connections."
    fi

    # Verify database accessibility
    echo_with_timestamp "Verifying database accessibility..."
    if ! su - $POSTGRES_USER -c "psql -p ${POSTGRES_PORT} -d ${POSTGRES_DB} -c 'SELECT 1;'" >/dev/null 2>&1; then
        echo_with_timestamp "ERROR: PostgreSQL is running but the database is not accessible. Exiting..."
        exit 1
    else
        echo_with_timestamp "PostgreSQL database is accessible."
    fi
fi

# Run Django commands
cd /app
echo_with_timestamp "Running Django commands..."
python manage.py migrate --noinput || true
python manage.py collectstatic --noinput || true

# Always start Gunicorn
echo "🚀 Starting Gunicorn..."
su - $POSTGRES_USER -c "cd /app && gunicorn --workers=4 --worker-class=gevent --timeout=300 --bind 0.0.0.0:${ADMIN_PORT} dispatcharr.wsgi:application &"
gunicorn_pid=$(pgrep -x gunicorn | sort | head -n1)
echo "✅ Gunicorn started with PID $gunicorn_pid"
pids+=("$gunicorn_pid")

echo "🚀 Starting nginx..."
nginx
nginx_pid=$(pgrep nginx | sort  | head -n1)
echo "✅ nginx started with PID $nginx_pid"
pids+=("$nginx_pid")

# Log PIDs
echo "📝 Process PIDs: ${pids[*]}"

echo "

       %%%%
    %%%%%%%%%%%
   %%%%%%%%%%%%%%%
   %%%%     %%%%%%%%%%
  %%%%%        %%%%%%%%%%
  @%%%%           %%%%%%%%%%
   %%%%     *        %%%%%%%%%%
   %%%%     ****        %%%%%%%%%%
   %%%%     *******         %%%%%%%%
   %%%%     ***********        %%%%%%
   %%%%     **************        %%%%
   %%%%     *************           %
   %%%%     **********         @%%% %
   %%%%     *******          %%%%%%
   %%%%     ****         %%%%%%%%%%
   %%%%               %%%%%%%%%%
   %%%%            %%%%%%%%%%
   %%%%         %%%%%%%%%
   %%%%      %%%%%%%%%@
          %%%%%%%%%
     @%%%%%%%%%%
         %%%%

DISPACTHARR HAS SUCCESSFULLY STARTED
"
# Wait for at least one process to exit and log the process that exited first
if [ ${#pids[@]} -gt 0 ]; then
    echo "⏳ Waiting for processes to exit..."
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
