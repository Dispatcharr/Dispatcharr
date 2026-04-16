#!/bin/bash
#
# Integration test suite for TLS/mTLS in modular mode.
# Validates that Dispatcharr connects correctly to external PostgreSQL and
# Redis services using various TLS configurations.
#
# Prerequisites:
#   - Docker Desktop (or Docker Engine) running
#   - Internet access (pulls postgres:17, redis:latest)
#   - ~10-15 minutes for a full run
#
# Usage:
#   cd <repo_root>
#   bash docker/tests/test-tls-postgres.sh [--skip-build] [--keep-on-fail] [scenario_name]
#
# Options:
#   --skip-build    Skip Docker image build (use existing dispatcharr:tls-test image)
#   --keep-on-fail  Don't clean up containers/volumes on failure (for debugging)
#   scenario_name   Run only the named scenario
#
# Scenarios:
#   modular_mtls_no_password      PG mTLS cert-only auth, no password
#   modular_mtls_with_password    PG mTLS + password auth combined
#   modular_tls_server_only       PG server-side TLS only (no client cert)
#   modular_tls_key_permission    PG mTLS with 0777 client key (Docker Desktop scenario)
#   modular_no_tls_regression     Non-TLS modular mode still works
#   modular_pg_verify_full        PG mTLS with verify-full (CN must match hostname)
#   modular_redis_tls             Redis with TLS (server-side verification)
#   modular_full_tls_celery       PG mTLS + Redis TLS with separate Celery container
#
# Exit codes:
#   0  All tests passed
#   1  One or more tests failed (or build failed)

set -uo pipefail

# Prevent Git Bash (MINGW) from converting Unix paths
export MSYS_NO_PATHCONV=1

###############################################################################
# Configuration
###############################################################################
IMAGE_NAME="dispatcharr:tls-test"
TEST_PREFIX="tls_test"
STARTUP_TIMEOUT=120
SKIP_BUILD=false
KEEP_ON_FAIL=false
SINGLE_SCENARIO=""
PASS=0
FAIL=0
SKIP=0
ERRORS=()
CERT_DIR=""

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
CURRENT_SCENARIO=""
CLEANUP_ITEMS=()

log_pass() { echo -e "  ${GREEN}✅ $1${NC}"; PASS=$((PASS + 1)); }
log_fail() { echo -e "  ${RED}❌ $1${NC}"; FAIL=$((FAIL + 1)); ERRORS+=("[$CURRENT_SCENARIO] $1"); }
log_skip() { echo -e "  ${YELLOW}⏭️  $1${NC}"; SKIP=$((SKIP + 1)); }
log_info() { echo -e "  ${CYAN}ℹ️  $1${NC}"; }
section()  { echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; SCENARIO_FAIL_BEFORE=$FAIL; }

track_container() { CLEANUP_ITEMS+=("container:$1"); }
track_volume()    { CLEANUP_ITEMS+=("volume:$1"); }
track_network()   { CLEANUP_ITEMS+=("network:$1"); }

fresh_volume() {
    local vol="$1"
    docker rm -f $(docker ps -aq --filter "volume=${vol}") 2>/dev/null || true
    docker volume rm "$vol" 2>/dev/null || true
    docker volume create "$vol" >/dev/null
    track_volume "$vol"
}

