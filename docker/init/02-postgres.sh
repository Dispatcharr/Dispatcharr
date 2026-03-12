#!/bin/bash

# Skip internal PostgreSQL setup in modular mode (using external database)
if [[ "$DISPATCHARR_ENV" != "modular" ]]; then

    # Ensure the PostgreSQL socket directory is writable by the application user.
    # The package installs this owned by the postgres system user, but PostgreSQL
    # runs as $POSTGRES_USER (PUID:PGID) in AIO mode.
    if [ -d /var/run/postgresql ]; then
        chown $PUID:$PGID /var/run/postgresql
    fi

    # Record PUID:PGID in a sentinel file so subsequent startups can skip
    # the expensive recursive chown when ownership is already correct.
    write_ownership_sentinel() {
        echo "$PUID:$PGID" > "${POSTGRES_DIR}/.owner_puid"
        chown "$PUID:$PGID" "${POSTGRES_DIR}/.owner_puid"
    }

    # Write standard pg_hba.conf and enable network listening.
    # Local (Unix socket): trust — safe for single-app containers where only
    # authorized processes connect. Network: password required via md5.
    # Idempotent: safe to call on every startup.
    configure_pg_network() {
        local datadir="$1"
        cat > "${datadir}/pg_hba.conf" <<HBAEOF
local   all   all   trust
host    all   all   0.0.0.0/0   md5
host    all   all   ::1/128     md5
HBAEOF
        chown "$PUID:$PGID" "${datadir}/pg_hba.conf"
        # Remove any active listen_addresses setting, then append the canonical
        # value. Avoids duplicate accumulation across restarts. Only targets
        # uncommented lines; leaves initdb's default comment intact.
        sed -Ei '/^[[:space:]]*listen_addresses[[:space:]]*=/d' "${datadir}/postgresql.conf"
        echo "listen_addresses='*'" >> "${datadir}/postgresql.conf"
    }

    # Legacy migration: move data from /data root into $POSTGRES_DIR.
    # Safe to remove once all deployments have upgraded past this layout.
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
        chown -R $PUID:$PGID $POSTGRES_DIR
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

    # =========================================================================
    # Existing data: ensure ownership, auth, and permissions are correct.
    # These guarantees run on EVERY startup with existing data — not just
    # upgrades. This eliminates conditional edge cases and ensures the
    # container always reaches a known-good state regardless of how the
    # data was originally created.
    # =========================================================================
    if [ -n "$CURRENT_VERSION" ] && [ -d "$POSTGRES_DIR" ]; then

        # --- 1. Ownership reconciliation (conditional — only when needed) ---
        # Two triggers cause a recursive chown:
        #   a) PG_VERSION owner doesn't match PUID (obvious mismatch)
        #   b) Sentinel file (.owner_puid) missing or stale — catches partial
        #      chown from a previous interrupted startup where early files
        #      (including PG_VERSION) got the new owner but deeper files didn't.
        # After a successful chown, the sentinel records PUID:PGID so
        # subsequent startups skip the expensive recursive operation.
        OWNERSHIP_SENTINEL="${POSTGRES_DIR}/.owner_puid"
        CURRENT_OWNER=$(stat -c '%u' "$PG_VERSION_FILE")
        _needs_chown=false
        if [ "$CURRENT_OWNER" != "$PUID" ]; then
            _needs_chown=true
        elif [ ! -f "$OWNERSHIP_SENTINEL" ] || [ "$(cat "$OWNERSHIP_SENTINEL" 2>/dev/null)" != "$PUID:$PGID" ]; then
            # Sentinel missing or stale. Could be:
            #   a) First startup with sentinel code (pre-existing data) — benign
            #   b) Interrupted chown from a previous startup — needs re-chown
            # Spot-check a deeper directory to distinguish: if base/ also
            # matches PUID:PGID, ownership is likely consistent (case a).
            _deeper_check=$(stat -c '%u:%g' "${POSTGRES_DIR}/base" 2>/dev/null)
            if [ "$_deeper_check" != "$PUID:$PGID" ]; then
                _needs_chown=true
            else
                # Spot-check passed — ownership is consistent, record sentinel
                # so future startups skip the spot-check entirely.
                write_ownership_sentinel
            fi
        fi

        if [ "$_needs_chown" = true ]; then
            echo "Migrating PostgreSQL data ownership from UID $CURRENT_OWNER to $PUID:$PGID..."
            echo "  This may take several minutes for large databases. Do not stop the container."
            if ! chown -R "$PUID:$PGID" "$POSTGRES_DIR" 2>/dev/null; then
                echo ""
                echo "================================================================"
                echo "ERROR: Cannot update ownership of $POSTGRES_DIR"
                echo "  Current owner: UID $CURRENT_OWNER"
                echo "  Target owner:  UID $PUID (GID $PGID)"
                echo ""
                echo "  This typically occurs with rootless Docker or restricted"
                echo "  filesystems (NFS with root_squash, CIFS/SMB)."
                echo ""
                echo "  To fix:"
                echo "    - Local/NFS: sudo chown -R $PUID:$PGID <host_path_to_data>/db"
                echo "    - CIFS/SMB:  set the mount uid=$PUID,gid=$PGID option instead"
                echo "  Then restart the container."
                echo "================================================================"
                echo ""
                exit 1
            fi
            chmod 700 "$POSTGRES_DIR"
            # Write sentinel LAST — if chown was interrupted, the sentinel
            # won't exist and next startup will re-run the full chown.
            write_ownership_sentinel
            echo "Ownership migration complete."
        fi

        # --- 2. Authentication guarantee (unconditional) ---
        # Always rewrite pg_hba.conf to the known-good state. This replaces
        # any auth method (peer, ident, md5, scram) left by previous images
        # or initdb defaults. Eliminates the class of bugs where the OS user
        # name doesn't match any PG role under peer/ident auth.
        configure_pg_network "${POSTGRES_DIR}"
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

        # Prepare the old cluster for pg_upgrade:
        # 1. Promote $POSTGRES_USER to superuser (needed for post-upgrade ops)
        # 2. Detect the bootstrap superuser (install user) — pg_upgrade
        #    requires -U to match this role exactly.
        # The old cluster's install user is "postgres" (pre-PUID images)
        # or $POSTGRES_USER (post-PUID images, future upgrades).
        _pg_tmp_port=5499
        echo "Preparing old cluster for upgrade..."
        su - "$POSTGRES_USER" -c "$OLD_BINDIR/pg_ctl -D $POSTGRES_DIR start -w -o '-c port=$_pg_tmp_port'"
        _promoted=false
        for _role in "postgres" "$POSTGRES_USER"; do
            if su - "$POSTGRES_USER" -c "psql -U $_role -d template1 -p $_pg_tmp_port -tAc 'SELECT 1;'" 2>/dev/null | grep -q 1; then
                if su - "$POSTGRES_USER" -c "psql -U $_role -d template1 -p $_pg_tmp_port -v ON_ERROR_STOP=1" <<UPGEOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$POSTGRES_USER') THEN
        CREATE ROLE $POSTGRES_USER WITH SUPERUSER LOGIN;
    ELSE
        ALTER ROLE $POSTGRES_USER WITH SUPERUSER;
    END IF;
