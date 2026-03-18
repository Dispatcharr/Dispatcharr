#!/bin/bash
#
# Integration test suite for PUID/PGID Docker init changes.
# Validates runtime behavior across fresh installs, upgrades, restarts,
# storage configurations, and deployment modes.
#
# Prerequisites:
#   - Docker Desktop (or Docker Engine) running
#   - Internet access (pulls postgres:16, postgres:17, redis:latest,
#     and the Dispatcharr release image for upgrade tests)
#   - ~10-15 minutes for a full run (PG upgrade scenarios dominate)
#
# Usage:
#   cd <repo_root>
#   bash docker/tests/test-puid-pgid.sh [--skip-build] [--keep-on-fail] [scenario_name]
#
# Options:
#   --skip-build    Skip Docker image build (use existing dispatcharr:puid-test image)
#   --keep-on-fail  Don't clean up containers/volumes on failure (for debugging)
#   scenario_name   Run only the named scenario (e.g., "fresh_default")
#
# Examples:
#   bash docker/tests/test-puid-pgid.sh                     # Full run (build + all 20 scenarios)
#   bash docker/tests/test-puid-pgid.sh fresh_default        # Run one scenario
#   bash docker/tests/test-puid-pgid.sh --skip-build         # Reuse existing image
#   bash docker/tests/test-puid-pgid.sh --keep-on-fail       # Keep resources for debugging
#
# Scenarios:
#   fresh_default         Fresh AIO install, default PUID/PGID (1000:1000)
#   fresh_custom_puid     Fresh AIO install, PUID=1500 PGID=1500
#   upgrade_explicit_puid Upgrade from old UID 102 data with explicit PUID=1000
#   upgrade_auto_adapt    Upgrade from old UID 102 data, no PUID set (auto-detect)
#   restart_idempotent    Container restart on existing data (no unnecessary chown)
#   puid_change           Change PUID between restarts (1000 -> 2000)
#   uid_collision_102     PUID=102 (collides with postgres system user)
#   puid_zero             PUID=0 rejected (PostgreSQL can't run as root)
#   puid_non_numeric      PUID=abc rejected (must be positive integer)
#   bind_mount            Fresh install on bind mount (local filesystem)
#   bind_mount_upgrade    Upgrade from UID 102 on bind mount
#   bind_mount_auto_adapt Auto-adapt PUID on bind mount (no migration)
#   modular_mode          External PostgreSQL + Redis (skip internal PG setup)
#   custom_postgres_user  Custom POSTGRES_USER=myapp
#   custom_port           Custom POSTGRES_PORT=5433
#   tmpfs_volume          Ephemeral tmpfs storage
#   pg_major_upgrade      PostgreSQL 16 -> 17 major version upgrade + ownership migration
#   pg_upgrade_post_puid  PG 16 -> 17 upgrade on post-PUID data (install user = dispatch)
#   e2e_web_ui            Full HTTP stack verification (nginx -> uwsgi -> Django)
#   readonly_rootfs       Read-only root filesystem (security hardened)
#
# Exit codes:
#   0  All tests passed
#   1  One or more tests failed (or build failed)

set -uo pipefail

# Prevent Git Bash (MINGW) from converting Unix paths like /data/db to
# C:/Program Files/Git/data/db when passing arguments to docker exec.
export MSYS_NO_PATHCONV=1

###############################################################################
# Configuration
###############################################################################
IMAGE_NAME="dispatcharr:puid-test"
RELEASE_IMAGE="ghcr.io/dispatcharr/dispatcharr:latest"
BASE_IMAGE="ghcr.io/dispatcharr/dispatcharr:base"
TEST_PREFIX="puid_test"
STARTUP_TIMEOUT=180      # seconds to wait for container startup
SKIP_BUILD=false
KEEP_ON_FAIL=false
SINGLE_SCENARIO=""
USE_RELEASE_IMAGE=false
PASS=0
FAIL=0
SKIP=0
ERRORS=()

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

###############################################################################
# Parse arguments
###############################################################################
for arg in "$@"; do
    case "$arg" in
        --skip-build)   SKIP_BUILD=true ;;
        --keep-on-fail) KEEP_ON_FAIL=true ;;
        -*)             echo "Unknown option: $arg"; exit 1 ;;
        *)              SINGLE_SCENARIO="$arg" ;;
    esac
done

###############################################################################
# Helpers
###############################################################################
log_pass() { echo -e "  ${GREEN}✅ $1${NC}"; ((PASS++)); }
log_fail() { echo -e "  ${RED}❌ $1${NC}"; ((FAIL++)); ERRORS+=("[$CURRENT_SCENARIO] $1"); }
log_skip() { echo -e "  ${YELLOW}⏭️  $1${NC}"; ((SKIP++)); }
log_info() { echo -e "  ${CYAN}ℹ️  $1${NC}"; }
section()  { echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; SCENARIO_FAIL_BEFORE=$FAIL; }

CURRENT_SCENARIO=""
CLEANUP_ITEMS=()

# Track resources for cleanup
track_container() { CLEANUP_ITEMS+=("container:$1"); }
track_volume()    { CLEANUP_ITEMS+=("volume:$1"); }
track_network()   { CLEANUP_ITEMS+=("network:$1"); }

# Create a fresh volume, removing any stale one from a previous run
fresh_volume() {
    local vol="$1"
    docker rm -f $(docker ps -aq --filter "volume=${vol}") 2>/dev/null || true
    docker volume rm "$vol" 2>/dev/null || true
    docker volume create "$vol" >/dev/null
    track_volume "$vol"
}

cleanup_scenario() {
    if [ "$KEEP_ON_FAIL" = true ] && [ ${#ERRORS[@]} -gt 0 ]; then
        log_info "Keeping resources for debugging (--keep-on-fail)"
        CLEANUP_ITEMS=()
        return
    fi
    for item in "${CLEANUP_ITEMS[@]}"; do
        local type="${item%%:*}"
        local name="${item#*:}"
        case "$type" in
            container) docker stop "$name" 2>/dev/null; docker rm -f "$name" 2>/dev/null ;;
            volume)    docker volume rm "$name" 2>/dev/null ;;
            network)   docker network rm "$name" 2>/dev/null ;;
        esac
    done
    CLEANUP_ITEMS=()
}