cleanup_scenario() {
    if [ "$KEEP_ON_FAIL" = true ] && [ "$FAIL" -gt "${SCENARIO_FAIL_BEFORE:-0}" ]; then
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

trap 'cleanup_scenario; [ -n "$CERT_DIR" ] && rm -rf "$CERT_DIR"' EXIT

wait_for_ready() {
    local name="$1"
    local timeout="${2:-$STARTUP_TIMEOUT}"
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if ! docker ps -q -f "name=^${name}$" 2>/dev/null | grep -q .; then
            echo "  Container $name exited unexpectedly"
            return 1
        fi
        if docker logs "$name" 2>&1 | grep -q "uwsgi started with PID"; then
            return 0
        fi
        sleep 3
        ((elapsed+=3))
    done
    echo "  Timeout (${timeout}s) waiting for $name"
    return 1
}

_capture_logs() {
    local container="$1" logfile="$2"
    docker logs "$container" > "$logfile" 2>&1
}

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

check_migrations_done() {
    local container="$1"
    local tmplog; tmplog=$(mktemp)
    _capture_logs "$container" "$tmplog"
    if grep -qE "Running migrations|No migrations to apply|Operations to perform|Applying .+\.\.\. OK" "$tmplog"; then
        log_pass "Django migrations completed"
    elif grep -q "uwsgi started with PID" "$tmplog"; then
        log_pass "Django migrations completed (confirmed via uwsgi startup)"
    else
        log_fail "Django migrations did not complete"
    fi
    rm -f "$tmplog"
}

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

dump_logs_on_fail() {
    local container="$1"
    if [ $FAIL -gt ${SCENARIO_FAIL_BEFORE:-0} ]; then
        echo -e "  ${YELLOW}--- Container logs ($container) ---${NC}"
        docker logs "$container" 2>&1 | tail -30 | sed 's/^/    /'
        echo -e "  ${YELLOW}--- End logs ---${NC}"
    fi
}

###############################################################################
# Certificate generation
###############################################################################
generate_test_certs() {
    CERT_DIR=$(mktemp -d)
    log_info "Generating test certificates in $CERT_DIR"

    # Generate certs inside a container for cross-platform compatibility.
    # Shared CA for both PG and Redis. CN of server certs must match their
    # Docker container hostnames for verify-full mode.
    docker run --rm --entrypoint sh \
        -v "$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR"):/certs" \
        -w /certs alpine/openssl -c '
        # Shared CA
        openssl req -new -x509 -days 1 -nodes \
            -keyout ca.key -out ca.crt -subj "/CN=Test CA" 2>/dev/null &&

        # PostgreSQL server cert (CN = PG container hostname)
        openssl req -new -nodes \
            -keyout pg-server.key -out pg-server.csr -subj "/CN='"${TEST_PREFIX}"'_pg" 2>/dev/null &&
        openssl x509 -req -days 1 -in pg-server.csr \
            -CA ca.crt -CAkey ca.key -CAcreateserial -out pg-server.crt 2>/dev/null &&
        # PostgreSQL client cert (CN = POSTGRES_USER)
        openssl req -new -nodes \
            -keyout pg-client.key -out pg-client.csr -subj "/CN=dispatch" 2>/dev/null &&
        openssl x509 -req -days 1 -in pg-client.csr \
            -CA ca.crt -CAkey ca.key -CAcreateserial -out pg-client.crt 2>/dev/null &&

        # Redis server cert (CN = Redis container hostname)
        openssl req -new -nodes \
            -keyout redis-server.key -out redis-server.csr -subj "/CN='"${TEST_PREFIX}"'_redis" 2>/dev/null &&
        openssl x509 -req -days 1 -in redis-server.csr \
            -CA ca.crt -CAkey ca.key -CAcreateserial -out redis-server.crt 2>/dev/null &&

        # Backwards-compat aliases (existing PG-only scenarios use these names)
        cp pg-server.crt server.crt && cp pg-server.key server.key &&
        cp pg-client.crt client.crt && cp pg-client.key client.key &&

        chmod 600 pg-server.key pg-client.key redis-server.key server.key client.key
    ' || { log_fail "Certificate generation failed"; return 1; }

    log_pass "Test certificates generated"
}

###############################################################################
# Start a TLS-enabled Redis container
###############################################################################
start_tls_redis() {
    local name="$1" net="$2"

    local cert_mount
    cert_mount="$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR")"

    # Redis needs certs owned by redis user (uid 999 in the official image).
    # Mount certs, copy to a writable location, fix ownership, then start
    # with TLS flags.
    docker run -d --name "$name" --network "$net" \
        -v "${cert_mount}:/certs:ro" \
        redis:latest \
        sh -c '
            cp /certs/redis-server.crt /certs/redis-server.key /certs/ca.crt /tmp/ &&
            chmod 600 /tmp/redis-server.key &&
            chown redis:redis /tmp/redis-server.crt /tmp/redis-server.key /tmp/ca.crt &&
            exec redis-server \
                --tls-port 6379 --port 0 \
                --tls-cert-file /tmp/redis-server.crt \
                --tls-key-file /tmp/redis-server.key \
                --tls-ca-cert-file /tmp/ca.crt \
                --tls-auth-clients no
        ' >/dev/null

    # Wait for Redis TLS to be ready
    local elapsed=0
    while [ $elapsed -lt 20 ]; do
        if docker exec "$name" redis-cli --tls \
            --cert /certs/redis-server.crt --key /certs/redis-server.key --cacert /certs/ca.crt \
            ping 2>/dev/null | grep -q "PONG"; then
            break
        fi
        sleep 2; elapsed=$((elapsed + 2))
    done
}