END
\$\$;
UPGEOF
                then
                    _promoted=true
                    break
                fi
            fi
        done

        # Detect the bootstrap superuser (OID 10 = the role that ran initdb).
        _install_user=$(su - "$POSTGRES_USER" -c "psql -d template1 -p $_pg_tmp_port -tAc \
            \"SELECT rolname FROM pg_authid WHERE oid = 10;\"" 2>/dev/null | tr -d '[:space:]')
        if [ -z "$_install_user" ]; then
            _install_user="postgres"
        fi

        su - "$POSTGRES_USER" -c "$OLD_BINDIR/pg_ctl -D $POSTGRES_DIR stop -w"
        if [ "$_promoted" != true ]; then
            echo "❌ Failed to prepare old cluster for upgrade."
            echo "   Could not promote '$POSTGRES_USER' to superuser in PG $CURRENT_VERSION."
            exit 1
        fi
        echo "Old cluster install user: $_install_user"

        # Prepare new data directory
        NEW_POSTGRES_DIR="${POSTGRES_DIR}_$PG_VERSION"

        # Remove new data directory if it already exists (from a failed/partial upgrade)
        if [ -d "$NEW_POSTGRES_DIR" ]; then
            echo "Warning: $NEW_POSTGRES_DIR already exists. Removing it to avoid upgrade issues."
            rm -rf "$NEW_POSTGRES_DIR"
        fi

        mkdir -p "$NEW_POSTGRES_DIR"
        chown -R $PUID:$PGID "$NEW_POSTGRES_DIR"
        chmod 700 "$NEW_POSTGRES_DIR"

        # Initialize new data directory with the same install user as the old
        # cluster. pg_upgrade requires the -U user to match both clusters.
        echo "Initializing new PostgreSQL data directory at $NEW_POSTGRES_DIR..."
        su - "$POSTGRES_USER" -c "$NEW_BINDIR/initdb -U $_install_user -D $NEW_POSTGRES_DIR"
        echo "Running pg_upgrade from $OLD_BINDIR to $NEW_BINDIR..."
        su - "$POSTGRES_USER" -c "$NEW_BINDIR/pg_upgrade -U $_install_user -b $OLD_BINDIR -B $NEW_BINDIR -d $POSTGRES_DIR -D $NEW_POSTGRES_DIR"

        # Move old data directory for backup, move new into place
        mv "$POSTGRES_DIR" "${POSTGRES_DIR}_backup_${CURRENT_VERSION}_$(date +%s)"
        mv "$NEW_POSTGRES_DIR" "$POSTGRES_DIR"

        # Apply standard connection configuration to the upgraded data directory.
        configure_pg_network "${POSTGRES_DIR}"

        # Record ownership sentinel for the newly upgraded data directory.
        write_ownership_sentinel

        echo "Upgrade complete. Old data directory backed up."

        # Uninstall PostgreSQL if we installed it just for upgrade
        if [ "$PG_INSTALLED_BY_SCRIPT" -eq 1 ]; then
            echo "Uninstalling temporary PostgreSQL $CURRENT_VERSION packages..."
            apt remove -y postgresql-$CURRENT_VERSION postgresql-contrib-$CURRENT_VERSION
            apt autoremove -y
        fi
    fi

    # Initialize PostgreSQL data directory (fresh install only).
    # Only runs initdb + configure_pg_network here. Database creation,
    # role setup, and password configuration are handled by the
    # unconditional guarantees (promote_app_role, ensure_app_database)
    # after PostgreSQL starts in entrypoint.sh.
    if [ -z "$(ls -A "$POSTGRES_DIR")" ]; then
        echo "Initializing PostgreSQL database..."
        mkdir -p "$POSTGRES_DIR"
        chown -R "$PUID:$PGID" "$POSTGRES_DIR"
        chmod 700 "$POSTGRES_DIR"

        # Initialize PostgreSQL as the application user.
        # The superuser role is automatically named $POSTGRES_USER.
        su - "$POSTGRES_USER" -c "$PG_BINDIR/initdb -D ${POSTGRES_DIR}"

        # Configure authentication and network access.
        configure_pg_network "${POSTGRES_DIR}"

        # Record ownership sentinel for the freshly initialized data directory.
        write_ownership_sentinel
    fi