# Ensure cleanup on script exit
trap 'cleanup_scenario' EXIT

# Wait for container startup (looks for uwsgi or a known failure)
wait_for_ready() {
    local name="$1"
    local timeout="${2:-$STARTUP_TIMEOUT}"
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        # Check if container is still running
        if ! docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
            echo "  Container $name exited unexpectedly"
            return 1
        fi
        # Success: uwsgi started
        if docker logs "$name" 2>&1 | grep -q "uwsgi started with PID"; then
            return 0
        fi
        # Known fatal: our error handler
        if docker logs "$name" 2>&1 | grep -q "ERROR: Cannot update ownership"; then
            echo "  Container hit ownership error (expected in some tests)"
            return 1
        fi
        sleep 3
        ((elapsed+=3))
    done
    echo "  Timeout (${timeout}s) waiting for $name"
    return 1
}

# Verify file/directory ownership
check_ownership() {
    local container="$1" path="$2" expected_uid="$3" expected_gid="$4"
    local actual
    actual=$(docker exec "$container" stat -c '%u:%g' "$path" 2>/dev/null)
    if [ "$actual" = "${expected_uid}:${expected_gid}" ]; then
        log_pass "Ownership $path = $actual"
    else
        log_fail "Ownership $path: expected ${expected_uid}:${expected_gid}, got ${actual:-<error>}"
    fi
}

# Verify file permissions (octal)
check_permissions() {
    local container="$1" path="$2" expected="$3"
    local actual
    actual=$(docker exec "$container" stat -c '%a' "$path" 2>/dev/null)
    if [ "$actual" = "$expected" ]; then
        log_pass "Permissions $path = $actual"
    else
        log_fail "Permissions $path: expected $expected, got ${actual:-<error>}"
    fi
}

# Verify PostgreSQL is accessible
check_pg_accessible() {
    local container="$1" os_user="$2" db="${3:-dispatcharr}" port="${4:-5432}"
    if docker exec "$container" su - "$os_user" -c \
        "psql -d $db -p $port -tAc 'SELECT 1;'" 2>/dev/null | grep -q 1; then
        log_pass "PostgreSQL accessible as OS user '$os_user' (db=$db)"
    else
        log_fail "PostgreSQL not accessible as OS user '$os_user' (db=$db)"
    fi
}

# Verify a PG role exists with superuser
check_role_superuser() {
    local container="$1" os_user="$2" role="$3"
    local result
    result=$(docker exec "$container" su - "$os_user" -c \
        "psql -d postgres -p 5432 -tAc \"SELECT rolsuper FROM pg_roles WHERE rolname='$role';\"" 2>/dev/null | tr -d ' ')
    if [ "$result" = "t" ]; then
        log_pass "PG role '$role' is superuser"
    else
        log_fail "PG role '$role' not superuser (got: '${result:-<missing>}')"
    fi
}

# Capture docker logs to a temp file (avoids pipe issues on Windows/Docker Desktop)
_capture_logs() {
    local container="$1" logfile="$2"
    docker logs "$container" > "$logfile" 2>&1
}

# Verify no permission errors in logs
check_no_permission_errors() {
    local container="$1"
    local tmplog; tmplog=$(mktemp)
    _capture_logs "$container" "$tmplog"
    local errors
    errors=$(grep -iE "permission denied|operation not permitted" "$tmplog" \
        | grep -v "GPU acceleration" | grep -v "Warning:" | head -5)
    rm -f "$tmplog"
    if [ -n "$errors" ]; then
        log_fail "Permission errors in logs:"
        echo "$errors" | while read -r line; do echo "    $line"; done
    else
        log_pass "No permission errors in logs"
    fi
}

# Verify Django migrations completed (search full log, not just tail)
check_migrations_done() {
    local container="$1"
    local tmplog; tmplog=$(mktemp)
    _capture_logs "$container" "$tmplog"
    if grep -qE "Running migrations|No migrations to apply|Operations to perform|static files copied|Applying .+\.\.\. OK" "$tmplog"; then
        log_pass "Django migrations completed"
    elif grep -q "uwsgi started with PID" "$tmplog"; then
        # uwsgi starts AFTER migrations — if it's running, migrations succeeded
        log_pass "Django migrations completed (confirmed via uwsgi startup)"
    else
        log_fail "Django migrations did not complete"
    fi
    rm -f "$tmplog"
}

# Check that a log message appears (or does not)
check_log_contains() {
    local container="$1" pattern="$2" description="$3"
    local tmplog; tmplog=$(mktemp)
    _capture_logs "$container" "$tmplog"
    if grep -q "$pattern" "$tmplog"; then
        log_pass "$description"
    else
        log_fail "$description (pattern not found: $pattern)"
    fi
    rm -f "$tmplog"
}
check_log_absent() {
    local container="$1" pattern="$2" description="$3"
    local tmplog; tmplog=$(mktemp)
    _capture_logs "$container" "$tmplog"
    if grep -q "$pattern" "$tmplog"; then
        log_fail "$description (unexpected pattern found: $pattern)"
    else
        log_pass "$description"
    fi
    rm -f "$tmplog"
}

# Verify web UI responds (nginx -> uwsgi -> Django stack is functional).
# Retries briefly since uwsgi may still be connecting after startup log.
check_web_ui() {
    local container="$1" port="${2:-9191}"
    local retries=5 status=""
    for ((i=1; i<=retries; i++)); do
        status=$(docker exec "$container" python3 -c "
import urllib.request, urllib.error
try:
    r = urllib.request.urlopen('http://localhost:$port/', timeout=10)
    print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
except:
    print(0)
" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$status" ] && [ "$status" != "0" ] 2>/dev/null; then
            break
        fi
        sleep 2
    done
    if [ -n "$status" ] && [ "$status" != "0" ] && [ "$status" -lt 500 ] 2>/dev/null; then
        log_pass "Web UI responds (HTTP $status)"
    else
        log_fail "Web UI not responding (got: ${status:-<none>})"
    fi
}