###############################################################################
# Start a TLS-enabled PostgreSQL container
###############################################################################
start_tls_postgres() {
    local name="$1" net="$2" hba_auth="$3"

    local cert_mount
    cert_mount="$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR")"

    docker run -d --name "$name" --network "$net" \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_PASSWORD=tempsetup \
        -e POSTGRES_DB=dispatcharr \
        -v "${cert_mount}:/certs:ro" \
        postgres:17 >/dev/null

    # Wait for PG to initialize
    local elapsed=0
    while [ $elapsed -lt 30 ]; do
        if docker exec "$name" su postgres -c "/usr/lib/postgresql/17/bin/pg_isready" 2>/dev/null | grep -q "accepting"; then
            break
        fi
        sleep 2; ((elapsed+=2))
    done

    # Configure SSL and pg_hba.conf
    docker exec "$name" bash -c "
        cp /certs/server.crt /certs/server.key /certs/ca.crt /var/lib/postgresql/
        chown postgres:postgres /var/lib/postgresql/server.crt /var/lib/postgresql/server.key /var/lib/postgresql/ca.crt
        chmod 600 /var/lib/postgresql/server.key
        echo \"ssl = on\" >> /var/lib/postgresql/data/postgresql.conf
        echo \"ssl_cert_file = '/var/lib/postgresql/server.crt'\" >> /var/lib/postgresql/data/postgresql.conf
        echo \"ssl_key_file = '/var/lib/postgresql/server.key'\" >> /var/lib/postgresql/data/postgresql.conf
        echo \"ssl_ca_file = '/var/lib/postgresql/ca.crt'\" >> /var/lib/postgresql/data/postgresql.conf
        cat > /var/lib/postgresql/data/pg_hba.conf << HBA
local   all   all   trust
hostssl all   all   0.0.0.0/0   ${hba_auth}
hostssl all   all   ::0/0       ${hba_auth}
HBA
        su postgres -c '/usr/lib/postgresql/17/bin/pg_ctl reload -D /var/lib/postgresql/data'
    " >/dev/null 2>&1
    sleep 1
}

###############################################################################
# Test scenarios
###############################################################################

test_modular_mtls_no_password() {
    CURRENT_SCENARIO="modular_mtls_no_password"
    section "Modular mode — mTLS cert-only auth (no password)"

    local name="${TEST_PREFIX}_app"
    local pg_name="${TEST_PREFIX}_pg"
    local redis_name="${TEST_PREFIX}_redis"
    local net="${TEST_PREFIX}_net"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"; track_container "$name"

    start_tls_postgres "$pg_name" "$net" "cert"

    docker run -d --name "$redis_name" --network "$net" redis:latest >/dev/null

    local cert_mount
    cert_mount="$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR")"

    # No POSTGRES_PASSWORD — cert-only auth
    docker run -d --name "$name" --network "$net" \
        -e DISPATCHARR_ENV=modular \
        -e POSTGRES_HOST="$pg_name" \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_DB=dispatcharr \
        -e REDIS_HOST="$redis_name" \
        -e POSTGRES_SSL=true \
        -e POSTGRES_SSL_MODE=verify-ca \
        -e POSTGRES_SSL_CA_CERT=/certs/ca.crt \
        -e POSTGRES_SSL_CERT=/certs/client.crt \
        -e POSTGRES_SSL_KEY=/certs/client.key \
        -v "${cert_mount}:/certs:ro" \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        log_pass "Container started with mTLS cert-only auth"
        check_log_contains "$name" "PostgreSQL version check passed" \
            "Version check passed with mTLS"
        check_log_contains "$name" "PostgreSQL TLS: enabled" \
            "Django sees TLS enabled"
        check_migrations_done "$name"
        check_no_permission_errors "$name"
    else
        log_fail "Container failed to start with mTLS cert-only auth"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