fi  # End of DISPATCHARR_ENV != modular check

# =========================================================================
# 3. Role guarantee (unconditional — runs after PostgreSQL starts)
#
# Ensures the application role ($POSTGRES_USER) exists with superuser
# privileges and the correct password. Called from entrypoint.sh after
# PostgreSQL starts on every AIO startup.
#
# Idempotent: checks before altering. Handles all scenarios:
#   - Fresh install: role exists from initdb, just verifies
#   - Upgrade from postgres-user: creates dispatch role, promotes to superuser
#   - PUID change: verifies existing role, updates password
#   - Normal restart: no-op (role already correct)
#
# Tries multiple database/role combinations to handle incomplete data
# (e.g., interrupted initialization from a previous image version).
# =========================================================================
promote_app_role() {
    if [[ "$DISPATCHARR_ENV" == "modular" ]]; then
        return 0
    fi

    echo "Ensuring application role is configured..."

    # Find a connectable superuser role. Try multiple databases in case
    # the default 'postgres' database doesn't exist (e.g., incomplete
    # initialization from a crashed previous container).
    # Single query per candidate: if connection fails, output is empty;
    # if connected but not superuser, output is 'f'. Only 't' passes.
    CONNECT_ROLE=""
    CONNECT_DB=""
    for try_db in "postgres" "template1"; do
        for try_role in "postgres" "$POSTGRES_USER"; do
            local _super
            _super=$(su - $POSTGRES_USER -c "psql -U $try_role -d $try_db -p ${POSTGRES_PORT} -tAc \
                \"SELECT rolsuper FROM pg_roles WHERE rolname='$try_role';\"" 2>/dev/null | tr -d '[:space:]')
            if [ "$_super" = "t" ]; then
                CONNECT_ROLE="$try_role"
                CONNECT_DB="$try_db"
                break 2
            fi
        done
    done

    if [ -z "$CONNECT_ROLE" ]; then
        echo "❌ Role setup failed: no connectable superuser role found."
        echo "   To recover manually:"
        echo "     su - $POSTGRES_USER -c \"psql -d template1 -p $POSTGRES_PORT\""
        echo "     CREATE ROLE $POSTGRES_USER WITH SUPERUSER LOGIN PASSWORD '<your_password>';"
        exit 1
    fi

    # Escape single quotes for safe SQL interpolation
    local _sql_pw="${POSTGRES_PASSWORD//\'/\'\'}"

    if ! su - $POSTGRES_USER -c "psql -U $CONNECT_ROLE -d $CONNECT_DB -p ${POSTGRES_PORT} -v ON_ERROR_STOP=1" <<EOSQL
DO \$\$
BEGIN
    -- Ensure the application role exists with superuser and login.
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$POSTGRES_USER') THEN
        CREATE ROLE $POSTGRES_USER WITH SUPERUSER LOGIN PASSWORD '${_sql_pw}';
    ELSE
        -- Only alter if not already superuser (idempotent).
        IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = '$POSTGRES_USER') THEN
            ALTER ROLE $POSTGRES_USER WITH SUPERUSER LOGIN;
        END IF;
        -- Ensure password is current regardless.
        ALTER ROLE $POSTGRES_USER WITH PASSWORD '${_sql_pw}';
    END IF;

    -- Rollback compatibility: preserve the postgres role as superuser so
    -- older images (which connect as the postgres DB role) continue to work.
    -- This block can be removed once rollback to pre-PUID images is no
    -- longer expected.
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'postgres') THEN
        IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = 'postgres') THEN
            ALTER ROLE postgres WITH SUPERUSER;
        END IF;
    END IF;