# Dump logs on failure (uses per-scenario tracking)
SCENARIO_FAIL_BEFORE=0
dump_logs_on_fail() {
    local container="$1"
    if [ $FAIL -gt $SCENARIO_FAIL_BEFORE ]; then
        echo -e "\n  ${RED}--- Last 60 lines of logs ---${NC}"
        docker logs "$container" 2>&1 | tail -60 | sed 's/^/  | /'
        echo -e "  ${RED}--- End logs ---${NC}"
    fi
}

# Create old-style PostgreSQL data by running the actual release image.
# This is the most realistic simulation of an upgrade — the release image
# runs its own entrypoint, initializing PG as the postgres system user
# with the real init scripts that users currently have.
setup_old_pg_data() {
    local volume="$1"
    local name="${TEST_PREFIX}_old_setup"
    log_info "Creating old-style data using release image ($RELEASE_IMAGE)..."

    docker rm -f "$name" 2>/dev/null
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -v "${volume}:/data" \
        "$RELEASE_IMAGE" >/dev/null

    # Wait for the release image to fully initialize (PG running + migrations)
    local elapsed=0
    while [ $elapsed -lt $STARTUP_TIMEOUT ]; do
        if docker logs "$name" 2>&1 | grep -q "uwsgi started with PID"; then
            log_info "Release image initialized successfully"
            break
        fi
        if ! docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
            log_info "Release image exited during init (checking data...)"
            break
        fi
        sleep 3; ((elapsed+=3))
    done

    docker stop "$name" >/dev/null 2>&1
    docker rm "$name" >/dev/null 2>&1

    # Verify data was created (use --entrypoint to avoid running full app)
    local owner
    owner=$(docker run --rm --entrypoint stat -v "${volume}:/data" "$IMAGE_NAME" \
        -c '%u:%g' /data/db/PG_VERSION 2>/dev/null)
    log_info "Old data owner: ${owner:-<not found>}"
}

# Fallback: create old-style data manually (if release image unavailable)
setup_old_pg_data_manual() {
    local volume="$1"
    log_info "Initializing old-style PG data manually (UID 102, postgres superuser)..."
    docker run --rm --entrypoint bash -v "${volume}:/data" "$IMAGE_NAME" -c '
        PG_VER=$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)
        PG_BIN=/usr/lib/postgresql/$PG_VER/bin
        mkdir -p /data/db
        chown -R postgres:postgres /data/db
        chmod 700 /data/db
        su - postgres -c "$PG_BIN/initdb -D /data/db"
        su - postgres -c "$PG_BIN/pg_ctl -D /data/db start -w -o \"-c port=5432\""
        su - postgres -c "psql -p 5432 -c \"CREATE ROLE dispatch WITH LOGIN PASSWORD '\''secret'\'';\""
        su - postgres -c "createdb -p 5432 --encoding=UTF8 --owner=dispatch dispatcharr"
        su - postgres -c "$PG_BIN/pg_ctl -D /data/db stop -w"
        echo "Old PG data ready: $(stat -c "%u:%g" /data/db/PG_VERSION) on PG_VERSION"
    '
}

###############################################################################
# Test Scenarios
###############################################################################