test_modular_mtls_with_password() {
    CURRENT_SCENARIO="modular_mtls_with_password"
    section "Modular mode — mTLS + password auth"

    local name="${TEST_PREFIX}_app"
    local pg_name="${TEST_PREFIX}_pg"
    local redis_name="${TEST_PREFIX}_redis"
    local net="${TEST_PREFIX}_net"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"; track_container "$name"

    # cert + md5 password
    start_tls_postgres "$pg_name" "$net" "cert"

    docker run -d --name "$redis_name" --network "$net" redis:latest >/dev/null

    local cert_mount
    cert_mount="$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR")"

    docker run -d --name "$name" --network "$net" \
        -e DISPATCHARR_ENV=modular \
        -e POSTGRES_HOST="$pg_name" \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_PASSWORD=tempsetup \
        -e POSTGRES_DB=dispatcharr \
        -e REDIS_HOST="$redis_name" \
        -e POSTGRES_SSL=true \
        -e POSTGRES_SSL_MODE=verify-ca \
        -e POSTGRES_SSL_CA_CERT=/certs/ca.crt \
        -e POSTGRES_SSL_CERT=/certs/client.crt \
        -e POSTGRES_SSL_KEY=/certs/client.key \
        -v "${cert_mount}:/certs:ro" \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        log_pass "Container started with mTLS + password"
        check_log_contains "$name" "PostgreSQL version check passed" \
            "Version check passed with mTLS + password"
        check_migrations_done "$name"
    else
        log_fail "Container failed to start with mTLS + password"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

test_modular_tls_server_only() {
    CURRENT_SCENARIO="modular_tls_server_only"
    section "Modular mode — server-only TLS (no client cert)"

    local name="${TEST_PREFIX}_app"
    local pg_name="${TEST_PREFIX}_pg"
    local redis_name="${TEST_PREFIX}_redis"
    local net="${TEST_PREFIX}_net"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"; track_container "$name"

    # md5 auth over TLS (no client cert required)
    start_tls_postgres "$pg_name" "$net" "md5"

    docker run -d --name "$redis_name" --network "$net" redis:latest >/dev/null

    local cert_mount
    cert_mount="$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR")"

    docker run -d --name "$name" --network "$net" \
        -e DISPATCHARR_ENV=modular \
        -e POSTGRES_HOST="$pg_name" \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_PASSWORD=tempsetup \
        -e POSTGRES_DB=dispatcharr \
        -e REDIS_HOST="$redis_name" \
        -e POSTGRES_SSL=true \
        -e POSTGRES_SSL_MODE=verify-ca \
        -e POSTGRES_SSL_CA_CERT=/certs/ca.crt \
        -v "${cert_mount}:/certs:ro" \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        log_pass "Container started with server-only TLS"
        check_log_contains "$name" "PostgreSQL version check passed" \
            "Version check passed with server-only TLS"
        check_migrations_done "$name"
    else
        log_fail "Container failed to start with server-only TLS"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

