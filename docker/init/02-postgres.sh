#!/bin/bash

# Skip internal PostgreSQL setup in modular mode (using external database)
if [[ "$DISPATCHARR_ENV" != "modular" ]]; then

    # Temporary migration from postgres in /data to $POSTGRES_DIR. Can likely remove
    # some time in the future.
    if [ -e "/data/postgresql.conf" ]; then
        echo "Migrating PostgreSQL data from /data to $POSTGRES_DIR..."

        # Create a temporary directory outside of /data
        mkdir -p /tmp/postgres_migration

        # Move the PostgreSQL files to the temporary directory
        mv /data/* /tmp/postgres_migration/

        # Create the target directory
        mkdir -p $POSTGRES_DIR

        # Move the files from temporary directory to the final location
        mv /tmp/postgres_migration/* $POSTGRES_DIR/

        # Clean up the temporary directory
        rmdir /tmp/postgres_migration

        # Set proper ownership and permissions for PostgreSQL data directory
        chown -R postgres:postgres $POSTGRES_DIR
        chmod 700 $POSTGRES_DIR

        echo "Migration completed successfully."
    fi

    PG_VERSION_FILE="${POSTGRES_DIR}/PG_VERSION"

    # Detect current version from data directory, if present
    if [ -f "$PG_VERSION_FILE" ]; then
        CURRENT_VERSION=$(cat "$PG_VERSION_FILE")
    else
        CURRENT_VERSION=""
    fi

    # Only run upgrade if current version is set and not the target
    if [ -n "$CURRENT_VERSION" ] && [ "$CURRENT_VERSION" != "$PG_VERSION" ]; then
        echo "Detected PostgreSQL data directory version $CURRENT_VERSION, upgrading to $PG_VERSION..."
        # Set binary paths for upgrade if needed
        OLD_BINDIR="/usr/lib/postgresql/${CURRENT_VERSION}/bin"
        NEW_BINDIR="/usr/lib/postgresql/${PG_VERSION}/bin"
        PG_INSTALLED_BY_SCRIPT=0
        if [ ! -d "$OLD_BINDIR" ]; then
            echo "PostgreSQL binaries for version $CURRENT_VERSION not found. Installing..."
            apt update && apt install -y postgresql-$CURRENT_VERSION postgresql-contrib-$CURRENT_VERSION
            if [ $? -ne 0 ]; then
                echo "Failed to install PostgreSQL version $CURRENT_VERSION. Exiting."
                exit 1
            fi
            PG_INSTALLED_BY_SCRIPT=1
        fi

        # Prepare new data directory
        NEW_POSTGRES_DIR="${POSTGRES_DIR}_$PG_VERSION"

        # Remove new data directory if it already exists (from a failed/partial upgrade)
        if [ -d "$NEW_POSTGRES_DIR" ]; then
            echo "Warning: $NEW_POSTGRES_DIR already exists. Removing it to avoid upgrade issues."
            rm -rf "$NEW_POSTGRES_DIR"
        fi

        mkdir -p "$NEW_POSTGRES_DIR"
        chown -R postgres:postgres "$NEW_POSTGRES_DIR"
        chmod 700 "$NEW_POSTGRES_DIR"

        # Initialize new data directory
        echo "Initializing new PostgreSQL data directory at $NEW_POSTGRES_DIR..."
        su - postgres -c "$NEW_BINDIR/initdb -D $NEW_POSTGRES_DIR"
        echo "Running pg_upgrade from $OLD_BINDIR to $NEW_BINDIR..."
        # Run pg_upgrade
        su - postgres -c "$NEW_BINDIR/pg_upgrade -b $OLD_BINDIR -B $NEW_BINDIR -d $POSTGRES_DIR -D $NEW_POSTGRES_DIR"

        # Move old data directory for backup, move new into place
        mv "$POSTGRES_DIR" "${POSTGRES_DIR}_backup_${CURRENT_VERSION}_$(date +%s)"
        mv "$NEW_POSTGRES_DIR" "$POSTGRES_DIR"

        echo "Upgrade complete. Old data directory backed up."

        # Uninstall PostgreSQL if we installed it just for upgrade
        if [ "$PG_INSTALLED_BY_SCRIPT" -eq 1 ]; then
            echo "Uninstalling temporary PostgreSQL $CURRENT_VERSION packages..."
            apt remove -y postgresql-$CURRENT_VERSION postgresql-contrib-$CURRENT_VERSION
            apt autoremove -y
        fi
    fi

    # Initialize PostgreSQL database
    if [ -z "$(ls -A $POSTGRES_DIR)" ]; then
        echo "Initializing PostgreSQL database..."
        mkdir -p $POSTGRES_DIR
        chown -R postgres:postgres $POSTGRES_DIR
        chmod 700 $POSTGRES_DIR

        # Initialize PostgreSQL
        su - postgres -c "$PG_BINDIR/initdb -D ${POSTGRES_DIR}"
        # Configure PostgreSQL
        echo "host all all 0.0.0.0/0 md5" >> "${POSTGRES_DIR}/pg_hba.conf"
        echo "listen_addresses='*'" >> "${POSTGRES_DIR}/postgresql.conf"

        # Start PostgreSQL
        echo "Starting Postgres..."
        su - postgres -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} start -w -t 300 -o '-c port=${POSTGRES_PORT}'"
        # Wait for PostgreSQL to be ready
        until su - postgres -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
            echo "Waiting for PostgreSQL to be ready..."
            sleep 1
        done

        postgres_pid=$(su - postgres -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} status" | sed -n 's/.*PID: \([0-9]\+\).*/\1/p')

        # Setup database if needed
        if ! su - postgres -c "psql -p ${POSTGRES_PORT} -tAc \"SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB';\"" | grep -q 1; then
            # Create PostgreSQL database
            echo "Creating PostgreSQL database..."
            su - postgres -c "createdb -p ${POSTGRES_PORT} --encoding=UTF8 ${POSTGRES_DB}"
                    # Create user, set ownership, and grant privileges
            echo "Creating PostgreSQL user..."
            su - postgres -c "psql -p ${POSTGRES_PORT} -d ${POSTGRES_DB}" <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$POSTGRES_USER') THEN
        CREATE ROLE $POSTGRES_USER WITH LOGIN PASSWORD '$POSTGRES_PASSWORD';
    END IF;