END
\$\$;
EOSQL
    then
        echo "❌ Role setup failed. The application may not be able to connect."
        echo "   Check PostgreSQL logs for details."
        echo "   To recover manually:"
        echo "     su - $POSTGRES_USER -c \"psql -d template1 -p $POSTGRES_PORT\""
        echo "     ALTER ROLE $POSTGRES_USER WITH SUPERUSER LOGIN PASSWORD '<your_password>';"
        exit 1
    fi

    echo "✅ Application role configured."
}

# =========================================================================
# 4. Database guarantee (unconditional — runs after role setup)
#
# Ensures the application database ($POSTGRES_DB) exists. Handles
# incomplete data from interrupted previous initializations where
# PG_VERSION exists but the application database was never created.
# =========================================================================
ensure_app_database() {
    if [[ "$DISPATCHARR_ENV" == "modular" ]]; then
        return 0
    fi

    # Connect to template1 (always exists) to check pg_database catalog.
    if su - $POSTGRES_USER -c "psql -d template1 -p ${POSTGRES_PORT} -tAc \
        \"SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB';\"" 2>/dev/null | grep -q 1; then
        return 0
    fi

    echo "Application database '$POSTGRES_DB' not found — creating..."
    if ! su - $POSTGRES_USER -c "createdb -p ${POSTGRES_PORT} --encoding=UTF8 ${POSTGRES_DB}" 2>/dev/null; then
        # Might already exist if the check failed for a transient reason.
        if su - $POSTGRES_USER -c "psql -d template1 -p ${POSTGRES_PORT} -tAc \
            \"SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB';\"" 2>/dev/null | grep -q 1; then
            return 0
        fi
        echo "❌ Failed to create database '$POSTGRES_DB'"
        exit 1
    fi
    echo "✅ Database '$POSTGRES_DB' created."
}