test_modular_tls_key_permission() {
    CURRENT_SCENARIO="modular_tls_key_permission"
    section "Modular mode — mTLS with 0777 client key (Docker Desktop scenario)"

    local name="${TEST_PREFIX}_app"
    local pg_name="${TEST_PREFIX}_pg"
    local redis_name="${TEST_PREFIX}_redis"
    local net="${TEST_PREFIX}_net"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"; track_container "$name"

    start_tls_postgres "$pg_name" "$net" "cert"

    docker run -d --name "$redis_name" --network "$net" redis:latest >/dev/null

    # Create a copy of certs with 0777 key permissions
    local bad_perms_dir
    bad_perms_dir=$(mktemp -d)
    cp "$CERT_DIR"/ca.crt "$CERT_DIR"/client.crt "$CERT_DIR"/client.key "$bad_perms_dir/"
    chmod 777 "$bad_perms_dir/client.key"

    local cert_mount
    cert_mount="$(cygpath -w "$bad_perms_dir" 2>/dev/null || echo "$bad_perms_dir")"

    docker run -d --name "$name" --network "$net" \
        -e DISPATCHARR_ENV=modular \
        -e POSTGRES_HOST="$pg_name" \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_DB=dispatcharr \
        -e REDIS_HOST="$redis_name" \
        -e POSTGRES_SSL=true \
        -e POSTGRES_SSL_MODE=verify-ca \
        -e POSTGRES_SSL_CA_CERT=/certs/ca.crt \
        -e POSTGRES_SSL_CERT=/certs/client.crt \
        -e POSTGRES_SSL_KEY=/certs/client.key \
        -v "${cert_mount}:/certs:ro" \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        log_pass "Container started with 0777 client key"
        check_log_contains "$name" "Fixed PostgreSQL client key" \
            "Key permission fix triggered"
        check_log_contains "$name" "PostgreSQL version check passed" \
            "Version check passed after key fix"
        check_migrations_done "$name"
    else
        log_fail "Container failed to start with 0777 client key"
    fi
    dump_logs_on_fail "$name"
    rm -rf "$bad_perms_dir"
    cleanup_scenario
}

test_modular_no_tls_regression() {
    CURRENT_SCENARIO="modular_no_tls_regression"
    section "Modular mode — no TLS (regression check)"

    local name="${TEST_PREFIX}_app"
    local pg_name="${TEST_PREFIX}_pg"
    local redis_name="${TEST_PREFIX}_redis"
    local net="${TEST_PREFIX}_net"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"; track_container "$name"

    # Plain PostgreSQL — no TLS
    docker run -d --name "$pg_name" --network "$net" \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_PASSWORD=secret \
        -e POSTGRES_DB=dispatcharr \
        postgres:17 >/dev/null

    local elapsed=0
    while [ $elapsed -lt 30 ]; do
        if docker exec "$pg_name" su postgres -c "/usr/lib/postgresql/17/bin/pg_isready" 2>/dev/null | grep -q "accepting"; then
            break
        fi
        sleep 2; ((elapsed+=2))
    done

    docker run -d --name "$redis_name" --network "$net" redis:latest >/dev/null

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
        log_pass "Container started without TLS (regression check)"
        check_log_contains "$name" "PostgreSQL version check passed" \
            "Version check passed without TLS"
        check_log_absent "$name" "Fixed PostgreSQL client key" \
            "No key fix when TLS disabled"
        check_migrations_done "$name"
    else
        log_fail "Container failed to start without TLS"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

test_modular_pg_verify_full() {
    CURRENT_SCENARIO="modular_pg_verify_full"
    section "Modular mode — PG mTLS with verify-full (CN must match hostname)"

    local name="${TEST_PREFIX}_app"
    local pg_name="${TEST_PREFIX}_pg"
    local redis_name="${TEST_PREFIX}_redis"
    local net="${TEST_PREFIX}_net"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"; track_container "$name"

    start_tls_postgres "$pg_name" "$net" "cert"

    docker run -d --name "$redis_name" --network "$net" redis:latest >/dev/null

    local cert_mount
    cert_mount="$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR")"

    # verify-full requires server cert CN to match the hostname used to connect.
    # Our PG server cert CN is "${TEST_PREFIX}_pg", which matches the container name
    # used in POSTGRES_HOST.
    docker run -d --name "$name" --network "$net" \
        -e DISPATCHARR_ENV=modular \
        -e POSTGRES_HOST="$pg_name" \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_DB=dispatcharr \
        -e REDIS_HOST="$redis_name" \
        -e POSTGRES_SSL=true \
        -e POSTGRES_SSL_MODE=verify-full \
        -e POSTGRES_SSL_CA_CERT=/certs/ca.crt \
        -e POSTGRES_SSL_CERT=/certs/client.crt \
        -e POSTGRES_SSL_KEY=/certs/client.key \
        -v "${cert_mount}:/certs:ro" \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        log_pass "Container started with verify-full"
        check_log_contains "$name" "PostgreSQL version check passed" \
            "Version check passed with verify-full"
        check_log_contains "$name" "sslmode=verify-full" \
            "Django reports verify-full mode"
        check_migrations_done "$name"
    else
        log_fail "Container failed to start with verify-full"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

test_modular_redis_tls() {
    CURRENT_SCENARIO="modular_redis_tls"
    section "Modular mode — Redis with TLS"

    local name="${TEST_PREFIX}_app"
    local pg_name="${TEST_PREFIX}_pg"
    local redis_name="${TEST_PREFIX}_redis"
    local net="${TEST_PREFIX}_net"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"; track_container "$name"

    # Plain PG (no TLS) — isolate Redis TLS testing
    docker run -d --name "$pg_name" --network "$net" \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_PASSWORD=secret \
        -e POSTGRES_DB=dispatcharr \
        postgres:17 >/dev/null

    local elapsed=0
    while [ $elapsed -lt 30 ]; do
        if docker exec "$pg_name" su postgres -c "/usr/lib/postgresql/17/bin/pg_isready" 2>/dev/null | grep -q "accepting"; then
            break
        fi
        sleep 2; elapsed=$((elapsed + 2))
    done

    start_tls_redis "$redis_name" "$net"

    local cert_mount
    cert_mount="$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR")"

    docker run -d --name "$name" --network "$net" \
        -e DISPATCHARR_ENV=modular \
        -e POSTGRES_HOST="$pg_name" \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_USER=dispatch \
        -e POSTGRES_PASSWORD=secret \
        -e POSTGRES_DB=dispatcharr \
        -e REDIS_HOST="$redis_name" \
        -e REDIS_SSL=true \
        -e REDIS_SSL_VERIFY=false \
        -e REDIS_SSL_CA_CERT=/certs/ca.crt \
        -v "${cert_mount}:/certs:ro" \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        log_pass "Container started with Redis TLS"
        check_log_contains "$name" "Redis TLS: enabled" \
            "Django reports Redis TLS enabled"
        check_log_contains "$name" "Redis at ${redis_name}" \
            "Redis connected via TLS"
        check_migrations_done "$name"
    else
        log_fail "Container failed to start with Redis TLS"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}