END
\$\$;
EOF
            echo "Setting PostgreSQL user privileges..."
            su postgres -c "$PG_BINDIR/psql -p ${POSTGRES_PORT} -c \"ALTER DATABASE ${POSTGRES_DB} OWNER TO $POSTGRES_USER;\""
            su postgres -c "$PG_BINDIR/psql -p ${POSTGRES_PORT} -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO $POSTGRES_USER;\""
            # Finished setting up PosgresSQL database
            echo "PostgreSQL database setup complete."
        fi

        kill $postgres_pid
        while kill -0 $postgres_pid; do
            sleep 1
        done
    fi

fi  # End of DISPATCHARR_ENV != modular check

ensure_utf8_encoding() {
    # Check encoding of existing database
    # Supports both internal (Unix socket) and external (TCP) PostgreSQL
    echo "Checking database encoding..."

    if [[ "$DISPATCHARR_ENV" == "modular" ]]; then
        # External database: use TCP connection with password
        CURRENT_ENCODING=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -w -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = current_database();" 2>/dev/null | tr -d ' ')
    else
        # Internal database: use Unix socket as postgres user
        CURRENT_ENCODING=$(su - postgres -c "psql -p ${POSTGRES_PORT} -d ${POSTGRES_DB} -tAc \"SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = current_database();\"" | tr -d ' ')
    fi

    if [ "$CURRENT_ENCODING" != "UTF8" ]; then
        echo "Database $POSTGRES_DB encoding is $CURRENT_ENCODING, converting to UTF8..."
        DUMP_FILE="/tmp/${POSTGRES_DB}_utf8_dump_$(date +%s).sql"

        if [[ "$DISPATCHARR_ENV" == "modular" ]]; then
            # External database: use TCP connection with password
            # Dump database (include permissions and ownership)
            PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -w -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$POSTGRES_DB" > "$DUMP_FILE" || { echo "Dump failed"; return 1; }
            # Drop and recreate database with UTF8 encoding using template0
            PGPASSWORD="$POSTGRES_PASSWORD" dropdb -w -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$POSTGRES_DB" || { echo "Drop failed"; return 1; }
            # Recreate database with UTF8 encoding
            PGPASSWORD="$POSTGRES_PASSWORD" createdb -w -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" --encoding=UTF8 --template=template0 "$POSTGRES_DB" || { echo "Create failed"; return 1; }
            # Restore data
            PGPASSWORD="$POSTGRES_PASSWORD" psql -w -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$DUMP_FILE" || { echo "Restore failed"; return 1; }
        else
            # Internal database: use Unix socket as postgres user
            # Dump database (include permissions and ownership)
            su - postgres -c "pg_dump -p ${POSTGRES_PORT} ${POSTGRES_DB}" > "$DUMP_FILE" || { echo "Dump failed"; return 1; }
            # Drop and recreate database with UTF8 encoding using template0
            su - postgres -c "dropdb -p ${POSTGRES_PORT} ${POSTGRES_DB}" || { echo "Drop failed"; return 1; }
            # Recreate database with UTF8 encoding and correct owner
            su - postgres -c "createdb -p ${POSTGRES_PORT} --encoding=UTF8 --template=template0 --owner=${POSTGRES_USER} ${POSTGRES_DB}" || { echo "Create failed"; return 1; }
            # Restore data
            cat "$DUMP_FILE" | su - postgres -c "psql -p ${POSTGRES_PORT} -d ${POSTGRES_DB}" || { echo "Restore failed"; return 1; }
        fi

        rm -f "$DUMP_FILE"
        echo "✅ Database $POSTGRES_DB converted to UTF8."
    else
        echo "✅ Database encoding is UTF8"
    fi
}