ensure_utf8_encoding() {
    # Check encoding of existing database
    # Supports both internal (Unix socket) and external (TCP) PostgreSQL
    echo "Checking database encoding..."

    if [[ "$DISPATCHARR_ENV" == "modular" ]]; then
        # External database: use TCP connection with password
        CURRENT_ENCODING=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -w -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = current_database();" 2>/dev/null | tr -d ' ')
    else
        # Internal database: use Unix socket as application user
        CURRENT_ENCODING=$(su - $POSTGRES_USER -c "psql -p ${POSTGRES_PORT} -d ${POSTGRES_DB} -tAc \"SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = current_database();\"" | tr -d ' ')
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
            # Internal database: use Unix socket as application user
            # Dump database (include permissions and ownership)
            su - $POSTGRES_USER -c "pg_dump -p ${POSTGRES_PORT} ${POSTGRES_DB}" > "$DUMP_FILE" || { echo "Dump failed"; return 1; }
            # Drop and recreate database with UTF8 encoding using template0
            su - $POSTGRES_USER -c "dropdb -p ${POSTGRES_PORT} ${POSTGRES_DB}" || { echo "Drop failed"; return 1; }
            # Recreate database with UTF8 encoding and correct owner
            su - $POSTGRES_USER -c "createdb -p ${POSTGRES_PORT} --encoding=UTF8 --template=template0 --owner=${POSTGRES_USER} ${POSTGRES_DB}" || { echo "Create failed"; return 1; }
            # Restore data
            cat "$DUMP_FILE" | su - $POSTGRES_USER -c "psql -p ${POSTGRES_PORT} -d ${POSTGRES_DB}" || { echo "Restore failed"; return 1; }
        fi

        rm -f "$DUMP_FILE"
        echo "✅ Database $POSTGRES_DB converted to UTF8."
    else
        echo "✅ Database encoding is UTF8"
    fi
}

check_external_postgres_version() {
    # Only check for modular deployments
    if [[ "$DISPATCHARR_ENV" != "modular" ]]; then
        return 0
    fi

    echo "🔍 Checking external PostgreSQL version compatibility..."

    # Get minimum required version from base image (set in entrypoint.sh)
    # PG_VERSION is from DispatcharrBase
    MIN_REQUIRED_VERSION=$PG_VERSION

    # Query external PostgreSQL version
    # Use $POSTGRES_DB — restricted users may not have access to the default 'postgres' database
    PG_VERSION_ERR=$(mktemp)
    EXTERNAL_VERSION=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -w -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SHOW server_version;" 2>"$PG_VERSION_ERR" | grep -oE '^[0-9]+')

    if [ -z "$EXTERNAL_VERSION" ]; then
        echo "❌ ERROR: Unable to determine external PostgreSQL version"
        echo "   Could not connect to database '$POSTGRES_DB' at ${POSTGRES_HOST}:${POSTGRES_PORT} as user '$POSTGRES_USER'"
        echo "   Error: $(cat "$PG_VERSION_ERR")"
        echo "   Please verify your database connection settings."
        rm -f "$PG_VERSION_ERR"
        return 1
    fi
    rm -f "$PG_VERSION_ERR"

    # Compare versions
    if [[ "$EXTERNAL_VERSION" -lt "$MIN_REQUIRED_VERSION" ]]; then
        # FAIL: Version too old
        echo ""
        echo "❌ ERROR: PostgreSQL version mismatch"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "  External Database: PostgreSQL $EXTERNAL_VERSION"
        echo "  Required Version:  PostgreSQL $MIN_REQUIRED_VERSION or higher"
        echo ""
        echo "  Your external PostgreSQL database is too old for Dispatcharr."
        echo "  Please upgrade to PostgreSQL $MIN_REQUIRED_VERSION or higher."
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        return 1

    elif [[ "$EXTERNAL_VERSION" -eq "$MIN_REQUIRED_VERSION" ]]; then
        # MATCH: Exact version match
        echo "✅ PostgreSQL version check passed"
        echo "   External Database: PostgreSQL $EXTERNAL_VERSION (matches target version)"

    else
        # HIGHER: Newer version
        echo "✅ PostgreSQL version check passed"
        echo "   External Database: PostgreSQL $EXTERNAL_VERSION"
        echo "   Target Version:    PostgreSQL $MIN_REQUIRED_VERSION"
        echo "   ℹ️  Your database is newer than the target version."
        echo "   PostgreSQL version should be compatible with Dispatcharr."
    fi

    return 0
}