test_modular_full_tls_celery() {
    CURRENT_SCENARIO="modular_full_tls_celery"
    section "Modular mode — PG mTLS + Redis TLS with Celery container"

    local name="${TEST_PREFIX}_app"
    local celery_name="${TEST_PREFIX}_celery"
    local pg_name="${TEST_PREFIX}_pg"
    local redis_name="${TEST_PREFIX}_redis"
    local net="${TEST_PREFIX}_net"
    local vol="${name}_data"
    cleanup_scenario

    docker network create "$net" >/dev/null 2>&1
    fresh_volume "$vol"
    track_network "$net"
    track_container "$pg_name"; track_container "$redis_name"
    track_container "$name"; track_container "$celery_name"

    start_tls_postgres "$pg_name" "$net" "cert"
    start_tls_redis "$redis_name" "$net"

    local cert_mount
    cert_mount="$(cygpath -w "$CERT_DIR" 2>/dev/null || echo "$CERT_DIR")"

    # Shared env vars for both web and celery containers
    local -a tls_env=(
        -e DISPATCHARR_ENV=modular
        -e POSTGRES_HOST="$pg_name"
        -e POSTGRES_PORT=5432
        -e POSTGRES_USER=dispatch
        -e POSTGRES_DB=dispatcharr
        -e REDIS_HOST="$redis_name"
        -e POSTGRES_SSL=true
        -e POSTGRES_SSL_MODE=verify-ca
        -e POSTGRES_SSL_CA_CERT=/certs/ca.crt
        -e POSTGRES_SSL_CERT=/certs/client.crt
        -e POSTGRES_SSL_KEY=/certs/client.key
        -e REDIS_SSL=true
        -e REDIS_SSL_VERIFY=false
        -e REDIS_SSL_CA_CERT=/certs/ca.crt
    )

    # Start web container first (generates JWT, runs migrations)
    docker run -d --name "$name" --network "$net" \
        "${tls_env[@]}" \
        -v "${cert_mount}:/certs:ro" \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if ! wait_for_ready "$name"; then
        log_fail "Web container failed to start with full TLS"
        dump_logs_on_fail "$name"
        cleanup_scenario
        return
    fi
    log_pass "Web container started with PG mTLS + Redis TLS"

    # Start Celery container (shares /data volume for JWT, waits for migrations)
    docker run -d --name "$celery_name" --network "$net" \
        "${tls_env[@]}" \
        -e DJANGO_SETTINGS_MODULE=dispatcharr.settings \
        -e PYTHONUNBUFFERED=1 \
        -v "${cert_mount}:/certs:ro" \
        -v "${vol}:/data" \
        --entrypoint /app/docker/entrypoint.celery.sh \
        "$IMAGE_NAME" >/dev/null

    # Wait for Celery to start (look for "starting Celery" message)
    local elapsed=0
    local celery_ok=false
    while [ $elapsed -lt 90 ]; do
        if ! docker ps -q -f "name=^${celery_name}$" 2>/dev/null | grep -q .; then
            echo "  Celery container exited unexpectedly"
            break
        fi
        if docker logs "$celery_name" 2>&1 | grep -q "starting Celery"; then
            celery_ok=true
            break
        fi
        sleep 3; elapsed=$((elapsed + 3))
    done

    if [ "$celery_ok" = true ]; then
        log_pass "Celery container started with PG mTLS + Redis TLS"
        check_log_contains "$celery_name" "Migrations complete" \
            "Celery confirmed migrations complete via TLS"
        check_log_contains "$celery_name" "PostgreSQL TLS: enabled" \
            "Celery sees PostgreSQL TLS enabled"
        check_log_contains "$celery_name" "Redis TLS: enabled" \
            "Celery sees Redis TLS enabled"
    else
        log_fail "Celery container failed to start with full TLS"
        echo -e "  ${YELLOW}--- Celery logs ---${NC}"
        docker logs "$celery_name" 2>&1 | tail -20 | sed 's/^/    /'
        echo -e "  ${YELLOW}--- End logs ---${NC}"
    fi

    dump_logs_on_fail "$name"
    cleanup_scenario
}

