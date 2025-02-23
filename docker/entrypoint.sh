#!/bin/sh

set -e  # Exit immediately if a command exits with a non-zero status

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
export PUID=${PUID:-1000}
export PGID=${PGID:-1000}
export DJANGO_SUPERUSER_USERNAME=${DEFAULT_USERNAME:-admin}
export DJANGO_SUPERUSER_PASSWORD=${DEFAULT_PASSWORD:-admin}
export DJANGO_SUPERUSER_EMAIL=${DEFAULT_EMAIL:-admin@dispatcharr.local}
export PGDATA=${PGDATA:-/app/data/db}
export PG_BINDIR="/usr/lib/postgresql/14/bin"


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

# Start PostgreSQL
su - postgres -c "$PG_BINDIR/pg_ctl -D $PGDATA start -w -t 300 -o '-c port=${POSTGRES_PORT}'"

# Wait for PostgreSQL to be ready
until su - postgres -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
    echo_with_timestamp "Waiting for PostgreSQL to be ready..."
    sleep 1
done

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

# Start Redis
echo_with_timestamp "Starting Redis..."
su - $POSTGRES_USER -c 'redis-server --daemonize yes'

# Run Django commands
echo_with_timestamp "Running Django commands..."
python manage.py collectstatic --noinput || true
python manage.py makemigrations --noinput || true
python manage.py migrate --noinput || true
echo_with_timestamp "Checking if Django superuser exists..."
if ! python manage.py shell -c "from django.contrib.auth import get_user_model; exit(0) if get_user_model().objects.filter(username='${DJANGO_SUPERUSER_USERNAME}').exists() else exit(1)"; then
    echo_with_timestamp "Superuser does not exist. Creating..."
    python manage.py createsuperuser --noinput || true
else
    echo_with_timestamp "Superuser already exists. Skipping creation."
fi

# Start Celery
echo_with_timestamp "Starting Celery..."
su - $POSTGRES_USER -c 'cd /app && celery -A dispatcharr worker --loglevel=info &'

# Start Gunicorn
echo_with_timestamp "Starting Gunicorn..."
su - $POSTGRES_USER -c 'cd /app && gunicorn --workers=4 --worker-class=gevent --timeout=300 --bind 0.0.0.0:9191 dispatcharr.wsgi:application'