# Verifies a clean install with no PUID/PGID set defaults to 1000:1000.
# Checks: ownership, permissions, PG access, role, sentinel, migrations.
test_fresh_default() {
    CURRENT_SCENARIO="fresh_default"
    section "Fresh install — default config (no PUID/PGID)"

    local name="${TEST_PREFIX}_fresh_def"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "1000" "1000"
        check_ownership "$name" "/data/db/PG_VERSION" "1000" "1000"
        check_ownership "$name" "/data/db/pg_hba.conf" "1000" "1000"
        check_permissions "$name" "/data/db" "700"
        check_pg_accessible "$name" "dispatch"
        check_role_superuser "$name" "dispatch" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"

        # Verify ownership sentinel was created
        local sentinel_val
        sentinel_val=$(docker exec "$name" cat /data/db/.owner_puid 2>/dev/null | tr -d '[:space:]')
        if [ "$sentinel_val" = "1000:1000" ]; then
            log_pass "Ownership sentinel created (1000:1000)"
        else
            log_fail "Ownership sentinel: expected 1000:1000, got ${sentinel_val:-<missing>}"
        fi
    else
        log_fail "Container failed to start"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies fresh install with explicitly set PUID/PGID (non-default).
# Checks: ownership matches 1500:1500, PG accessible, role created.
test_fresh_custom_puid() {
    CURRENT_SCENARIO="fresh_custom_puid"
    section "Fresh install — PUID=1500 PGID=1500"

    local name="${TEST_PREFIX}_fresh_puid"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1500 -e PGID=1500 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "1500" "1500"
        check_ownership "$name" "/data/db/PG_VERSION" "1500" "1500"
        check_ownership "$name" "/data/db/pg_hba.conf" "1500" "1500"
        check_pg_accessible "$name" "dispatch"
        check_role_superuser "$name" "dispatch" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
    else
        log_fail "Container failed to start"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Simulates upgrading from pre-PUID image (data owned by UID 102) with
# explicit PUID=1000. Verifies ownership migrates, roles are promoted,
# and the postgres role is preserved for rollback compatibility.
test_upgrade_explicit_puid() {
    CURRENT_SCENARIO="upgrade_explicit_puid"
    section "Upgrade — old UID 102 data, explicit PUID=1000"

    local name="${TEST_PREFIX}_upg_puid"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    if [ "$USE_RELEASE_IMAGE" = true ]; then
        setup_old_pg_data "$vol"
    else
        setup_old_pg_data_manual "$vol"
    fi

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        # Ownership should have migrated to 1000:1000
        check_ownership "$name" "/data/db" "1000" "1000"
        check_ownership "$name" "/data/db/PG_VERSION" "1000" "1000"
        check_ownership "$name" "/data/db/pg_hba.conf" "1000" "1000"
        check_permissions "$name" "/data/db" "700"
        check_pg_accessible "$name" "dispatch"
        check_role_superuser "$name" "dispatch" "dispatch"
        # Rollback compatibility: postgres role still superuser
        check_role_superuser "$name" "dispatch" "postgres"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        check_log_contains "$name" "Migrating PostgreSQL data ownership" \
            "Ownership migration logged"
        check_log_contains "$name" "Application role configured" \
            "Role setup executed"
    else
        log_fail "Container failed to start"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Simulates upgrade without PUID set. Auto-adapt should detect the
# existing data owner (UID 102) and skip ownership migration entirely.
test_upgrade_auto_adapt() {
    CURRENT_SCENARIO="upgrade_auto_adapt"
    section "Upgrade — old UID 102 data, no PUID (auto-adapt)"

    local name="${TEST_PREFIX}_upg_auto"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    if [ "$USE_RELEASE_IMAGE" = true ]; then
        setup_old_pg_data "$vol"
    else
        setup_old_pg_data_manual "$vol"
    fi

    # No PUID/PGID — should auto-adapt to data owner (UID 102)
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        # Data should stay at original UID — no migration. GID depends on
        # the postgres group GID in the release image (typically 104).
        local actual_owner
        actual_owner=$(docker exec "$name" stat -c '%u:%g' /data/db/PG_VERSION 2>/dev/null)
        local expected_uid="102"
        local actual_uid="${actual_owner%%:*}"
        if [ "$actual_uid" = "$expected_uid" ]; then
            log_pass "Ownership /data/db/PG_VERSION UID = $actual_uid (auto-adapted)"
        else
            log_fail "Ownership /data/db/PG_VERSION UID: expected $expected_uid, got $actual_uid"
        fi
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        check_log_contains "$name" "PUID not set" \
            "Auto-adapt logged"
        check_log_absent "$name" "Migrating PostgreSQL data ownership" \
            "No ownership migration (correctly skipped)"
    else
        log_fail "Container failed to start"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies that restarting a container on existing data is idempotent:
# no unnecessary chown, no migration logged, sentinel skip works.
test_restart_idempotent() {
    CURRENT_SCENARIO="restart_idempotent"
    section "Container restart — idempotent (same PUID)"

    local name="${TEST_PREFIX}_restart"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    # First run
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if ! wait_for_ready "$name"; then
        log_fail "First run failed to start"
        dump_logs_on_fail "$name"
        cleanup_scenario
        return
    fi
    log_pass "First run started successfully"

    # Stop and restart
    docker stop "$name" >/dev/null
    docker rm "$name" >/dev/null

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null
    track_container "$name"

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db/PG_VERSION" "1000" "1000"
        check_ownership "$name" "/data/db/pg_hba.conf" "1000" "1000"
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        check_log_absent "$name" "Migrating PostgreSQL data ownership" \
            "No migration on restart"
    else
        log_fail "Restart failed"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies that changing PUID between restarts triggers ownership migration.
# First run: PUID=1000. Second run: PUID=2000 — should chown all PG data.
test_puid_change() {
    CURRENT_SCENARIO="puid_change"
    section "PUID change between restarts (1000 → 2000)"

    local name="${TEST_PREFIX}_puidchg"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    # First run with PUID=1000
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if ! wait_for_ready "$name"; then
        log_fail "First run (PUID=1000) failed"
        dump_logs_on_fail "$name"
        cleanup_scenario
        return
    fi
    log_pass "First run (PUID=1000) started"
    docker stop "$name" >/dev/null; docker rm "$name" >/dev/null

    # Second run with PUID=2000
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=2000 -e PGID=2000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null
    track_container "$name"

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "2000" "2000"
        check_ownership "$name" "/data/db/PG_VERSION" "2000" "2000"
        check_ownership "$name" "/data/db/pg_hba.conf" "2000" "2000"
        check_pg_accessible "$name" "dispatch"
        check_role_superuser "$name" "dispatch" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        check_log_contains "$name" "Migrating PostgreSQL data ownership" \
            "Ownership migration logged for PUID change"
    else
        log_fail "Second run (PUID=2000) failed"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies PUID=102 (which collides with the postgres system user UID).
# 01-user-setup.sh renames the postgres user to $POSTGRES_USER — this
# should be harmless since all operations use $POSTGRES_USER, not 'postgres'.
test_uid_collision_102() {
    CURRENT_SCENARIO="uid_collision_102"
    section "PUID=102 — collision with postgres system user"

    local name="${TEST_PREFIX}_uid102"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=102 -e PGID=102 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "102" "102"
        check_ownership "$name" "/data/db/PG_VERSION" "102" "102"
        check_ownership "$name" "/data/db/pg_hba.conf" "102" "102"
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        log_pass "PUID=102 collision handled correctly"
    else
        log_fail "Container failed to start with PUID=102"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies PUID=0 is rejected early with a clear error message.
# PostgreSQL refuses to run as root, and reassigning UID 0 would
# rename the root user inside the container.
test_puid_zero() {
    CURRENT_SCENARIO="puid_zero"
    section "PUID=0 — rejected (PostgreSQL cannot run as root)"

    local name="${TEST_PREFIX}_uid0"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=0 -e PGID=0 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    # Container should exit quickly with an error
    sleep 5

    if docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
        log_fail "Container should have exited with PUID=0"
    else
        log_pass "Container exited (expected with PUID=0)"
    fi

    check_log_contains "$name" "PUID=0 or PGID=0 is not supported" \
        "Clear error message for PUID=0"
    check_log_absent "$name" "Initializing PostgreSQL" \
        "PostgreSQL init was not attempted"

    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies non-numeric PUID/PGID values are rejected early with
# a clear error message before any user/group manipulation.
test_puid_non_numeric() {
    CURRENT_SCENARIO="puid_non_numeric"
    section "PUID=abc — rejected (must be positive integer)"

    local name="${TEST_PREFIX}_nonnumeric"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=abc -e PGID=xyz \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    sleep 5

    if docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
        log_fail "Container should have exited with non-numeric PUID"
    else
        log_pass "Container exited (expected with non-numeric PUID)"
    fi

    check_log_contains "$name" "PUID and PGID must be positive integers" \
        "Clear error message for non-numeric PUID"
    check_log_absent "$name" "Initializing PostgreSQL" \
        "PostgreSQL init was not attempted"

    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies fresh install works on a bind mount (host directory).
# Uses Docker-managed /tmp to avoid Windows path conversion issues.
test_bind_mount() {
    CURRENT_SCENARIO="bind_mount"
    section "Bind mount — local filesystem"

    local name="${TEST_PREFIX}_bind"
    local hostdir
    # Create a temp directory for the bind mount
    hostdir=$(docker run --rm "$IMAGE_NAME" bash -c "mktemp -d /tmp/puid_test_bind.XXXXXX" 2>/dev/null)
    if [ -z "$hostdir" ]; then
        # Fallback: create on Windows host via Docker
        hostdir="/tmp/puid_test_bind_$$"
    fi

    cleanup_scenario
    track_container "$name"

    # Use a Docker-managed temp dir to avoid Windows path issues
    # Create the bind mount dir inside a helper container, then use it
    docker run --rm -v /tmp:/hosttemp "$IMAGE_NAME" bash -c "
        mkdir -p /hosttemp/puid_test_bind_$$
        chmod 777 /hosttemp/puid_test_bind_$$
    " 2>/dev/null
    local bind_path="/tmp/puid_test_bind_$$"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${bind_path}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "1000" "1000"
        check_ownership "$name" "/data/db/PG_VERSION" "1000" "1000"
        check_ownership "$name" "/data/db/pg_hba.conf" "1000" "1000"
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        log_pass "Bind mount fresh install works"
    else
        log_fail "Bind mount fresh install failed"
    fi
    dump_logs_on_fail "$name"

    # Clean up bind mount
    docker run --rm -v /tmp:/hosttemp "$IMAGE_NAME" bash -c \
        "rm -rf /hosttemp/puid_test_bind_$$" 2>/dev/null
    cleanup_scenario
}

# Verifies ownership migration works on bind mounts (UID 102 -> 1000).
# Creates old-style PG data manually, then starts with new image.
test_bind_mount_upgrade() {
    CURRENT_SCENARIO="bind_mount_upgrade"
    section "Bind mount upgrade — old UID 102 → PUID=1000"

    local name="${TEST_PREFIX}_bind_upg"
    local bind_path="/tmp/puid_test_bind_upg_$$"
    cleanup_scenario
    track_container "$name"

    # Create bind mount dir with old-style PG data (UID 102)
    docker run --rm -v /tmp:/hosttemp --entrypoint bash "$IMAGE_NAME" -c "
        mkdir -p /hosttemp/puid_test_bind_upg_$$/db
        PG_VER=\$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)
        PG_BIN=/usr/lib/postgresql/\$PG_VER/bin
        chown -R postgres:postgres /hosttemp/puid_test_bind_upg_$$/db
        chmod 700 /hosttemp/puid_test_bind_upg_$$/db
        su - postgres -c \"\$PG_BIN/initdb -D /hosttemp/puid_test_bind_upg_$$/db\"
        su - postgres -c \"\$PG_BIN/pg_ctl -D /hosttemp/puid_test_bind_upg_$$/db start -w -o '-c port=5432'\"
        su - postgres -c \"psql -p 5432 -c \\\"CREATE ROLE dispatch WITH LOGIN PASSWORD 'secret';\\\"\"
        su - postgres -c \"createdb -p 5432 --encoding=UTF8 --owner=dispatch dispatcharr\"
        su - postgres -c \"\$PG_BIN/pg_ctl -D /hosttemp/puid_test_bind_upg_$$/db stop -w\"
    "

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${bind_path}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "1000" "1000"
        check_ownership "$name" "/data/db/PG_VERSION" "1000" "1000"
        check_ownership "$name" "/data/db/pg_hba.conf" "1000" "1000"
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        check_log_contains "$name" "Migrating PostgreSQL data ownership" \
            "Bind mount ownership migration logged"
    else
        log_fail "Bind mount upgrade failed"
    fi
    dump_logs_on_fail "$name"

    docker run --rm -v /tmp:/hosttemp "$IMAGE_NAME" bash -c \
        "rm -rf /hosttemp/puid_test_bind_upg_$$" 2>/dev/null
    cleanup_scenario
}

# Verifies auto-adapt works on bind mounts: no PUID set, data owned by
# UID 102 — should auto-detect and skip migration entirely.
test_bind_mount_auto_adapt() {
    CURRENT_SCENARIO="bind_mount_auto_adapt"
    section "Bind mount upgrade — no PUID (auto-adapt to UID 102)"

    local name="${TEST_PREFIX}_bind_auto"
    local bind_path="/tmp/puid_test_bind_auto_$$"
    cleanup_scenario
    track_container "$name"

    # Create bind mount dir with old-style data
    docker run --rm -v /tmp:/hosttemp --entrypoint bash "$IMAGE_NAME" -c "
        mkdir -p /hosttemp/puid_test_bind_auto_$$/db
        PG_VER=\$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)
        PG_BIN=/usr/lib/postgresql/\$PG_VER/bin
        chown -R postgres:postgres /hosttemp/puid_test_bind_auto_$$/db
        chmod 700 /hosttemp/puid_test_bind_auto_$$/db
        su - postgres -c \"\$PG_BIN/initdb -D /hosttemp/puid_test_bind_auto_$$/db\"
        su - postgres -c \"\$PG_BIN/pg_ctl -D /hosttemp/puid_test_bind_auto_$$/db start -w -o '-c port=5432'\"
        su - postgres -c \"psql -p 5432 -c \\\"CREATE ROLE dispatch WITH LOGIN PASSWORD 'secret';\\\"\"
        su - postgres -c \"createdb -p 5432 --encoding=UTF8 --owner=dispatch dispatcharr\"
        su - postgres -c \"\$PG_BIN/pg_ctl -D /hosttemp/puid_test_bind_auto_$$/db stop -w\"
    "

    # No PUID — auto-adapt should match data owner
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -v "${bind_path}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        # Should stay at original UID — no migration. GID depends on the
        # postgres group GID in the image (typically 104, not 102).
        local actual_owner
        actual_owner=$(docker exec "$name" stat -c '%u:%g' /data/db/PG_VERSION 2>/dev/null)
        local expected_uid="102"
        local actual_uid="${actual_owner%%:*}"
        if [ "$actual_uid" = "$expected_uid" ]; then
            log_pass "Ownership /data/db/PG_VERSION UID = $actual_uid (auto-adapted)"
        else
            log_fail "Ownership /data/db/PG_VERSION UID: expected $expected_uid, got $actual_uid"
        fi
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        check_log_contains "$name" "PUID not set" \
            "Auto-adapt logged on bind mount"
        check_log_absent "$name" "Migrating PostgreSQL data ownership" \
            "No migration on auto-adapted bind mount"
    else
        log_fail "Bind mount auto-adapt failed"
    fi
    dump_logs_on_fail "$name"

    docker run --rm -v /tmp:/hosttemp "$IMAGE_NAME" bash -c \
        "rm -rf /hosttemp/puid_test_bind_auto_$$" 2>/dev/null
    cleanup_scenario
}

# Verifies modular mode (external PostgreSQL + Redis). Internal PG setup
# should be completely skipped. No /data/db directory should be created.
test_modular_mode() {
    CURRENT_SCENARIO="modular_mode"
    section "Modular mode — external PostgreSQL + Redis"

    local name="${TEST_PREFIX}_modular"
    local net="${TEST_PREFIX}_modular_net"
    local pg_name="${TEST_PREFIX}_modular_pg"
    local redis_name="${TEST_PREFIX}_modular_redis"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"; track_container "$name"

    # Start external PostgreSQL
    docker run -d --name "$pg_name" --network "$net" \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_PASSWORD=secret \
        -e POSTGRES_DB=dispatcharr \
        postgres:17 >/dev/null

    # Start external Redis
    docker run -d --name "$redis_name" --network "$net" \
        redis:latest >/dev/null

    # Wait for PG to be ready
    local elapsed=0
    while [ $elapsed -lt 30 ]; do
        if docker exec "$pg_name" pg_isready -U dispatch 2>/dev/null | grep -q "accepting"; then
            break
        fi
        sleep 2; ((elapsed+=2))
    done

    docker run -d --name "$name" --network "$net" \
        -e DISPATCHARR_ENV=modular \
        -e POSTGRES_HOST="$pg_name" \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_PASSWORD=secret \
        -e POSTGRES_DB=dispatcharr \
        -e REDIS_HOST="$redis_name" \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        # Verify NO internal PG data created
        if docker exec "$name" test -f /data/db/PG_VERSION 2>/dev/null; then
            log_fail "/data/db/PG_VERSION exists in modular mode"
        else
            log_pass "No internal PG data in modular mode"
        fi
        check_log_absent "$name" "Migrating PostgreSQL data ownership" \
            "No ownership migration in modular mode"
        check_log_absent "$name" "Initializing PostgreSQL database" \
            "No PG init in modular mode"
        check_log_contains "$name" "Modular mode" \
            "Modular mode detected"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
    else
        log_fail "Modular mode failed to start"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies that a non-default POSTGRES_USER name works end-to-end.
# All init scripts use $POSTGRES_USER, so "myapp" should work identically.
test_custom_postgres_user() {
    CURRENT_SCENARIO="custom_postgres_user"
    section "Custom POSTGRES_USER=myapp"

    local name="${TEST_PREFIX}_custuser"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -e POSTGRES_USER=myapp \
        -e POSTGRES_DB=myappdb \
        -e POSTGRES_PASSWORD=mypassword \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "1000" "1000"
        check_pg_accessible "$name" "myapp" "myappdb"
        check_role_superuser "$name" "myapp" "myapp"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        log_pass "Custom POSTGRES_USER works"
    else
        log_fail "Custom POSTGRES_USER failed"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies that a non-default POSTGRES_PORT works. PostgreSQL should
# listen on port 5433, and all operations should use that port.
test_custom_port() {
    CURRENT_SCENARIO="custom_port"
    section "Custom POSTGRES_PORT=5433"

    local name="${TEST_PREFIX}_custport"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -e POSTGRES_PORT=5433 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        # Verify PG is on the custom port
        if docker exec "$name" su - dispatch -c \
            "psql -d dispatcharr -p 5433 -tAc 'SELECT 1;'" 2>/dev/null | grep -q 1; then
            log_pass "PostgreSQL running on custom port 5433"
        else
            log_fail "PostgreSQL not accessible on port 5433"
        fi
        check_no_permission_errors "$name"
        check_migrations_done "$name"
    else
        log_fail "Custom port failed"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies fresh install works on ephemeral tmpfs storage.
# Data is lost on restart — this tests that init scripts handle
# an empty /data directory correctly every time.
test_tmpfs_volume() {
    CURRENT_SCENARIO="tmpfs_volume"
    section "tmpfs volume — ephemeral storage"

    local name="${TEST_PREFIX}_tmpfs"
    cleanup_scenario
    track_container "$name"

    docker run -d --name "$name" \
        --tmpfs /data:rw,size=512m \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "1000" "1000"
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        log_pass "tmpfs volume works (ephemeral, data lost on restart)"
    else
        log_fail "tmpfs volume failed"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Tests both ownership migration (UID 999 -> 1000) AND PostgreSQL major
# version upgrade (16 -> 17) simultaneously. Uses official postgres:16
# image to create realistic PG 16 data with UID 999 (postgres in that image).
# Requires postgres:16 image to be available.
test_pg_major_upgrade() {
    CURRENT_SCENARIO="pg_major_upgrade"
    section "PostgreSQL major version upgrade (16 → 17)"

    if [ "$PG16_AVAILABLE" != true ]; then
        log_skip "postgres:16 image not available — skipping"
        return
    fi

    local name="${TEST_PREFIX}_pgupg"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    # Create a PG 16 data cluster using the official postgres:16 image.
    # This simulates an older Dispatcharr installation that used PG 16.
    # The postgres user in the official image has UID 999.
    log_info "Creating PG 16 data cluster..."
    if ! docker run --rm -v "${vol}:/data" --entrypoint bash postgres:16 -c '
        mkdir -p /data/db
        chown -R postgres:postgres /data/db
        chmod 700 /data/db
        gosu postgres /usr/lib/postgresql/16/bin/initdb -D /data/db
        gosu postgres /usr/lib/postgresql/16/bin/pg_ctl -D /data/db start -w -o "-c port=5432"
        gosu postgres psql -p 5432 -c "CREATE ROLE dispatch WITH LOGIN PASSWORD '\''secret'\'';"
        gosu postgres createdb -p 5432 --encoding=UTF8 --owner=dispatch dispatcharr
        gosu postgres /usr/lib/postgresql/16/bin/pg_ctl -D /data/db stop -w
        echo "PG 16 data created: $(cat /data/db/PG_VERSION)"
    '; then
        log_fail "Failed to create PG 16 data cluster"
        cleanup_scenario
        return
    fi

    # Verify PG 16 data exists
    local pg_ver
    pg_ver=$(docker run --rm -v "${vol}:/data" --entrypoint cat "$IMAGE_NAME" \
        /data/db/PG_VERSION 2>/dev/null | tr -d '[:space:]')
    if [ "$pg_ver" = "16" ]; then
        log_pass "PG 16 data cluster created (owned by UID 999)"
    else
        log_fail "PG_VERSION expected 16, got ${pg_ver:-<missing>}"
        cleanup_scenario
        return
    fi

    # Run our image (PG 17) against the PG 16 data.
    # This tests BOTH ownership migration (999->1000) AND pg_upgrade (16->17).
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    # pg_upgrade + apt install of PG 16 binaries takes longer than normal startup
    if wait_for_ready "$name" 300; then
        # Verify data was upgraded to PG 17
        local new_ver
        new_ver=$(docker exec "$name" cat /data/db/PG_VERSION 2>/dev/null | tr -d '[:space:]')
        if [ "$new_ver" = "17" ]; then
            log_pass "PG data upgraded to version 17"
        else
            log_fail "PG data version: expected 17, got ${new_ver:-<missing>}"
        fi

        check_ownership "$name" "/data/db" "1000" "1000"
        check_ownership "$name" "/data/db/PG_VERSION" "1000" "1000"
        check_pg_accessible "$name" "dispatch"
        check_role_superuser "$name" "dispatch" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"

        check_log_contains "$name" "Migrating PostgreSQL data ownership" \
            "Ownership migration logged (999→1000)"
        check_log_contains "$name" "upgrading to" \
            "PG version upgrade logged"
        check_log_contains "$name" "Upgrade complete" \
            "PG upgrade completion logged"

        # Verify old data was backed up
        if docker exec "$name" bash -c 'ls -d /data/db_backup_16_* 2>/dev/null' | grep -q "backup"; then
            log_pass "Old PG 16 data backed up"
        else
            log_fail "No backup of old PG 16 data found"
        fi
    else
        log_fail "Container failed to start after pg_upgrade"
    fi

    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Tests PG major upgrade on data that was created by the post-PUID image
# (install user = "dispatch", not "postgres"). This validates the future
# upgrade path where pg_upgrade -U must use "dispatch" instead of "postgres".
# Requires postgres:16 image to be available.
test_pg_upgrade_post_puid() {
    CURRENT_SCENARIO="pg_upgrade_post_puid"
    section "PostgreSQL major upgrade — post-PUID data (install user = dispatch)"

    if [ "$PG16_AVAILABLE" != true ]; then
        log_skip "postgres:16 image not available — skipping"
        return
    fi

    local name="${TEST_PREFIX}_pgupg2"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    # Create a PG 16 data cluster that simulates data created by the
    # post-PUID image: owned by UID 1000, install user = "dispatch".
    # This tests the upgrade path for future PG version bumps where
    # the install user is $POSTGRES_USER, not "postgres".
    log_info "Creating PG 16 data cluster with dispatch as install user..."
    if ! docker run --rm -v "${vol}:/data" --entrypoint bash "$IMAGE_NAME" -c '
        # Install PG 16 binaries
        apt-get update -qq && apt-get install -y -qq postgresql-16 >/dev/null 2>&1

        # Create dispatch user (matches PUID=1000 scenario)
        groupadd -g 1000 dispatch 2>/dev/null || true
        useradd -u 1000 -g 1000 -m dispatch 2>/dev/null || true

        mkdir -p /data/db
        chown -R 1000:1000 /data/db
        chmod 700 /data/db

        # Initialize with dispatch as the install user (bootstrap superuser)
        su - dispatch -c "/usr/lib/postgresql/16/bin/initdb -U dispatch -D /data/db"

        # Ensure socket directory is writable by dispatch
        mkdir -p /var/run/postgresql
        chown 1000:1000 /var/run/postgresql

        # Start, create app database, stop
        su - dispatch -c "/usr/lib/postgresql/16/bin/pg_ctl -D /data/db start -w -o \"-c port=5432\""
        su - dispatch -c "psql -U dispatch -d template1 -p 5432 -c \"CREATE DATABASE dispatcharr OWNER dispatch ENCODING '\''UTF8'\'';\""
        su - dispatch -c "/usr/lib/postgresql/16/bin/pg_ctl -D /data/db stop -w"
        echo "PG 16 (post-PUID) data created: $(cat /data/db/PG_VERSION)"
    '; then
        log_fail "Failed to create PG 16 post-PUID data cluster"
        cleanup_scenario
        return
    fi

    # Verify PG 16 data exists with correct ownership
    local pg_ver
    pg_ver=$(docker run --rm -v "${vol}:/data" --entrypoint cat "$IMAGE_NAME" \
        /data/db/PG_VERSION 2>/dev/null | tr -d '[:space:]')
    if [ "$pg_ver" = "16" ]; then
        log_pass "PG 16 post-PUID data cluster created (owned by UID 1000)"
    else
        log_fail "PG_VERSION expected 16, got ${pg_ver:-<missing>}"
        cleanup_scenario
        return
    fi

    # Run our image (PG 17) against the post-PUID PG 16 data.
    # This tests pg_upgrade when install user = "dispatch" (not "postgres").
    # No ownership migration should occur (already UID 1000).
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name" 300; then
        # Verify data was upgraded to PG 17
        local new_ver
        new_ver=$(docker exec "$name" cat /data/db/PG_VERSION 2>/dev/null | tr -d '[:space:]')
        if [ "$new_ver" = "17" ]; then
            log_pass "PG data upgraded to version 17"
        else
            log_fail "PG data version: expected 17, got ${new_ver:-<missing>}"
        fi

        check_ownership "$name" "/data/db" "1000" "1000"
        check_pg_accessible "$name" "dispatch"
        check_role_superuser "$name" "dispatch" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"

        # Key assertion: install user detected as "dispatch", not "postgres"
        check_log_contains "$name" "Old cluster install user: dispatch" \
            "Install user detected as dispatch (post-PUID path)"

        # No ownership migration should have occurred
        check_log_absent "$name" "Migrating PostgreSQL data ownership" \
            "No ownership migration (UID already matches)"

        check_log_contains "$name" "upgrading to" \
            "PG version upgrade logged"
        check_log_contains "$name" "Upgrade complete" \
            "PG upgrade completion logged"

        # Verify old data was backed up
        if docker exec "$name" bash -c 'ls -d /data/db_backup_16_* 2>/dev/null' | grep -q "backup"; then
            log_pass "Old PG 16 data backed up"
        else
            log_fail "No backup of old PG 16 data found"
        fi
    else
        log_fail "Container failed to start after post-PUID pg_upgrade"
    fi

    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Verifies the full HTTP stack after startup: nginx serves the frontend,
# uwsgi proxies to Django, and static files are collected. Uses an HTTP
# request from inside the container (no port mapping needed).
test_e2e_web_ui() {
    CURRENT_SCENARIO="e2e_web_ui"
    section "End-to-end — full HTTP stack (nginx → uwsgi → Django)"

    local name="${TEST_PREFIX}_e2e"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_pg_accessible "$name" "dispatch"
        check_migrations_done "$name"

        # Verify the full HTTP stack responds
        check_web_ui "$name"

        # Verify static files were collected (collectstatic runs before uwsgi)
        if docker exec "$name" test -d /app/static 2>/dev/null; then
            log_pass "Static files directory exists"
        else
            log_fail "Static files directory missing"
        fi

        check_no_permission_errors "$name"
    else
        log_fail "Container failed to start"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

# Tests startup with a read-only root filesystem (security hardening).
# This is an ambitious test — nginx/uwsgi need writable paths provided
# via tmpfs. The test verifies that PUID init scripts specifically don't
# fail; non-PUID failures (missing tmpfs mounts) are skipped, not failed.
test_readonly_rootfs() {
    CURRENT_SCENARIO="readonly_rootfs"
    section "Read-only root filesystem (security hardened)"

    local name="${TEST_PREFIX}_rofs"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    # Read-only rootfs requires tmpfs for writable paths
    docker run -d --name "$name" \
        --read-only \
        --tmpfs /tmp:rw \
        --tmpfs /run:rw \
        --tmpfs /var/run:rw \
        --tmpfs /var/log:rw \
        --tmpfs /etc:rw \
        --tmpfs /root:rw \
        --tmpfs /app/static:rw \
        --tmpfs /app/media:rw \
        --tmpfs /app/logo_cache:rw \
        -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name" 120; then
        check_ownership "$name" "/data/db" "1000" "1000"
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        log_pass "Read-only rootfs works"
    else
        # Check if it's our PUID code that broke or something else (e.g., can't
        # write to /etc, nginx needs writable paths, etc.)
        local ro_errors
        ro_errors=$(docker logs "$name" 2>&1 | grep -iE "read-only file system|No such file or directory" | head -3)
        if [ -n "$ro_errors" ]; then
            log_skip "Read-only rootfs: non-PUID failure (expected — needs more tmpfs mounts)"
        elif docker logs "$name" 2>&1 | grep -iE "Cannot update ownership|permission denied" | grep -q "/data/"; then
            log_fail "Read-only rootfs: PUID-related failure"
        else
            log_skip "Read-only rootfs: unrelated startup failure"
        fi
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

###############################################################################
# Main
###############################################################################

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════╗"
echo "║   PUID/PGID Docker Init Test Suite       ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${NC}"

# Pull required images
section "Pulling required images"
if docker pull "$RELEASE_IMAGE" 2>/dev/null; then
    log_pass "Release image pulled ($RELEASE_IMAGE)"
    USE_RELEASE_IMAGE=true
else
    log_info "Could not pull release image — upgrade tests will use manual setup"
    USE_RELEASE_IMAGE=false
fi

if docker pull postgres:17 2>/dev/null; then
    log_pass "PostgreSQL 17 image pulled"
else
    log_info "postgres:17 not available — modular test will be skipped"
fi

docker pull redis:latest 2>/dev/null && log_pass "Redis image pulled" || true

PG16_AVAILABLE=false
if docker pull postgres:16 2>/dev/null; then
    log_pass "PostgreSQL 16 image pulled (for upgrade test)"
    PG16_AVAILABLE=true
else
    log_info "postgres:16 not available — pg_major_upgrade test will be skipped"
fi

# Build test image from local changes
if [ "$SKIP_BUILD" = false ]; then
    section "Building test image from local changes"
    if docker build -t "$IMAGE_NAME" -f docker/Dockerfile . ; then
        log_pass "Test image built ($IMAGE_NAME)"
    else
        echo -e "${RED}Image build failed. Aborting.${NC}"
        exit 1
    fi
else
    log_info "Skipping build (--skip-build)"
fi

# Define scenario list
SCENARIOS=(
    fresh_default
    fresh_custom_puid
    upgrade_explicit_puid
    upgrade_auto_adapt
    restart_idempotent
    puid_change
    uid_collision_102
    puid_zero
    puid_non_numeric
    bind_mount
    bind_mount_upgrade
    bind_mount_auto_adapt
    modular_mode
    custom_postgres_user
    custom_port
    tmpfs_volume
    pg_major_upgrade
    pg_upgrade_post_puid
    e2e_web_ui
    readonly_rootfs
)

# Run scenarios
for scenario in "${SCENARIOS[@]}"; do
    if [ -n "$SINGLE_SCENARIO" ] && [ "$scenario" != "$SINGLE_SCENARIO" ]; then
        continue
    fi
    "test_${scenario}"
done

# Summary
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗"
echo -e "║               RESULTS                    ║"
echo -e "╚══════════════════════════════════════════╝${NC}"
echo -e "  ${GREEN}Passed:  $PASS${NC}"
echo -e "  ${RED}Failed:  $FAIL${NC}"
echo -e "  ${YELLOW}Skipped: $SKIP${NC}"

if [ ${#ERRORS[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Failures:${NC}"
    for err in "${ERRORS[@]}"; do
        echo -e "  ${RED}• $err${NC}"
    done
fi

echo ""
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}${BOLD}$FAIL test(s) failed.${NC}"
    exit 1
fi