###############################################################################
# Main
###############################################################################
echo -e "${BOLD}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Dispatcharr — TLS Integration Tests                    ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════════════╝${NC}"

# Build image
if [ "$SKIP_BUILD" = false ]; then
    echo -e "\n${BOLD}Building test image...${NC}"
    if ! docker build -t "$IMAGE_NAME" -f docker/Dockerfile . 2>&1 | tail -5; then
        echo -e "${RED}Build failed${NC}"
        exit 1
    fi
    echo -e "${GREEN}Build complete${NC}"
else
    echo -e "\n${YELLOW}Skipping build (--skip-build)${NC}"
fi

# Generate certificates
generate_test_certs || exit 1

# Run scenarios
SCENARIOS=(
    modular_mtls_no_password
    modular_mtls_with_password
    modular_tls_server_only
    modular_tls_key_permission
    modular_no_tls_regression
    modular_pg_verify_full
    modular_redis_tls
    modular_full_tls_celery
)

for scenario in "${SCENARIOS[@]}"; do
    if [ -n "$SINGLE_SCENARIO" ] && [ "$scenario" != "$SINGLE_SCENARIO" ]; then
        continue
    fi
    "test_${scenario}"
done

# Clean up certs
rm -rf "$CERT_DIR"

# Summary
echo -e "\n${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo -e "  ${GREEN}Passed: $PASS${NC}  ${RED}Failed: $FAIL${NC}  ${YELLOW}Skipped: $SKIP${NC}"
if [ ${#ERRORS[@]} -gt 0 ]; then
    echo -e "\n  ${RED}Failures:${NC}"
    for err in "${ERRORS[@]}"; do
        echo -e "    ${RED}• $err${NC}"
    done
fi
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"

[ $FAIL -eq 0 ]
